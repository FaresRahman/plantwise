"""Engine registration + auto-detection. Adapters register themselves by
decorating their class with @register_adapter — nothing else in the app
enumerates engines by name, so adding a new adapter module (+ importing it
from db_adapters/__init__.py) is the entire integration surface.
"""
from __future__ import annotations

import asyncio

from app.core.db_adapters.base import AdapterError, ConnectionParams, DatabaseAdapter, PrerequisiteMissingError

_ADAPTERS: dict[str, type[DatabaseAdapter]] = {}


def register_adapter(cls: type[DatabaseAdapter]) -> type[DatabaseAdapter]:
    if not cls.engine_key:
        raise ValueError(f"{cls.__name__} must set engine_key")
    _ADAPTERS[cls.engine_key] = cls
    return cls


def get_adapter_class(engine_key: str) -> type[DatabaseAdapter]:
    try:
        return _ADAPTERS[engine_key]
    except KeyError:
        raise AdapterError(f"Unsupported database engine '{engine_key}'")


def list_supported_engines() -> list[dict]:
    """For the connection-form UI's engine picker/detection-result display."""
    return [
        {
            "engine": cls.engine_key,
            "display_name": cls.display_name,
            "tier": cls.tier,
            "prerequisite_note": cls.prerequisite_note,
            "local_only": cls.local_only,
        }
        for cls in sorted(_ADAPTERS.values(), key=lambda c: (c.tier, c.display_name))
    ]


async def detect_engine(params: ConnectionParams, include_local_only: bool = False) -> dict:
    """Try to identify which engine params.host:port is actually running.

    Returns {"detected": [engine_key, ...], "version": str | None,
    "ambiguous": bool}. `detected` has exactly one entry in the normal case;
    zero means nothing we support answered on that host/port; more than one
    is genuinely ambiguous (rare) and the caller should ask the user to pick
    explicitly via ConnectionParams.engine instead of guessing.
    """
    if params.engine:
        cls = get_adapter_class(params.engine)
        adapter = cls(params)
        try:
            info = await adapter.test_connection()
        finally:
            await adapter.close()
        return {"detected": [params.engine], "version": info.get("version"), "ambiguous": False}

    pool = [cls for cls in _ADAPTERS.values() if include_local_only or not cls.local_only]
    port_matches = [cls for cls in pool if params.port in cls.default_ports]
    fallback = sorted((cls for cls in pool if cls not in port_matches), key=lambda c: c.tier)
    port_matched_keys = {cls.engine_key for cls in port_matches}

    successes: list[tuple[str, str | None]] = []

    for cls in port_matches + fallback:
        adapter = cls(params)
        try:
            info = await asyncio.wait_for(adapter.test_connection(), timeout=params.connect_timeout_seconds)
            successes.append((cls.engine_key, info.get("version")))
            # A port match that actually connects is decisive — later,
            # slower attempts against every other engine would just burn
            # time for a result we already have.
            if cls.engine_key in port_matched_keys:
                break
        except PrerequisiteMissingError:
            # Only trust this as a real signal when the port itself already
            # pointed at this exact engine — during the blind fallback sweep
            # (no port match at all), a tier-2 driver simply not being
            # installed says nothing about what's actually running on this
            # host/port, so it must not be surfaced as "this looks like X".
            if cls.engine_key in port_matched_keys:
                raise PrerequisiteMissingError(
                    f"This looks like {cls.display_name} (default port {params.port}), but the "
                    f"server-side driver isn't ready: {cls.prerequisite_note}"
                )
            continue
        except (AdapterError, asyncio.TimeoutError, OSError):
            continue
        finally:
            await adapter.close()

    return {
        "detected": [key for key, _ in successes],
        "version": successes[0][1] if len(successes) == 1 else None,
        "ambiguous": len(successes) > 1,
    }

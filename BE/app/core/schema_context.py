"""Generic infrastructure for structured-query chat tools.

Each module registers which of its models are safe to query and describes
them (business meaning, units, curated examples) via register_queryable_model
— the same registration pattern as module_registry/contracts. A
SchemaContextProvider compiles that into a compact context string that goes
into that module's ChatToolSpec description, so the LLM sees schema +
semantics + examples without any separate "context injection" pipeline
stage.

Swappable by design: StaticSchemaProvider (below) is the only implementation
today, appropriate while the platform's queryable schema is small (~25
tables at full v1 scope). If Phase-2 connectors (ERP/MES/SCADA/PLC) grow
that enough to blow a prompt's context budget, add a RetrievalSchemaProvider
behind the same ABC — callers (chat tool descriptions) don't change either
way.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy import Table
from sqlalchemy.orm import DeclarativeBase


@dataclass
class ColumnDoc:
    """Curated semantic metadata for one column — the part that can never be
    derived from introspecting the ORM (business meaning, unit, enum values).
    """

    name: str
    semantic: str = ""


@dataclass
class QueryableModel:
    model: type[DeclarativeBase]
    description: str = ""
    columns: list[ColumnDoc] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)  # curated "question -> DSL shape" pairs


_REGISTRY: dict[str, list[QueryableModel]] = {}


def register_queryable_model(module: str, queryable: QueryableModel) -> None:
    _REGISTRY.setdefault(module, []).append(queryable)


class SchemaContextProvider(ABC):
    @abstractmethod
    def get_context(self, module: str) -> str: ...


class StaticSchemaProvider(SchemaContextProvider):
    """Generates context by combining live ORM introspection (table/column
    names/types — always accurate, can't drift) with the hand-curated
    semantic layer registered alongside it (meaning/units/examples — the part
    that genuinely can't be derived mechanically).
    """

    def get_context(self, module: str) -> str:
        queryables = _REGISTRY.get(module, [])
        if not queryables:
            return f"No queryable schema registered for module '{module}'."

        lines: list[str] = []
        for qm in queryables:
            table = qm.model.__table__
            assert isinstance(table, Table)
            lines.append(f"Table: {table.name}")
            if qm.description:
                lines.append(f"  {qm.description}")
            for column in table.columns:
                doc = next((c.semantic for c in qm.columns if c.name == column.name), "")
                suffix = f": {doc}" if doc else ""
                lines.append(f"  - {column.name} ({column.type}){suffix}")
            if qm.examples:
                lines.append("  Examples:")
                for example in qm.examples:
                    lines.append(f"    {example}")
        return "\n".join(lines)

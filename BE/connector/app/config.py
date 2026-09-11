"""Local, on-disk connector configuration — registration state, the SaaS
backend URL, and (if configured) the one database connection this connector
instance relays. Nothing here is ever sent anywhere except the connector's
own outbound requests to the SaaS backend it's registered with.

Secrets (the connector token, the DB password) are Fernet-encrypted with a
key stored in a separate local file. This is a pragmatic choice, not the
strongest possible one — an OS-native credential store (Windows Credential
Manager / macOS Keychain / Linux Secret Service) would be more secure, but
also less reliable on a headless/unattended machine, which is a realistic
deployment target for something like this. Documenting the tradeoff here
rather than leaving it implicit: this protects secrets from casual
inspection of the config file and from anyone without filesystem access to
this machine, not from an attacker who already has that access.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet


def _app_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "PlantwiseConnector"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_DIR = Path(os.environ.get("CONNECTOR_CONFIG_DIR", "")) if os.environ.get("CONNECTOR_CONFIG_DIR") else _app_data_dir()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
KEY_FILE = CONFIG_DIR / "local.key"
LOG_FILE = CONFIG_DIR / "connector.log"


def _load_or_create_key() -> bytes:
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    try:
        # Best-effort lock-down — owner read/write only. No-op on Windows
        # (which doesn't use POSIX mode bits), where NTFS ACLs would be the
        # real mechanism; not implemented here to keep this dependency-free.
        os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


@dataclass
class DbConnectionConfig:
    engine: str | None = None
    host: str = ""
    port: int = 0
    database: str | None = None
    username: str = ""
    encrypted_password: str = ""
    ssl: bool = False


@dataclass
class ConnectorConfig:
    backend_url: str = "http://localhost:8000/api/v1"
    connector_id: int | None = None
    encrypted_token: str | None = None
    db_connection: DbConnectionConfig | None = None
    poll_interval_seconds: float = 3.0

    @property
    def is_registered(self) -> bool:
        return self.connector_id is not None and self.encrypted_token is not None

    @property
    def token(self) -> str | None:
        return decrypt(self.encrypted_token) if self.encrypted_token else None

    @property
    def db_password(self) -> str | None:
        if not self.db_connection or not self.db_connection.encrypted_password:
            return None
        return decrypt(self.db_connection.encrypted_password)


def load_config() -> ConnectorConfig:
    if not CONFIG_FILE.exists():
        return ConnectorConfig()
    data = json.loads(CONFIG_FILE.read_text())
    db_conn = DbConnectionConfig(**data["db_connection"]) if data.get("db_connection") else None
    data["db_connection"] = db_conn
    return ConnectorConfig(**data)


def save_config(config: ConnectorConfig) -> None:
    data = asdict(config)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))

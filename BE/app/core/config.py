from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENV: str = "development"

    DATABASE_URL: str = "postgresql+asyncpg://plantwise:plantwise@localhost:5433/plantwise"

    JWT_SECRET: str = "dev-only-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    # Encrypts stored Database Import credentials at rest (persistent Cloud
    # DB connections only — the default one-time-import mode never persists
    # credentials at all, see core/credential_crypto.py). Dev-only value
    # below is a fixed, publicly-known Fernet key — production must set a
    # real one from its secrets manager/KMS via the env var.
    DB_CRED_ENCRYPTION_KEY: str = "YbECEYkR9gS0b4cgTKQRQ5Wm4WSV89jXeQ9GJC2V2-8="

    OPENAI_API_KEY: str = ""
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"

    # Open-source, local embedding model (fastembed / ONNX) — see core/llm.py.
    # BAAI/bge-base-en-v1.5 outputs 768-dim vectors; keep in sync with
    # core/vectorstore.py:EMBEDDING_DIM if this is ever changed.
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@plantwise.local"

    FRONTEND_URL: str = "http://192.168.13.134:4173"
    CORS_ORIGINS: list[str] = ["http://192.168.13.134:4173"]

    # Production-only settings
    ALLOWED_HOSTS: str = ""          # comma-separated, e.g. "example.com,www.example.com"
    RATE_LIMIT: str = "100/minute"   # per-IP rate limit
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600      # seconds

    MAX_UPLOAD_SIZE_MB: int = 50     # maximum CSV upload size in MB

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def model_post_init(self, _context) -> None:
        if self.ENV == "production":
            if self.JWT_SECRET == "dev-only-secret-change-me":
                raise ValueError(
                    "JWT_SECRET must be changed from the dev default in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            if not self.SMTP_HOST:
                # auth/service.py auto-verifies signups/invites whenever
                # SMTP_HOST is unset (a deliberate dev convenience so local
                # dev doesn't need a mail server) — PRD §5.1/§5.1.1 requires
                # email verification in production, so a real deployment
                # that simply hasn't configured SMTP yet must fail loudly at
                # startup rather than silently skip verification for every
                # signup and invite.
                raise ValueError(
                    "SMTP_HOST must be configured in production — without it, email verification and "
                    "invite/alert emails are silently skipped (see auth/service.py's auto_verify)."
                )
            if self.DB_CRED_ENCRYPTION_KEY == "YbECEYkR9gS0b4cgTKQRQ5Wm4WSV89jXeQ9GJC2V2-8=":
                raise ValueError(
                    "DB_CRED_ENCRYPTION_KEY must be changed from the dev default in production — it "
                    "encrypts stored Database Import credentials at rest. Generate one with: "
                    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )


settings = Settings()

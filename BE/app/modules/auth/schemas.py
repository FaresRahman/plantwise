from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    tenant_id: int
    email: str
    full_name: str
    role: str
    is_verified: bool

    model_config = {"from_attributes": True}


class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str = "operator"


class BulkInviteEntry(BaseModel):
    email: EmailStr
    # Full name is optional here (unlike the single-invite endpoint) — bulk
    # invites are typically pasted from a list of addresses without names
    # handy, so the backend derives a reasonable display name from the email
    # local-part rather than making that a required field the admin has to
    # fill in one-by-one.
    full_name: str | None = None
    role: str | None = None


class BulkInviteRequest(BaseModel):
    invites: list[BulkInviteEntry] = Field(min_length=1, max_length=50)
    default_role: str = "operator"


class BulkInviteError(BaseModel):
    email: str
    message: str


class BulkInviteResult(BaseModel):
    invited: list[UserOut]
    errors: list[BulkInviteError]


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.config import settings
from app.core.email import send_email
from app.core.models_shared import Tenant
from app.core.security import create_token, decode_access_token, hash_password, verify_password
from app.modules.auth.models import User
from app.modules.auth.schemas import BulkInviteEntry, SignupRequest


class AuthError(Exception):
    pass


async def signup(db: AsyncSession, payload: SignupRequest) -> User:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise AuthError("An account with this email already exists")

    tenant = Tenant(name=payload.tenant_name)
    db.add(tenant)
    await db.flush()  # get tenant.id without a full commit

    # When SMTP_HOST is empty (dev mode), auto-verify the user so the
    # signup→login flow works end-to-end without a real mail server.
    auto_verify = not settings.SMTP_HOST

    user = User(
        tenant_id=tenant.id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role="admin",  # the person who signs up and creates the tenant is its Admin
        is_verified=auto_verify,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await log_audit(
        db, tenant.id, user.id, action="signup", entity_type="tenant",
        entity_id=tenant.id, details=f"tenant={tenant.name} email={user.email}",
    )

    _send_verification_email(user)
    return user


async def login(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.hashed_password):
        raise AuthError("Invalid email or password")
    if not user.is_verified:
        raise AuthError("Please verify your email before logging in")
    if not user.is_active:
        raise AuthError("This account has been deactivated")
    return user


async def verify_email(db: AsyncSession, token: str) -> User:
    try:
        payload = decode_access_token(token)
    except Exception:
        raise AuthError("Invalid or expired verification link")
    if payload.get("purpose") != "verify_email":
        raise AuthError("Invalid verification token")

    user = await db.get(User, int(payload["sub"]))
    if not user:
        raise AuthError("User not found")
    user.is_verified = True
    await db.commit()
    return user


async def invite_user(db: AsyncSession, tenant_id: int, email: str, full_name: str, role: str, inviter_name: str) -> User:
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise AuthError("An account with this email already exists")
    if role not in ("admin", "operator", "viewer"):
        raise AuthError(f"Unknown role '{role}'")

    tenant = await db.get(Tenant, tenant_id)
    tenant_name = tenant.name if tenant else "Plantwise"

    role_label = {"admin": "Administrator", "operator": "Operator", "viewer": "Viewer"}.get(role, role)

    # Same dev-mode auto-verify for invited users — no email round-trip needed.
    auto_verify = not settings.SMTP_HOST

    user = User(
        tenant_id=tenant_id,
        email=email,
        hashed_password=hash_password(""),  # unusable until accept_invite sets a real one
        full_name=full_name,
        role=role,
        is_verified=auto_verify,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_token({"sub": str(user.id), "purpose": "accept_invite"}, expires_minutes=60 * 24 * 7)
    link = f"{settings.FRONTEND_URL}/accept-invite?token={token}"

    html = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f7fa; padding:40px 0; margin:0">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 2px 12px rgba(0,0,0,.08)">
  <tr>
    <td style="background:#101010; padding:32px 40px">
      <h1 style="color:#F5C518; font-size:22px; margin:0; font-weight:600">Plantwise</h1>
    </td>
  </tr>
  <tr>
    <td style="padding:40px">
      <h2 style="color:#1a1a2e; font-size:18px; margin:0 0 8px; font-weight:600">You've been invited to {tenant_name}</h2>
      <p style="color:#555; font-size:15px; line-height:1.6; margin:0 0 12px">
        {inviter_name} has invited you to join <strong>{tenant_name}</strong> on Plantwise as a <strong>{role_label}</strong>.
      </p>
      <p style="color:#555; font-size:15px; line-height:1.6; margin:0 0 24px">
        Click below to set your password and get started.
      </p>
      <a href="{link}" style="display:inline-block; background:#F5C518; color:#14110A; text-decoration:none; padding:14px 32px; border-radius:8px; font-size:15px; font-weight:600">Set your password</a>
      <p style="color:#888; font-size:13px; line-height:1.6; margin:24px 0 0">
        Or paste this link in your browser:<br>
        <a href="{link}" style="color:#C99E0E; word-break:break-all">{link}</a>
      </p>
      <p style="color:#aaa; font-size:12px; line-height:1.6; margin:32px 0 0; border-top:1px solid #eaeaea; padding-top:20px">
        This invitation link expires in 7 days. If you weren't expecting this, you can safely ignore this email.
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>
"""

    send_email(
        to=[email],
        subject=f"{inviter_name} invited you to {tenant_name} on Plantwise",
        html_body=html,
    )
    return user


def _derive_full_name(email: str) -> str:
    """Bulk invites are commonly pasted as a list of bare addresses with no
    name handy — rather than force one-by-one entry to fill in a name, derive
    a reasonable display name from the local-part (e.g. "jane.doe" ->
    "Jane Doe"). It's editable later from the admin console like any name.
    """
    local = email.split("@", 1)[0]
    parts = [p for p in re.split(r"[._\-+0-9]+", local) if p]
    return " ".join(p.capitalize() for p in parts) or local


async def invite_users_bulk(
    db: AsyncSession, tenant_id: int, entries: list[BulkInviteEntry], default_role: str, inviter_name: str
) -> tuple[list[User], list[dict]]:
    """Invite many users at once — the multi-email alternative to submitting
    the single-invite form once per teammate. Each entry can override the
    role; entries without one fall back to default_role. A bad entry (e.g.
    duplicate email) is collected as an error rather than aborting the whole
    batch, so the rest of a large paste still goes through.
    """
    invited: list[User] = []
    errors: list[dict] = []
    for entry in entries:
        role = entry.role or default_role
        full_name = entry.full_name or _derive_full_name(entry.email)
        try:
            user = await invite_user(db, tenant_id, entry.email, full_name, role, inviter_name)
            invited.append(user)
        except AuthError as exc:
            errors.append({"email": entry.email, "message": str(exc)})
    return invited, errors


async def accept_invite(db: AsyncSession, token: str, password: str) -> User:
    try:
        payload = decode_access_token(token)
    except Exception:
        raise AuthError("Invalid or expired invite link")
    if payload.get("purpose") != "accept_invite":
        raise AuthError("Invalid invite token")

    user = await db.get(User, int(payload["sub"]))
    if not user:
        raise AuthError("User not found")
    user.hashed_password = hash_password(password)
    user.is_verified = True
    await db.commit()
    return user


def _send_verification_email(user: User) -> None:
    token = create_token({"sub": str(user.id), "purpose": "verify_email"}, expires_minutes=60 * 24)
    link = f"{settings.FRONTEND_URL}/verify?token={token}"

    if not settings.SMTP_HOST:
        print(f"[email:dev-mode] User {user.email} auto-verified (SMTP_HOST is empty).")
        print(f"[email:dev-mode] Verification link (for reference): {link}")
        return

    html = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f7fa; padding:40px 0; margin:0">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 2px 12px rgba(0,0,0,.08)">
  <tr>
    <td style="background:#101010; padding:32px 40px">
      <h1 style="color:#F5C518; font-size:22px; margin:0; font-weight:600">Plantwise</h1>
    </td>
  </tr>
  <tr>
    <td style="padding:40px">
      <h2 style="color:#1a1a2e; font-size:18px; margin:0 0 12px; font-weight:600">Verify your email address</h2>
      <p style="color:#555; font-size:15px; line-height:1.6; margin:0 0 24px">
        Thanks for signing up, {user.full_name}. Click the button below to confirm your email and activate your account.
      </p>
      <a href="{link}" style="display:inline-block; background:#F5C518; color:#14110A; text-decoration:none; padding:14px 32px; border-radius:8px; font-size:15px; font-weight:600">Verify your email</a>
      <p style="color:#888; font-size:13px; line-height:1.6; margin:24px 0 0">
        Or paste this link in your browser:<br>
        <a href="{link}" style="color:#C99E0E; word-break:break-all">{link}</a>
      </p>
      <p style="color:#aaa; font-size:12px; line-height:1.6; margin:32px 0 0; border-top:1px solid #eaeaea; padding-top:20px">
        This link expires in 24 hours. If you didn't create this account, you can safely ignore this email.
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>
"""

    send_email(
        to=[user.email],
        subject="Verify your Plantwise account",
        html_body=html,
    )

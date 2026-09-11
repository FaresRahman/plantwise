from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.module_registry import ModuleRegistration, register_module
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.modules.auth import service
from app.modules.auth.schemas import (
    AcceptInviteRequest,
    BulkInviteRequest,
    BulkInviteResult,
    InviteRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "auth", "status": "ok"}


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db), request: Request = None):
    try:
        user = await service.signup(db, payload)
    except service.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db), request: Request = None):
    try:
        user = await service.login(db, payload.email, payload.password)
    except service.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.get("/verify")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    try:
        await service.verify_email(db, token)
    except service.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "verified"}


@router.post("/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def invite(
    request: Request,
    payload: InviteRequest,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_role("admin")),
):
    try:
        user = await service.invite_user(db, admin.tenant_id, payload.email, payload.full_name, payload.role, admin.full_name)
    except service.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        db, admin.tenant_id, admin.id, action="invite_user", entity_type="user", entity_id=user.id,
        details=f"email={user.email} role={user.role}",
    )
    return user


@router.post("/invite-bulk", response_model=BulkInviteResult)
@limiter.limit("10/minute")
async def invite_bulk(
    request: Request,
    payload: BulkInviteRequest,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_role("admin")),
):
    """Invite several teammates in one submit instead of the single-invite
    form once per person — full_name is optional per entry (derived from the
    email if omitted) since a bulk paste is usually just a list of addresses.
    """
    invited, errors = await service.invite_users_bulk(db, admin.tenant_id, payload.invites, payload.default_role, admin.full_name)
    for user in invited:
        await log_audit(
            db, admin.tenant_id, admin.id, action="invite_user", entity_type="user", entity_id=user.id,
            details=f"email={user.email} role={user.role}",
        )
    return BulkInviteResult(invited=invited, errors=errors)


@router.post("/accept-invite", response_model=TokenResponse)
@limiter.limit("10/minute")
async def accept_invite(request: Request, payload: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await service.accept_invite(db, payload.token, payload.password)
    except service.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return user


register_module(
    ModuleRegistration(
        key="auth",
        prefix="auth",
        router=router,
        get_summary=None,
        get_shift_contribution=None,
    )
)

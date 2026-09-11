"""Dev A calls these two functions from day one (predictive-maintenance
recommendations, inventory low-stock, quality-trend flags). Signatures are
final — do not change them without telling Dev A. Fill in the real behavior
(AlertSetting thresholds, recipients, dedup, templated email) behind them;
until then they just log to console so callers aren't blocked.

See DEV_BRIEF_TEAMMATE.md section 5.1.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import send_email
from app.modules.notifications.models import AlertSetting, SentAlert
from app.modules.notifications.schemas import AlertSettingOut


def _absolute_link(path: str) -> str:
    """Callers pass a frontend-relative path (e.g. "/inventory"). A bare
    relative link is meaningless inside an email client (there's no page
    origin to resolve it against), so always resolve against FRONTEND_URL
    before it goes in an <a href>.
    """
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{settings.FRONTEND_URL.rstrip('/')}{path if path.startswith('/') else f'/{path}'}"

_URGENCY_RANK = {"low": 0, "med": 1, "high": 2}

# Hard-coded fallback when a tenant hasn't configured a module yet.
# Predictive-maintenance is on by default at High per the PRD's hard v1
# requirement; every other module's alerts are opt-in (off by default).
DEFAULT_SETTINGS: dict[str, AlertSettingOut] = {
    "predictive_maintenance": AlertSettingOut(
        module="predictive_maintenance", urgency_threshold="high", enabled=True, recipients=[]
    ),
}


def _default_for(module: str) -> AlertSettingOut:
    return DEFAULT_SETTINGS.get(
        module, AlertSettingOut(module=module, urgency_threshold="high", enabled=False, recipients=[])
    )


async def get_setting(db: AsyncSession, tenant_id: int, module: str) -> AlertSettingOut:
    row = await db.scalar(
        select(AlertSetting).where(AlertSetting.tenant_id == tenant_id, AlertSetting.module == module)
    )
    if row is None:
        return _default_for(module)
    return AlertSettingOut(
        module=row.module, urgency_threshold=row.urgency_threshold, enabled=row.enabled, recipients=row.recipients
    )


async def upsert_setting(
    db: AsyncSession, tenant_id: int, module: str, urgency_threshold: str, enabled: bool, recipients: list[str]
) -> AlertSettingOut:
    row = await db.scalar(
        select(AlertSetting).where(AlertSetting.tenant_id == tenant_id, AlertSetting.module == module)
    )
    if row is None:
        row = AlertSetting(tenant_id=tenant_id, module=module)
        db.add(row)
    row.urgency_threshold = urgency_threshold
    row.enabled = enabled
    row.recipients = recipients
    await db.commit()
    return AlertSettingOut(module=module, urgency_threshold=urgency_threshold, enabled=enabled, recipients=recipients)


async def _role_recipients(db: AsyncSession, tenant_id: int, roles: tuple[str, ...]) -> list[str]:
    # Read-only cross-module query into auth's User model — the same kind of
    # reach the brief explicitly sanctions (Quality reading Production's
    # query functions) rather than duplicating user data here.
    from app.modules.auth.models import User

    result = await db.scalars(
        select(User.email).where(User.tenant_id == tenant_id, User.role.in_(roles), User.is_verified.is_(True))
    )
    return list(result)


def _recommendation_email(
    asset_name: str, issue: str, evidence: str, recommended_action: str,
    urgency: str, estimated_window: str, dashboard_link: str,
) -> str:
    urgency_color = {"high": "#D42E22", "med": "#C76F14", "low": "#0C6EC4"}.get(urgency, "#6b7280")
    urgency_bg = {"high": "#FFF1F0", "med": "#FDF2E6", "low": "#EBF6FF"}.get(urgency, "#f9fafb")
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f7fa; padding:40px 0; margin:0">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 2px 12px rgba(0,0,0,.08)">
  <tr>
    <td style="background:{urgency_color}; padding:20px 40px">
      <h1 style="color:#fff; font-size:18px; margin:0; font-weight:600">Plantwise — {urgency.upper()} Urgency Alert</h1>
    </td>
  </tr>
  <tr>
    <td style="padding:32px 40px">
      <div style="background:{urgency_bg}; border-left:4px solid {urgency_color}; padding:16px 20px; border-radius:6px; margin-bottom:24px">
        <p style="color:#111; font-size:16px; font-weight:700; margin:0 0 4px">{issue}</p>
        <p style="color:{urgency_color}; font-size:14px; font-weight:600; margin:0">{asset_name}</p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px">
        <tr><td style="padding:8px 0; font-size:13px; color:#888; font-weight:600; width:140px">Evidence</td><td style="padding:8px 0; font-size:14px; color:#333">{evidence}</td></tr>
        <tr><td style="padding:8px 0; font-size:13px; color:#888; font-weight:600">Recommended action</td><td style="padding:8px 0; font-size:14px; color:#333">{recommended_action}</td></tr>
        <tr><td style="padding:8px 0; font-size:13px; color:#888; font-weight:600">Estimated window</td><td style="padding:8px 0; font-size:14px; color:#333">{estimated_window}</td></tr>
      </table>
      <a href="{_absolute_link(dashboard_link)}" style="display:inline-block; background:{urgency_color}; color:#fff; text-decoration:none; padding:14px 32px; border-radius:8px; font-size:15px; font-weight:600">View on dashboard</a>
      <p style="color:#aaa; font-size:12px; line-height:1.6; margin:24px 0 0; border-top:1px solid #eaeaea; padding-top:20px">
        This is an automated alert from Plantwise. You received this because you are an Admin or Operator.
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


async def trigger_recommendation_alert(
    db: AsyncSession,
    tenant_id: int,
    asset_name: str,
    issue: str,
    evidence: str,
    recommended_action: str,
    urgency: Literal["low", "med", "high"],
    estimated_window: str,
    dashboard_link: str,
) -> None:
    # Don't send alerts until onboarding is complete — recommendations are still
    # computed and stored, but the plant isn't operational yet and the team may
    # not be fully configured (BRD §6.1: onboarding is a setup-only phase).
    from app.modules.onboarding.service import is_onboarding_complete
    if not await is_onboarding_complete(db, tenant_id):
        return

    setting = await get_setting(db, tenant_id, "predictive_maintenance")
    if not setting.enabled:
        return
    if _URGENCY_RANK[urgency] < _URGENCY_RANK[setting.urgency_threshold]:
        return

    sent = await db.scalar(
        select(SentAlert).where(
            SentAlert.tenant_id == tenant_id, SentAlert.asset_name == asset_name, SentAlert.issue == issue
        )
    )
    if sent and _URGENCY_RANK[urgency] <= _URGENCY_RANK[sent.last_urgency]:
        return  # still-open at same/lower urgency — don't re-send

    recipients = await _role_recipients(db, tenant_id, ("admin", "operator"))
    recipients = sorted(set(recipients) | set(setting.recipients))

    send_email(
        to=recipients,
        subject=f"[{urgency.upper()}] Maintenance recommendation: {asset_name}",
        html_body=_recommendation_email(
            asset_name, issue, evidence, recommended_action, urgency, estimated_window, dashboard_link
        ),
    )

    if sent:
        sent.last_urgency = urgency
    else:
        db.add(SentAlert(tenant_id=tenant_id, asset_name=asset_name, issue=issue, last_urgency=urgency))
    await db.commit()


async def clear_sent_alert(db: AsyncSession, tenant_id: int, asset_name: str, issue: str) -> None:
    """Call this when a recommendation closes (actioned/dismissed). The
    de-dup ledger is scoped to "still-open" recommendations per the PRD
    (§5.6) — without clearing it here, a brand-new recurrence of the same
    asset+issue after closure would be silently suppressed forever instead of
    alerting again like a fresh occurrence should.
    """
    sent = await db.scalar(
        select(SentAlert).where(
            SentAlert.tenant_id == tenant_id, SentAlert.asset_name == asset_name, SentAlert.issue == issue
        )
    )
    if sent:
        await db.delete(sent)
        await db.commit()


async def trigger_generic_alert(
    db: AsyncSession,
    tenant_id: int,
    module: str,
    title: str,
    message: str,
    dashboard_link: str,
) -> None:
    setting = await get_setting(db, tenant_id, module)
    if not setting.enabled:
        return

    # Dedup: use module as asset_name and title as issue so the same
    # SentAlert ledger that serves predictive-maintenance also prevents
    # noisy repeats for low-stock / quality-trend / missing-data alerts.
    existing = await db.scalar(
        select(SentAlert).where(
            SentAlert.tenant_id == tenant_id,
            SentAlert.asset_name == module,
            SentAlert.issue == title,
        )
    )
    if existing:
        return  # already sent — don't spam

    recipients = await _role_recipients(db, tenant_id, ("admin", "operator"))
    recipients = sorted(set(recipients) | set(setting.recipients))
    if not recipients:
        # Nothing to actually send — don't record a dedup row for an alert
        # that never went anywhere, or a later attempt (once recipients
        # exist) would be silently suppressed forever by this no-op.
        return

    send_email(
        to=recipients,
        subject=f"[Plantwise] {title}",
        html_body=(
            f"<h2 style='color:#14110A'>{title}</h2><p style='color:#333'>{message}</p>"
            f"<p><a href='{_absolute_link(dashboard_link)}' "
            f"style='display:inline-block; background:#F5C518; color:#14110A; text-decoration:none; "
            f"padding:10px 22px; border-radius:8px; font-size:14px; font-weight:600'>View on dashboard</a></p>"
        ),
    )

    # Recorded after the send attempt (matches trigger_recommendation_alert's
    # ordering) rather than before it — previously this committed first, so
    # an empty-recipients case or a raised send error would still mark the
    # alert "sent" and permanently suppress it.
    db.add(SentAlert(tenant_id=tenant_id, asset_name=module, issue=title, last_urgency=""))
    await db.commit()


async def clear_generic_alert(db: AsyncSession, tenant_id: int, module: str, title: str) -> None:
    """Mirrors clear_sent_alert for the generic (non-PM) alert path. Call
    this once the underlying condition (low stock, defect spike, tolerance
    drift, missing data) is confirmed resolved — without it, a generic alert
    never re-fires on recurrence even after the title's condition genuinely
    went away and came back, unlike PM's escalation/re-open model.
    """
    existing = await db.scalar(
        select(SentAlert).where(
            SentAlert.tenant_id == tenant_id, SentAlert.asset_name == module, SentAlert.issue == title
        )
    )
    if existing:
        await db.delete(existing)
        await db.commit()


async def check_missing_data(db: AsyncSession, tenant_id: int) -> None:
    """BRD §5.4/§6.2: 'if a module's expected upload/entry hasn't arrived,
    nudge the responsible role.' Classified by §5.6 alongside low-stock and
    quality-trend as an 'other alert' — off by default, per-tenant
    configurable, using the same trigger_generic_alert path (no separate
    enable/threshold logic needed).

    No cron in v1 (per the brief's own "a simple scheduled check is fine"
    allowance) — this runs opportunistically whenever the dashboard is
    loaded, gated by last_nudged_at so it fires at most once per cadence
    window rather than on every page view.
    """
    from app.core.models_shared import ModuleFreshness

    now = datetime.now(timezone.utc)
    rows = list(await db.scalars(select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id)))

    for row in rows:
        last_updated = row.last_updated_at
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        if now - last_updated <= timedelta(hours=row.expected_cadence_hours):
            # Fresh again — clear any standing "overdue" alert so a future
            # recurrence of the same module going stale re-nudges instead of
            # being silently suppressed by the earlier SentAlert row.
            title = row.module.replace("_", " ").title()
            await clear_generic_alert(db, tenant_id, "missing_data", f"{title} data is overdue")
            continue

        last_nudged = row.last_nudged_at
        if last_nudged is not None:
            if last_nudged.tzinfo is None:
                last_nudged = last_nudged.replace(tzinfo=timezone.utc)
            if now - last_nudged <= timedelta(hours=row.expected_cadence_hours):
                continue  # already nudged this cadence window

        title = row.module.replace("_", " ").title()
        # Gate on a dedicated "missing_data" setting, NOT `row.module` itself —
        # predictive_maintenance's own AlertSetting defaults to enabled=True,
        # but that default is specifically for its recommendation alerts
        # (§5.6). Missing-data nudges are "off by default" for every module
        # per that same section, so they need their own, separately-off
        # toggle rather than inheriting PM's unrelated default.
        await trigger_generic_alert(
            db,
            tenant_id,
            "missing_data",
            title=f"{title} data is overdue",
            message=(
                f"{title} hasn't been updated since {last_updated.strftime('%Y-%m-%d %H:%M UTC')} "
                f"(expected every {row.expected_cadence_hours}h). Please upload today's data."
            ),
            dashboard_link=f"/{row.module.replace('_', '-')}",
        )
        row.last_nudged_at = now.replace(tzinfo=None)
        await db.commit()


async def send_daily_digest(db: AsyncSession, tenant_id: int) -> dict:
    """Optional daily digest of open recommendations/flags (PRD §5.6 —
    explicitly [ASSUMPTION]/nice-to-have, off by default). Gated by the same
    per-tenant AlertSetting pattern as every other alert type, keyed under the
    "daily_digest" pseudo-module (not tied to any single data module).

    No cron in v1: an Admin triggers it via POST /notifications/digest/send,
    the same "generate now" convention Shift Reports already uses instead of
    a real scheduler.
    """
    from app.core import module_registry

    setting = await get_setting(db, tenant_id, "daily_digest")
    if not setting.enabled:
        return {"sent": False, "reason": "daily digest is disabled for this tenant"}

    sections: list[str] = []
    total_alerts = 0
    for registration in module_registry.MODULES:
        if registration.get_summary is None:
            continue
        summary = await registration.get_summary(db, tenant_id)
        if summary.alerts_count > 0:
            total_alerts += summary.alerts_count
            sections.append(
                f"<li><strong>{summary.title}:</strong> {summary.headline} ({summary.alerts_count} alert(s))</li>"
            )

    body = f"<ul>{''.join(sections)}</ul>" if sections else "<p>No open recommendations or flags across any module.</p>"

    recipients = await _role_recipients(db, tenant_id, ("admin", "operator"))
    recipients = sorted(set(recipients) | set(setting.recipients))
    if not recipients:
        return {"sent": False, "reason": "no recipients configured"}

    send_email(
        to=recipients,
        subject=f"[Plantwise] Daily summary — {total_alerts} open alert(s)",
        html_body=(
            f"<h2 style='color:#14110A'>Daily Summary</h2><div style='color:#333'>{body}</div>"
            f"<p><a href='{_absolute_link('/dashboard')}' "
            f"style='display:inline-block; background:#F5C518; color:#14110A; text-decoration:none; "
            f"padding:10px 22px; border-radius:8px; font-size:14px; font-weight:600'>View dashboard</a></p>"
        ),
    )
    return {"sent": True, "recipients": recipients, "total_alerts": total_alerts}

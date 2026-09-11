"""Minimal local config UI — served on localhost only, for the customer to
paste their registration key and configure the one database connection
this connector relays. This is deliberately plain (no build step, no JS
framework): it's an admin tool for one person on one machine, not a
product surface.
"""
from __future__ import annotations

import html
import logging
from urllib.parse import quote

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app import api_client
from app.config import ConnectorConfig, DbConnectionConfig, encrypt, load_config, save_config
from db_adapters import AdapterError, ConnectionParams, PrerequisiteMissingError, get_adapter_class
from db_adapters.registry import detect_engine

logger = logging.getLogger("connector.web")

app = FastAPI(title="Plantwise Local Connector")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} | Plantwise Connector</title>
<style>
  :root {{
    --ink: #0A0A09; --secondary: #54544D; --tertiary: #9B9B94;
    --border: #DEDEDA; --border-subtle: #EBEBE8; --surface: #FFFFFF; --bg: #F5F5F4;
    --gold: #F5C518; --gold-ink: #14110A; --gold-dark: #C99E0E;
    --success: #158A4C; --error: #AB2419;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 640px; margin: 0 auto; padding: 0 0 40px; color: var(--ink); background: var(--bg); }}
  .chrome {{ background: #101010; color: #FFFFFF; padding: 18px 20px; display: flex; align-items: center; gap: 10px; margin-bottom: 28px; }}
  .chrome .led {{ width: 8px; height: 8px; border-radius: 50%; background: var(--gold); flex: none; }}
  .chrome .name {{ font-size: 15px; font-weight: 700; letter-spacing: .01em; }}
  .content {{ padding: 0 20px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ font-size: 14px; font-weight: 700; color: var(--ink); margin: 0 0 12px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin: 16px 0; }}
  label {{ display: block; font-size: 13px; font-weight: 600; margin: 12px 0 5px; }}
  input, select {{ width: 100%; padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; box-sizing: border-box; background: var(--surface); color: var(--ink); }}
  input:focus, select:focus {{ outline: none; border-color: var(--gold-dark); box-shadow: 0 0 0 3px rgba(245,197,24,0.25); }}
  button {{ margin-top: 18px; margin-right: 8px; padding: 10px 18px; border: 1px solid var(--gold-dark); border-radius: 8px; background: var(--gold); color: var(--gold-ink); font-size: 13.5px; font-weight: 700; cursor: pointer; }}
  button:hover {{ background: var(--gold-dark); }}
  .ok {{ color: var(--success); font-weight: 600; font-size: 13.5px; }}
  .err {{ color: var(--error); font-weight: 600; font-size: 13.5px; }}
  .muted {{ color: var(--secondary); font-size: 13px; line-height: 1.6; }}
  a {{ color: var(--gold-dark); text-decoration: none; font-weight: 600; }}
  a:hover {{ text-decoration: underline; }}
</style></head>
<body>
<div class="chrome"><span class="led"></span><span class="name">Plantwise Local Connector</span></div>
<div class="content">{body}</div>
</body></html>""")


@app.get("/", response_class=HTMLResponse)
async def status_page():
    config = load_config()
    reg_status = (
        f'<p class="ok">Registered, connector id {config.connector_id}</p>'
        if config.is_registered
        else '<p class="err">Not registered yet</p>'
    )
    db_status = (
        f'<p class="ok">Configured: {html.escape(config.db_connection.engine or "(auto-detect)")} at '
        f'{html.escape(config.db_connection.host)}:{config.db_connection.port}</p>'
        if config.db_connection
        else '<p class="err">No database connection configured</p>'
    )
    both_done = config.is_registered and config.db_connection is not None
    flow_status = (
        "<p class=\"ok\">Both steps are done. This app is checking in with Plantwise and keeping your data synced.</p>"
        if both_done
        else "<p class=\"muted\">Finish both steps below to start syncing.</p>"
    )
    body = f"""
    <div class="card">
      <h2>How this works</h2>
      {flow_status}
      <p class="muted">
        1. Register this connector once, using a key from the Plantwise dashboard.<br>
        2. Tell it how to reach your database, right here on this computer.<br>
        3. Leave this app running. It checks in with Plantwise every {config.poll_interval_seconds:g} seconds, and
        whenever the dashboard needs a fresh read from your database, this app fetches it and sends it back.
        Nothing is ever pushed to your database from outside, and your database password never leaves this
        computer.
      </p>
    </div>
    <div class="card">
      <h2>Registration</h2>
      {reg_status}
      <p class="muted">Backend: {html.escape(config.backend_url)}</p>
      <a href="/register">Register or re-register</a>
    </div>
    <div class="card">
      <h2>Database connection</h2>
      {db_status}
      <a href="/connection">Configure database connection</a>
    </div>
    <p class="muted">Logs are saved to connector.log next to this app's config directory.</p>
    """
    return _page("Status", body)


@app.get("/register", response_class=HTMLResponse)
async def register_form(error: str | None = None):
    config = load_config()
    error_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    body = f"""
    <h1>Register this connector</h1>
    <p class="muted">Generate a registration key from the Plantwise dashboard, under Admin, then Data Sources, then
    Connectors. Paste that key here.</p>
    {error_html}
    <form method="post" action="/register" class="card">
      <label>Backend URL</label>
      <input name="backend_url" value="{html.escape(config.backend_url)}" required />
      <label>Registration key</label>
      <input name="registration_key" placeholder="Paste the key from the dashboard" required />
      <button type="submit">Register</button>
    </form>
    <p><a href="/">Back to status</a></p>
    """
    return _page("Register", body)


@app.post("/register")
async def do_register(backend_url: str = Form(...), registration_key: str = Form(...)):
    try:
        registration = await api_client.register(backend_url.rstrip("/"), registration_key.strip())
    except api_client.ApiClientError as exc:
        return RedirectResponse(f"/register?error={quote(str(exc))}", status_code=303)

    config = load_config()
    config.backend_url = backend_url.rstrip("/")
    config.encrypted_token = encrypt(registration["connector_token"])
    config.connector_id = registration["connector_id"]
    save_config(config)
    logger.info("registered as connector %s (%s)", registration["connector_id"], registration["connector_name"])
    return RedirectResponse("/", status_code=303)


@app.get("/connection", response_class=HTMLResponse)
async def connection_form(error: str | None = None, ok: str | None = None):
    config = load_config()
    dbc = config.db_connection or DbConnectionConfig()
    error_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    ok_html = f'<p class="ok">{html.escape(ok)}</p>' if ok else ""
    body = f"""
    <h1>Database connection</h1>
    <p class="muted">Read-only access is strongly recommended. Create a database user with SELECT-only permissions.</p>
    {error_html}{ok_html}
    <form method="post" action="/connection" class="card">
      <label>Host or IP address</label>
      <input name="host" value="{html.escape(dbc.host)}" required />
      <label>Port</label>
      <input name="port" type="number" value="{dbc.port or ''}" required />
      <label>Database name (optional)</label>
      <input name="database" value="{html.escape(dbc.database or '')}" />
      <label>Username</label>
      <input name="username" value="{html.escape(dbc.username)}" required />
      <label>Password</label>
      <input name="password" type="password" placeholder="{'Unchanged' if dbc.encrypted_password else ''}" />
      <label><input name="ssl" type="checkbox" style="width:auto;display:inline-block" {"checked" if dbc.ssl else ""} /> Use SSL</label>
      <button type="submit" name="action" value="test">Test connection</button>
      <button type="submit" name="action" value="save">Save</button>
    </form>
    <p><a href="/">Back to status</a></p>
    """
    return _page("Database connection", body)


@app.post("/connection")
async def do_connection(
    action: str = Form(...),
    host: str = Form(...),
    port: int = Form(...),
    database: str = Form(""),
    username: str = Form(...),
    password: str = Form(""),
    ssl: bool = Form(False),
):
    config = load_config()
    existing_password = config.db_password if config.db_connection else None
    effective_password = password or existing_password or ""

    params = ConnectionParams(host=host, port=port, username=username, password=effective_password, database=database or None, ssl=ssl)
    try:
        detection = await detect_engine(params, include_local_only=True)
    except PrerequisiteMissingError as exc:
        return RedirectResponse(f"/connection?error={quote(str(exc))}", status_code=303)
    except AdapterError as exc:
        return RedirectResponse(f"/connection?error={quote(f'Could not connect: {exc}')}", status_code=303)

    if not detection["detected"]:
        return RedirectResponse("/connection?error=Could not connect. Check the host, port, and credentials.", status_code=303)
    engine = detection["detected"][0]

    if action == "test":
        return RedirectResponse(f"/connection?ok={quote(f'Connected successfully as {engine}.')}", status_code=303)

    config.db_connection = DbConnectionConfig(
        engine=engine, host=host, port=port, database=database or None, username=username,
        encrypted_password=encrypt(effective_password), ssl=ssl,
    )
    save_config(config)
    logger.info("database connection saved (%s at %s:%s)", engine, host, port)
    return RedirectResponse(f"/connection?ok={quote(f'Saved. Detected engine: {engine}.')}", status_code=303)

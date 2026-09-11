# Plantwise Local Connector

A small standalone application a customer installs inside their private
network to let Plantwise's Database Import feature reach a database that
isn't directly reachable from the cloud. It never accepts inbound
connections — it polls the Plantwise backend for work and posts results
back over outbound HTTPS only.

## How it works

1. An admin generates a **registration key** from the Plantwise dashboard
   (`POST /db-import/connectors`) and hands it to whoever installs the
   connector.
2. The connector's local config UI (`http://127.0.0.1:8765`, opens
   automatically on start) takes that key and exchanges it for a long-lived
   **connector token** (`POST /db-import/connectors/register`). Only a hash
   of the token is ever stored on the backend; only the token itself is
   stored locally (encrypted — see `app/config.py`).
3. The customer configures **one database connection** in the same local UI.
   Credentials never leave this machine — the backend never sees them.
4. The connector polls `GET /db-import/connector/jobs/next` every few
   seconds. When the dashboard enqueues a job (test/discover/read against
   this connector's database), the connector executes it locally using the
   same `db_adapters` package the cloud-direct import path uses, then posts
   the result to `POST /db-import/connector/jobs/{id}/result`.

## Running in development

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python main.py
```

Opens `http://127.0.0.1:8765` in your browser. Set `CONNECTOR_CONFIG_DIR`
to point config/logs somewhere other than the OS default app-data
directory (useful for running more than one instance side by side, e.g.
in tests).

## Building the packaged executable

```
.venv/Scripts/pyinstaller packaging/connector.spec --distpath dist --workpath build
```

Produces `dist/PlantwiseConnector.exe` (Windows) — a single file, no
separate Python install needed on the target machine.

## What's deliberately out of scope for this version

- **Auto-update.** Flagged from the start as a separate follow-up — it
  needs its own release/version-check channel design, not bundled into
  this pass.
- **Multiple database connections per connector install.** One connector,
  one database, matching the spec's "customer configures local database
  connection details" (singular). Running several connectors is how you'd
  cover several databases today.
- **Dashboard-side UI for browsing a connector's tables and feeding that
  into the same mapping/preview/commit flow Cloud DB Import uses.** The
  backend job-relay API this needs already exists and is verified working
  end-to-end (see below); wiring it into `DatabaseImportWizard` on the
  frontend is a distinct, sizable follow-up, not built in this pass.

## Verified

Live end-to-end smoke test against a real MySQL container: registered a
connector, configured + auto-detected its database connection, enqueued a
`discover_tables` job from the "dashboard" side, watched the connector poll,
execute, and report back, and confirmed the result on the backend. Not yet
verified: the actual packaged `.exe` (the spec is written but a full
PyInstaller build wasn't run in this session — freezing a working Python
app is comparatively low-risk, but it's still unverified until it's done).

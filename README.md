# Plantwise

Factory operations dashboard — production, quality, inventory, shift
reports, and equipment maintenance for a plant, in one place. Data comes in
either from manual entry, CSV/Excel uploads, or a direct connection to the
plant's own database through a small local connector app.

## Contents

- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Getting started](#getting-started)
- [Environment variables](#environment-variables)
- [Project structure](#project-structure)
- [Tests](#tests)
- [Docker / production](#docker--production)
- [Connector](#connector)
- [Troubleshooting](#troubleshooting)

## Architecture

```
FE (React SPA)  --->  BE (FastAPI)  --->  Postgres (+ pgvector)
                            ^
                            |
              Connector (customer's network) — pulls data from
              the customer's own database and syncs it to BE
```

- `FE/` — the dashboard users log into.
- `BE/` — the API. Owns auth, business logic, and the database.
- `BE/connector/` — a separate, standalone app. Packaged into a single
  `.exe` a customer runs on their own machine so Plantwise can read their
  database without that database being exposed to the internet. Built and
  shipped independently of the main backend.

## Tech stack

| | |
|---|---|
| Backend | FastAPI, SQLAlchemy (async), Alembic, Postgres + pgvector |
| Frontend | React, TypeScript, Vite, React Router |
| Auth | JWT |
| Chatbot / SOP search | OpenAI (chat) + a local embedding model (no API key needed for search) |
| Tests | pytest (backend), Vitest (frontend) |
| Deployment | Docker, Nginx (serves the frontend), Gunicorn + Uvicorn (backend) |

## Prerequisites

- Python 3.11+
- Node 18+
- Docker (for Postgres locally)

## Getting started

### 1. Database

```bash
cd BE
docker compose up -d
```

Starts Postgres on port **5433** (not 5432) so it doesn't clash with a
Postgres you might already have running.

### 2. Backend

```bash
cd BE
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env
python run.py dev
```

API runs at `http://localhost:8010`. Interactive API docs at
`http://localhost:8010/docs`.

### 3. Frontend

```bash
cd FE
npm install
copy .env.example .env        # macOS/Linux: cp .env.example .env
npm run dev
```

Dashboard runs at `http://localhost:5173`.

## Environment variables

Full list with comments is in `BE/.env.example` and `FE/.env.example`. The
ones you actually need to touch for local dev:

| Variable | Where | Required? | Notes |
|---|---|---|---|
| `JWT_SECRET` | `BE/.env` | Yes | Any long random string |
| `DATABASE_URL` | `BE/.env` | No | Default matches `docker compose up -d` above |
| `OPENAI_API_KEY` | `BE/.env` | No | Only needed for the SOP chatbot |
| `SMTP_HOST` | `BE/.env` | No | Leave blank to print emails to the console instead of sending |
| `VITE_API_URL` | `FE/.env` | Yes | Where the frontend sends API requests |

Never commit a real `.env` file — `.gitignore` already excludes them, keep
it that way.

## Project structure

```
BE/
  app/
    core/          shared infra — db, auth, config, db import adapters
    modules/        one folder per feature (production, quality, inventory,
                    predictive_maintenance, shift_reports, sop, admin, ...)
                    each with router.py / service.py / models.py / schemas.py
  alembic/          database migrations
  connector/        standalone customer-side connector app (see below)
  tests/

FE/
  src/
    api/            one file per backend module, typed request/response calls
    app/            routes, top-level layout
    auth/           login/signup/session handling
    modules/        one folder per feature, mirrors the backend modules
    components/     shared UI (buttons, tables, cards, etc.)
```

## Tests

```bash
cd BE && pytest
cd FE && npm test
```

## Docker / production

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Set `DB_PASSWORD`, `JWT_SECRET`, `OPENAI_API_KEY`, and the SMTP variables in
your shell or an `.env` file before running this — see
`docker-compose.prod.yml` for the full list. This brings up Postgres, the
API (Gunicorn + Uvicorn workers), and the frontend (Nginx) together.

## Connector

`BE/connector/` ships separately from the main backend — it's built with
PyInstaller into one `.exe` a customer downloads and runs on their own
network. See `BE/connector/README.md` for how to build and package it.

## Troubleshooting

- **Port 5433 already in use** — you likely have another Plantwise
  Postgres container running, or something else bound to it. Change the
  port mapping in `BE/docker-compose.yml` and update `DATABASE_URL` to match.
- **CORS errors in the browser** — `CORS_ORIGINS` in `BE/.env` needs to list
  every origin the frontend is actually served from (dev is `:5173`, prod
  preview is `:4173`). Only enforced when `ENV=production`.
- **Chatbot/SOP search not working** — check `OPENAI_API_KEY` is set; the
  embedding model itself doesn't need a key, but chat responses do.

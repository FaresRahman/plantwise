# Plantwise

Plantwise is a factory operations dashboard. It tracks production, quality,
inventory, shift reports, and equipment maintenance for a plant, and pulls
data in either from manual entry, CSV/Excel uploads, or a direct connection
to the plant's own database via a small local connector app.

It's split into two parts:

- `BE/` — FastAPI backend, Postgres (with pgvector for the SOP chatbot)
- `FE/` — React + TypeScript frontend, built with Vite

## Modules

- **Production** — line output, downtime, targets
- **Quality** — measurements, holds/releases
- **Inventory**
- **Predictive maintenance** — asset readings, failure recommendations
- **Shift reports**
- **SOP** — standard operating procedures + a chatbot that answers questions against them
- **Admin / onboarding** — tenant setup, user invites
- **DB import** — connect a customer's own database (Postgres, MySQL, MSSQL, Oracle, SQLite, and a few others) and pull data in on a schedule

## Running it locally

You'll need Python 3.11+, Node 18+, and Docker (for Postgres).

### 1. Database

```
cd BE
docker compose up -d
```

This starts Postgres on port 5433 (not 5432, so it doesn't clash with a
Postgres you might already have running locally).

### 2. Backend

```
cd BE
python -m venv .venv
.venv\Scripts\activate      # or source .venv/bin/activate on Mac/Linux
pip install -r requirements.txt
copy .env.example .env      # or cp on Mac/Linux — then fill in the values
python run.py dev
```

API comes up on `http://localhost:8010`.

At minimum, set `JWT_SECRET` in `.env` to something random. Everything else
has sane defaults for local dev — leave `OPENAI_API_KEY` blank if you don't
need the chatbot, and leave `SMTP_HOST` blank to have emails print to the
console instead of actually sending.

### 3. Frontend

```
cd FE
npm install
copy .env.example .env       # point VITE_API_URL at your backend
npm run dev
```

Frontend comes up on `http://localhost:5173`.

## Tests

```
cd BE
pytest

cd FE
npm test
```

## Docker (production-style)

```
docker compose -f docker-compose.prod.yml up -d --build
```

Needs `DB_PASSWORD`, `JWT_SECRET`, `OPENAI_API_KEY`, and the SMTP variables
set in your shell/`.env` first — see `docker-compose.prod.yml` for the full
list.

## Connector

`BE/connector/` is a separate standalone app — it's what gets packaged into
the `.exe` a customer runs on their own network to let Plantwise pull data
from their database without exposing it to the internet. It's built and
shipped independently of the main backend (see `BE/connector/README.md`).

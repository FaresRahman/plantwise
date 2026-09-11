"""PlantWise unified launcher — one script, two modes.

Usage:
    python run.py dev     → uvicorn --reload on port 8010 (development)
    python run.py prod    → uvicorn workers on port 8010 (production-like, cross-platform)

No argument defaults to ``dev``.
"""

import os
import platform
import subprocess
import sys

# ---------------------------------------------------------------------------
# Auto-activate the project venv if we're not already running inside it.
# This makes "python run.py" work from any shell without manually activating.
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))

if platform.system() == "Windows":
    _VENV_PYTHON = os.path.join(_HERE, ".venv", "Scripts", "python.exe")
else:
    _VENV_PYTHON = os.path.join(_HERE, ".venv", "bin", "python")

if os.path.normcase(sys.executable) != os.path.normcase(_VENV_PYTHON) and os.path.isfile(_VENV_PYTHON):
    subprocess.run([_VENV_PYTHON] + sys.argv, check=True)
    sys.exit(0)

# ---------------------------------------------------------------------------

MODE = sys.argv[1] if len(sys.argv) > 1 else "dev"

if MODE not in ("dev", "prod"):
    print(f"Usage: python run.py [dev|prod]  (got: {MODE!r})")
    sys.exit(1)

# Ensure we're in the BE directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

PORT = "8010"
HOST = "0.0.0.0"

if MODE == "dev":
    print(f"DEVELOPMENT mode — uvicorn --reload on {HOST}:{PORT}")
    os.environ.setdefault("ENV", "development")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--host", HOST, "--port", PORT],
        check=True,
    )
else:
    os.environ.setdefault("ENV", "production")
    is_windows = platform.system() == "Windows"

    if is_windows:
        print(f"PRODUCTION mode — uvicorn workers on {HOST}:{PORT}")
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", PORT, "--workers", "4"],
            check=True,
        )
    else:
        print(f"PRODUCTION mode — gunicorn + uvicorn workers on {HOST}:{PORT}")
        subprocess.run(
            [
                "gunicorn", "app.main:app",
                "--worker-class", "uvicorn.workers.UvicornWorker",
                "--workers", "4",
                "--bind", f"{HOST}:{PORT}",
                "--access-logfile", "-",
                "--error-logfile", "-",
                "--timeout", "120",
            ],
            check=True,
        )

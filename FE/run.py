"""PlantWise Frontend launcher — one script, two modes.

Usage:
    python run.py dev     → vite dev server on port 5173 (development)
    python run.py prod    → vite build + vite preview on port 4173 (production preview)

No argument defaults to ``dev``.
"""

import os
import subprocess
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "dev"

if MODE not in ("dev", "prod"):
    print(f"Usage: python run.py [dev|prod]  (got: {MODE!r})")
    sys.exit(1)

# Ensure we're in the FE directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

if MODE == "dev":
    print("Starting FRONTEND in DEVELOPMENT mode (vite dev, port 5173)")
    subprocess.run(
        ["npx", "vite", "--port", "5173", "--host"],
        check=True,
        shell=True,
    )
else:
    print("Starting FRONTEND in PRODUCTION mode (typecheck + build + preview, port 4173)")
    # Matches package.json's "prod" script exactly (tsc -b && vite build &&
    # vite preview) — vite build alone uses esbuild for transpilation only,
    # so it silently strips types without erroring on a real type error;
    # tsc -b is what actually catches one before it ships.
    subprocess.run(["npx", "tsc", "-b"], check=True, shell=True)
    subprocess.run(["npx", "vite", "build"], check=True, shell=True)
    subprocess.run(
        ["npx", "vite", "preview", "--port", "4173", "--host"],
        check=True,
        shell=True,
    )

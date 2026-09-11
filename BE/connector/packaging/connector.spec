# PyInstaller spec for the Plantwise Local Connector — a single executable
# a customer downloads and runs, no separate Python install required.
#
# Build from the connector/ directory:
#   .venv/Scripts/pyinstaller packaging/connector.spec --distpath dist --workpath build
#
# Output: dist/PlantwiseConnector(.exe) — one file, run it, it opens the
# local config UI in the default browser and starts polling for jobs.
block_cipher = None

a = Analysis(
    ['../main.py'],
    pathex=['..'],
    binaries=[],
    datas=[],
    # PyInstaller's static analyzer follows main.py -> app.web -> app.poller
    # -> db_adapters/__init__.py's explicit imports on its own; these are
    # listed anyway as a defensive backstop for uvicorn's dynamically
    # selected event-loop/protocol implementations, which static analysis
    # can miss. Tier-2 adapters (db2/firebird/informix) intentionally
    # exclude ibm_db/firebird.driver themselves — they're lazy-imported at
    # call time (see db_adapters/db2.py etc.) and simply aren't installed in
    # this venv unless a build specifically needs them; that's by design; see
    # requirements.txt's commented-out tier-2 section.
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'db_adapters',
        'db_adapters.postgres',
        'db_adapters.mysql',
        'db_adapters.mssql',
        'db_adapters.oracle',
        'db_adapters.hana',
        'db_adapters.sqlite',
        'db_adapters.db2',
        'db_adapters.firebird',
        'db_adapters.informix',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='PlantwiseConnector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Keeps a visible console window so a customer can see startup errors
    # and log output directly — swap to False once there's a proper tray
    # icon / notification UX to surface that instead (auto-update work).
    console=True,
    icon=None,
)

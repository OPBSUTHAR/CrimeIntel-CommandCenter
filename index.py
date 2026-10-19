"""Vercel entrypoint for CrimeIntel AI - FastAPI backend + React SPA in one function.

Local development is unaffected: `cd backend && uvicorn main:app` still works as-is.
This module only adapts the app to Vercel's serverless environment:

* runs with the backend directory as CWD (main.py mounts ./storage relative to CWD)
* copies the bundled demo database to /tmp (the only writable path on Vercel)
* derives ALLOWED_ORIGINS from Vercel's own environment variables (CORS + CSRF)
* selects the always-available grounded provider (no Ollama in the cloud)
* serves the built React app (frontend/dist) for all non-API routes
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"

# ---- serverless environment wiring (runs before the backend is imported) ----
sys.path.insert(0, str(BACKEND))

# Writable demo database: seed /tmp from the bundled backup on cold start
if not os.environ.get("CRIMEINTEL_DB_PATH"):
    db_path = str(Path("/tmp") / "crimeintel.db")
    backup = BACKEND / "data" / "crimeintel.db.backup"
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        if not os.path.exists(db_path) and backup.exists():
            shutil.copyfile(str(backup), db_path)
    except OSError:
        pass
    os.environ.setdefault("CRIMEINTEL_DB_PATH", db_path)

# Origins used by CORS and the CSRF middleware (exact-match against the request Origin)
origins = ["http://localhost:5175"]
for var in ("VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL"):
    host = os.environ.get(var)
    if host and ("https://" + host) not in origins:
        origins.append("https://" + host)
os.environ.setdefault("ALLOWED_ORIGINS", ",".join(origins))

# No Ollama inside Vercel functions -> use the grounded template provider
os.environ.setdefault("LLM_PROVIDER", "fallback")

# Fixed demo JWT secret so sessions survive across serverless instances
os.environ.setdefault("JWT_SECRET", "crimeintel-vercel-demo-2026")

# main.py mounts storage/ and loads .env relative to the CWD
os.chdir(BACKEND)

from main import app  # noqa: E402

# ---- serve the React build on the same origin as the API ----
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="frontend-assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if full_path.startswith(("api/", "storage/")):
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    dist_root = DIST.resolve()
    candidate = (DIST / full_path).resolve()
    if full_path and str(candidate).startswith(str(dist_root)) and candidate.is_file():
        return FileResponse(str(candidate))

    index_file = DIST / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return JSONResponse(
        status_code=503,
        content={"detail": "Frontend build not found. Run: cd frontend && npm run build"},
    )

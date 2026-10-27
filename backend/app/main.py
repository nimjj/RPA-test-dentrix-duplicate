import asyncio
import logging
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .config import cfg
from .db import SessionLocal, init_db
from .deps import MAINTENANCE_MESSAGE
from .errors import ApiError
from .routers import auth as auth_router
from .routers import dev as dev_router
from .routers import patients as patients_router
from .runtime_settings import get_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="LedgerLab API", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

MAINTENANCE_HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Down for maintenance</title></head><body style="font-family:sans-serif;max-width:32rem;margin:4rem auto">
<h1>Down for maintenance</h1><p>{MAINTENANCE_MESSAGE}</p></body></html>"""


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(exc.body(), status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        {"code": "validation_error", "message": "Some fields are missing or invalid.",
         "errors": [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]},
        status_code=422,
    )


def _chaos_settings() -> dict:
    with SessionLocal() as db:
        return get_settings(db)


@app.middleware("http")
async def chaos(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    # Dev tools, health and the config the SPA needs to know about chaos stay reachable.
    exempt = path.startswith("/api/dev") or path in ("/api/health", "/api/public-config", "/api/_shell") or path.startswith("/api/docs") or path == "/api/openapi.json"
    if exempt:
        return await call_next(request)
    s = _chaos_settings()
    # Auth routes decide per user (admins may still log in to switch the outage off).
    if s["chaos_outage"] and not path.startswith("/api/auth/"):
        return JSONResponse(
            {"code": "maintenance", "message": MAINTENANCE_MESSAGE, "maintenance": True}, status_code=503
        )
    if s["chaos_slow"]:
        await asyncio.sleep(random.uniform(0.5, 4.0))
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/public-config")
def public_config():
    s = _chaos_settings()
    return {
        "app_name": "LedgerLab",
        "captcha_provider": cfg.captcha_provider,
        "recaptcha_site_key": cfg.recaptcha_site_key,
        "ui_changed": s["chaos_ui_changed"],
        "slow_mode": s["chaos_slow"],
        "outage": s["chaos_outage"],
    }


@app.get("/api/_shell")
def shell():
    """nginx asks this before serving the SPA shell, so page loads get a real
    HTTP 503 during an outage (and X-Accel-Redirect hands back index.html otherwise)."""
    if _chaos_settings()["chaos_outage"]:
        return HTMLResponse(MAINTENANCE_HTML, status_code=503)
    return Response(status_code=200, headers={"X-Accel-Redirect": "/_spa/index.html"})


app.include_router(auth_router.router, prefix="/api")
app.include_router(patients_router.router, prefix="/api")
app.include_router(dev_router.router, prefix="/api")

import logging
import re
import secrets
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import alerts, auth, devices, telemetry, tickets
from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.errors import AppError, register_error_handlers
from app.core.request_context import set_request_id
from app.services.runtime import runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fleet.api")
_VALID_RID = re.compile(r"^[A-Za-z0-9_.-]{8,40}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _VALID_RID.match(incoming) else "req_" + secrets.token_hex(8)
        set_request_id(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.error("unhandled error %s %s\n%s", request.method, request.url.path, traceback.format_exc(limit=-8))
            response = JSONResponse(status_code=500, content={"error": {
                "code": "INTERNAL_ERROR", "message": "Something went wrong. Share the request ID with support.",
                "details": [], "request_id": rid}})
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-ms"] = str(int((time.perf_counter() - start) * 1000))
        return response


simulator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global simulator
    s = get_settings()
    if s.background_enabled:
        if s.simulator_enabled:
            from app.sim.fleet import FleetSimulator
            simulator = FleetSimulator(get_clock())
        await runtime.start(simulator)
    yield
    if s.background_enabled:
        await runtime.stop(simulator)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Dispenser Fleet Lab API", version=s.app_version, lifespan=lifespan,
                  description="Connected medication dispenser fleet (simulated). Synthetic data only.",
                  docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
    register_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)
    if s.cors_origin_list:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_methods=["*"], allow_headers=["*"],
                           expose_headers=["X-Request-ID", "X-Response-Time-ms"])
    for m in (auth, devices, alerts, tickets, telemetry):
        app.include_router(m.router, prefix="/api/v1")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str):
        raise AppError(404, "NOT_FOUND", f"No API route for /api/{rest}.")

    dist = Path(s.frontend_dist) if s.frontend_dist else None
    if dist and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()

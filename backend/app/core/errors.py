"""Standard error envelope: {"error": {"code", "message", "details", "request_id"}}."""

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

log = logging.getLogger("medicare.errors")


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list[dict] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def not_found(entity: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"{entity} not found.")


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def unprocessable(message: str, field: str | None = None, code: str = "VALIDATION_ERROR") -> AppError:
    details = [{"field": field, "issue": message}] if field else []
    return AppError(422, code, message, details)


def _body(code: str, message: str, details: list | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or [], "request_id": get_request_id()}}


# Database constraint name → API error. Lets DB-level guards surface as precise, friendly errors.
CONSTRAINT_ERRORS: dict[str, tuple[int, str, str]] = {
    "uq_fault_per_device": (409, "FAULT_ACTIVE", "This fault is already active on the device."),
    "uq_schedule_time": (409, "SCHEDULE_DUPLICATE", "That time is already in the schedule."),
    "uq_users_email": (409, "EMAIL_TAKEN", "Email already in use."),
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
                429: "RATE_LIMITED"}.get(exc.status_code, "HTTP_ERROR")
        headers = getattr(exc, "headers", None)
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            details.append({"field": ".".join(loc) or None, "issue": err.get("msg", "Invalid value")})
        if any(e.get("type") == "json_invalid" for e in exc.errors()):
            return JSONResponse(status_code=400, content=_body("MALFORMED_JSON", "Request body is not valid JSON.", details))
        request.state.validation_fields = [d["field"] for d in details]
        return JSONResponse(status_code=422, content=_body("VALIDATION_ERROR", "One or more fields are invalid.", details))

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError):
        name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None) or ""
        if name in CONSTRAINT_ERRORS:
            status, code, message = CONSTRAINT_ERRORS[name]
            return JSONResponse(status_code=status, content=_body(code, message))
        if name.startswith("ck_"):
            return JSONResponse(status_code=422, content=_body(
                "CONSTRAINT_VIOLATION", "The data violates a database rule.", [{"field": None, "issue": name}]))
        if name.startswith("fk_"):
            return JSONResponse(status_code=422, content=_body("INVALID_REFERENCE", "A referenced record does not exist."))
        request.state.error_trace = traceback.format_exc(limit=-5)
        return JSONResponse(status_code=409, content=_body("CONFLICT", "The request conflicts with existing data."))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        request.state.error_trace = traceback.format_exc(limit=-8)
        log.exception("Unhandled error")
        return JSONResponse(status_code=500, content=_body(
            "INTERNAL_ERROR", "Something went wrong. Share the request ID with support."))

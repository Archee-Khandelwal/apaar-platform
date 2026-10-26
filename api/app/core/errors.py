"""The single error envelope documented in docs/API_CONTRACT.md section 0.5."""
from __future__ import annotations

from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def api_error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> HTTPException:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return HTTPException(status_code=status_code, detail={"error": payload})


def raise_not_found(message: str = "Not found.") -> NoReturn:
    raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", message)


def raise_reason_required(message: str) -> NoReturn:
    raise api_error(status.HTTP_400_BAD_REQUEST, "REASON_REQUIRED", message)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            body = detail
        else:
            code = {
                400: "BAD_REQUEST",
                401: "NOT_AUTHENTICATED",
                403: "FORBIDDEN_ROLE",
                404: "NOT_FOUND",
                409: "CONFLICT",
                413: "FILE_TOO_LARGE",
                415: "UNSUPPORTED_FILE",
            }.get(exc.status_code, "ERROR")
            body = {"error": {"code": code, "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request body or parameters are not valid.",
                    "details": {"errors": [
                        {"loc": [str(part) for part in err.get("loc", [])], "msg": err.get("msg")}
                        for err in exc.errors()
                    ]},
                }
            },
        )

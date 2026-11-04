from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.core.middleware import security_headers

app = FastAPI(title="Trendova API v1", version="v1")
app.middleware("http")(security_headers)

def error_response(status, code, message, details=None, headers=None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details or []}}, status_code=status, headers=headers)

@app.exception_handler(AppError)
async def app_error(_: Request, error: AppError):
    return error_response(error.status_code, error.code, error.message, error.details, error.headers)

@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, error: RequestValidationError):
    return error_response(422, "VALIDATION_ERROR", "Request validation failed", error.errors())

@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}

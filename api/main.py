"""
AISO FastAPI Backend
Wraps the existing Python pipeline (setup2.py, collect.py, analysis1.py, analysis2.py)
into a secure REST API for the Next.js frontend.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import time
import os

from api.routes import health, clients, pipeline

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AISO API",
    description="AI Search Optimization Platform — Backend API",
    version="0.1.0",
    docs_url="/api/docs" if os.getenv("ENV") != "production" else None,  # Hide docs in prod
    redoc_url=None,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://sapienic.com",
    "https://app.sapienic.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# ── Trusted hosts ────────────────────────────────────────────────────────────
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "sapienic.com", "*.sapienic.com"],
)

# ── Request timing middleware ─────────────────────────────────────────────────
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    response.headers["X-Process-Time"] = f"{duration:.4f}s"
    # Remove server fingerprinting (MutableHeaders uses del, not pop)
    try:
        del response.headers["server"]
    except KeyError:
        pass
    return response

# ── Global exception handler ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[AISO API Error] {request.method} {request.url.path} — {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "An internal error occurred. Please try again."},
    )


@app.on_event("startup")
def on_startup():
    from api.database import init_db
    init_db()

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(health.router,   prefix="/api/v1")
app.include_router(clients.router,  prefix="/api/v1")
app.include_router(pipeline.router, prefix="/api/v1")

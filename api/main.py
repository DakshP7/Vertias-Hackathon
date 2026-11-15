from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers tables)
from .config import BASE_DIR, DISCLAIMER, settings
from .database import Base, engine
from .routers import auth, ct_demo, dashboard, meta, notes, patients, reports, scans


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    from .services import ct_service
    ct_service.recover_stale()
    yield


app = FastAPI(
    title="CellIQ API",
    version="0.1.0",
    description="Lung scan triage support platform. " + DISCLAIMER,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disclaimer_header(request, call_next):
    response = await call_next(request)
    response.headers["X-CellIQ-Disclaimer"] = "Research prototype. Not a diagnosis. Doctor review required."
    if request.url.path.startswith("/app"):
        # The built-in UI only loads its own scripts; no inline scripts or outside sources.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-cache"
    return response


for r in (auth.router, ct_demo.router, dashboard.router, patients.router, scans.router, notes.router, reports.router, meta.router):
    app.include_router(r)

WEB_DIR = BASE_DIR / "web"
if WEB_DIR.is_dir():
    # Built-in UI for local use. A custom UI can replace this and call the same API.
    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/" if WEB_DIR.is_dir() else "/docs")

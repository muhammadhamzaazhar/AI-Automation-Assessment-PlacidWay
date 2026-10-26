"""HTTP API and the static chat UI.

Run locally with:  uvicorn app.api:app --reload
"""

import asyncio
import logging
import mimetypes
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app import factory
from app.chat.schemas import ChatTurn
from app.chat.service import ChatService
from app.config import Settings, get_settings
from app.rate_limit import RateLimiter
from app.refresh import RefreshManager
from app.retrieval.embeddings import Embedder
from app.retrieval.knowledge_base import KnowledgeBase
from app.storage import Storage

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
mimetypes.add_type("image/avif", ".avif")  # not in every platform's MIME table (used by the logo)
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# --- request / response models ---

class ChatRequest(BaseModel):
    message: str = Field(max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    disclaimer_shown: bool = False

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class SourceOut(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    intent: str
    answerable: bool
    show_quote_cta: bool
    disclaimer: str | None
    quote_url: str


class LeadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=200, pattern=EMAIL_PATTERN)
    message: str | None = Field(default=None, max_length=2000)
    consent: bool
    conversation: list[ChatTurn] = Field(default_factory=list, max_length=40)

    @field_validator("consent")
    @classmethod
    def must_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("consent is required to be contacted")
        return value


# --- wiring ---

@dataclass
class AppServices:
    chat: ChatService
    storage: Storage
    refresher: RefreshManager | None = None


def build_services(settings: Settings) -> AppServices:
    client = factory.openai_client(settings)
    embedder = Embedder(client, settings.embedding_model)
    storage = Storage(settings.db_path)
    chat = factory.chat_service(settings, client, factory.load_knowledge_base(settings, embedder), storage)

    def use_new_knowledge_base(new_kb: KnowledgeBase) -> None:
        chat.kb = new_kb

    # On Vercel the project files are read-only, so a live refresh can't save the new index.
    refresher = None if settings.vercel else RefreshManager(settings, embedder, use_new_knowledge_base)
    return AppServices(chat, storage, refresher)


async def _scheduled_refresh(refresher: RefreshManager, hours: float) -> None:
    while True:
        await asyncio.sleep(hours * 3600)
        log.info("Scheduled content refresh: %s", "started" if refresher.start() else "already running")


# --- app ---

def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    settings = settings or get_settings()
    limiter = RateLimiter(settings.rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services or build_services(settings)
        task = None
        if settings.refresh_interval_hours > 0 and app.state.services.refresher:
            task = asyncio.create_task(
                _scheduled_refresh(app.state.services.refresher, settings.refresh_interval_hours)
            )
        yield
        if task:
            task.cancel()

    app = FastAPI(title="PlacidWay Knowledge Chatbot", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def get_services(request: Request) -> AppServices:
        return request.app.state.services

    def rate_limited(request: Request) -> None:
        # Behind a proxy (Vercel, Hugging Face) the visitor's IP is the first X-Forwarded-For entry.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        client = forwarded or (request.client.host if request.client else "unknown")
        if not limiter.allow(client):
            raise HTTPException(429, "Too many requests. Please wait a minute and try again.")

    def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
        if settings.admin_token is None:
            raise HTTPException(404, "Admin endpoints are disabled (ADMIN_TOKEN is not set).")
        expected = settings.admin_token.get_secret_value()
        if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
            raise HTTPException(401, "Invalid or missing X-Admin-Token header.")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Something went wrong. Please try again."}, status_code=500)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health(services: AppServices = Depends(get_services)) -> dict:
        kb = services.chat.kb
        return {"status": "ok", "chunks": len(kb.chunks), "index_built_at": kb.built_at,
                "llm_model": settings.llm_model}

    @app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(rate_limited)])
    def chat(body: ChatRequest, services: AppServices = Depends(get_services)) -> ChatResponse:
        reply = services.chat.reply(body.message, body.history, body.disclaimer_shown)
        return ChatResponse(**asdict(reply), quote_url=settings.quote_url)

    @app.post("/api/leads", status_code=201, dependencies=[Depends(rate_limited)])
    def create_lead(body: LeadRequest, services: AppServices = Depends(get_services)) -> dict:
        lead_id = services.storage.add_lead(
            body.name.strip(), body.email.strip(), body.message,
            [turn.model_dump() for turn in body.conversation],
        )
        return {"ok": True, "id": lead_id}

    @app.post("/admin/refresh", status_code=202, dependencies=[Depends(require_admin)])
    def start_refresh(services: AppServices = Depends(get_services)) -> dict:
        if services.refresher is None:
            raise HTTPException(501, "Live refresh isn't available on this host. Run "
                                     "`python -m scripts.ingest`, commit data/ and redeploy.")
        if not services.refresher.start():
            raise HTTPException(409, "A refresh is already running.")
        return {"started": True, "check_status_at": "/admin/refresh"}

    @app.get("/admin/refresh", dependencies=[Depends(require_admin)])
    def refresh_status(services: AppServices = Depends(get_services)) -> dict:
        return services.refresher.status() if services.refresher else {"running": False}

    @app.get("/admin/unanswered", dependencies=[Depends(require_admin)])
    def unanswered(limit: int = Query(200, ge=1, le=1000),
                   services: AppServices = Depends(get_services)) -> list[dict]:
        return services.storage.list_unanswered(limit)

    @app.get("/admin/leads", dependencies=[Depends(require_admin)])
    def leads(limit: int = Query(200, ge=1, le=1000),
              services: AppServices = Depends(get_services)) -> list[dict]:
        return services.storage.list_leads(limit)

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()

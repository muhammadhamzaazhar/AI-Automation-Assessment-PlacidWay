"""Application settings, read from environment variables."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Source(BaseModel):
    """One page of the knowledge base, as listed in config/sources.yaml."""

    id: str
    page_type: str
    url: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # LLM provider
    openai_api_key: SecretStr | None = None
    llm_model: str = "gpt-6-luna"
    llm_reasoning_effort: str = "low"
    embedding_model: str = "text-embedding-3-small"

    # Content
    sources_file: Path = PROJECT_ROOT / "config" / "sources.yaml"
    data_dir: Path = PROJECT_ROOT / "data"

    # Crawler. robots.txt Crawl-delay wins when it is longer than this minimum.
    crawler_user_agent: str = (
        "PlacidWayAssessmentBot/1.0 (AI Automation Engineer assessment; respects robots.txt)"
    )
    crawl_min_delay_seconds: float = 1.0

    # Retrieval and chat
    retrieval_top_k: int = 10
    min_relevance: float = 0.25  # best cosine similarity below this means "nothing relevant"
    history_turns: int = 6  # user+assistant pairs passed to the query rewriter
    quote_url: str = (
        "https://www.placidway.com/rfi/5/Alternative-Cancer-Treatment-by-ITC-Immunity-Therapy-Center"
    )

    # Operations
    admin_token: SecretStr | None = None  # admin endpoints are disabled when unset
    rate_limit_per_minute: int = 20
    refresh_interval_hours: float = 0  # 0 disables the scheduled refresh

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @field_validator("openai_api_key", "admin_token", mode="before")
    @classmethod
    def empty_means_unset(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    def load_sources(self) -> list[Source]:
        data = yaml.safe_load(self.sources_file.read_text(encoding="utf-8"))
        return [Source(**item) for item in data["sources"]]


@lru_cache
def get_settings() -> Settings:
    return Settings()

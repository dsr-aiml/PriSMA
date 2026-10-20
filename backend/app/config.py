from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://prisma:prisma@db:5432/prisma"
    redis_url: str = "redis://redis:6379/0"
    public_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_days: int = 7
    demo_step_seconds: float = 0.8
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:1.7b"
    ollama_embedding_model: str = "all-minilm"
    local_model_max_bytes: int = Field(default=2_000_000_000, ge=100_000_000, le=2_000_000_000)
    allow_large_local_models: bool = False
    ollama_balanced_model: str = ""
    ollama_advanced_model: str = ""
    balanced_model_max_bytes: int = Field(default=5_000_000_000, ge=100_000_000, le=8_000_000_000)
    advanced_model_max_bytes: int = Field(default=10_000_000_000, ge=100_000_000, le=24_000_000_000)
    inference_memory_budget_bytes: int = Field(default=3_000_000_000, ge=1_000_000_000, le=64_000_000_000)
    local_gpu_layers: int = Field(default=0, ge=-1, le=200)
    tinyfish_enabled: bool = False
    tinyfish_api_key: str = ""
    tinyfish_search_daily_limit: int = Field(default=100, ge=1, le=500)
    tinyfish_fetch_daily_limit: int = Field(default=200, ge=1, le=1000)
    tinyfish_cache_seconds: int = Field(default=3600, ge=0, le=86400)
    tinyfish_searches_per_run: int = Field(default=1, ge=1, le=5)
    tinyfish_fetch_attempts_per_run: int = Field(default=6, ge=1, le=20)
    tinyfish_search_max_per_run: int = Field(default=5, ge=0, le=5)
    tinyfish_fetch_max_per_run: int = Field(default=20, ge=1, le=20)
    browser_observer_url: str = "http://browser:8010"
    public_file_max_per_run: int = Field(default=12, ge=1, le=12)
    analysis_max_passages: int = Field(default=48, ge=2, le=120)
    analysis_max_embedding_requests: int = Field(default=64, ge=1, le=128)
    analysis_max_requests: int = Field(default=16, ge=1, le=64)
    source_bundle_characters: int = Field(default=12_000_000, ge=1_000_000, le=24_000_000)
    model_context_tokens: int = Field(default=4096, ge=2048, le=4096)
    model_output_tokens: int = Field(default=1200, ge=256, le=1600)
    model_threads: int = Field(default=3, ge=1, le=3)
    model_timeout_seconds: int = Field(default=180, ge=10, le=240)
    research_timeout_seconds: int = Field(default=45, ge=15, le=90)
    allow_hosted_models: bool = False
    allow_hosted_queries: bool = True
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_query_model: str = "gemini-flash-latest"
    gemini_query_context_tokens: int = Field(default=32768, ge=4096, le=32768)
    gemini_query_output_tokens: int = Field(default=3000, ge=800, le=4096)
    gemini_query_rpm: int = Field(default=6, ge=1, le=60)
    gemini_query_input_tpm: int = Field(default=120000, ge=10000, le=1000000)
    gemini_quota_project: str = ""
    research_max_wait_seconds: int = Field(default=65, ge=0, le=90)
    research_total_seconds: int = Field(default=180, ge=60, le=200)
    research_retry_attempts: int = Field(default=3, ge=1, le=3)
    gemini_embedding_model: str = "gemini-embedding-001"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def settings() -> Settings:
    return Settings()

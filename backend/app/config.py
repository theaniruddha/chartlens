from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://chartlens@localhost:5433/chartlens"
    test_database_url: str = "postgresql+psycopg://chartlens@localhost:5433/chartlens_test"

    llm_provider: str = "mock"  # mock | ollama | ollama_cloud | groq

    ollama_local_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_cloud_api_key: str = ""
    ollama_base_url: str = "https://ollama.com"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Model for the inline lint pass; defaults to the main model. Swap to e.g.
    # nemotron-3-nano:30b via LINT_MODEL once its latency is dependable.
    lint_model: str = ""

    show_trace: bool = True

    # Optional LangSmith tracing (opt-in via env)
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "chartlens"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Global configuration for qr-form-agent using pydantic-settings."""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Environment
    dry_run: bool = Field(default=False, description="Run pipeline without network writes or live submits")
    debug: bool = Field(default=False, description="Enable debug logging")

    # Storage & DB
    data_dir: Path = Field(default=Path("./data"), description="Directory for persistent data, profiles, and screenshots")
    database_url: str = Field(default="sqlite:///./data/qr_agent.db", description="SQLite database URL")

    # LLM settings
    anthropic_api_key: Optional[str] = Field(default=None, description="API key for Anthropic Claude")
    gemini_api_key: Optional[str] = Field(default=None, description="API key for Google Gemini")
    llm_provider: str = Field(default="anthropic", description="LLM provider: anthropic, gemini, or mock")
    llm_model: str = Field(default="claude-3-5-sonnet-20241022", description="Model name for field mapping & profile extraction")

    # Mapping & Safety thresholds
    confidence_threshold: float = Field(default=0.75, description="Minimum confidence threshold to auto-fill without review flag")
    rate_limit_per_domain_seconds: float = Field(default=2.0, description="Minimum delay between requests to the same domain")

    # Review Web UI & Notifications
    review_server_host: str = Field(default="127.0.0.1", description="Host for FastAPI review UI")
    review_server_port: int = Field(default=8000, description="Port for FastAPI review UI")
    telegram_bot_token: Optional[str] = Field(default=None, description="Optional Telegram bot token")
    telegram_chat_id: Optional[str] = Field(default=None, description="Optional Telegram chat ID")

    def ensure_data_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "profiles").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)


settings = Settings()

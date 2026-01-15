from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Follows 12-factor app configuration principles.
    """
    
    # Pydantic v2 settings config
    # env_file is only used as fallback, env vars take precedence
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Ensure environment variables override .env file
        env_ignore_empty=True,
    )
    
    # Database Configuration - required from .env
    DATABASE_URL: str
    
    # Logging Configuration - required from .env
    LOG_LEVEL: str
    
    # Webhook Security - required from .env
    WEBHOOK_SECRET: str


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to avoid reading .env file on every request.
    """
    return Settings()


# Global settings instance
settings = get_settings()

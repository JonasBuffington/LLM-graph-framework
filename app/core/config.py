# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    REDIS_URL: str
    GEMINI_API_KEY: str = ""
    LIMITER_STORAGE_URI: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
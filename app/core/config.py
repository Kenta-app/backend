from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Kenta News API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str

    # CORS
    BACKEND_CORS_ORIGINS: list = ["*"]

    # Stance remains an experimental research component until the local
    # four-class corpus and held-out evaluation satisfy the release gates.
    STANCE_PUBLIC_ENABLED: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

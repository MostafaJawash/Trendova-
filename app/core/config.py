"""
Application configuration using environment variables.
"""
import os
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env file in project root
load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        # Database configuration with environment variable fallbacks
        self.DATABASE_HOST = os.getenv("DATABASE_HOST", "localhost")
        self.DATABASE_PORT = int(os.getenv("DATABASE_PORT", "3306"))
        self.DATABASE_USER = os.getenv("DATABASE_USER", "root")
        self.DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")
        self.DATABASE_NAME = os.getenv("DATABASE_NAME", "ecommerce")

        # JWT configuration
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        self.ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

        # Validate JWT configuration
        self._validate_jwt_config()

    @property
    def database_url(self) -> str:
        """Construct database URL from components."""
        return f"mysql+pymysql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"

    def _validate_jwt_config(self):
        """Validate JWT configuration settings."""
        if not self.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY must be set in environment variables")

        # Reject placeholder secrets from example files
        placeholder_secrets = [
            "your_long_random_secret_key_here",
            "your-secret-key",
            "secret",
            "change-me",
            "replace-with-random-secret",
            "REPLACE_WITH_SECURE_RANDOM_SECRET_KEY"
        ]
        if self.JWT_SECRET_KEY.lower() in placeholder_secrets:
            raise ValueError("JWT_SECRET_KEY must be set to a secure random value, not a placeholder")

        # Ensure secret key is sufficiently long (at least 32 bytes for HS256)
        if len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")

        if self.JWT_ALGORITHM not in ["HS256", "HS384", "HS512"]:
            raise ValueError(f"Unsupported JWT algorithm: {self.JWT_ALGORITHM}")

        if self.ACCESS_TOKEN_EXPIRE_MINUTES <= 0:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be a positive integer")


settings = Settings()

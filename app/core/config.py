from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str | None = None
    database_host: str = 'localhost'; database_port: int = 3306
    database_user: str = 'root'; database_password: str = ''; database_name: str = 'ecommerce'
    secret_key: str = Field(min_length=32)
    access_token_expire_minutes: int = 60
    admin_email: str = 'admin@example.com'; admin_password: str = Field(min_length=8); admin_full_name: str = 'Administrator'
    upload_dir: str = 'uploads'; max_upload_mb: int = 5; inventory_mode: str = 'fake'
    inventory_grpc_addr: str = 'inventory-service:50051'
    inventory_timeout_seconds: float = 2.0
    @property
    def sqlalchemy_url(self): return self.database_url or f'mysql+pymysql://{self.database_user}:{self.database_password}@{self.database_host}:{self.database_port}/{self.database_name}'
settings = Settings(); Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

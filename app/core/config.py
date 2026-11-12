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
    db_query_count: bool = False  # DB_QUERY_COUNT=1 exposes X-DB-Query-Count (diagnostics only)
    revoked_purge_interval_seconds: int = 300  # background purge of expired revoked tokens
    # ---- Req 3: read replica, Redis, cache, ETag ----
    database_replica_url: str | None = None
    database_replica_host: str | None = None   # same credentials/db name as the primary
    database_replica_port: int = 3306
    use_read_replica: bool = False             # false = everything on the primary
    redis_url: str | None = None
    redis_timeout_seconds: float = 0.15        # connect + socket timeout (100-200 ms budget)
    ryw_window_seconds: int = 5                # must exceed the replica lag measured under create_order load
    cache_enabled: bool = False
    etag_enabled: bool = False
    cache_list_ttl_seconds: int = 60
    cache_detail_ttl_seconds: int = 300
    cache_ttl_jitter: float = 0.10             # +-10%
    cache_lock_ms: int = 5000
    cache_wait_ms: int = 600                   # how long a stampede loser waits for the winner's fill
    inventory_batch_max: int = 200
    diag_allow_stock_mode: bool = False        # diagnostics instance only: lets ?stock_mode=naive|batch override stock_mode
    gzip_enabled: bool = True                  # GZipMiddleware (Accept-Encoding: gzip); ETag stays the hash of the UNcompressed body
    stock_mode: str = 'batch'                  # 'batch' (one GetStockBatch call) | 'naive' (N calls; benchmark/test variant only)             # max product ids per GetStockBatch call
    @property
    def replica_url(self):
        if self.database_replica_url: return self.database_replica_url
        if self.database_replica_host:
            return f'mysql+pymysql://{self.database_user}:{self.database_password}@{self.database_replica_host}:{self.database_replica_port}/{self.database_name}'
        return None
    @property
    def sqlalchemy_url(self): return self.database_url or f'mysql+pymysql://{self.database_user}:{self.database_password}@{self.database_host}:{self.database_port}/{self.database_name}'
settings = Settings(); Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

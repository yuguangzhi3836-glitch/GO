from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import make_url
from go_hotel.core.config import Settings, settings


def create_runtime_engine(config: Settings):
    """One bounded pool per process; never retry a transaction implicitly.

    SQLite keeps its existing dialect-specific pool behavior, including in-memory
    fixtures. Each API process and each worker must be counted before scaling.
    """
    options = {"pool_pre_ping": True}
    if make_url(config.database_url).get_backend_name() == "postgresql":
        options.update(
            pool_size=config.database_pool_size,
            max_overflow=config.database_max_overflow,
            pool_timeout=config.database_pool_timeout_seconds,
            pool_recycle=config.database_pool_recycle_seconds,
        )
    return create_engine(config.database_url, **options)


engine = create_runtime_engine(settings)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

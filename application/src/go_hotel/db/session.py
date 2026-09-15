from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from go_hotel.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

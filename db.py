"""Database engine, session factory, and table bootstrapping."""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(config: Config) -> None:
    """Create the engine, session factory, and all tables if they don't exist."""
    global _engine, _SessionLocal
    _engine = create_engine(
        config.database_url,
        echo=False,
        pool_pre_ping=True,
    )
    _SessionLocal = sessionmaker(bind=_engine)
    Base.metadata.create_all(_engine)
    logger.info("Database initialised — tables created (if missing).")


def get_session() -> Session:
    """Return a new database session.  Caller is responsible for closing it."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised.  Call init_db() first.")
    return _SessionLocal()

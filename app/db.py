from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        # check_same_thread off because FastAPI serves sync endpoints from a
        # threadpool, so a session may not run on the thread that made it.
        _engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    return _engine


def init_db() -> None:
    from app import models  # noqa: F401  imports register the tables on the metadata

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session

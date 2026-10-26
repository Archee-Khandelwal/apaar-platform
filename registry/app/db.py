"""Registry database: the list of 'issued' APAAR IDs."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from registry.app.config import registry_settings


class Base(DeclarativeBase):
    pass


class IssuedApaar(Base):
    __tablename__ = "issued_apaar"

    apaar: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dob: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD


engine = create_engine(
    registry_settings.registry_database_url,
    connect_args={"check_same_thread": False}
    if registry_settings.registry_database_url.startswith("sqlite")
    else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_registry_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_registry_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

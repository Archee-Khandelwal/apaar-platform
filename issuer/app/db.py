"""Issuer database: the documents boards, counselling authorities and immigration
offices have genuinely issued, as DigiLocker would know them. All synthetic."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import JSON, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from issuer.app.config import issuer_settings


class Base(DeclarativeBase):
    pass


class IssuedRecord(Base):
    __tablename__ = "issued_records"

    reference_no: Mapped[str] = mapped_column(String(40), primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(48))
    issuer_name: Mapped[str] = mapped_column(String(160))
    holder_name: Mapped[str] = mapped_column(String(160))
    holder_dob: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ISO
    issued_on: Mapped[str] = mapped_column(String(10))  # ISO
    sha256: Mapped[str] = mapped_column(String(64))  # of the file as issued
    # Key facts printed on the document (year, marks, roll number, ...), compared when
    # a file is a re-scan and its hash cannot match.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="valid")  # valid | revoked


engine = create_engine(
    issuer_settings.issuer_database_url,
    connect_args={"check_same_thread": False}
    if issuer_settings.issuer_database_url.startswith("sqlite")
    else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_issuer_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_issuer_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

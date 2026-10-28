"""Document verification (Phase 5). Phase 4 stores documents as ``pending``."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.core import StudentDocument


def verify_document(db: Session, document: StudentDocument) -> StudentDocument:
    """Run every check on a freshly stored document. Filled in by Phase 5."""
    return document

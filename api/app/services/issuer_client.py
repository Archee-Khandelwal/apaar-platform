"""Typed client for the mock Issuer & DigiLocker registry (port 8002).

Like the APAAR registry client, it never raises: an issuer that is down, slow or
answering garbage yields ``status="unavailable"``, and the document goes to an officer
instead of being silently passed or failed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("apaar.issuer_client")


@dataclass
class IssuerResult:
    status: str  # verified | mismatch | not_found | revoked | unavailable
    reference_no: str | None = None
    matched_by: str | None = None
    issuer_name: str | None = None
    doc_type: str | None = None
    issued_on: str | None = None
    doc_type_match: bool | None = None
    holder_name_match: bool | None = None
    holder_dob_match: bool | None = None
    differing_facts: list[str] = field(default_factory=list)
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value not in (None, [])}


class IssuerClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.issuer_url).rstrip("/")
        self.api_key = api_key or settings.issuer_api_key
        self.timeout = timeout if timeout is not None else settings.issuer_timeout_seconds
        self._transport = transport

    def verify(
        self,
        *,
        reference_no: str,
        doc_type: str | None,
        sha256: str,
        holder_name: str | None,
        holder_dob: str | None,
        facts: dict[str, Any],
    ) -> IssuerResult:
        payload = {
            "reference_no": reference_no,
            "doc_type": doc_type,
            "sha256": sha256,
            "holder_name": holder_name,
            "holder_dob": holder_dob,
            "facts": facts,
        }
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"X-API-Key": self.api_key},
                transport=self._transport,
            ) as client:
                response = client.post("/documents/verify", json=payload)
            response.raise_for_status()
            body = response.json()
            status = body.get("status")
            if status not in ("verified", "mismatch", "not_found", "revoked"):
                raise ValueError(f"unexpected issuer status {status!r}")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Issuer registry unavailable: %s", exc)
            return IssuerResult(
                status="unavailable",
                reference_no=reference_no,
                message="The issuer registry did not answer; the document needs an officer.",
            )
        return IssuerResult(
            status=status,
            reference_no=body.get("reference_no", reference_no),
            matched_by=body.get("matched_by"),
            issuer_name=body.get("issuer_name"),
            doc_type=body.get("doc_type"),
            issued_on=body.get("issued_on"),
            doc_type_match=body.get("doc_type_match"),
            holder_name_match=body.get("holder_name_match"),
            holder_dob_match=body.get("holder_dob_match"),
            differing_facts=list(body.get("differing_facts") or []),
        )

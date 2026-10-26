"""Typed client for the mock APAAR registry.

If the registry is slow, unreachable or returns garbage, we return
``status="source_unavailable"`` rather than raising: an upload must never fail because a
third-party registry is down (Step 4 of docs/PLAN.md). Rows are stored and marked for
re-check, and no APAAR_NOT_FOUND / APAAR_MISMATCH flag is raised for them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.core.crypto import mask_apaar, normalize_apaar

logger = logging.getLogger("apaar.registry_client")

BATCH_LIMIT = 500
UNAVAILABLE_MESSAGE = "APAAR registry did not respond; rows stored and marked for re-check."


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class RegistryResult:
    """One record's verification outcome."""

    status: str  # match | mismatch | not_found | consent_required | source_unavailable
    apaar_masked: str = "XXXX-XXXX-XXXX"
    name_similarity: int | None = None
    dob_match: bool | None = None
    checked_at: str = field(default_factory=_now)
    ref: str | None = None
    message: str | None = None

    @property
    def available(self) -> bool:
        return self.status != "source_unavailable"

    def as_dict(self) -> dict:
        data = {
            "status": self.status,
            "apaar_masked": self.apaar_masked,
            "name_similarity": self.name_similarity,
            "dob_match": self.dob_match,
            "checked_at": self.checked_at,
        }
        if self.ref is not None:
            data["ref"] = self.ref
        if self.message:
            data["message"] = self.message
        return data


@dataclass
class RegistryRecord:
    """One record to check. ``ref`` lets the caller match results back to rows."""

    apaar: str
    name: str | None = None
    dob: str | None = None
    ref: str | None = None

    def payload(self) -> dict:
        return {
            "apaar": normalize_apaar(self.apaar) or "",
            "name": self.name,
            "dob": self.dob,
            "ref": self.ref,
        }


class RegistryClient:
    """Thin wrapper over the registry's HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        retries: int = 1,
    ) -> None:
        self.base_url = (base_url or settings.registry_url).rstrip("/")
        self.api_key = api_key or settings.registry_api_key
        self.timeout = timeout if timeout is not None else settings.registry_timeout_seconds
        self.retries = retries
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"X-API-Key": self.api_key},
            transport=self._transport,
        )

    # ------------------------------------------------------------------ single

    def verify(self, record: RegistryRecord) -> RegistryResult:
        results = self.verify_batch([record])
        return results[0] if results else self._unavailable([record])[0]

    # ------------------------------------------------------------------ batch

    def verify_batch(self, records: list[RegistryRecord]) -> list[RegistryResult]:
        """Verify up to any number of records, chunked to the registry's batch limit."""
        if not records:
            return []

        results: list[RegistryResult] = []
        for start in range(0, len(records), BATCH_LIMIT):
            chunk = records[start : start + BATCH_LIMIT]
            results.extend(self._verify_chunk(chunk))
        return results

    def _verify_chunk(self, chunk: list[RegistryRecord]) -> list[RegistryResult]:
        payload = {"records": [record.payload() for record in chunk]}
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            try:
                with self._client() as client:
                    response = client.post("/verify/batch", json=payload)
                response.raise_for_status()
                body = response.json()
                by_ref = {item.get("ref"): item for item in body.get("results", [])}
                ordered = body.get("results", [])
                out: list[RegistryResult] = []
                for index, record in enumerate(chunk):
                    item = by_ref.get(record.ref) if record.ref is not None else None
                    if item is None:
                        item = ordered[index] if index < len(ordered) else None
                    if item is None:
                        out.append(
                            RegistryResult(
                                status="source_unavailable",
                                apaar_masked=mask_apaar(record.apaar),
                                ref=record.ref,
                                message="Registry returned fewer results than records sent.",
                            )
                        )
                        continue
                    out.append(
                        RegistryResult(
                            status=item.get("status", "source_unavailable"),
                            apaar_masked=item.get("apaar_masked") or mask_apaar(record.apaar),
                            name_similarity=item.get("name_similarity"),
                            dob_match=item.get("dob_match"),
                            checked_at=item.get("checked_at") or _now(),
                            ref=record.ref,
                        )
                    )
                return out
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = exc
                if attempt < self.retries:
                    continue

        logger.warning("APAAR registry unavailable (%s): %s", type(last_error).__name__, last_error)
        return self._unavailable(chunk)

    def _unavailable(self, chunk: list[RegistryRecord]) -> list[RegistryResult]:
        return [
            RegistryResult(
                status="source_unavailable",
                apaar_masked=mask_apaar(record.apaar),
                ref=record.ref,
                message=UNAVAILABLE_MESSAGE,
            )
            for record in chunk
        ]

    # ------------------------------------------------------------------ seeding

    def bulk_insert(self, records: list[dict]) -> dict:
        """Used by /datagen to register issued APAAR IDs with the mock registry."""
        inserted = 0
        skipped = 0
        for start in range(0, len(records), BATCH_LIMIT):
            chunk = records[start : start + BATCH_LIMIT]
            with self._client() as client:
                response = client.post("/registry/apaar/bulk", json={"records": chunk})
            response.raise_for_status()
            body = response.json()
            inserted += body.get("inserted", 0)
            skipped += body.get("skipped_existing", 0)
        return {"inserted": inserted, "skipped_existing": skipped}

    def health(self) -> dict:
        try:
            with self._client() as client:
                response = client.get("/health")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            return {"status": "unavailable", "error": type(exc).__name__, "detail": str(exc)}


def get_registry_client() -> RegistryClient:
    return RegistryClient()

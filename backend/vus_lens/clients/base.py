"""Fail-loud foundations shared by every public-data client.

``AsyncSourceClient`` turns the messy outcomes of a network call — timeouts,
connection resets, 4xx/5xx, non-JSON bodies — into a structured
:class:`HttpResult` that **never** collapses into "benign". Each concrete
client interprets that outcome into a :class:`SourceResult`, deciding for
*itself* what a 404 means (for MyVariant, "no record"; for others it may be an
error). The base layer never makes that call silently.

One short-lived ``httpx.AsyncClient`` is created per request. That is slightly
less efficient than a shared pool but far simpler and lifecycle-safe for the
single-variant demo; it can be swapped for a shared client when the FastAPI app
is wired up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models.evidence import Provenance, SourceResult


@dataclass(frozen=True)
class HttpResult:
    """Low-level outcome of one HTTP attempt. Structured, never raised.

    ``ok`` is True only on a 2xx/3xx response with a JSON body successfully
    parsed. A ``status_code`` is surfaced even on failure so the caller can tell
    a 404 ("no record") apart from a 503 ("source down").
    """

    ok: bool
    status_code: int | None = None
    json: Any | None = None
    error: str | None = None
    timed_out: bool = False


class AsyncSourceClient:
    """Base class holding a source's identity, timeout, and provenance stamp."""

    def __init__(
        self,
        source_name: str,
        timeout: float,
        *,
        dataset_version: str | None = None,
        license_note: str | None = None,
    ) -> None:
        self.source_name = source_name
        self.timeout = timeout
        self.dataset_version = dataset_version
        self.license_note = license_note

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def provenance(self, endpoint: str, query: Any) -> Provenance:
        """Stamp where/when this lookup was made, for the evidence card."""
        return Provenance(
            source=self.source_name,
            endpoint=endpoint,
            query=query,
            dataset_version=self.dataset_version,
            license=self.license_note,
            retrieved_at=self._now(),
        )

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        """Make one request and return a structured outcome. Never raises."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
        except httpx.TimeoutException as exc:
            return HttpResult(
                ok=False, timed_out=True, error=f"timeout after {self.timeout}s ({exc!r})"
            )
        except httpx.HTTPError as exc:
            return HttpResult(ok=False, error=f"request error: {exc!r}")

        if resp.status_code >= 400:
            # Surface the code; let the caller decide EMPTY vs ERROR. We refuse
            # to guess that a failure means "nothing wrong here".
            return HttpResult(
                ok=False, status_code=resp.status_code, error=f"HTTP {resp.status_code}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            return HttpResult(
                ok=False,
                status_code=resp.status_code,
                error=f"non-JSON response ({exc!r})",
            )
        return HttpResult(ok=True, status_code=resp.status_code, json=payload)

    def failure_result(self, http: HttpResult, provenance: Provenance) -> SourceResult:
        """Build the loud SourceResult for a non-recoverable failure.

        TIMEOUT and ERROR both mean *evidence unavailable* — the auditor treats
        them as fail-loud, never as benign.
        """
        if http.timed_out:
            return SourceResult.timeout(
                self.source_name, provenance, http.error or "timed out"
            )
        return SourceResult.error(
            self.source_name, provenance, http.error or "request failed"
        )


__all__ = ["HttpResult", "AsyncSourceClient"]

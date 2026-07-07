"""Typed results from public-data sources.

The whole integrity story rests on one distinction this module makes
un-ignorable: a source that **failed** is not the same as a source that
returned **no record**, and neither is the same as **benign**. Every client
returns a ``SourceResult`` carrying an explicit :class:`SourceStatus`, so no
downstream code can silently read a miss or an outage as "no evidence /
benign" (build brief Sections 0 and 6.3).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class SourceStatus(str, Enum):
    """Outcome of a single source lookup.

    The pairing that matters:

    * ``OK`` / ``EMPTY`` — we actually heard back from the source. ``EMPTY``
      means the source authoritatively has no record for this variant; that can
      be *evidence* (e.g. "not observed in gnomAD" supports rarity) but it is
      **never** the same as benign.
    * ``ERROR`` / ``TIMEOUT`` — we did not hear back. The evidence is
      *unavailable*, and must be surfaced loudly, never treated as reassuring.
    """

    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    TIMEOUT = "timeout"


class Provenance(BaseModel):
    """Where a piece of evidence came from — for the transparent evidence card."""

    source: str
    endpoint: str
    query: Any = None
    dataset_version: str | None = None
    license: str | None = None
    retrieved_at: datetime


class SourceResult(BaseModel):
    """A single source's answer for a variant, with its status and provenance.

    Use the classmethod constructors rather than the raw initializer so the
    intent (ok / empty / error / timeout) is explicit at every call site.
    """

    source: str
    status: SourceStatus
    data: dict[str, Any] | None = None
    message: str | None = None
    provenance: Provenance | None = None

    # --- explicit constructors -------------------------------------------------
    @classmethod
    def ok(
        cls,
        source: str,
        data: dict[str, Any],
        provenance: Provenance | None = None,
        message: str | None = None,
    ) -> "SourceResult":
        """The source returned a usable record."""
        return cls(
            source=source,
            status=SourceStatus.OK,
            data=data,
            message=message,
            provenance=provenance,
        )

    @classmethod
    def empty(
        cls,
        source: str,
        provenance: Provenance | None = None,
        message: str | None = None,
    ) -> "SourceResult":
        """The source was reached but has no record for this variant (NOT benign)."""
        return cls(
            source=source,
            status=SourceStatus.EMPTY,
            data=None,
            message=message,
            provenance=provenance,
        )

    @classmethod
    def error(
        cls,
        source: str,
        provenance: Provenance | None = None,
        message: str | None = None,
    ) -> "SourceResult":
        """The request failed — evidence unavailable, never read as benign."""
        return cls(
            source=source,
            status=SourceStatus.ERROR,
            data=None,
            message=message,
            provenance=provenance,
        )

    @classmethod
    def timeout(
        cls,
        source: str,
        provenance: Provenance | None = None,
        message: str | None = None,
    ) -> "SourceResult":
        """The request timed out — evidence unavailable, never read as benign."""
        return cls(
            source=source,
            status=SourceStatus.TIMEOUT,
            data=None,
            message=message,
            provenance=provenance,
        )

    # --- semantics for the Confidence Auditor (trigger 6.3) --------------------
    @property
    def is_ok(self) -> bool:
        """True only when a usable record was returned."""
        return self.status is SourceStatus.OK

    @property
    def reached_source(self) -> bool:
        """True if we heard back at all (OK or EMPTY); False for ERROR/TIMEOUT."""
        return self.status in (SourceStatus.OK, SourceStatus.EMPTY)

    @property
    def is_unavailable(self) -> bool:
        """Evidence unavailable (ERROR/TIMEOUT). Must fail loud, never benign."""
        return self.status in (SourceStatus.ERROR, SourceStatus.TIMEOUT)


__all__ = ["SourceStatus", "Provenance", "SourceResult"]

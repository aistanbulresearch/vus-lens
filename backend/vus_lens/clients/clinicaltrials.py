"""ClinicalTrials.gov API v2 client — trials for a gene or condition.

**Optional context only** (build brief Section 5). It enriches the result card
with relevant trials but is never on the critical path: if it fails, the caller
keeps going and the failure is shown, not swallowed. Like every client it still
returns a typed ``SourceResult`` — a failure is ERROR/TIMEOUT (fail loud), and
"no trials found" is EMPTY, never silently blank.
"""

from __future__ import annotations

from typing import Any

from ..config import SETTINGS
from ..models.evidence import SourceResult
from .base import AsyncSourceClient

SOURCE = "ClinicalTrials.gov v2"
LICENSE = "U.S. Government public domain"
STUDY_URL = "https://clinicaltrials.gov/study/"


def _normalize_study(study: dict[str, Any]) -> dict[str, Any]:
    ps = study.get("protocolSection", {}) or {}
    idm = ps.get("identificationModule", {}) or {}
    stm = ps.get("statusModule", {}) or {}
    cond = ps.get("conditionsModule", {}) or {}
    nct_id = idm.get("nctId")
    return {
        "nct_id": nct_id,
        "title": idm.get("briefTitle"),
        "status": stm.get("overallStatus"),
        "conditions": cond.get("conditions"),
        "url": f"{STUDY_URL}{nct_id}" if nct_id else None,
    }


class ClinicalTrialsClient(AsyncSourceClient):
    """Search ClinicalTrials.gov for trials relevant to a gene / condition."""

    def __init__(self) -> None:
        super().__init__(
            SOURCE,
            SETTINGS.clinicaltrials_timeout,
            license_note=LICENSE,
        )
        self.base_url = SETTINGS.clinicaltrials_base_url

    async def search(
        self,
        *,
        gene: str | None = None,
        condition: str | None = None,
        page_size: int = 5,
    ) -> SourceResult:
        """Search by gene (free-text term) and/or condition. One is required."""
        params: dict[str, Any] = {"pageSize": page_size, "countTotal": "true"}
        if condition:
            params["query.cond"] = condition
        if gene:
            params["query.term"] = gene
        if "query.cond" not in params and "query.term" not in params:
            prov = self.provenance(f"{self.base_url}/studies", params)
            return SourceResult.error(SOURCE, prov, "need a gene or condition to search")

        url = f"{self.base_url}/studies"
        prov = self.provenance(url, params)
        http = await self.request_json("GET", url, params=params)
        if not http.ok:
            return self.failure_result(http, prov)

        body = http.json or {}
        studies = body.get("studies", [])
        if not studies:
            return SourceResult.empty(
                SOURCE, prov, f"no trials for {condition or gene}"
            )

        data = {
            "total_count": body.get("totalCount"),
            "returned": len(studies),
            "query": {"gene": gene, "condition": condition},
            "trials": [_normalize_study(s) for s in studies],
        }
        return SourceResult.ok(SOURCE, data, prov)


__all__ = ["ClinicalTrialsClient"]

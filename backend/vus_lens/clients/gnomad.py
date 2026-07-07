"""gnomAD GraphQL v4 client — allele frequency + ancestry breakdown.

This is the source behind the tool's centerpiece (build brief Section 6.1).
gnomAD v4 reports allele counts per genetic ancestry group, including **mid**
(Middle Eastern) — the group relevant to a Turkish patient, and one represented
roughly 200x less than Non-Finnish Europeans. The client surfaces the real
**allele number (AN)** per ancestry so the Confidence Auditor can later judge
whether a frequency-based ACMG criterion is adequately powered for this patient.

Exome and genome are distinct samples and are kept separate. Nothing is
computed or judged here — the raw counts are surfaced faithfully.
"""

from __future__ import annotations

from typing import Any

from ..config import SETTINGS
from ..models.evidence import SourceResult
from ..models.variant import VariantQuery
from .base import AsyncSourceClient

SOURCE = "gnomAD v4"
LICENSE = "gnomAD terms of use (open)"

# gnomAD's own genetic-ancestry group labels (factual, from gnomAD docs).
ANCESTRY_LABELS: dict[str, str] = {
    "afr": "African / African-American",
    "ami": "Amish",
    "amr": "Admixed American",
    "asj": "Ashkenazi Jewish",
    "eas": "East Asian",
    "fin": "Finnish",
    "mid": "Middle Eastern",
    "nfe": "Non-Finnish European",
    "sas": "South Asian",
    "remaining": "Remaining individuals",
}

QUERY = """
query VariantAncestry($variantId: String!, $dataset: DatasetId!) {
  variant(variantId: $variantId, dataset: $dataset) {
    variant_id
    exome  { ac an af populations { id ac an } }
    genome { ac an af populations { id ac an } }
  }
}
"""


def _extract_sample(sample: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull totals + per-ancestry AN/AC, dropping sex-split (`_XX`/`_XY`) ids."""
    if not sample:
        return None
    populations: dict[str, Any] = {}
    for p in sample.get("populations", []):
        pid = p.get("id", "")
        if "_" in pid or pid in ("XX", "XY"):
            continue
        populations[pid] = {"an": p.get("an"), "ac": p.get("ac")}
    return {
        "an": sample.get("an"),
        "ac": sample.get("ac"),
        "af": sample.get("af"),
        "populations": populations,
    }


def _normalize(variant: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_id": variant.get("variant_id"),
        "exome": _extract_sample(variant.get("exome")),
        "genome": _extract_sample(variant.get("genome")),
    }


def ancestry_allele_number(data: dict[str, Any], population: str) -> dict[str, Any]:
    """Combined exome+genome AN/AC for one ancestry — a convenience for 6.1.

    Returns the parts and their sum so callers can see exactly what the total
    rests on. Absent samples contribute nothing (and are reported as None).
    """
    exome = (data.get("exome") or {}).get("populations", {}).get(population)
    genome = (data.get("genome") or {}).get("populations", {}).get(population)
    exome_an = exome.get("an") if exome else None
    genome_an = genome.get("an") if genome else None
    total_an = (exome_an or 0) + (genome_an or 0)
    return {
        "population": population,
        "label": ANCESTRY_LABELS.get(population, population),
        "exome_an": exome_an,
        "genome_an": genome_an,
        "total_an": total_an,
        "exome_ac": exome.get("ac") if exome else None,
        "genome_ac": genome.get("ac") if genome else None,
    }


class GnomadClient(AsyncSourceClient):
    """Fetch a variant's allele frequency + ancestry breakdown from gnomAD v4."""

    def __init__(self) -> None:
        super().__init__(
            SOURCE,
            SETTINGS.gnomad_timeout,
            dataset_version=SETTINGS.gnomad_dataset,
            license_note=LICENSE,
        )
        self.url = SETTINGS.gnomad_graphql_url
        self.dataset = SETTINGS.gnomad_dataset

    async def fetch(self, query: VariantQuery) -> SourceResult:
        variant_id = query.gnomad_variant_id()
        if not variant_id:
            prov = self.provenance(self.url, query.raw)
            return SourceResult.error(
                SOURCE, prov, "no hg38 chrom-pos-ref-alt to build a gnomAD id"
            )
        return await self.fetch_by_id(variant_id)

    async def fetch_by_id(self, variant_id: str) -> SourceResult:
        variables = {"variantId": variant_id, "dataset": self.dataset}
        prov = self.provenance(self.url, {"variantId": variant_id, "dataset": self.dataset})
        http = await self.request_json(
            "POST", self.url, json_body={"query": QUERY, "variables": variables}
        )
        if not http.ok:
            return self.failure_result(http, prov)

        body = http.json or {}
        errors = body.get("errors")
        variant = (body.get("data") or {}).get("variant")

        if errors:
            messages = "; ".join(e.get("message", str(e)) for e in errors)
            # gnomAD reports a missing variant as an error, not just null.
            if "not found" in messages.lower():
                return SourceResult.empty(SOURCE, prov, f"not in gnomAD {self.dataset}: {variant_id}")
            return SourceResult.error(SOURCE, prov, f"GraphQL error: {messages}")

        if not variant:
            return SourceResult.empty(SOURCE, prov, f"not in gnomAD {self.dataset}: {variant_id}")

        return SourceResult.ok(SOURCE, _normalize(variant), prov)


__all__ = ["GnomadClient", "ancestry_allele_number", "ANCESTRY_LABELS"]

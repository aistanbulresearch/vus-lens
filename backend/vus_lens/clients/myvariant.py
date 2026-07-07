"""MyVariant.info client — ClinVar, REVEL, AlphaMissense, dbNSFP.

Two things this client is careful about (build brief Section 5):

1. **Per-transcript in-silico scores.** REVEL and AlphaMissense arrive as either
   a scalar or a per-transcript *array* aligned with ``dbnsfp.ensembl.transcriptid``.
   We select the value for the canonical transcript and **never take the max**
   (that would bias every variant toward "damaging"). When the available signals
   cannot uniquely identify the canonical transcript, we report the score as
   *uncertain* and keep the raw array — we do not invent a single number.

2. **ClinVar is surfaced, not judged.** We return the raw per-submission
   significances and review statuses. This client does not compute an overall
   classification — that is the deterministic ACMG layer's job (Day 2).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..config import SETTINGS
from ..models.evidence import SourceResult
from ..models.variant import VariantQuery
from .base import AsyncSourceClient

SOURCE = "MyVariant.info"
LICENSE = "open aggregation of public sources (ClinVar, dbNSFP, etc.)"

# Requested fields. Broad enough to normalize evidence + resolve hg38 coords for
# the gnomAD handoff, without pulling the entire (large) document.
FIELDS = ",".join(
    [
        "chrom",
        "vcf",
        "clinvar",
        "dbnsfp.hg38",
        "dbnsfp.genename",
        "dbnsfp.ensembl",
        "dbnsfp.vep_canonical",
        "dbnsfp.appris",
        "dbnsfp.revel",
        "dbnsfp.alphamissense",
    ]
)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _select_canonical_score(
    score: Any,
    transcript_ids: Any,
    vep_canonical: Any,
    appris: Any,
) -> dict[str, Any]:
    """Pick the single in-silico score for the canonical transcript.

    Order (each step only fires when it uniquely resolves):
      1. scalar score       -> use it (dbNSFP already collapsed to one value)
      2. all values equal   -> use it (no ambiguity)
      3. exactly one vep_canonical == "YES"
      4. exactly one appris == "principal1"
      5. unresolved         -> value=None, uncertain=True (keep raw; never max)
    """
    if score is None:
        return {"value": None, "transcript": None, "method": "absent", "uncertain": False, "raw": None}

    if not isinstance(score, list):
        tid = transcript_ids[0] if isinstance(transcript_ids, list) and transcript_ids else transcript_ids
        return {"value": score, "transcript": tid, "method": "single", "uncertain": False, "raw": score}

    scores = score
    tids = transcript_ids if isinstance(transcript_ids, list) else [transcript_ids] * len(scores)

    # 2) uniform
    non_null = [s for s in scores if s is not None]
    if non_null and len(set(non_null)) == 1:
        idx = scores.index(non_null[0])
        return {"value": non_null[0], "transcript": _safe(tids, idx), "method": "uniform", "uncertain": False, "raw": scores}

    # 3) vep_canonical uniquely "YES"
    vc = vep_canonical if isinstance(vep_canonical, list) else None
    if vc and len(vc) == len(scores):
        yes_idx = [i for i, v in enumerate(vc) if str(v).upper() == "YES"]
        if len(yes_idx) == 1 and scores[yes_idx[0]] is not None:
            i = yes_idx[0]
            return {"value": scores[i], "transcript": _safe(tids, i), "method": "vep_canonical", "uncertain": False, "raw": scores}

    # 4) appris uniquely principal1
    ap = appris if isinstance(appris, list) else None
    if ap and len(ap) == len(scores):
        princ = [i for i, v in enumerate(ap) if str(v).lower() == "principal1"]
        if len(princ) == 1 and scores[princ[0]] is not None:
            i = princ[0]
            return {"value": scores[i], "transcript": _safe(tids, i), "method": "appris_principal1", "uncertain": False, "raw": scores}

    # 5) unresolved — surface uncertainty, keep the raw array, never take the max
    return {
        "value": None,
        "transcript": None,
        "method": "unresolved",
        "uncertain": True,
        "raw": scores,
        "range": [min(non_null), max(non_null)] if non_null else None,
    }


def _safe(seq: list[Any], i: int) -> Any:
    return seq[i] if isinstance(seq, list) and 0 <= i < len(seq) else None


def _extract_clinvar(clinvar: dict[str, Any] | None) -> dict[str, Any] | None:
    if not clinvar:
        return None
    submissions = []
    for rcv in _as_list(clinvar.get("rcv")):
        if not isinstance(rcv, dict):
            continue
        cond = rcv.get("conditions") or {}
        submissions.append(
            {
                "significance": rcv.get("clinical_significance"),
                "review_status": rcv.get("review_status"),
                "condition": cond.get("name") if isinstance(cond, dict) else cond,
                "accession": rcv.get("accession"),
                "last_evaluated": rcv.get("last_evaluated"),
            }
        )
    significances = sorted({s["significance"] for s in submissions if s["significance"]})
    return {
        "variant_id": clinvar.get("variant_id"),
        "gene": clinvar.get("gene"),
        "submissions": submissions,
        "significances": significances,
    }


def _extract_hg38(doc: dict[str, Any]) -> dict[str, Any] | None:
    """hg38 chrom/pos/ref/alt for the gnomAD handoff (gnomAD v4 is GRCh38)."""
    chrom = str(doc.get("chrom")) if doc.get("chrom") is not None else None
    dbnsfp = doc.get("dbnsfp") or {}
    clinvar = doc.get("clinvar") or {}
    hg38 = clinvar.get("hg38") or dbnsfp.get("hg38")
    ref = clinvar.get("ref") or dbnsfp.get("ref")
    alt = clinvar.get("alt") or dbnsfp.get("alt")
    if not (chrom and hg38 and isinstance(hg38, dict) and hg38.get("start")):
        return None
    return {"chrom": chrom, "pos": int(hg38["start"]), "ref": ref, "alt": alt}


def _normalize(doc: dict[str, Any]) -> dict[str, Any]:
    dbnsfp = doc.get("dbnsfp") or {}
    ensembl = dbnsfp.get("ensembl") or {}
    tids = ensembl.get("transcriptid")
    gene = dbnsfp.get("genename")
    if isinstance(gene, list):
        gene = gene[0] if gene else None

    revel_raw = (dbnsfp.get("revel") or {}).get("score") if isinstance(dbnsfp.get("revel"), dict) else None
    am = dbnsfp.get("alphamissense") if isinstance(dbnsfp.get("alphamissense"), dict) else {}
    am_raw = am.get("score") if am else None

    revel = _select_canonical_score(revel_raw, tids, dbnsfp.get("vep_canonical"), dbnsfp.get("appris"))
    alphamissense = _select_canonical_score(am_raw, tids, dbnsfp.get("vep_canonical"), dbnsfp.get("appris"))
    if am:
        alphamissense["pred"] = am.get("pred")
        alphamissense["rankscore"] = am.get("rankscore")

    return {
        "gene": gene or (doc.get("clinvar") or {}).get("gene"),
        "myvariant_id": doc.get("_id"),
        "hg38": _extract_hg38(doc),
        "clinvar": _extract_clinvar(doc.get("clinvar")),
        "revel": revel,
        "alphamissense": alphamissense,
        "transcripts": {
            "ensembl_ids": tids,
            "vep_canonical": dbnsfp.get("vep_canonical"),
            "appris": dbnsfp.get("appris"),
        },
    }


class MyVariantClient(AsyncSourceClient):
    """Fetch and normalize a variant from MyVariant.info."""

    def __init__(self) -> None:
        super().__init__(
            SOURCE,
            SETTINGS.myvariant_timeout,
            license_note=LICENSE,
        )
        self.base_url = SETTINGS.myvariant_base_url

    async def fetch(self, query: VariantQuery) -> SourceResult:
        """Resolve a variant by rsID (with ref/alt) or by MyVariant hg19 HGVS id."""
        if query.rsid:
            return await self._fetch_by_rsid(query)
        if query.hgvs:
            return await self._fetch_by_id(query.hgvs)
        prov = self.provenance(self.base_url, query.raw)
        return SourceResult.error(SOURCE, prov, "no rsID or HGVS id in query")

    async def _fetch_by_rsid(self, query: VariantQuery) -> SourceResult:
        url = f"{self.base_url}/query"
        params = {"q": query.rsid, "fields": FIELDS, "size": 20}
        prov = self.provenance(url, params)
        http = await self.request_json("GET", url, params=params)
        if not http.ok:
            return self.failure_result(http, prov)

        hits = (http.json or {}).get("hits", [])
        if not hits:
            return SourceResult.empty(SOURCE, prov, f"no MyVariant record for {query.rsid}")

        # Disambiguate multi-allelic rsIDs by the requested ref/alt.
        if query.ref and query.alt:
            hits = [h for h in hits if (h.get("vcf") or {}).get("ref") == query.ref and (h.get("vcf") or {}).get("alt") == query.alt] or hits
        if len(hits) > 1 and not (query.ref and query.alt):
            ids = [h.get("_id") for h in hits]
            return SourceResult.error(SOURCE, prov, f"ambiguous rsID: {len(hits)} alleles {ids}; specify ref/alt")

        return SourceResult.ok(SOURCE, _normalize(hits[0]), prov)

    async def _fetch_by_id(self, variant_id: str) -> SourceResult:
        url = f"{self.base_url}/variant/{quote(variant_id, safe='')}"
        params = {"fields": FIELDS}
        prov = self.provenance(url, {"id": variant_id, "fields": FIELDS})
        http = await self.request_json("GET", url, params=params)
        if not http.ok:
            if http.status_code == 404:
                return SourceResult.empty(SOURCE, prov, f"no MyVariant record for {variant_id}")
            return self.failure_result(http, prov)
        return SourceResult.ok(SOURCE, _normalize(http.json or {}), prov)


__all__ = ["MyVariantClient"]

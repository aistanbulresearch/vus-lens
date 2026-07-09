"""Deterministic end-to-end evaluation: variant -> clients -> ACMG -> bundle.

This is the **no-LLM** spine (build brief Section 4): fetch public data, map it to
ACMG criteria, aggregate into an evidence bundle with a deterministic class and
the detections that the Day-3 triggers and Day-4 reasoning layers will explain.
Every source failure is surfaced (fail loud), never read as benign.
"""

from __future__ import annotations

from dataclasses import dataclass

from .acmg.aggregate import EvidenceBundle, aggregate_evidence
from .acmg.clinvar import ClinVarResult, read_clinvar
from .acmg.frequency import FrequencyResult, assess_frequency
from .acmg.insilico import InSilicoResult, assess_insilico
from .clients.gnomad import GnomadClient
from .clients.myvariant import MyVariantClient
from .models.evidence import SourceResult
from .models.variant import VariantQuery


@dataclass(frozen=True)
class EvaluationResult:
    query: VariantQuery
    gene: str | None
    myvariant: SourceResult
    gnomad: SourceResult
    frequency: FrequencyResult
    insilico: InSilicoResult
    clinvar: ClinVarResult
    bundle: EvidenceBundle


async def evaluate_variant(
    query: VariantQuery,
    *,
    myvariant_client: MyVariantClient | None = None,
    gnomad_client: GnomadClient | None = None,
) -> EvaluationResult:
    mv = myvariant_client or MyVariantClient()
    gn = gnomad_client or GnomadClient()

    mv_res = await mv.fetch(query)

    # Resolve hg38 coordinates from MyVariant for the gnomAD lookup.
    gene = query.gene
    resolved = query
    if mv_res.is_ok:
        data = mv_res.data or {}
        gene = gene or data.get("gene")
        hg = data.get("hg38")
        if hg and hg.get("pos"):
            resolved = query.model_copy(
                update={"chrom": hg.get("chrom"), "pos": hg.get("pos"), "ref": hg.get("ref"), "alt": hg.get("alt"), "gene": gene}
            )

    gn_res = await gn.fetch(resolved)

    frequency = assess_frequency(gn_res, gene)
    insilico = assess_insilico(mv_res, gene)
    clinvar = read_clinvar(mv_res)
    bundle = aggregate_evidence(frequency, insilico, clinvar, gene)

    return EvaluationResult(query, gene, mv_res, gn_res, frequency, insilico, clinvar, bundle)


__all__ = ["EvaluationResult", "evaluate_variant"]

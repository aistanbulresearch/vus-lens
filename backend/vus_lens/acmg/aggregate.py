"""Deterministic evidence aggregation — the final class and the reasoning substrate.

Combines the assigned criteria into an ACMG class using the Richards 2015
combining rules, restricted to the criteria this tool actually assigns
(BA1/BS1/BP4 benign; PM2/PP3 pathogenic). With only those, pathogenic
combinations never reach Likely Pathogenic/Pathogenic, so variants remain VUS
unless benign criteria fire — an honest consequence of the tool's scope, not a
bug.

It also emits **deterministic detections** — well-defined, verifiable
observations (e.g. the deterministic class contradicts ClinVar; in-silico
non-concordance) that are the raw material the Day-3 triggers and Day-4 reasoning
layers explain. **No LLM here.** The class comes from this layer alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .clinvar import ClinVarResult
from .criteria import ACMGCriterion, EvidenceStrength
from .frequency import FrequencyResult
from .insilico import InSilicoResult


class ACMGClass(str, Enum):
    BENIGN = "Benign"
    LIKELY_BENIGN = "Likely benign"
    VUS = "Uncertain significance"
    LIKELY_PATHOGENIC = "Likely pathogenic"
    PATHOGENIC = "Pathogenic"


@dataclass(frozen=True)
class EvidenceItem:
    criterion: ACMGCriterion
    strength: EvidenceStrength | None
    source: str
    reason: str
    citation: str


@dataclass(frozen=True)
class EvidenceBundle:
    gene: str | None
    acmg_class: ACMGClass
    class_basis: str
    criteria: tuple[EvidenceItem, ...]
    clinvar: ClinVarResult
    detections: tuple[str, ...]
    unavailable_sources: tuple[str, ...]


def _classify(criteria: tuple[EvidenceItem, ...]) -> tuple[ACMGClass, str]:
    crits = [i.criterion for i in criteria]
    if ACMGCriterion.BA1 in crits:
        return ACMGClass.BENIGN, "BA1 (allele frequency too common) - stand-alone benign"
    n_bs = crits.count(ACMGCriterion.BS1)
    n_bp = crits.count(ACMGCriterion.BP4)
    if n_bs >= 2:
        return ACMGClass.BENIGN, ">=2 Benign Strong"
    if (n_bs >= 1 and n_bp >= 1) or n_bp >= 2:
        return ACMGClass.LIKELY_BENIGN, "1 Benign Strong + 1 Benign Supporting (or >=2 Supporting)"
    # PM2 (Moderate) + PP3 (Supporting) cannot reach LP/P per Richards 2015 (no
    # PVS1/PS in scope) -> such variants stay VUS. Honest, not a defect.
    return ACMGClass.VUS, "criteria do not meet a benign or pathogenic combination - uncertain"


def _items(frequency: FrequencyResult, insilico: InSilicoResult) -> tuple[EvidenceItem, ...]:
    items: list[EvidenceItem] = []
    if frequency.criterion:
        items.append(EvidenceItem(frequency.criterion, None, f"frequency [{frequency.spec_source}]", frequency.reason, frequency.citation))
    if insilico.criterion:
        items.append(EvidenceItem(insilico.criterion, insilico.strength, f"in-silico [{insilico.spec_source}]", insilico.reason, insilico.citation))
    return tuple(items)


def aggregate_evidence(
    frequency: FrequencyResult,
    insilico: InSilicoResult,
    clinvar: ClinVarResult,
    gene: str | None = None,
) -> EvidenceBundle:
    criteria = _items(frequency, insilico)
    acmg_class, basis = _classify(criteria)

    detections: list[str] = []
    unavailable: list[str] = []
    if not frequency.data_available:
        unavailable.append("frequency")
    if not insilico.data_available:
        unavailable.append("in-silico")
    if not clinvar.data_available:
        unavailable.append("ClinVar")
    for src in unavailable:
        detections.append(f"evidence unavailable: {src} - not the same as benign (fail-loud)")

    benign_class = acmg_class in (ACMGClass.BENIGN, ACMGClass.LIKELY_BENIGN)
    path_class = acmg_class in (ACMGClass.PATHOGENIC, ACMGClass.LIKELY_PATHOGENIC)
    if benign_class and clinvar.has_pathogenic:
        detections.append(
            f"deterministic class '{acmg_class.value}' conflicts with ClinVar pathogenic "
            f"{list(clinvar.significances)} - cross-source conflict [Layer 2]"
        )
    if path_class and clinvar.has_benign:
        detections.append(
            f"deterministic class '{acmg_class.value}' conflicts with ClinVar benign "
            f"{list(clinvar.significances)} - cross-source conflict [Layer 2]"
        )
    if insilico.band == "indeterminate" and clinvar.has_pathogenic:
        detections.append("in-silico indeterminate while ClinVar reports pathogenic [Layer 2]")
    if insilico.crosscheck_note:
        detections.append(f"in-silico cross-check: {insilico.crosscheck_note}")

    return EvidenceBundle(gene, acmg_class, basis, criteria, clinvar, tuple(detections), tuple(unavailable))


__all__ = ["ACMGClass", "EvidenceItem", "EvidenceBundle", "aggregate_evidence"]

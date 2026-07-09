"""Deterministic ACMG frequency criteria: PM2 / BS1 / BA1.

Maps a gnomAD ``SourceResult`` to at most one frequency criterion using cited
thresholds (``thresholds.py``). Uses **grpmax** - the highest allele frequency
among ancestry groups with an adequate sample - per ClinGen SVI, so a variant
common in one population is not missed. No LLM, no tuning.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.evidence import SourceResult
from .criteria import ACMGCriterion
from .thresholds import (
    BA1_AF,
    BS1_AF,
    CITATION_BA1,
    CITATION_BS1,
    CITATION_PM2,
    GRPMAX_AN_FLOOR,
    PM2_AF,
)


@dataclass(frozen=True)
class FrequencyResult:
    criterion: ACMGCriterion | None
    applied: bool
    data_available: bool
    grpmax_af: float | None
    grpmax_pop: str | None
    global_af: float | None
    reason: str
    citation: str


def _combined_pop_afs(data: dict) -> dict[str, tuple[int, int, float]]:
    exome = (data.get("exome") or {}).get("populations", {}) or {}
    genome = (data.get("genome") or {}).get("populations", {}) or {}
    out: dict[str, tuple[int, int, float]] = {}
    for pop in set(exome) | set(genome):
        an = (exome.get(pop, {}).get("an") or 0) + (genome.get(pop, {}).get("an") or 0)
        ac = (exome.get(pop, {}).get("ac") or 0) + (genome.get(pop, {}).get("ac") or 0)
        out[pop] = (an, ac, (ac / an if an else 0.0))
    return out


def _grpmax(
    pop_afs: dict[str, tuple[int, int, float]], an_floor: int
) -> tuple[str, float] | None:
    """Highest AF among ancestries with an adequate sample (AN >= an_floor)."""
    best: tuple[str, float] | None = None
    for pop, (an, ac, af) in pop_afs.items():
        if an < an_floor:
            continue
        if best is None or af > best[1]:
            best = (pop, af)
    return best


def _global_af(data: dict) -> float:
    exome, genome = data.get("exome") or {}, data.get("genome") or {}
    an = (exome.get("an") or 0) + (genome.get("an") or 0)
    ac = (exome.get("ac") or 0) + (genome.get("ac") or 0)
    return ac / an if an else 0.0


def assess_frequency(gnomad: SourceResult) -> FrequencyResult:
    # Fail loud: an unreachable gnomAD is evidence UNAVAILABLE, never "absent".
    if gnomad.is_unavailable:
        return FrequencyResult(
            None, False, False, None, None, None,
            "gnomAD unavailable - frequency criteria not assessed "
            "(evidence unavailable, not benign)",
            "",
        )
    # EMPTY: reached gnomAD, no record -> genuinely absent -> supports PM2.
    if not gnomad.is_ok:
        return FrequencyResult(
            ACMGCriterion.PM2, True, True, 0.0, None, 0.0,
            "absent from gnomAD (no record) - supports PM2", CITATION_PM2,
        )

    data = gnomad.data or {}
    pop_afs = _combined_pop_afs(data)
    grpmax = _grpmax(pop_afs, GRPMAX_AN_FLOOR)
    grpmax_af = grpmax[1] if grpmax else 0.0
    grpmax_pop = grpmax[0] if grpmax else None
    global_af = _global_af(data)

    if grpmax_af > BA1_AF:
        return FrequencyResult(
            ACMGCriterion.BA1, True, True, grpmax_af, grpmax_pop, global_af,
            f"grpmax AF {grpmax_af:.3g} ({grpmax_pop}) exceeds BA1 threshold {BA1_AF}",
            CITATION_BA1,
        )
    if grpmax_af > BS1_AF:
        return FrequencyResult(
            ACMGCriterion.BS1, True, True, grpmax_af, grpmax_pop, global_af,
            f"grpmax AF {grpmax_af:.3g} ({grpmax_pop}) exceeds BS1 threshold {BS1_AF}",
            CITATION_BS1,
        )
    if grpmax_af < PM2_AF:
        return FrequencyResult(
            ACMGCriterion.PM2, True, True, grpmax_af, grpmax_pop, global_af,
            f"grpmax AF {grpmax_af:.3g} is below PM2 threshold {PM2_AF} (rare/absent)",
            CITATION_PM2,
        )
    return FrequencyResult(
        None, False, True, grpmax_af, grpmax_pop, global_af,
        f"grpmax AF {grpmax_af:.3g} is between PM2 and BS1 thresholds - no frequency criterion",
        "",
    )


__all__ = ["FrequencyResult", "assess_frequency"]

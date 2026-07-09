"""Deterministic ACMG frequency criteria: PM2 / BS1 / BA1.

Maps a gnomAD ``SourceResult`` to at most one frequency criterion using cited,
gene-specific thresholds where available (ClinGen VCEP for ATM/PALB2) and a
labeled generic SVI default otherwise (``thresholds.py``).

Metric split, per the VCEP spec text:
- **BA1 / BS1** use the **grpmax filtering AF** (gnomAD v4 faf95) — sample-size
  aware, so a variant merely undersampled is not called benign.
- **PM2** uses the **raw grpmax AF** (point estimate) with an adequacy floor.

No LLM, no tuning. Fail loud: an unreachable gnomAD is *unavailable*, never
"absent".
"""

from __future__ import annotations

from dataclasses import dataclass

from ..clients.gnomad import grpmax_faf
from ..models.evidence import SourceResult
from .criteria import ACMGCriterion
from .thresholds import GRPMAX_AN_FLOOR, frequency_spec


@dataclass(frozen=True)
class FrequencyResult:
    criterion: ACMGCriterion | None
    applied: bool
    data_available: bool
    gene: str | None
    spec_source: str  # "VCEP" or "generic"
    spec_label: str
    grpmax_faf: float | None  # filtering AF used for BA1/BS1
    grpmax_af: float | None  # raw grpmax used for PM2
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


def _raw_grpmax(pop_afs: dict[str, tuple[int, int, float]], an_floor: int) -> tuple[str, float] | None:
    """Highest raw AF among ancestries with an adequate sample (AN >= floor)."""
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


def assess_frequency(gnomad: SourceResult, gene: str | None = None) -> FrequencyResult:
    spec = frequency_spec(gene)

    # Fail loud: an unreachable gnomAD is evidence UNAVAILABLE, never "absent".
    if gnomad.is_unavailable:
        return FrequencyResult(
            None, False, False, gene, spec.source, spec.label, None, None, None, None,
            "gnomAD unavailable - frequency criteria not assessed "
            "(evidence unavailable, not benign)",
            "",
        )
    # EMPTY: reached gnomAD, no record -> genuinely absent -> supports PM2.
    if not gnomad.is_ok:
        return FrequencyResult(
            ACMGCriterion.PM2, True, True, gene, spec.source, spec.label, 0.0, 0.0, None, 0.0,
            "absent from gnomAD (no record) - supports PM2", spec.label,
        )

    data = gnomad.data or {}
    faf, _faf_pop = grpmax_faf(data)  # filtering AF for BA1/BS1
    pop_afs = _combined_pop_afs(data)
    raw = _raw_grpmax(pop_afs, GRPMAX_AN_FLOOR)  # point estimate for PM2
    raw_af = raw[1] if raw else 0.0
    raw_pop = raw[0] if raw else None
    global_af = _global_af(data)

    if faf > spec.ba1:
        crit = ACMGCriterion.BA1
        reason = f"grpmax filtering AF {faf:.3g} exceeds BA1 {spec.ba1:.3g} [{spec.source}]"
    elif faf > spec.bs1:
        crit = ACMGCriterion.BS1
        reason = f"grpmax filtering AF {faf:.3g} exceeds BS1 {spec.bs1:.3g} [{spec.source}]"
    elif raw_af <= spec.pm2:
        crit = ACMGCriterion.PM2
        reason = f"raw grpmax AF {raw_af:.3g} at/below PM2 {spec.pm2:.3g} (rare/absent) [{spec.source}]"
    else:
        crit = None
        reason = (
            f"grpmax filtering AF {faf:.3g} / raw {raw_af:.3g} between PM2 and BS1 "
            f"- no frequency criterion [{spec.source}]"
        )

    return FrequencyResult(
        crit, crit is not None, True, gene, spec.source, spec.label,
        faf, raw_af, raw_pop, global_af, reason, spec.label if crit else "",
    )


__all__ = ["FrequencyResult", "assess_frequency"]

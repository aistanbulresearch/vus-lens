"""Deterministic ACMG in-silico criteria: PP3 / BP4 from a single calibrated tool.

Per ClinGen / Pejaver (FINAL_BRIEF 5b):
- PP3/BP4 come from ONE calibrated tool — **REVEL** on the canonical transcript.
  REVEL and AlphaMissense are correlated, so AlphaMissense is **not** a second
  criterion; it is surfaced as a **Layer-2 cross-check** only.
- The **indeterminate band** yields neither criterion: a mid-range REVEL is never
  read as benign (the naive 0.5-cutoff error this tool exists to avoid).
- **Uncertain canonical transcript** -> no PP3/BP4 + a visible flag.
- A gene whose VCEP uses a different tool (PALB2: SpliceAI-only) gets no
  protein-level REVEL criterion; we do not run live SpliceAI -> declared gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.evidence import SourceResult
from .criteria import ACMGCriterion, EvidenceStrength
from .thresholds import InSilicoSpec, insilico_spec


@dataclass(frozen=True)
class InSilicoResult:
    criterion: ACMGCriterion | None
    strength: EvidenceStrength | None
    applied: bool
    data_available: bool
    gene: str | None
    spec_source: str
    spec_label: str
    tool: str
    revel: float | None
    band: str
    transcript: str | None
    alphamissense: dict[str, Any] | None  # Layer-2 cross-check, NOT a criterion
    crosscheck_note: str | None
    reason: str
    citation: str
    flags: tuple[str, ...]


def _classify_revel(revel: float, spec: InSilicoSpec):
    """Return (criterion, strength, band). Single tool; never stack/max."""
    for thr, strength in spec.pp3:  # high -> low
        if revel >= thr:
            return ACMGCriterion.PP3, strength, f"PP3_{strength.value}"
    for thr, strength in spec.bp4:  # low -> high (strongest first)
        if revel <= thr:
            return ACMGCriterion.BP4, strength, f"BP4_{strength.value}"
    return None, None, "indeterminate"


_AM_DIRECTION = {"P": "pathogenic", "B": "benign", "A": "ambiguous"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _am_direction(pred: Any) -> str | None:
    """Resolve an AlphaMissense direction from a scalar OR per-transcript pred.

    AlphaMissense is a Layer-2 cross-check — a *directional* signal, not a scored
    criterion — so a per-transcript pred array that agrees on one direction is
    unambiguous regardless of which transcript is canonical. This deliberately
    differs from REVEL (the criterion), where an unresolved canonical transcript
    withholds the criterion. Mixed predictions -> no directional call (we do not
    fabricate a direction), matching the same discipline.
    """
    dirs = {_AM_DIRECTION.get(str(p).upper()) for p in _as_list(pred) if p is not None}
    dirs.discard(None)  # ignore unknown pred codes
    return next(iter(dirs)) if len(dirs) == 1 else None


def _crosscheck(am: dict[str, Any], criterion) -> tuple[dict[str, Any] | None, str | None]:
    """Surface AlphaMissense for Layer 2 (not a criterion) with a (dis)agreement note.

    Fires when the AM predictions resolve to one direction — either a canonical
    scalar score (single transcript) or a per-transcript array whose predictions
    all agree. When only the array agrees (no single canonical value), we report
    the direction and the score range, never a fabricated single number.
    """
    if not am:
        return None, None
    am_dir = _am_direction(am.get("pred"))
    if am_dir is None:  # no unanimous AM direction -> no clean cross-check
        return None, None

    value = am.get("value")
    rng = am.get("range")
    n_tx = len([p for p in _as_list(am.get("pred")) if p is not None])
    surfaced = {
        "value": value,
        "pred": am.get("pred"),
        "direction": am_dir,
        "score_range": rng,
        "n_transcripts": n_tx,
    }
    if value is not None:
        detail = f"{value:.3g}"
    elif isinstance(rng, list) and len(rng) == 2:
        detail = f"{rng[0]:.3g}-{rng[1]:.3g} across {n_tx} transcripts"
    else:
        detail = f"consistent across {n_tx} transcripts"

    revel_dir = (
        "pathogenic" if criterion is ACMGCriterion.PP3
        else "benign" if criterion is ACMGCriterion.BP4
        else "indeterminate"
    )
    if am_dir == "ambiguous":
        note = f"AlphaMissense ambiguous ({detail}); REVEL {revel_dir} (cross-source signal for Layer 2)"
    elif revel_dir == "indeterminate":
        note = f"AlphaMissense {am_dir} ({detail}) while REVEL is indeterminate (cross-source signal for Layer 2)"
    elif am_dir == revel_dir:
        note = f"AlphaMissense {am_dir} ({detail}) concordant with REVEL ({revel_dir})"
    else:
        note = f"AlphaMissense {am_dir} ({detail}) disagrees with REVEL ({revel_dir}) - cross-source conflict for Layer 2"
    return surfaced, note


def assess_insilico(myvariant: SourceResult, gene: str | None = None) -> InSilicoResult:
    spec = insilico_spec(gene)

    def result(criterion, strength, band, revel, transcript, am_dict, note, reason, citation, flags):
        return InSilicoResult(
            criterion, strength, criterion is not None, True, gene, spec.source,
            spec.label, spec.tool, revel, band, transcript, am_dict, note, reason,
            citation, tuple(flags),
        )

    # Fail loud: an unreachable MyVariant is evidence unavailable, never benign.
    if myvariant.is_unavailable:
        return InSilicoResult(
            None, None, False, False, gene, spec.source, spec.label, spec.tool,
            None, "unavailable", None, None, None,
            "MyVariant unavailable - in-silico not assessed (evidence unavailable, not benign)",
            "", (),
        )

    data = myvariant.data or {}
    revel_sel = data.get("revel") or {}
    am = data.get("alphamissense") or {}
    transcript = revel_sel.get("transcript")

    # Gene whose VCEP uses a non-REVEL tool (PALB2: SpliceAI-only).
    if not spec.protein_predictor_used:
        return result(
            None, None, "protein_predictor_not_used", revel_sel.get("value"), transcript, None, None,
            f"{gene} VCEP uses {spec.tool} for PP3/BP4; protein-level REVEL not applied; "
            f"SpliceAI not run (declared gap)",
            spec.label, ["protein_predictor_not_used", "splice_not_scored"],
        )

    # Uncertain canonical transcript -> no assignment + visible flag.
    if revel_sel.get("uncertain") or revel_sel.get("method") == "unresolved":
        return result(
            None, None, "transcript_ambiguity", None, transcript, None, None,
            "transcript ambiguity - in-silico evidence not applied", "", ["transcript_ambiguity"],
        )

    revel = revel_sel.get("value")
    if revel is None:
        return result(
            None, None, "absent", None, transcript, None, None,
            "no REVEL score (not a scored missense variant)", "", ["revel_absent"],
        )

    criterion, strength, band = _classify_revel(revel, spec)
    am_dict, note = _crosscheck(am, criterion)
    reason = f"REVEL {revel:.3g} -> {band} [{spec.source}]"
    return result(criterion, strength, band, revel, transcript, am_dict, note, reason, spec.label if criterion else "", [])


__all__ = ["InSilicoResult", "assess_insilico"]

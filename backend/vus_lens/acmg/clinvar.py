"""ClinVar read — significance + review status **surfaced, not re-judged**.

The tool reports what ClinVar says (per-submission significances and review
status) and derives only the booleans needed for later conflict detection
(does ClinVar carry P/LP? B/LB? is it conflicting?). It does **not** convert
ClinVar into an ACMG criterion (no PP5/BP6) — ClinVar is context, and material
for the Layer-2 cross-source reasoning, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.evidence import SourceResult

_PLP = {"pathogenic", "likely pathogenic", "pathogenic/likely pathogenic"}
_BEN = {"benign", "likely benign", "benign/likely benign"}


@dataclass(frozen=True)
class ClinVarResult:
    data_available: bool
    variant_id: str | None
    significances: tuple[str, ...]
    review_status: tuple[str, ...]
    has_pathogenic: bool
    has_benign: bool
    is_conflicting: bool
    n_submissions: int
    summary: str


def read_clinvar(myvariant: SourceResult) -> ClinVarResult:
    # Fail loud: an unreachable source is not "no ClinVar".
    if myvariant.is_unavailable:
        return ClinVarResult(
            False, None, (), (), False, False, False, 0,
            "ClinVar not read - MyVariant unavailable (evidence unavailable, not benign)",
        )

    clinvar = (myvariant.data or {}).get("clinvar")
    if not clinvar:
        return ClinVarResult(True, None, (), (), False, False, False, 0, "no ClinVar record")

    significances = tuple(clinvar.get("significances") or [])
    submissions = clinvar.get("submissions") or []
    review_status = tuple(sorted({s.get("review_status") for s in submissions if s.get("review_status")}))
    low = [s.lower() for s in significances]
    has_pathogenic = any(s in _PLP for s in low)
    has_benign = any(s in _BEN for s in low)
    is_conflicting = any("conflicting" in s for s in low) or (has_pathogenic and has_benign)

    summary = (
        f"ClinVar {clinvar.get('variant_id') or '?'}: {list(significances)} "
        f"({len(submissions)} submission(s); {list(review_status)})"
    )
    return ClinVarResult(
        True, clinvar.get("variant_id"), significances, review_status,
        has_pathogenic, has_benign, is_conflicting, len(submissions), summary,
    )


__all__ = ["ClinVarResult", "read_clinvar"]

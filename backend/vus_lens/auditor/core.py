"""The Confidence Auditor — three deterministic, source-anchored triggers.

- 6.1 ancestry-frequency: a frequency-based rarity call (assigned OR withheld)
  is unreliable when the patient's ancestry sample is too small to support it.
  The adequacy floor is the **rule of 3** (Hanley & Lippman-Hand 1983): to be
  ~95% confident an allele is rarer than f having seen zero copies, you need
  ~3/f alleles. If gnomAD `mid` has fewer, the call rests on too little data.
- 6.2 repeat-expansion: the variant's gene is a known STR-expansion locus that
  short-read WES cannot size — flag regardless of the computed class.
- 6.3 empty != clean: any unavailable source (or the declared Turkish Variome
  subset boundary) is surfaced, never read as benign.

OFF/ON is simply whether ``audit()`` is run: OFF = the deterministic evidence
bundle alone; ON = the bundle plus these warnings on top. The auditor never
changes the class.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..acmg.aggregate import EvidenceBundle
from ..acmg.criteria import ACMGCriterion
from ..acmg.frequency import FrequencyResult
from ..acmg.thresholds import frequency_spec
from ..clients.gnomad import ancestry_allele_number
from ..models.evidence import SourceResult
from .repeat_loci import repeat_locus

_RULE_OF_3 = 3.0  # Hanley & Lippman-Hand 1983


@dataclass(frozen=True)
class AuditWarning:
    trigger: str
    severity: str  # "caution" or "critical"
    message: str
    detail: str
    citation: str | None


@dataclass(frozen=True)
class AuditResult:
    warnings: tuple[AuditWarning, ...]

    @property
    def passed(self) -> bool:
        return not self.warnings


def _threshold_in_play(frequency: FrequencyResult, gene: str | None) -> float | None:
    """The frequency threshold this variant's call turns on (assigned or withheld)."""
    spec = frequency_spec(gene)
    if frequency.criterion is ACMGCriterion.BA1:
        return spec.ba1
    if frequency.criterion is ACMGCriterion.BS1:
        return spec.bs1
    if frequency.criterion is ACMGCriterion.PM2:
        return spec.pm2
    # Withheld: no criterion assigned, but the variant is rare (grpmax below BS1)
    # -> a PM2-type rarity call was in play. Below BS1 is the rare zone.
    if frequency.grpmax_af is not None and frequency.grpmax_af < spec.bs1:
        return spec.pm2
    return None


def _turkish_variome_note(tv: SourceResult) -> str:
    if tv.is_ok and tv.data:
        af = (tv.data.get("turkish") or {}).get("af")
        return f"Turkish Variome reports AF {af} (N=3,362)."
    if tv.is_unavailable:
        return "Turkish Variome unavailable."
    if tv.message and "outside" in tv.message:
        return "The gene is outside the indexed Turkish Variome subset."
    return "The variant is also not observed in the Turkish Variome (N=3,362)."


def check_ancestry_frequency(
    frequency: FrequencyResult,
    gnomad: SourceResult,
    turkish_variome: SourceResult,
    gene: str | None,
) -> AuditWarning | None:
    if not gnomad.is_ok:  # no frequency data -> 6.3 handles it, not 6.1
        return None
    mid = ancestry_allele_number(gnomad.data, "mid")
    mid_an = mid["total_an"] or 0
    mid_ac = (mid["exome_ac"] or 0) + (mid["genome_ac"] or 0)
    if mid_ac != 0:  # variant observed in mid -> the mid data speaks to the call
        return None
    threshold = _threshold_in_play(frequency, gene)
    if threshold is None:  # no frequency/rarity call in play
        return None
    adequate_an = _RULE_OF_3 / threshold
    if mid_an >= adequate_an:  # mid sample large enough for this call
        return None
    return AuditWarning(
        trigger="6.1 ancestry-frequency",
        severity="caution",
        message=f"Frequency evidence for Middle Eastern ancestry rests on N={mid_an} alleles.",
        detail=(
            f"This is a rarity call at threshold {threshold:g}; confidently supporting "
            f"it (zero observations) needs ~{adequate_an:.0f} alleles by the rule of 3, "
            f"but gnomAD mid has only {mid_an}. {_turkish_variome_note(turkish_variome)} "
            f"The frequency evidence is unreliable for a Turkish patient; interpret with caution."
        ),
        citation="Rule of 3 (Hanley & Lippman-Hand 1983); gnomAD v4 mid; Turkish Variome (Kars et al. 2021)",
    )


def check_repeat_expansion(gene: str | None) -> AuditWarning | None:
    locus = repeat_locus(gene)
    if not locus:
        return None
    return AuditWarning(
        trigger="6.2 repeat-expansion",
        severity="critical",
        message=f"{locus.gene} is a repeat-expansion locus ({locus.disorder}).",
        detail=(
            f"Short-read WES cannot reliably size the {locus.motif} repeat; a normal-range "
            f"result does not exclude {locus.disorder}. Targeted repeat-sizing "
            f"(repeat-primed PCR / long-read) is required, regardless of the computed class."
        ),
        citation=locus.citation,
    )


def check_empty_not_clean(
    bundle: EvidenceBundle,
    gnomad: SourceResult,
    turkish_variome: SourceResult,
) -> list[AuditWarning]:
    warnings: list[AuditWarning] = []
    for src in bundle.unavailable_sources:
        warnings.append(
            AuditWarning(
                trigger="6.3 empty-not-clean",
                severity="caution",
                message=f"{src} evidence unavailable.",
                detail=f"The {src} lookup failed or was unreachable - this is NOT the same as 'absent' or 'benign'.",
                citation=None,
            )
        )
    if not turkish_variome.is_ok and turkish_variome.message and "outside" in turkish_variome.message:
        warnings.append(
            AuditWarning(
                trigger="6.3 empty-not-clean",
                severity="caution",
                message="Gene outside the indexed Turkish Variome subset.",
                detail=f"{turkish_variome.message} - absence from the subset is not evidence of absence in Turks.",
                citation=None,
            )
        )
    return warnings


def audit(evaluation) -> AuditResult:
    """Run all three triggers over a pipeline EvaluationResult."""
    warnings: list[AuditWarning] = []
    anc = check_ancestry_frequency(
        evaluation.frequency, evaluation.gnomad, evaluation.turkish_variome, evaluation.gene
    )
    if anc:
        warnings.append(anc)
    rep = check_repeat_expansion(evaluation.gene)
    if rep:
        warnings.append(rep)
    warnings.extend(check_empty_not_clean(evaluation.bundle, evaluation.gnomad, evaluation.turkish_variome))
    return AuditResult(tuple(warnings))


__all__ = [
    "AuditWarning",
    "AuditResult",
    "check_ancestry_frequency",
    "check_repeat_expansion",
    "check_empty_not_clean",
    "audit",
]

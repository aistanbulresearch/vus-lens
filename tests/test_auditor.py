"""Tests for the Confidence Auditor's three triggers (build brief Section 6).

Each trigger fires from real data via a deterministic, cited rule — never a
hard-coded condition tied to a demo variant.
"""

from __future__ import annotations

from vus_lens.acmg.criteria import ACMGCriterion
from vus_lens.acmg.frequency import FrequencyResult
from vus_lens.auditor.core import (
    check_ancestry_frequency,
    check_empty_not_clean,
    check_repeat_expansion,
)
from vus_lens.models.evidence import SourceResult


def freq(criterion=None, grpmax_af=0.0, source="generic"):
    return FrequencyResult(
        criterion, criterion is not None, True, None, source, "label",
        grpmax_af, grpmax_af, None, grpmax_af, "reason", "cite",
    )


def gnomad_mid(mid_an, mid_ac):
    ex = {
        "an": mid_an, "ac": mid_ac, "af": (mid_ac / mid_an if mid_an else 0.0),
        "faf95_popmax": 0.0, "faf95_pop": None,
        "populations": {"mid": {"an": mid_an, "ac": mid_ac}},
    }
    return SourceResult.ok("gnomAD v4", {"variant_id": "x", "exome": ex, "genome": None})


TV_EMPTY = SourceResult.empty("Turkish Variome", message="variant not observed in Turkish Variome subset")


# --- 6.2 repeat-expansion --------------------------------------------------
def test_repeat_expansion_fires_for_atn1():
    w = check_repeat_expansion("ATN1")
    assert w is not None
    assert "repeat" in w.message.lower() or "repeat" in w.detail.lower()
    assert "NBK1491" in (w.citation or "")


def test_repeat_expansion_none_for_non_locus_gene():
    assert check_repeat_expansion("ATM") is None


# --- 6.1 ancestry-frequency (decoupled, rule-of-3) -------------------------
def test_ancestry_fires_for_rare_variant_absent_in_mid():
    # hero-like: PM2 (ATM, threshold 1e-5), mid AC 0 on a tiny AN -> fire
    w = check_ancestry_frequency(freq(ACMGCriterion.PM2), gnomad_mid(5764, 0), TV_EMPTY, gene="ATM")
    assert w is not None
    assert "5764" in w.message


def test_ancestry_none_when_variant_observed_in_mid():
    # HFE-like: BA1, but the variant IS seen in mid (AC 10) -> mid data speaks -> no fire
    w = check_ancestry_frequency(freq(ACMGCriterion.BA1, grpmax_af=0.071), gnomad_mid(6048, 10), TV_EMPTY, gene="HFE")
    assert w is None


def test_ancestry_none_when_mid_sample_adequate():
    # PM2 but mid AN large enough for the rule-of-3 bar -> no fire
    w = check_ancestry_frequency(freq(ACMGCriterion.PM2), gnomad_mid(500_000, 0), TV_EMPTY, gene="ATM")
    assert w is None


def test_ancestry_none_when_gnomad_unavailable():
    w = check_ancestry_frequency(freq(ACMGCriterion.PM2), SourceResult.error("gnomAD v4", message="503"), TV_EMPTY, gene="ATM")
    assert w is None


def test_ancestry_fires_on_withheld_rare_call():
    # No criterion assigned, but the variant is rare (grpmax below BS1) and mid AC 0 -> withheld call still fires
    w = check_ancestry_frequency(freq(None, grpmax_af=1.27e-5), gnomad_mid(6074, 0), TV_EMPTY, gene="ATM")
    assert w is not None


# --- 6.3 empty != clean ----------------------------------------------------
def test_empty_not_clean_from_unavailable_sources():
    from vus_lens.acmg.aggregate import ACMGClass, EvidenceBundle
    from vus_lens.acmg.clinvar import ClinVarResult

    cv = ClinVarResult(False, None, (), (), False, False, False, 0, "unavailable")
    bundle = EvidenceBundle("ATN1", ACMGClass.VUS, "basis", (), cv, (), ("frequency", "in-silico", "ClinVar"))
    warnings = check_empty_not_clean(bundle, SourceResult.error("gnomAD v4"), TV_EMPTY)
    assert len(warnings) >= 3
    assert all("not the same as" in w.detail.lower() or "not" in w.detail.lower() for w in warnings)

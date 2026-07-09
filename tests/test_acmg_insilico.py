"""Tests for deterministic ACMG in-silico criteria (PP3 / BP4).

Discipline (FINAL_BRIEF 5b): PP3/BP4 from a single calibrated tool (REVEL);
AlphaMissense is a Layer-2 cross-check, never a second criterion; the
indeterminate band yields neither criterion (a mid-range REVEL is NOT benign).
Thresholds are cited (Pejaver 2022; ATM/PALB2 VCEP) and pinned here, not tuned.
"""

from __future__ import annotations

from vus_lens.acmg.criteria import ACMGCriterion, EvidenceStrength
from vus_lens.acmg.insilico import assess_insilico
from vus_lens.models.evidence import SourceResult


def _myvariant(revel=None, revel_method="single", revel_uncertain=False, am=None, am_pred=None, gene="SOMEGENE"):
    return SourceResult.ok(
        "MyVariant.info",
        {
            "gene": gene,
            "revel": {"value": revel, "transcript": "ENST1", "method": revel_method, "uncertain": revel_uncertain, "raw": revel},
            "alphamissense": {"value": am, "transcript": "ENST1", "method": "single", "uncertain": False, "raw": am, "pred": am_pred},
        },
    )


# --- generic Pejaver bands -------------------------------------------------
def test_generic_pp3_supporting():
    r = assess_insilico(_myvariant(revel=0.70))  # [0.644, 0.773)
    assert r.criterion is ACMGCriterion.PP3
    assert r.strength is EvidenceStrength.SUPPORTING
    assert r.spec_source == "generic"


def test_generic_pp3_strong():
    r = assess_insilico(_myvariant(revel=0.95))  # >= 0.932
    assert r.criterion is ACMGCriterion.PP3
    assert r.strength is EvidenceStrength.STRONG


def test_generic_bp4_supporting():
    r = assess_insilico(_myvariant(revel=0.25))  # (0.183, 0.290]
    assert r.criterion is ACMGCriterion.BP4
    assert r.strength is EvidenceStrength.SUPPORTING


def test_generic_bp4_very_strong():
    r = assess_insilico(_myvariant(revel=0.002))  # <= 0.003
    assert r.criterion is ACMGCriterion.BP4
    assert r.strength is EvidenceStrength.VERY_STRONG


def test_generic_indeterminate_is_neither():
    r = assess_insilico(_myvariant(revel=0.50))  # (0.290, 0.644)
    assert r.criterion is None
    assert r.band == "indeterminate"


def test_generic_supporting_boundary_inclusive():
    assert assess_insilico(_myvariant(revel=0.644)).criterion is ACMGCriterion.PP3
    assert assess_insilico(_myvariant(revel=0.643)).criterion is None  # just below -> indeterminate


# --- gene-specific ATM VCEP ------------------------------------------------
def test_atm_pp3_supporting_only():
    r = assess_insilico(_myvariant(revel=0.80, gene="ATM"), gene="ATM")  # > 0.7333
    assert r.criterion is ACMGCriterion.PP3
    assert r.strength is EvidenceStrength.SUPPORTING
    assert r.spec_source == "VCEP"
    assert "GN020" in r.spec_label


def test_atm_bp4_supporting():
    r = assess_insilico(_myvariant(revel=0.20, gene="ATM"), gene="ATM")  # <= 0.249
    assert r.criterion is ACMGCriterion.BP4


def test_hero_atm_arg248gly_revel_0_38_is_indeterminate():
    # THE hero case: 0.249 < 0.38 < 0.7333 -> neither PP3 nor BP4 (not benign)
    r = assess_insilico(_myvariant(revel=0.38, gene="ATM"), gene="ATM")
    assert r.criterion is None
    assert r.band == "indeterminate"


# --- AlphaMissense is a cross-check, not a criterion -----------------------
def test_alphamissense_is_crosscheck_not_criterion():
    # REVEL indeterminate + AlphaMissense pathogenic -> criterion still None,
    # but AM is surfaced for Layer 2 with a discordance note.
    r = assess_insilico(_myvariant(revel=0.38, am=0.868, am_pred="P", gene="ATM"), gene="ATM")
    assert r.criterion is None  # REVEL alone decides; AM never assigns PP3
    assert r.alphamissense is not None and r.alphamissense["pred"] == "P"
    assert r.crosscheck_note and "revel" in r.crosscheck_note.lower()


def _myvariant_am_array(revel, revel_gene, am_value, am_pred, am_range):
    """MyVariant shape where AlphaMissense is an unresolved per-transcript array
    (canonical value None) — the real HFE C282Y case: 10 transcripts, mixed
    vep_canonical/appris alignment, so no single canonical score, but every
    per-transcript prediction agrees."""
    return SourceResult.ok(
        "MyVariant.info",
        {
            "gene": revel_gene,
            "revel": {"value": revel, "transcript": "ENST1", "method": "uniform", "uncertain": False, "raw": revel},
            "alphamissense": {
                "value": am_value, "transcript": None, "method": "unresolved",
                "uncertain": True, "raw": am_range, "range": am_range, "pred": am_pred,
            },
        },
    )


def test_am_array_unanimous_pred_resolves_direction_as_crosscheck():
    # HFE-like: AM array can't resolve to the canonical transcript (value None),
    # but all 10 predictions are "P" -> direction is unambiguous -> surface it.
    r = assess_insilico(
        _myvariant_am_array(0.872, "HFE", None, ["P"] * 10, am_range=[0.9403, 0.9738])
    )
    assert r.criterion is ACMGCriterion.PP3  # REVEL alone still decides the criterion
    assert r.alphamissense is not None
    assert r.alphamissense["direction"] == "pathogenic"
    assert r.alphamissense["value"] is None  # no single canonical number fabricated
    assert r.crosscheck_note and "pathogenic" in r.crosscheck_note.lower()
    assert "concordant" in r.crosscheck_note.lower()  # PP3 (pathogenic) == AM pathogenic


def test_am_array_mixed_pred_yields_no_crosscheck():
    # Predictions disagree across transcripts -> no unanimous direction ->
    # drop the cross-check (never fabricate a direction). Criterion still stands.
    r = assess_insilico(
        _myvariant_am_array(0.872, "HFE", None, ["P", "B", "P", "A"], am_range=[0.3, 0.95])
    )
    assert r.criterion is ACMGCriterion.PP3
    assert r.alphamissense is None
    assert r.crosscheck_note is None


# --- fail-loud / edge cases ------------------------------------------------
def test_uncertain_transcript_no_criterion_with_flag():
    r = assess_insilico(_myvariant(revel=None, revel_method="unresolved", revel_uncertain=True))
    assert r.criterion is None
    assert "transcript_ambiguity" in r.flags


def test_revel_absent_no_criterion():
    r = assess_insilico(_myvariant(revel=None, revel_method="absent"))
    assert r.criterion is None
    assert r.band == "absent"


def test_myvariant_unavailable_is_fail_loud():
    r = assess_insilico(SourceResult.error("MyVariant.info", message="HTTP 500"))
    assert r.criterion is None
    assert r.data_available is False


def test_palb2_uses_spliceai_no_protein_revel():
    # PALB2 VCEP: SpliceAI-only; a high REVEL must NOT produce PP3 (protein pred not used)
    r = assess_insilico(_myvariant(revel=0.95, gene="PALB2"), gene="PALB2")
    assert r.criterion is None
    assert "protein_predictor_not_used" in r.flags

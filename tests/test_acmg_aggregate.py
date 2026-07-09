"""Tests for deterministic evidence aggregation.

The bundle combines the assigned criteria into an ACMG class using the Richards
2015 combining rules (limited to the criteria this tool assigns), keeps ClinVar
surfaced-not-judged, and emits **deterministic detections** (e.g. class-vs-ClinVar
conflict) as the substrate the reasoning layers will later explain. No LLM.
"""

from __future__ import annotations

from vus_lens.acmg.aggregate import ACMGClass, aggregate_evidence
from vus_lens.acmg.clinvar import ClinVarResult
from vus_lens.acmg.criteria import ACMGCriterion, EvidenceStrength
from vus_lens.acmg.frequency import FrequencyResult
from vus_lens.acmg.insilico import InSilicoResult


def freq(criterion=None, source="generic", available=True):
    return FrequencyResult(
        criterion, criterion is not None, available, None, source, "freq-label",
        0.0, 0.0, None, 0.0, "reason", "cite" if criterion else "",
    )


def insil(criterion=None, strength=None, band="indeterminate", note=None, available=True):
    return InSilicoResult(
        criterion, strength, criterion is not None, available, None, "generic",
        "insil-label", "REVEL", 0.38, band, "ENST", None, note, "reason",
        "cite" if criterion else "", (),
    )


def cv(has_p=False, has_b=False, conflicting=False, sigs=(), available=True):
    return ClinVarResult(available, "123", tuple(sigs), (), has_p, has_b, conflicting, len(sigs), "summary")


def test_hero_pm2_only_is_vus():
    b = aggregate_evidence(freq(ACMGCriterion.PM2), insil(None), cv(conflicting=True, sigs=["Conflicting"]), gene="ATM")
    assert b.acmg_class is ACMGClass.VUS
    assert any(i.criterion is ACMGCriterion.PM2 for i in b.criteria)


def test_ba1_alone_is_benign():
    b = aggregate_evidence(freq(ACMGCriterion.BA1), insil(None), cv(), gene="X")
    assert b.acmg_class is ACMGClass.BENIGN


def test_bs1_plus_bp4_is_likely_benign():
    b = aggregate_evidence(freq(ACMGCriterion.BS1), insil(ACMGCriterion.BP4, EvidenceStrength.SUPPORTING, band="BP4_supporting"), cv(), gene="X")
    assert b.acmg_class is ACMGClass.LIKELY_BENIGN


def test_contradictory_bs1_and_pp3_is_vus():
    b = aggregate_evidence(freq(ACMGCriterion.BS1), insil(ACMGCriterion.PP3, EvidenceStrength.SUPPORTING, band="PP3_supporting"), cv(), gene="X")
    assert b.acmg_class is ACMGClass.VUS


def test_hfe_benign_class_conflicts_with_clinvar_pathogenic():
    # BA1 -> deterministic Benign; ClinVar Pathogenic -> a detection must fire (Layer-2 substrate)
    b = aggregate_evidence(
        freq(ACMGCriterion.BA1),
        insil(ACMGCriterion.PP3, EvidenceStrength.MODERATE, band="PP3_moderate"),
        cv(has_p=True, sigs=["Pathogenic"]),
        gene="HFE",
    )
    assert b.acmg_class is ACMGClass.BENIGN
    assert any("ClinVar" in d and "pathogenic" in d.lower() for d in b.detections)


def test_insilico_noncordance_is_surfaced_as_detection():
    note = "AlphaMissense pathogenic while REVEL is indeterminate (cross-source signal for Layer 2)"
    b = aggregate_evidence(freq(ACMGCriterion.PM2), insil(None, band="indeterminate", note=note), cv(), gene="ATM")
    assert any("AlphaMissense" in d for d in b.detections)


def test_unavailable_source_is_fail_loud():
    b = aggregate_evidence(freq(None, available=False), insil(None), cv(), gene="X")
    assert "frequency" in b.unavailable_sources
    assert any("unavailable" in d.lower() for d in b.detections)

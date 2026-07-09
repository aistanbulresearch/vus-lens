"""Tests for the ClinVar read — significance + review status **surfaced, not
re-judged**. ClinVar is context and conflict-detection material; it is never
converted into an ACMG criterion.
"""

from __future__ import annotations

from vus_lens.acmg.clinvar import read_clinvar
from vus_lens.models.evidence import SourceResult


def _mv(significances, review="criteria provided, single submitter"):
    subs = [
        {"significance": s, "review_status": review, "condition": "X", "accession": f"RCV{i}"}
        for i, s in enumerate(significances)
    ]
    return SourceResult.ok(
        "MyVariant.info",
        {"clinvar": {"variant_id": "123", "significances": significances, "submissions": subs}},
    )


def test_pathogenic_detected():
    r = read_clinvar(_mv(["Pathogenic"]))
    assert r.has_pathogenic is True
    assert r.has_benign is False
    assert r.data_available is True


def test_benign_detected():
    r = read_clinvar(_mv(["Benign", "Likely benign"]))
    assert r.has_benign is True
    assert r.has_pathogenic is False


def test_conflicting_label_is_not_pathogenic():
    # "Conflicting interpretations of pathogenicity" must NOT trip has_pathogenic
    r = read_clinvar(_mv(["Conflicting interpretations of pathogenicity"]))
    assert r.is_conflicting is True
    assert r.has_pathogenic is False


def test_mixed_p_and_b_is_conflicting():
    r = read_clinvar(_mv(["Pathogenic", "Benign"]))
    assert r.is_conflicting is True
    assert r.has_pathogenic is True and r.has_benign is True


def test_hfe_like_pathogenic_plus_risk_factor():
    r = read_clinvar(_mv(["Pathogenic", "risk factor"]))
    assert r.has_pathogenic is True
    assert r.n_submissions == 2


def test_no_clinvar_record_is_available_but_empty():
    r = read_clinvar(SourceResult.ok("MyVariant.info", {"gene": "X"}))  # no clinvar key
    assert r.data_available is True
    assert r.significances == ()
    assert "no ClinVar" in r.summary


def test_myvariant_unavailable_is_fail_loud():
    r = read_clinvar(SourceResult.error("MyVariant.info", message="HTTP 500"))
    assert r.data_available is False

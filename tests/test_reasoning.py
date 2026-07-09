"""Tests for the Day-4 reasoning substrate — the authenticity backbone.

These verify the *structural* guarantee, with NO LLM call: every finding handed
to a reasoning layer is a verbatim slice of a real deterministic detection or
auditor warning (nothing invented), findings route to the right layer, the
Layer-3 degradation rule fires on the right evidence, and the output guardrail
catches self-classification. A stub reasoner stands in for Claude so orchestration
is testable offline.
"""

from __future__ import annotations

from vus_lens.acmg.aggregate import ACMGClass, EvidenceBundle, EvidenceItem
from vus_lens.acmg.clinvar import ClinVarResult
from vus_lens.acmg.criteria import ACMGCriterion, EvidenceStrength
from vus_lens.acmg.frequency import FrequencyResult
from vus_lens.acmg.insilico import InSilicoResult
from vus_lens.auditor.core import AuditResult, AuditWarning
from vus_lens.models.evidence import SourceResult
from vus_lens.models.variant import VariantQuery
from vus_lens.pipeline import EvaluationResult
from vus_lens.reasoning.client import guardrail_violations
from vus_lens.reasoning.findings import build_reasoning_input
from vus_lens.reasoning.layers import _layer3_is_material, reason_over


class StubReasoner:
    """Stands in for Claude — records calls, returns canned text (no network)."""

    def __init__(self, text: str = "explained.") -> None:
        self.text = text
        self.calls: list[tuple[str, str]] = []

    def available(self) -> bool:
        return True

    def reason(self, system: str, user: str):
        self.calls.append((system, user))
        return self.text, ()


def _gnomad_mid_ok(mid_an, mid_ac):
    ex = {"an": mid_an, "ac": mid_ac, "af": 0.0, "faf95_popmax": 0.0, "faf95_pop": None,
          "populations": {"mid": {"an": mid_an, "ac": mid_ac}}}
    return SourceResult.ok("gnomAD v4", {"variant_id": "x", "exome": ex, "genome": None})


def _hfe_evaluation():
    """HFE-like: Benign class carrying a PP3, contradicting ClinVar Pathogenic +
    both in-silico tools; only Layer-3 content is a soft TV subset boundary."""
    freq = FrequencyResult(ACMGCriterion.BA1, True, True, "HFE", "generic", "label",
                           0.071, 0.071, "nfe", 0.057, "grpmax FAF 0.071 exceeds BA1", "cite")
    am = {"direction": "pathogenic", "value": None, "score_range": [0.9403, 0.9738],
          "pred": ["P"] * 10, "n_transcripts": 10}
    ins = InSilicoResult(ACMGCriterion.PP3, EvidenceStrength.MODERATE, True, True, "HFE",
                         "generic", "label", "REVEL", 0.872, "PP3_moderate", "ENST1", am,
                         "AlphaMissense pathogenic (0.94-0.974 across 10 transcripts) concordant with REVEL (pathogenic)",
                         "REVEL 0.872 -> PP3_moderate", "cite", ())
    cv = ClinVarResult(True, "vid", ("Pathogenic",), ("criteria provided",), True, False, False, 5, "summary")
    criteria = (
        EvidenceItem(ACMGCriterion.BA1, None, "frequency [generic]", "grpmax FAF 0.071 exceeds BA1", "cite"),
        EvidenceItem(ACMGCriterion.PP3, EvidenceStrength.MODERATE, "in-silico [generic]", "REVEL 0.872 -> PP3_moderate", "cite"),
    )
    detections = (
        "deterministic class 'Benign' conflicts with ClinVar pathogenic ['Pathogenic'] - cross-source conflict [Layer 2]",
        "internal inconsistency: class 'Benign' but pathogenic criterion(s) ['PP3'] assigned [Layer 1]",
        "in-silico cross-check: AlphaMissense pathogenic (0.94-0.974 across 10 transcripts) concordant with REVEL (pathogenic)",
    )
    bundle = EvidenceBundle("HFE", ACMGClass.BENIGN, "BA1 - stand-alone benign", criteria, cv, detections, ())
    audit = AuditResult((
        AuditWarning("6.3 empty-not-clean", "caution", "Gene outside the indexed Turkish Variome subset.",
                     "absence from the subset is not evidence of absence.", None),
    ))
    ev = EvaluationResult(
        VariantQuery(raw="HFE p.Cys282Tyr", rsid="rs1800562", gene="HFE", ref="G", alt="A"),
        "HFE", SourceResult.ok("MyVariant.info", {}), _gnomad_mid_ok(6048, 10),
        SourceResult.empty("Turkish Variome", message="variant not observed in Turkish Variome subset"),
        freq, ins, cv, bundle,
    )
    return ev, audit


def _atn1_evaluation():
    """ATN1-like: repeat-expansion locus, frequency unavailable (fail-loud). The
    story is entirely input triage."""
    freq = FrequencyResult(None, False, False, "ATN1", "generic", "label",
                           None, None, None, None, "gnomAD unavailable", "")
    ins = InSilicoResult(None, None, False, True, "ATN1", "generic", "label", "REVEL",
                         None, "absent", None, None, None, "no REVEL", "", ("revel_absent",))
    cv = ClinVarResult(True, None, (), (), False, False, False, 0, "no ClinVar record")
    detections = ("evidence unavailable: frequency - not the same as benign (fail-loud)",)
    bundle = EvidenceBundle("ATN1", ACMGClass.VUS, "uncertain", (), cv, detections, ("frequency",))
    audit = AuditResult((
        AuditWarning("6.2 repeat-expansion", "critical", "ATN1 is a repeat-expansion locus (DRPLA).",
                     "short-read WES cannot size the CAG repeat.", "GeneReviews NBK1491"),
        AuditWarning("6.3 empty-not-clean", "caution", "frequency evidence unavailable.",
                     "the frequency lookup failed - NOT the same as absent.", None),
    ))
    ev = EvaluationResult(
        VariantQuery(raw="ATN1 CAG[17]", hgvs="chr12:g.7045894GCA[17]", gene="ATN1"),
        "ATN1", SourceResult.ok("MyVariant.info", {}), SourceResult.error("gnomAD v4", message="no hg38 id"),
        SourceResult.error("Turkish Variome", message="no hg38 id"), freq, ins, cv, bundle,
    )
    return ev, audit


# --- authenticity: every finding is a verbatim slice of a real detection ----
def test_findings_are_verbatim_from_real_detections():
    ev, audit = _hfe_evaluation()
    rin = build_reasoning_input(ev, audit)
    real_texts = list(ev.bundle.detections) + [f"{w.message} {w.detail}" for w in audit.warnings]
    for layer in (1, 2, 3):
        for f in rin.findings(layer):
            assert any(f.statement in t for t in real_texts), f"invented finding: {f.statement!r}"


def test_layer_routing_hfe():
    ev, audit = _hfe_evaluation()
    rin = build_reasoning_input(ev, audit)
    assert [f.kind for f in rin.layer1] == ["internal_inconsistency"]
    assert {f.kind for f in rin.layer2} == {"cross_source_conflict", "insilico_crosscheck"}
    assert [f.kind for f in rin.layer3] == ["subset_boundary"]


# --- Layer-3 degradation rule ----------------------------------------------
def test_hfe_layer3_degrades_soft_boundary_only():
    ev, audit = _hfe_evaluation()
    rin = build_reasoning_input(ev, audit)
    assert _layer3_is_material(rin) is False  # only a soft subset boundary
    stub = StubReasoner()
    outs = {o.layer: o for o in reason_over(ev, audit, stub)}
    assert outs[3].status == "degraded"
    assert outs[1].status == "reasoned" and outs[2].status == "reasoned"
    assert len(stub.calls) == 2  # Claude called for L1 and L2 only, never L3


def test_atn1_layer3_material_is_kept():
    ev, audit = _atn1_evaluation()
    rin = build_reasoning_input(ev, audit)
    assert _layer3_is_material(rin) is True  # repeat locus + unreachable source
    assert {f.kind for f in rin.layer3} == {"assay_suitability", "input_completeness"}
    stub = StubReasoner()
    outs = {o.layer: o for o in reason_over(ev, audit, stub)}
    assert outs[3].status == "reasoned"
    assert outs[1].status == "no_findings" and outs[2].status == "no_findings"
    assert len(stub.calls) == 1  # only Layer 3 had material to explain


# --- output guardrail (self-classification is forbidden) -------------------
def test_guardrail_flags_self_classification():
    assert guardrail_violations("On balance I would reclassify this as pathogenic.")
    assert guardrail_violations("The correct classification is Likely Pathogenic.")


def test_guardrail_clean_on_descriptive_language():
    # Describing a source or restating the tool's class is allowed, not a violation.
    assert guardrail_violations("ClinVar reports this variant as Pathogenic; the tool classified it Benign.") == ()
    assert guardrail_violations("The frequency data alone cannot support a rarity call here.") == ()

"""The authenticity backbone of the Day-4 reasoning layer — a **deterministic**
extractor that turns a completed evaluation into the exact, verbatim substrate
the LLM is allowed to explain.

The reasoning layers (Layer 1/2/3) NEVER see the raw variant or free-form context.
They see only a ``ReasoningInput`` assembled here: the deterministic class, the
assigned criteria, and the real detections/warnings the no-LLM layers already
produced — each carried **verbatim**. This is what makes "every explanation
traces to a real detection" a structural guarantee rather than a hope: if a
detection is not in this object, the model is never told about it, so it cannot
explain (or invent) it.

No LLM here. No thresholds, no classification. Pure re-shaping of real output.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..auditor.core import AuditResult
from ..pipeline import EvaluationResult


@dataclass(frozen=True)
class Finding:
    """One real, verbatim observation the model is permitted to explain."""

    layer: int  # 1 = evidence self-audit, 2 = cross-source, 3 = input triage
    kind: str
    statement: str  # VERBATIM from the deterministic layer — never paraphrased here
    citation: str | None = None


@dataclass(frozen=True)
class ReasoningInput:
    """Everything — and only what — a reasoning layer is given about a variant."""

    query: str
    gene: str | None
    acmg_class: str
    class_basis: str
    criteria: tuple[str, ...]
    clinvar: str
    key_numbers: tuple[str, ...]
    sources: str
    layer1: tuple[Finding, ...]
    layer2: tuple[Finding, ...]
    layer3: tuple[Finding, ...]

    def findings(self, layer: int) -> tuple[Finding, ...]:
        return {1: self.layer1, 2: self.layer2, 3: self.layer3}[layer]

    def has_findings(self, layer: int) -> bool:
        return bool(self.findings(layer))


def _criteria_lines(ev: EvaluationResult) -> tuple[str, ...]:
    out = []
    for it in ev.bundle.criteria:
        strength = f"/{it.strength.value}" if it.strength else ""
        out.append(f"{it.criterion.value}{strength} [{it.source}]: {it.reason} (cite: {it.citation})")
    return tuple(out)


def _clinvar_line(ev: EvaluationResult) -> str:
    cv = ev.clinvar
    if not cv.data_available:
        return "ClinVar: unavailable (not read as absent)"
    sig = list(cv.significances) or ["(no submissions)"]
    return (
        f"ClinVar significances {sig}; review_status={cv.review_status!r}; "
        f"has_pathogenic={cv.has_pathogenic} has_benign={cv.has_benign} conflicting={cv.is_conflicting}"
    )


def _g(x) -> str:
    """Format a float to 3 significant figures so the model receives clean numbers
    (the raw gnomAD FAF can carry float noise like 2.999999999999999e-07) — the
    value is unchanged, only its printed form."""
    return f"{x:.3g}" if isinstance(x, float) else str(x)


def _key_numbers(ev: EvaluationResult) -> tuple[str, ...]:
    nums: list[str] = []
    f = ev.frequency
    if f.data_available and ev.gnomad.is_ok:
        nums.append(
            f"gnomAD grpmax filtering AF (FAF95) = {_g(f.grpmax_faf)}; raw grpmax AF = {_g(f.grpmax_af)}; "
            f"global AF = {_g(f.global_af)} [spec: {f.spec_source} {f.spec_label}]"
        )
        from ..clients.gnomad import ancestry_allele_number

        mid = ancestry_allele_number(ev.gnomad.data, "mid")
        nums.append(
            f"gnomAD Middle Eastern (mid): AN={mid['total_an']} AC={mid['exome_ac']}/{mid['genome_ac']}"
        )
    ins = ev.insilico
    if ins.revel is not None:
        nums.append(f"REVEL = {ins.revel} -> band '{ins.band}' [{ins.spec_source} {ins.spec_label}]")
    if ins.alphamissense:
        nums.append(
            f"AlphaMissense: direction={ins.alphamissense.get('direction')} "
            f"value={ins.alphamissense.get('value')} range={ins.alphamissense.get('score_range')} "
            f"(Layer-2 cross-check, not a criterion)"
        )
    return tuple(nums)


def build_reasoning_input(evaluation: EvaluationResult, audit: AuditResult) -> ReasoningInput:
    """Assemble the verbatim, layer-tagged substrate for the reasoning layers."""
    b = evaluation.bundle
    warnings = audit.warnings

    layer1: list[Finding] = []
    layer2: list[Finding] = []
    layer3: list[Finding] = []

    # Deterministic detections carry explicit [Layer N] tags (aggregate.py). We
    # route by tag and keep the detection string verbatim as the statement.
    for d in b.detections:
        if "[Layer 1]" in d:
            layer1.append(Finding(1, "internal_inconsistency", d, "ACMG/AMP (Richards 2015)"))
        elif "[Layer 2]" in d:
            layer2.append(Finding(2, "cross_source_conflict", d, None))
        elif d.startswith("in-silico cross-check:"):
            layer2.append(Finding(2, "insilico_crosscheck", d, "AlphaMissense (Cheng 2023); REVEL (Ioannidis 2016)"))
        elif "fail-loud" in d:
            # A required source was unreachable -> a MATERIAL input-completeness fact.
            layer3.append(Finding(3, "input_completeness", d, None))

    # In-silico withheld for transcript ambiguity is an input-adequacy fact.
    if "transcript_ambiguity" in evaluation.insilico.flags:
        layer3.append(
            Finding(3, "transcript_adequacy", "in-silico withheld: canonical transcript could not be resolved -> PP3/BP4 not applied", None)
        )

    # Auditor warnings route by trigger: 6.1 is cross-source (ancestry vs the
    # frequency call); 6.2 is assay suitability (material); 6.3 splits into a
    # material source failure vs a *soft* declared-subset boundary. The 6.3
    # unavailable-source warnings duplicate the verbatim fail-loud detections
    # above, so only the subset-boundary variant is added here.
    for w in warnings:
        stmt = f"{w.message} {w.detail}"
        if w.trigger.startswith("6.1"):
            layer2.append(Finding(2, "ancestry_adequacy", stmt, w.citation))
        elif w.trigger.startswith("6.2"):
            layer3.append(Finding(3, "assay_suitability", stmt, w.citation))
        elif w.trigger.startswith("6.3") and ("outside" in w.message.lower() or "subset" in w.message.lower()):
            layer3.append(Finding(3, "subset_boundary", stmt, w.citation))

    return ReasoningInput(
        query=evaluation.query.raw,
        gene=evaluation.gene,
        acmg_class=b.acmg_class.value,
        class_basis=b.class_basis,
        criteria=_criteria_lines(evaluation),
        clinvar=_clinvar_line(evaluation),
        key_numbers=_key_numbers(evaluation),
        sources=(
            f"MyVariant={evaluation.myvariant.status.value}, "
            f"gnomAD={evaluation.gnomad.status.value}, "
            f"TurkishVariome={evaluation.turkish_variome.status.value}"
        ),
        layer1=tuple(layer1),
        layer2=tuple(layer2),
        layer3=tuple(layer3),
    )


__all__ = ["Finding", "ReasoningInput", "build_reasoning_input"]

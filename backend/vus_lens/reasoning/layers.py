"""Orchestrate the three reasoning layers over one evaluation, with the Layer-3
degradation rule (FINAL_BRIEF Day-4): keep input triage only when it adds
authentic value; otherwise drop it and keep Layers 1-2.

The degradation decision is deterministic and evidence-driven — Layer 3 is kept
only when it carries a *material* input-adequacy finding (a repeat-locus assay
mismatch, a withheld-for-transcript-ambiguity call, or an unreachable required
source). A variant whose only Layer-3 content is a soft declared-subset boundary,
or which has none at all, degrades — so a clean SNV never gets a manufactured
"input looks fine" paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..auditor.core import AuditResult
from ..pipeline import EvaluationResult
from .client import ClaudeReasoner, ReasoningUnavailable
from .findings import Finding, ReasoningInput, build_reasoning_input
from .prompts import SYSTEM_PROMPT, build_layer_prompt

_LAYER_TITLES = {1: "Evidence self-audit", 2: "Cross-source reconciliation", 3: "Input triage"}
_MATERIAL_L3 = {"assay_suitability", "transcript_adequacy", "input_completeness"}


@dataclass(frozen=True)
class LayerOutput:
    layer: int
    title: str
    findings: tuple[Finding, ...]
    reasoning: str
    status: str  # "reasoned" | "no_findings" | "degraded" | "unavailable"
    guardrail: tuple[str, ...] = ()


def _layer3_is_material(rin: ReasoningInput) -> bool:
    return any(f.kind in _MATERIAL_L3 for f in rin.layer3)


def reason_over(
    evaluation: EvaluationResult,
    audit: AuditResult,
    reasoner: ClaudeReasoner | None = None,
) -> list[LayerOutput]:
    """Produce Layer 1/2/3 outputs. Never changes the deterministic class."""
    reasoner = reasoner or ClaudeReasoner()
    rin = build_reasoning_input(evaluation, audit)
    outputs: list[LayerOutput] = []

    for layer in (1, 2, 3):
        title = _LAYER_TITLES[layer]
        findings = rin.findings(layer)

        # Layer-3 degradation rule.
        if layer == 3 and not _layer3_is_material(rin):
            note = "No material input-adequacy concern; input triage adds nothing beyond Layers 1-2."
            if rin.layer3:  # a soft subset-boundary note existed but doesn't warrant a layer
                note += f" (Soft note carried by the auditor only: {rin.layer3[0].statement.split('.')[0]}.)"
            outputs.append(LayerOutput(3, title, findings, note, "degraded"))
            continue

        if not findings:
            outputs.append(LayerOutput(layer, title, findings, "No findings.", "no_findings"))
            continue

        try:
            text, violations = reasoner.reason(SYSTEM_PROMPT, build_layer_prompt(layer, rin))
            outputs.append(LayerOutput(layer, title, findings, text, "reasoned", violations))
        except ReasoningUnavailable as e:
            outputs.append(LayerOutput(layer, title, findings, str(e), "unavailable"))

    return outputs


def _degraded_note(rin: ReasoningInput) -> str:
    note = "No material input-adequacy concern; input triage adds nothing beyond Layers 1-2."
    if rin.layer3:  # a soft subset-boundary note existed but doesn't warrant a layer
        note += f" (Soft note carried by the auditor only: {rin.layer3[0].statement.split('.')[0]}.)"
    return note


def reasoning_plan(evaluation: EvaluationResult, audit: AuditResult) -> list[dict]:
    """The per-layer plan (status + findings) WITHOUT calling the API — lets the UI
    render the three layer slots and their status the instant the audit is turned
    on, then stream text into the 'reasoned' ones."""
    rin = build_reasoning_input(evaluation, audit)
    plan: list[dict] = []
    for layer in (1, 2, 3):
        findings = [f.statement for f in rin.findings(layer)]
        if layer == 3 and not _layer3_is_material(rin):
            status, note = "degraded", _degraded_note(rin)
            findings = []
        elif not rin.findings(layer):
            status, note = "no_findings", "No findings."
        else:
            status, note = "reasoned", None
        plan.append({"layer": layer, "title": _LAYER_TITLES[layer], "status": status, "findings": findings, "note": note})
    return plan


async def reason_over_stream(
    evaluation: EvaluationResult,
    audit: AuditResult,
    reasoner: ClaudeReasoner | None = None,
):
    """Async generator of SSE-friendly dict events for the web UI. Same layers and
    degradation rule as reason_over; text is streamed token-by-token."""
    reasoner = reasoner or ClaudeReasoner()
    rin = build_reasoning_input(evaluation, audit)
    for layer in (1, 2, 3):
        title = _LAYER_TITLES[layer]
        findings = rin.findings(layer)
        if layer == 3 and not _layer3_is_material(rin):
            yield {"type": "layer", "layer": 3, "title": title, "status": "degraded", "text": _degraded_note(rin)}
            continue
        if not findings:
            yield {"type": "layer", "layer": layer, "title": title, "status": "no_findings", "text": "No findings."}
            continue
        yield {"type": "layer_start", "layer": layer, "title": title, "findings": [f.statement for f in findings]}
        try:
            async for kind, payload in reasoner.reason_stream(SYSTEM_PROMPT, build_layer_prompt(layer, rin)):
                if kind == "delta":
                    yield {"type": "delta", "layer": layer, "text": payload}
                else:
                    yield {"type": "layer_done", "layer": layer, "guardrail": list(payload)}
        except ReasoningUnavailable as e:
            yield {"type": "layer", "layer": layer, "title": title, "status": "unavailable", "text": str(e)}
    yield {"type": "done"}


__all__ = [
    "LayerOutput",
    "reason_over",
    "reason_over_stream",
    "reasoning_plan",
    "build_reasoning_input",
    "ReasoningInput",
]

"""Prompts for the Day-4 reasoning layers.

The system prompt is the enforcement point for the authenticity bar: Claude is
told, in the strongest terms, that it explains findings it is given and does not
classify, invent, or embellish. The user prompt hands it ONLY the verbatim
``ReasoningInput`` substrate -- never the raw variant or open-ended context -- so
there is nothing to hallucinate from.
"""

from __future__ import annotations

from .findings import Finding, ReasoningInput

SYSTEM_PROMPT = """\
You are the reasoning-and-audit layer of a clinical-genetics decision-support \
tool called VUS-Lens. A DETERMINISTIC (non-LLM) engine has already fetched public \
data, mapped it to ACMG/AMP criteria, computed a classification, and produced a \
set of machine-verified findings. Your ONLY job is to explain those findings to a \
clinical geneticist in plain, precise language.

HARD RULES -- these are non-negotiable and override any instinct to be helpful:
1. EXPLAIN ONLY WHAT YOU ARE GIVEN. Every sentence must trace to a finding, \
criterion, number, or citation in the input. Do NOT introduce any clinical fact, \
allele frequency, gene function, penetrance figure, mechanism, or citation that \
is not present in the input. If you don't have it, don't say it.
2. YOU DO NOT CLASSIFY. Never assert, change, upgrade, downgrade, or imply an \
ACMG classification of your own. You may restate the deterministic class ("the \
tool classified this as X") and describe what a source reports ("ClinVar reports \
Pathogenic"). You may NEVER say the variant "is"/"should be"/"is really" a class, \
nor recommend reclassification.
3. DO NOT INVENT NUMBERS. Use only the numbers provided, verbatim.
4. CALIBRATED, NOT DRAMATIC. State uncertainty as uncertainty. No alarming or \
persuasive language beyond what the finding literally supports.
5. REASONING, NOT RESTATEMENT. Connect the findings into an interpretation -- what \
a disagreement means, which source to weight for this patient and why -- but every \
inferential step must rest on a provided finding. Do not merely repeat the finding \
text back.
6. If a layer has no findings, reply with exactly: "No findings." Never manufacture \
content to fill space.

Audience: a clinician who will make the call. You inform; you never decide. \
Keep each layer to 2-5 sentences.\
"""


def _fmt_findings(findings: tuple[Finding, ...]) -> str:
    if not findings:
        return "(none)"
    lines = []
    for f in findings:
        cite = f" [cite: {f.citation}]" if f.citation else ""
        lines.append(f"- ({f.kind}) {f.statement}{cite}")
    return "\n".join(lines)


def _context_block(rin: ReasoningInput) -> str:
    crit = "\n".join(f"  - {c}" for c in rin.criteria) or "  - (none assigned)"
    nums = "\n".join(f"  - {n}" for n in rin.key_numbers) or "  - (none)"
    return (
        f"VARIANT: {rin.query}  |  gene: {rin.gene}\n"
        f"SOURCES REACHED: {rin.sources}\n"
        f"DETERMINISTIC CLASS (fixed, not yours to change): {rin.acmg_class} -- {rin.class_basis}\n"
        f"ASSIGNED ACMG CRITERIA:\n{crit}\n"
        f"{rin.clinvar}\n"
        f"KEY NUMBERS (verbatim; use only these):\n{nums}"
    )


_LAYER_TASK = {
    1: (
        "LAYER 1 -- EVIDENCE SELF-AUDIT.\n"
        "Question: is the deterministic engine's OWN output internally consistent? "
        "If a finding below reports an internal contradiction (e.g. a benign class "
        "carrying a pathogenic criterion), explain exactly what the contradiction is, "
        "why the tool's own rules produce it, and what the clinician should take from "
        "it. Do not reach outside the tool's own output."
    ),
    2: (
        "LAYER 2 -- CROSS-SOURCE RECONCILIATION.\n"
        "Question: where do the independent sources (the deterministic class, ClinVar, "
        "the in-silico predictors, the ancestry-specific frequency data) agree or "
        "conflict? For each conflict below, explain what it means and -- WITHOUT changing "
        "the class -- which source a clinician should weight for THIS patient and why, "
        "grounded only in the findings and numbers given."
    ),
    3: (
        "LAYER 3 -- INPUT TRIAGE.\n"
        "Question: are the assay and inputs the right instrument for THIS variant, and "
        "is the evidence base complete? Using only the findings below, explain any way "
        "the input is structurally unsuited to the variant (e.g. a short-read/SNV "
        "pipeline against a repeat-expansion locus) or incomplete (a required source "
        "unreachable). Do not re-explain the cross-source conflicts from Layer 2."
    ),
}


def build_layer_prompt(layer: int, rin: ReasoningInput) -> str:
    findings = rin.findings(layer)
    return (
        f"{_LAYER_TASK[layer]}\n\n"
        f"--- CONTEXT (grounding only) ---\n{_context_block(rin)}\n\n"
        f"--- LAYER {layer} FINDINGS (explain these; nothing else) ---\n{_fmt_findings(findings)}\n\n"
        f"Write the Layer {layer} explanation now, following the HARD RULES."
    )


__all__ = ["SYSTEM_PROMPT", "build_layer_prompt"]

"""Day-4 reasoning-and-audit layer.

Three Claude-powered layers that turn the deterministic pipeline's real, verbatim
detections into plain-language clinical reasoning — without ever changing the
class. The authenticity guarantee is structural: the layers only ever see the
``ReasoningInput`` assembled in ``findings.py`` from real detections, so an
explanation cannot reference anything the no-LLM layers did not actually find.
"""

from __future__ import annotations

from .client import ClaudeReasoner, ReasoningUnavailable, credentials_available, guardrail_violations
from .findings import Finding, ReasoningInput, build_reasoning_input
from .layers import LayerOutput, reason_over

__all__ = [
    "build_reasoning_input",
    "ReasoningInput",
    "Finding",
    "reason_over",
    "LayerOutput",
    "ClaudeReasoner",
    "ReasoningUnavailable",
    "credentials_available",
    "guardrail_violations",
]

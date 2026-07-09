"""Runtime Claude client for the reasoning layers, plus an output guardrail.

Design notes:
- Model is ``claude-opus-4-8`` with adaptive thinking, streamed (the skill's
  default for anything non-trivial). The reasoning is short, but streaming keeps
  us safe against timeouts and matches the SDK's recommended path.
- ``credentials_available()`` gates the call. If no credential resolves, we raise
  ``ReasoningUnavailable`` rather than silently degrading — the caller decides
  whether to skip reasoning or surface the requirement. (Fail loud, never fake.)
- ``guardrail_violations()`` is a post-hoc safety net against the one thing the
  system prompt forbids most strongly: the model emitting a classification of its
  own. It is deliberately conservative — it flags explicit self-classification
  verbs, not descriptive statements like "ClinVar reports Pathogenic".
"""

from __future__ import annotations

import os
import re

MODEL = "claude-opus-4-8"

# Explicit self-classification / reclassification verbs. Conservative on purpose:
# these match the model asserting its OWN verdict, not describing a source's.
_CLASSIFY_REDFLAGS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bI (would |'d )?(re-?)?classif",
        r"\bshould be (re-?)?classif",
        r"\bthe (correct|true|actual|real) classification is\b",
        r"\bI (would |'d )?(re-?)?(call|categori[sz]e|label) (it|this)\b",
        r"\breclassif(y|ied|ication)\b",
        r"\bmy (assessment|classification|verdict) is\b",
    )
]


class ReasoningUnavailable(RuntimeError):
    """No Claude credential is resolvable — runtime reasoning cannot be produced."""


def credentials_available() -> bool:
    """True if the Anthropic SDK can resolve a credential from the environment.

    Covers the direct env credentials. (An ``ant auth login`` profile would also
    work for the SDK, but is not detectable from here without invoking it; direct
    env vars are the deployment path we document.)
    """
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def guardrail_violations(text: str) -> tuple[str, ...]:
    """Return any hard-rule violations detected in reasoning output (empty = clean)."""
    hits = []
    for rx in _CLASSIFY_REDFLAGS:
        m = rx.search(text)
        if m:
            hits.append(f"possible self-classification: '{m.group(0).strip()}'")
    return tuple(hits)


class ClaudeReasoner:
    """Thin wrapper over the Anthropic SDK for the reasoning layers."""

    def __init__(self, model: str = MODEL) -> None:
        self.model = model
        self._client = None

    def available(self) -> bool:
        return credentials_available()

    def _anthropic(self):
        if self._client is None:
            import anthropic  # lazy: keep the SDK optional until reasoning runs

            self._client = anthropic.Anthropic()
        return self._client

    def reason(self, system: str, user: str) -> tuple[str, tuple[str, ...]]:
        """Produce one layer's reasoning. Returns (text, guardrail_violations).

        Raises ReasoningUnavailable if no credential resolves — the deterministic
        pipeline still stands on its own; only the plain-language layer is gated.
        """
        if not self.available():
            raise ReasoningUnavailable(
                "No ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN resolved. The deterministic "
                "evaluation and auditor run without a key; the plain-language reasoning "
                "layer calls claude-opus-4-8 at runtime and needs a credential."
            )
        client = self._anthropic()
        with client.messages.stream(
            model=self.model,
            max_tokens=1500,
            system=system,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": user}],
        ) as stream:
            message = stream.get_final_message()
        text = "".join(b.text for b in message.content if b.type == "text").strip()
        return text, guardrail_violations(text)


__all__ = ["ClaudeReasoner", "ReasoningUnavailable", "credentials_available", "guardrail_violations", "MODEL"]

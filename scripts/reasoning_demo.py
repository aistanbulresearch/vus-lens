"""Day-4 reasoning layers over the locked 3-variant set — end to end.

For each variant this runs the REAL deterministic pipeline + auditor, assembles
the verbatim reasoning substrate, and then runs the three Claude reasoning layers
(Layer 1 evidence self-audit, Layer 2 cross-source reconciliation, Layer 3 input
triage with the degradation rule).

If a Claude credential resolves (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN), the
layers call claude-opus-4-8 and print the real reasoning. If not, the layers are
credential-gated and this prints the EXACT substrate + prompt the runtime would
send — so the input is fully inspectable and the reasoning is reproducible with a
key. Pass --show-prompts to always dump the assembled user prompts.

Run:  uv run --no-sync python scripts/reasoning_demo.py [--show-prompts]
"""

from __future__ import annotations

import asyncio
import sys

try:  # load ANTHROPIC_API_KEY from a gitignored .env at the repo root, if present
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Model output contains em-dashes; Windows consoles default to cp1252 and would
# mangle them. Emit UTF-8 so the reasoning renders cleanly in a terminal demo.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from vus_lens.auditor.core import audit
from vus_lens.models.variant import VariantQuery
from vus_lens.pipeline import evaluate_variant
from vus_lens.reasoning.client import ClaudeReasoner
from vus_lens.reasoning.findings import build_reasoning_input
from vus_lens.reasoning.layers import reason_over
from vus_lens.reasoning.prompts import build_layer_prompt

VARIANTS = [
    VariantQuery(raw="ATM p.Arg248Gly (HERO)", rsid="rs730881336", gene="ATM", ref="C", alt="G"),
    VariantQuery(raw="HFE p.Cys282Tyr (C282Y)", rsid="rs1800562", gene="HFE", ref="G", alt="A"),
    VariantQuery(raw="ATN1 CAG[17] (normal-range)", hgvs="chr12:g.7045894GCA[17]", gene="ATN1"),
]

SHOW_PROMPTS = "--show-prompts" in sys.argv


def rule(title: str) -> None:
    print("\n" + "=" * 80 + f"\n{title}\n" + "=" * 80)


def _print_input(rin) -> None:
    print("  SUBSTRATE handed to the reasoning layers (verbatim; nothing else is seen):")
    print(f"    class (fixed): {rin.acmg_class} - {rin.class_basis}")
    print(f"    sources: {rin.sources}")
    for layer in (1, 2, 3):
        fs = rin.findings(layer)
        print(f"    Layer {layer} findings: {len(fs)}")
        for f in fs:
            print(f"      - ({f.kind}) {f.statement}")


async def main() -> None:
    reasoner = ClaudeReasoner()
    live = reasoner.available()
    rule(f"Day-4 reasoning layers  |  Claude credential available: {live}  |  model: {reasoner.model}")
    if not live:
        print("  NOTE: no ANTHROPIC_API_KEY/AUTH_TOKEN in this environment. The deterministic")
        print("  pipeline + auditor + substrate below are REAL; the plain-language layers are")
        print("  credential-gated (they call claude-opus-4-8 at runtime). The assembled prompt")
        print("  is printed so the reasoning is reproducible with a key.")
        print("  To run the real reasoning: put ANTHROPIC_API_KEY=... in a .env file at the repo")
        print("  root (gitignored), then re-run this script.")

    for q in VARIANTS:
        ev = await evaluate_variant(q)
        au = audit(ev)
        rin = build_reasoning_input(ev, au)
        rule(f"{q.raw}   [gene {ev.gene}]   class={ev.bundle.acmg_class.value}")
        _print_input(rin)

        print("\n  REASONING:")
        for out in reason_over(ev, au, reasoner):
            print(f"\n  -- Layer {out.layer}: {out.title}  [{out.status}] --")
            if out.status == "degraded":
                print(f"     {out.reasoning}")
                continue
            if out.status == "no_findings":
                print("     No findings for this layer.")
                continue
            if out.status == "reasoned":
                print(f"     {out.reasoning}")
                if out.guardrail:
                    print(f"     [GUARDRAIL] {out.guardrail}")
                continue
            # unavailable — show the credential-gated notice; dump the exact prompt.
            print(f"     [credential-gated] {out.reasoning}")
            if SHOW_PROMPTS or not live:
                print("     --- exact USER prompt the runtime would send ---")
                for line in build_layer_prompt(out.layer, rin).splitlines():
                    print(f"     | {line}")


if __name__ == "__main__":
    asyncio.run(main())

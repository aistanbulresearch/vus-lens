"""End-to-end deterministic evaluation of the locked 3-variant demo set.

Runs each variant through the real pipeline (clients -> ACMG -> bundle) and
prints what the DETERMINISTIC layer genuinely produces, including the
`detections` that are the substrate the Day-4 reasoning layers will explain.
No LLM here. Honest: if a variant doesn't produce the expected material, it
shows here.

Run:  uv run python scripts/evaluate_variants.py
"""

from __future__ import annotations

import asyncio

from vus_lens.clients.gnomad import ancestry_allele_number
from vus_lens.models.variant import VariantQuery
from vus_lens.pipeline import evaluate_variant

VARIANTS = [
    VariantQuery(raw="ATM p.Arg248Gly (HERO)", rsid="rs730881336", gene="ATM", ref="C", alt="G"),
    VariantQuery(raw="HFE p.Cys282Tyr (C282Y)", rsid="rs1800562", gene="HFE", ref="G", alt="A"),
    VariantQuery(raw="ATN1 c.1506_1508dup (repeat)", rsid="rs60216939", gene="ATN1"),
]


def rule(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


async def main() -> None:
    for q in VARIANTS:
        r = await evaluate_variant(q)
        b = r.bundle
        rule(f"{q.raw}   [gene {r.gene}]")
        print(f"  sources: MyVariant={r.myvariant.status.value}  gnomAD={r.gnomad.status.value}")
        print(f"  DETERMINISTIC CLASS: {b.acmg_class.value}  ({b.class_basis})")

        print("  assigned criteria:")
        if b.criteria:
            for it in b.criteria:
                s = f"/{it.strength.value}" if it.strength else ""
                print(f"    - {it.criterion.value}{s}  [{it.source}]  {it.reason}")
        else:
            print("    (none)")

        print(f"  in-silico: REVEL {r.insilico.revel} -> {r.insilico.band}  [{r.insilico.spec_source}]")
        if r.insilico.crosscheck_note:
            print(f"             AM cross-check (Layer-2): {r.insilico.crosscheck_note}")

        cv = r.clinvar
        print(f"  ClinVar: {list(cv.significances)}  (P/LP={cv.has_pathogenic} B/LB={cv.has_benign} conflicting={cv.is_conflicting})")

        if r.gnomad.is_ok:
            mid = ancestry_allele_number(r.gnomad.data, "mid")
            print(f"  gnomAD: global AF {r.frequency.global_af:.2e} | grpmax FAF {r.frequency.grpmax_faf} | mid AN {mid['total_an']} AC {mid['exome_ac']}/{mid['genome_ac']}")
        else:
            print(f"  gnomAD: {r.gnomad.status.value} - {r.gnomad.message}")

        print("  >>> DETECTIONS (substrate for the reasoning layers):")
        if b.detections:
            for d in b.detections:
                print(f"      * {d}")
        else:
            print("      (no inconsistencies detected - would show 'audit passed')")


if __name__ == "__main__":
    asyncio.run(main())

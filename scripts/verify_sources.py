"""Live verification harness for every public-data client (Day-1 acceptance).

Prints REAL data flowing from each source - not "it works" - and fails loud if
any *core* source is unreachable. Optional sources (ClinicalTrials.gov) are
reported but never fail the run. It also exercises the fail-loud paths so
"empty != clean" is visible.

Run:  uv run python scripts/verify_sources.py
"""

from __future__ import annotations

import asyncio
import sys

import pandas as pd

from vus_lens.clients.clinicaltrials import ClinicalTrialsClient
from vus_lens.clients.gnomad import GnomadClient, ancestry_allele_number
from vus_lens.clients.myvariant import MyVariantClient
from vus_lens.clients.turkish_variome import DEFAULT_PARQUET, TurkishVariomeClient
from vus_lens.models.variant import VariantQuery

# ATM p.Val2424Gly - rich across sources; ATM is one of the demo genes.
PRIMARY = VariantQuery(raw="ATM p.Val2424Gly", rsid="rs28904921", gene="ATM", ref="T", alt="G")

status_log: dict[str, str] = {}


def rule(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def record(source: str, res) -> None:
    status_log[source] = res.status.value
    flag = "" if res.reached_source else "  <-- FAIL LOUD (evidence unavailable)"
    print(f"[{res.status.value.upper():7}] {source}{flag}")
    if res.message:
        print(f"          note: {res.message}")


async def main() -> int:
    mv, gn, tv, ct = (
        MyVariantClient(),
        GnomadClient(),
        TurkishVariomeClient(),
        ClinicalTrialsClient(),
    )

    # ---- 1. MyVariant.info ---------------------------------------------------
    rule("1. MyVariant.info - ClinVar + REVEL + AlphaMissense (canonical transcript)")
    mv_res = await mv.fetch(PRIMARY)
    record("MyVariant.info", mv_res)
    resolved = PRIMARY.model_copy()
    if mv_res.is_ok:
        d = mv_res.data
        print(f"  gene {d['gene']} | MyVariant id {d['myvariant_id']} | hg38 {d['hg38']}")
        cv = d["clinvar"]
        if cv:
            print(f"  ClinVar variant {cv['variant_id']}: {cv['significances']} ({len(cv['submissions'])} submissions)")
        print(f"  REVEL: {d['revel']['value']} ({d['revel']['method']})  |  AlphaMissense: {d['alphamissense']['value']} / pred {d['alphamissense'].get('pred')}")
        hg = d["hg38"] or {}
        resolved = PRIMARY.model_copy(update={"chrom": hg.get("chrom"), "pos": hg.get("pos"), "ref": hg.get("ref"), "alt": hg.get("alt")})

    # ---- 2. gnomAD v4 (the centerpiece) -------------------------------------
    rule("2. gnomAD GraphQL v4 - ancestry allele numbers (trigger 6.1)")
    gn_res = await gn.fetch(resolved)
    record("gnomAD v4", gn_res)
    if gn_res.is_ok:
        mid = ancestry_allele_number(gn_res.data, "mid")
        nfe = ancestry_allele_number(gn_res.data, "nfe")
        ex = gn_res.data["exome"] or {}
        print(f"  exome total AN {ex.get('an')} | AC {ex.get('ac')}")
        print(f"  mid ({mid['label']}): total AN {mid['total_an']} (exome {mid['exome_an']} + genome {mid['genome_an']}), AC {mid['exome_ac']}/{mid['genome_ac']}")
        print(f"  nfe ({nfe['label']}): total AN {nfe['total_an']}")
        if mid["total_an"]:
            print(f"  >>> frequency evidence for a Turkish patient rests on {mid['total_an']:,} mid alleles (nfe/mid ~{nfe['total_an'] / mid['total_an']:.0f}x)")

    # ---- 3. Turkish Variome subset ------------------------------------------
    rule("3. Turkish Variome - local CC BY demo-gene subset")
    tv_res = await tv.fetch(resolved)
    record("Turkish Variome", tv_res)
    if tv._index is not None:
        print(f"  index: {len(tv._index):,} hg38-keyed rows ({tv._skipped_no_hg38} skipped, no GRCh38 coord)")
    if tv_res.is_ok:
        print(f"  Turkish AF {tv_res.data['turkish']['af']} (AC {tv_res.data['turkish']['ac']} / AN {tv_res.data['turkish']['an']})")

    # positive demonstration: a real indexed Turkish variant (highest AF in subset)
    if DEFAULT_PARQUET.exists():
        df = pd.read_parquet(DEFAULT_PARQUET)
        top = df.dropna(subset=["AF"]).sort_values("AF", ascending=False).head(1)
        if not top.empty:
            r = top.iloc[0]
            demo_q = VariantQuery(raw=f"{r['GeneName']} indexed", gene=str(r["GeneName"]), chrom=str(r["CHROM"]), pos=int(r["GRCh38Pos"]), ref=str(r["REF"]), alt=str(r["ALT"]))
            demo_res = await tv.fetch(demo_q)
            print(f"\n  real indexed example -> {r['GeneName']} {r['CHROM']}:{int(r['GRCh38Pos'])} {r['REF']}>{r['ALT']}")
            if demo_res.is_ok:
                t = demo_res.data["turkish"]
                print(f"  [OK     ] Turkish Variome: AF {t['af']:.4f} (AC {t['ac']} / AN {t['an']}, Hom {t['hom']} / Het {t['het']})")

    # ---- 4. ClinicalTrials.gov (optional context) ---------------------------
    rule("4. ClinicalTrials.gov v2 - optional context (never blocks)")
    ct_res = await ct.search(condition="Ataxia Telangiectasia", gene="ATM", page_size=3)
    record("ClinicalTrials.gov", ct_res)
    if ct_res.is_ok:
        print(f"  {ct_res.data['total_count']} trials; showing {ct_res.data['returned']}:")
        for t in ct_res.data["trials"]:
            print(f"    - {t['nct_id']} | {t['status']} | {(t['title'] or '')[:60]}")

    # ---- 5. Fail-loud paths (empty != clean) --------------------------------
    rule("5. Fail-loud checks - a miss is never treated as benign")
    miss = await gn.fetch_by_id("11-108329202-T-A")
    print(f"  gnomAD unknown variant  -> {miss.status.value.upper()} (reached_source={miss.reached_source}, is_unavailable={miss.is_unavailable})")
    off = await tv.fetch(VariantQuery(raw="BRCA1 test", gene="BRCA1", chrom="17", pos=43044295, ref="A", alt="G"))
    print(f"  Turkish Variome BRCA1   -> {off.status.value.upper()}: {off.message}")

    # ---- summary -------------------------------------------------------------
    rule("SUMMARY")
    core = ["MyVariant.info", "gnomAD v4", "Turkish Variome"]
    for s, st in status_log.items():
        print(f"  {s:22} {st}")
    unavailable = [s for s in core if status_log.get(s) in ("error", "timeout")]
    if unavailable:
        print(f"\nFAIL LOUD: core source(s) unavailable: {unavailable}")
        return 1
    print("\nAll core sources reachable (OK or EMPTY). ClinicalTrials is optional context.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Cohort-scale batch panel — deterministic engine ONLY, no LLM.

Runs the ATM/PALB2 ClinVar germline-VUS cohort (retrieved live from ClinVar via
MyVariant) through the *same* deterministic functions the demo uses
(assess_frequency / assess_insilico / read_clinvar / aggregate_evidence / audit)
— no reimplementation. Two performance facts shape the design:

  * gnomAD per-variant querying is rate-limited (~90% HTTP 429 at concurrency 6),
    but its gene endpoint returns EVERY variant's frequency + ancestry in one
    request. So all gnomAD data = 2 requests (ATM + PALB2 gene-bulk). Verified:
    the gene-bulk's Middle-Eastern AN/AC matches the per-variant path exactly.
    Caveat: the gene endpoint omits faf95, so BA1/BS1 (benign frequency calls,
    which a VUS cohort rarely triggers and which are NOT in the headline) are not
    computed in the batch. PM2 + the ancestry rule-of-3 are exact.
  * MyVariant is not rate-limited; the cohort is pulled via its scroll API.

A PARITY GATE runs first: for the hero + sampled ATM/PALB2 cohort variants it
compares the offline batch path against the online per-variant pipeline on the
headline-relevant fields and ABORTS on mismatch. Only then is the full cohort run.

Buckets (LOCKED, cited — no tuning). Denominator stated explicitly.
  Rigor axis, among MISSENSE VUS where AlphaMissense has a pathogenic-direction call:
    X = corroborated by the single calibrated criterion (REVEL PP3 fired)
    Y = AlphaMissense-flagged, NOT corroborated by the calibrated criterion
        (neutral framing — AlphaMissense is a valuable signal, insufficient alone
        under ACMG), reported with composition:
          REVEL indeterminate / REVEL benign-direction (BP4) / REVEL withheld
          (PALB2 SpliceAI-only or transcript ambiguity) / REVEL absent
  Disparity axis, among gnomAD-PRESENT variants:
    Z = auditor 6.1 fired (Middle-Eastern sample inadequate by the rule of 3,
        Hanley & Lippman-Hand 1983) — reported absolute + rate.
  Could-not-evaluate (explicit, never "clean"):
    MyVariant unavailable, or variant absent from gnomAD (no ancestry data).

Run:  uv run --no-sync python scripts/cohort_batch.py [--full]
Without --full, only the parity gate + a size report run (safe, no full cohort).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

try:  # model output / em-dashes render cleanly on a cp1252 Windows console
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from vus_lens.acmg.aggregate import aggregate_evidence
from vus_lens.acmg.clinvar import read_clinvar
from vus_lens.acmg.criteria import ACMGCriterion
from vus_lens.acmg.frequency import assess_frequency
from vus_lens.acmg.insilico import assess_insilico
from vus_lens.auditor.core import audit
from vus_lens.clients.base import AsyncSourceClient
from vus_lens.clients.gnomad import GnomadClient, _extract_sample
from vus_lens.clients.myvariant import FIELDS, MyVariantClient, _normalize
from vus_lens.clients.turkish_variome import TurkishVariomeClient
from vus_lens.config import SETTINGS
from vus_lens.models.evidence import SourceResult
from vus_lens.models.variant import VariantQuery
from vus_lens.pipeline import EvaluationResult, evaluate_variant

GENES = ["ATM", "PALB2"]
VUS_FILTER = 'clinvar.rcv.clinical_significance:"Uncertain significance"'
RETRIEVED = "2026-07-11"

GENE_BULK_QUERY = """
query GeneVariants($symbol: String!, $dataset: DatasetId!) {
  gene(gene_symbol: $symbol, reference_genome: GRCh38) {
    variants(dataset: $dataset) {
      variant_id
      exome  { ac an af faf95 { popmax popmax_population } populations { id ac an } }
      genome { ac an af faf95 { popmax popmax_population } populations { id ac an } }
    }
  }
}
"""


# --------------------------------------------------------------------------- IO
async def _mv(params: dict):
    return await AsyncSourceClient("mv", SETTINGS.myvariant_timeout).request_json(
        "GET", f"{SETTINGS.myvariant_base_url}/query", params=params
    )


async def gene_bulk(symbol: str) -> tuple[str, dict]:
    """(status, {gnomad_variant_id: normalized gnomAD data}) for a whole gene."""
    http = await AsyncSourceClient("gn-bulk", 180.0).request_json(
        "POST", SETTINGS.gnomad_graphql_url,
        json_body={"query": GENE_BULK_QUERY, "variables": {"symbol": symbol, "dataset": SETTINGS.gnomad_dataset}},
    )
    if not http.ok or (http.json or {}).get("errors"):
        return "error", {}
    variants = ((http.json or {}).get("data", {}).get("gene") or {}).get("variants") or []
    lookup = {}
    for v in variants:
        lookup[v["variant_id"]] = {
            "variant_id": v["variant_id"],
            "exome": _extract_sample(v.get("exome")),
            "genome": _extract_sample(v.get("genome")),
        }
    return "ok", lookup


async def scroll_cohort(gene: str) -> list[dict]:
    """All ClinVar-VUS hits for a gene via MyVariant's scroll API."""
    q = f"dbnsfp.genename:{gene} AND {VUS_FILTER}"
    http = await _mv({"q": q, "fields": FIELDS, "fetch_all": "true", "size": 1000})
    body = http.json or {}
    hits = list(body.get("hits", []))
    scroll_id = body.get("_scroll_id")
    while scroll_id:
        http = await _mv({"scroll_id": scroll_id})
        body = http.json or {}
        new = body.get("hits", [])
        if not new:
            break
        hits += new
        scroll_id = body.get("_scroll_id")
    return hits


# ------------------------------------------------------------------- evaluation
def _gn_source(vid: str | None, gn_status: str, lookup: dict) -> SourceResult:
    if gn_status != "ok":  # whole-gene bulk failed -> fail loud for every variant
        return SourceResult.error("gnomAD v4", message="gnomAD gene-bulk unavailable")
    if not vid:
        return SourceResult.error("gnomAD v4", message="no hg38 coords to build a gnomAD id")
    if vid in lookup:
        return SourceResult.ok("gnomAD v4", lookup[vid])
    return SourceResult.empty("gnomAD v4", message=f"not in gnomAD {SETTINGS.gnomad_dataset}: {vid}")


async def offline_eval(hit: dict, gene: str, gn_status: str, lookup: dict, tv: TurkishVariomeClient):
    """Mirror evaluate_variant using PRE-FETCHED MyVariant + gene-bulk gnomAD."""
    mv_data = _normalize(hit)
    mv_sr = SourceResult.ok("MyVariant.info", mv_data)
    hg = mv_data.get("hg38") or {}
    resolved = VariantQuery(
        raw=hit.get("_id", "?"), gene=gene,
        chrom=hg.get("chrom"), pos=hg.get("pos"), ref=hg.get("ref"), alt=hg.get("alt"),
    )
    gn_sr = _gn_source(resolved.gnomad_variant_id(), gn_status, lookup)
    tv_sr = await tv.fetch(resolved)
    freq = assess_frequency(gn_sr, gene)
    ins = assess_insilico(mv_sr, gene)
    cv = read_clinvar(mv_sr)
    bundle = aggregate_evidence(freq, ins, cv, gene)
    ev = EvaluationResult(resolved, gene, mv_sr, gn_sr, tv_sr, freq, ins, cv, bundle)
    return ev, audit(ev)


def bucketize(ev: EvaluationResult, au) -> dict:
    from vus_lens.acmg.insilico import _am_direction

    ins = ev.insilico
    # RAW AlphaMissense call (from MyVariant), independent of whether the tool
    # SURFACES it as a criterion -- so PALB2 (protein prediction withheld by the
    # VCEP) still counts toward "AlphaMissense-alone flags pathogenic", landing in
    # Y as 'REVEL withheld'. AlphaMissense only scores missense, so this restricts
    # the denominator to missense VUS automatically.
    mv_am = (ev.myvariant.data or {}).get("alphamissense") or {}
    am_path = _am_direction(mv_am.get("pred")) == "pathogenic"
    revel_pp3 = ins.criterion is ACMGCriterion.PP3
    # Y composition (neutral): why REVEL did not corroborate an AM-pathogenic call
    if "protein_predictor_not_used" in ins.flags or "transcript_ambiguity" in ins.flags:
        y_kind = "REVEL withheld"
    elif ins.band == "indeterminate":
        y_kind = "REVEL indeterminate"
    elif ins.criterion is ACMGCriterion.BP4:
        y_kind = "REVEL benign-direction"
    elif ins.band == "absent" or ins.revel is None:
        y_kind = "REVEL absent"
    else:
        y_kind = "other"
    from vus_lens.clients.gnomad import ancestry_allele_number
    mid = ancestry_allele_number(ev.gnomad.data, "mid") if ev.gnomad.is_ok else None
    return {
        "gene": ev.gene,
        "mv_ok": ev.myvariant.is_ok,
        "gn_status": ev.gnomad.status.value,
        "gn_ok": ev.gnomad.is_ok,
        "am_path": am_path,
        "revel_pp3": revel_pp3,
        "y_kind": y_kind if (am_path and not revel_pp3) else None,
        "fired_61": any(w.trigger.startswith("6.1") for w in au.warnings),
        "acmg_class": ev.bundle.acmg_class.value,
        "freq_crit": ev.frequency.criterion.value if ev.frequency.criterion else None,
        "mid_an": mid["total_an"] if mid else None,
        "mid_ac": (mid["exome_ac"] or 0) + (mid["genome_ac"] or 0) if mid else None,
    }


# ------------------------------------------------------------------ parity gate
# HARD fields must match exactly (the headline axes). SOFT fields (frequency
# criterion / class) may differ ONLY for a common variant where the online path
# assigns BA1/BS1 from faf95 that the gene-bulk omits -- a documented limitation,
# not a bug, and never part of the N/X/Y/Z headline.
_HARD = ["am_path", "revel_pp3", "y_kind", "fired_61", "gn_status", "mid_an", "mid_ac"]
_SOFT = ["freq_crit", "acmg_class"]


async def _online_with_retry(q, mv, gn, tv):
    """Online per-variant evaluate, retrying gnomAD 429s so the parity comparison
    has real data (the offline gene-bulk path is never rate-limited)."""
    ev = await evaluate_variant(q, myvariant_client=mv, gnomad_client=gn, turkish_variome_client=tv)
    tries = 0
    while ev.gnomad.is_unavailable and tries < 6:
        await asyncio.sleep(5)
        ev = await evaluate_variant(q, myvariant_client=mv, gnomad_client=gn, turkish_variome_client=tv)
        tries += 1
    return ev


async def parity_gate(lookups: dict, tv: TurkishVariomeClient, samples: list[tuple[dict, str]]) -> bool:
    print("\n=== PARITY GATE: offline batch vs online pipeline ===")
    print("  HARD fields (must match): headline axes.  SOFT (freq/class): faf95-gap on common variants only.")
    mv, gn = MyVariantClient(), GnomadClient()
    ok = True
    for hit, gene in samples:
        q = VariantQuery(raw=hit.get("_id", "?"), hgvs=hit.get("_id"), gene=gene)
        ev_on = await _online_with_retry(q, mv, gn, tv)
        await asyncio.sleep(1)  # be gentle on gnomAD between samples
        b_on = bucketize(ev_on, audit(ev_on))
        ev_off, au_off = await offline_eval(hit, gene, "ok", lookups[gene], tv)
        b_off = bucketize(ev_off, au_off)
        hard = {k: (b_on.get(k), b_off.get(k)) for k in _HARD if b_on.get(k) != b_off.get(k)}
        soft = {k: (b_on.get(k), b_off.get(k)) for k in _SOFT if b_on.get(k) != b_off.get(k)}
        tag = "OK  " if not hard else "HARD-MISMATCH"
        print(f"  [{tag}] {gene} {hit.get('_id')}  class={b_off['acmg_class']} amP={b_off['am_path']} REVEL_PP3={b_off['revel_pp3']} 6.1={b_off['fired_61']} midAN={b_off['mid_an']}")
        if hard:
            print(f"        HARD diffs: {hard}")
            ok = False
        if soft:
            print(f"        soft diffs (faf95-gap, expected on common variants): {soft}")
    print(f"  parity (hard fields): {'PASS' if ok else 'FAIL'}")
    return ok


# ------------------------------------------------------------------- full run
def summarize(rows: list[dict], n_total: int, counts: dict) -> dict:
    evaluable = [r for r in rows if r["mv_ok"]]
    mv_fail = sum(1 for r in rows if not r["mv_ok"])
    gn_present = [r for r in evaluable if r["gn_ok"]]
    gn_absent = sum(1 for r in evaluable if r["gn_status"] == "empty")
    gn_error = sum(1 for r in evaluable if r["gn_status"] in ("error", "timeout"))
    am_path = [r for r in evaluable if r["am_path"]]
    X = sum(1 for r in am_path if r["revel_pp3"])
    Y = [r for r in am_path if not r["revel_pp3"]]
    y_comp = dict(Counter(r["y_kind"] for r in Y))
    z = sum(1 for r in gn_present if r["fired_61"])
    return {
        "cohort_label": f"ATM/PALB2 ClinVar germline VUS, retrieved {RETRIEVED}",
        "sources": "MyVariant.info (ClinVar significance + REVEL + AlphaMissense) + gnomAD v4 gene-bulk (frequency + Middle-Eastern ancestry)",
        "note": "deterministic engine only, no LLM. Predominantly germline (ClinVar significance filter, not a clean germline/somatic split). Regenerate: uv run --no-sync python scripts/cohort_batch.py --full",
        "cohort_counts": counts,
        "N_total": n_total,
        "evaluated": len(evaluable),
        "could_not_evaluate": {"myvariant_unavailable": mv_fail, "gnomad_error": gn_error, "absent_from_gnomad": gn_absent},
        "rigor": {
            "denominator": "missense VUS with an AlphaMissense pathogenic-direction call",
            "N_am_pathogenic": len(am_path),
            "X_corroborated_revel_pp3": X,
            "Y_not_corroborated": len(Y),
            "Y_composition": y_comp,
        },
        "disparity": {
            "gnomad_present": len(gn_present),
            "Z_mid_inadequate_rule_of_3": z,
            "Z_rate_of_gnomad_present": round(z / len(gn_present), 4) if gn_present else None,
        },
    }


async def run_full(lookups, statuses, cohorts, tv) -> dict:
    tv0 = time.perf_counter()
    rows: list[dict] = []
    for gene in GENES:
        for hit in cohorts[gene]:
            ev, au = await offline_eval(hit, gene, statuses[gene], lookups[gene], tv)
            rows.append(bucketize(ev, au))
    counts = {g: len(cohorts[g]) for g in GENES}
    summary = summarize(rows, sum(counts.values()), counts)
    print(f"\n  full cohort evaluated in {time.perf_counter()-tv0:.1f}s (local; gnomAD/MyVariant fetched upfront)")
    return summary


async def main():
    full = "--full" in sys.argv
    print(f"COHORT BATCH — deterministic engine only, no LLM. mode={'FULL RUN' if full else 'parity + size only'}")

    print("\n=== 1. gnomAD gene-bulk (2 requests) ===")
    statuses, lookups = {}, {}
    for g in GENES:
        t = time.perf_counter()
        statuses[g], lookups[g] = await gene_bulk(g)
        print(f"  {g}: status={statuses[g]} variants={len(lookups[g])} ({time.perf_counter()-t:.1f}s)")

    print("\n=== 2. cohort derivation (MyVariant scroll) ===")
    cohorts = {}
    for g in GENES:
        t = time.perf_counter()
        cohorts[g] = await scroll_cohort(g)
        print(f"  {g} VUS pulled: {len(cohorts[g])} ({time.perf_counter()-t:.1f}s)")
    total = sum(len(cohorts[g]) for g in GENES)
    print(f"  COHORT TOTAL: {total}  ({RETRIEVED})")

    tv = TurkishVariomeClient()

    # parity gate: hero + first few of each gene
    from vus_lens.models.variant import VariantQuery as _VQ  # noqa
    hero_hits = [h for h in cohorts["ATM"] if h.get("_id") == "chr11:g.108115594C>G"]
    samples = [(h, "ATM") for h in (hero_hits + cohorts["ATM"][:4])] + [(h, "PALB2") for h in cohorts["PALB2"][:4]]
    passed = await parity_gate(lookups, tv, samples)
    if not passed:
        print("\nABORT: parity gate failed — batch diverges from the online engine. Not running full cohort.")
        return

    if not full:
        print("\nParity PASSED. Re-run with --full to execute the full cohort.")
        return

    print("\n=== 3. full cohort run (deterministic buckets) ===")
    summary = await run_full(lookups, statuses, cohorts, tv)
    out = Path("data/cohort/cohort_result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\n(written to {out})")


if __name__ == "__main__":
    asyncio.run(main())

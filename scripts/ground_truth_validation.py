"""Ground-truth SAFETY validation — deterministic engine ONLY, no LLM.

Measures whether the deterministic engine is correct *in the safe direction*
against KNOWN-classified ATM/PALB2 ClinVar variants (not VUS/conflicting). NOT a
concordance test — the engine uses a subset of ACMG (frequency + in-silico +
ClinVar-read; no PS3/PM3/PP1/PVS1), so it cannot and should not reproduce full
expert classifications. Two honest metrics only:

  PRIMARY  Safe-direction guarantee: of known Pathogenic/Likely-pathogenic
           variants, how many does the engine output as Benign/Likely-benign?
           Claim = ZERO (never false reassurance). Any breaker is listed with its
           mechanism — never tuned away. The one plausible legitimate breaker is a
           "pathogenic" common enough to trip BA1/BS1 (the HFE-C282Y low-
           penetrance / risk-allele pattern) — an interesting finding, not a bug.

  DIRECTIONAL  Per class, engine-output distribution, VUS split into
           {has-frequency-data} vs {absent-from-gnomAD}, could-not-evaluate
           explicit (empty != clean). Benign-machinery liveness (true-B/LB
           correctly called) keeps the zero demonstrably meaningful.

Fetch design (feasibility-gated 2026-07-11). The engine can output Benign/LB only
via BA1/BS1, which need gnomAD faf95. gnomAD's public API is rate-limited
(~11 variants/min) AND caps alias-batched queries at ~30 — so faf95 for all 2,580
would take hours. But faf95 <= raw grpmax AF, so a variant whose RAW grpmax AF is
below the BS1 threshold cannot trip BA1/BS1 and is PM2/VUS regardless. So:
  * gene-bulk (2 requests, no throttle) gives raw AC/AN for every variant;
  * per-variant faf95 (throttled) is fetched ONLY for the potentially-common
    subset (raw grpmax AF >= 0.3 * BS1, a safety-margined screen);
  * everything else is scored from gene-bulk (faf95 absent -> PM2 by raw AF,
    identical to what the demo would compute for a rare variant).
A PARITY GATE compares this hybrid against the online per-variant evaluate_variant
on a sample (incl. common variants) and ABORTS on any hard mismatch. Empty != clean:
a source that fails loud -> could-not-evaluate. Leakage: the classified filter
excludes all VUS (demo hero + cohort); non-ATM/PALB2 presets can't appear.

Run: uv run --no-sync python scripts/ground_truth_validation.py --tier 2star --write data/validation/gt_2star.json
     --screen-only stops after reporting the throttled-subset size.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from vus_lens.acmg.aggregate import aggregate_evidence
from vus_lens.acmg.clinvar import read_clinvar
from vus_lens.acmg.frequency import assess_frequency
from vus_lens.acmg.insilico import assess_insilico
from vus_lens.acmg.thresholds import frequency_spec
from vus_lens.clients.base import AsyncSourceClient
from vus_lens.clients.gnomad import GnomadClient, _extract_sample
from vus_lens.clients.myvariant import FIELDS, MyVariantClient, _normalize
from vus_lens.clients.turkish_variome import TurkishVariomeClient
from vus_lens.config import SETTINGS
from vus_lens.models.evidence import SourceResult
from vus_lens.models.variant import VariantQuery
from vus_lens.pipeline import EvaluationResult, evaluate_variant

GENES = ["ATM", "PALB2"]
RETRIEVED = "2026-07-11"

CLASS_MAP = {
    "pathogenic": "P", "likely pathogenic": "LP", "pathogenic/likely pathogenic": "P/LP",
    "benign": "B", "likely benign": "LB", "benign/likely benign": "B/LB",
}
PATH_CLASSES = {"P", "LP", "P/LP"}
CLASSIFIED = "(" + " OR ".join(f'clinvar.rcv.clinical_significance:"{c}"' for c in CLASS_MAP) + ")"

REVIEW_ORDER = [
    "practice guideline", "reviewed by expert panel",
    "criteria provided, multiple submitters, no conflicts",
    "criteria provided, single submitter", "criteria provided, conflicting classifications",
    "criteria provided, conflicting interpretations", "no assertion criteria provided",
    "no assertion provided",
]
STAR = {"practice guideline": "4*", "reviewed by expert panel": "3*",
        "criteria provided, multiple submitters, no conflicts": "2*"}
TIER_MAX_RANK = {"3star": REVIEW_ORDER.index("reviewed by expert panel"),
                 "2star": REVIEW_ORDER.index("criteria provided, multiple submitters, no conflicts")}
BENIGN_ENGINE = {"Benign", "Likely benign"}
SCREEN_MARGIN = 0.3  # fetch per-variant faf95 if raw AF >= SCREEN_MARGIN * BS1 (safety-margined)

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


async def scroll(q: str) -> list[dict]:
    http = await _mv({"q": q, "fields": FIELDS, "fetch_all": "true", "size": 1000})
    body = http.json or {}
    hits = list(body.get("hits", []))
    sid = body.get("_scroll_id")
    while sid:
        http = await _mv({"scroll_id": sid})
        body = http.json or {}
        new = body.get("hits", [])
        if not new:
            break
        hits += new
        sid = body.get("_scroll_id")
    return hits


async def gene_bulk(symbol: str) -> tuple[str, dict]:
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


def ground_truth(hit: dict) -> tuple[int | None, str | None]:
    data = _normalize(hit)
    subs = ((data.get("clinvar") or {}).get("submissions")) or []
    best_rank, best_sig = None, None
    for s in subs:
        rs = (s.get("review_status") or "").strip().lower()
        if rs in STAR:
            rank = REVIEW_ORDER.index(rs)
            if best_rank is None or rank < best_rank:
                best_rank, best_sig = rank, s.get("significance")
    if best_rank is None:
        return None, None
    return best_rank, CLASS_MAP.get((best_sig or "").strip().lower())


def screen_af(bulk_data: dict) -> float:
    """Most generous raw AF from gene-bulk: max(global, any-pop AF, ignoring AN floor).
    Used only to decide whether a variant COULD be common enough to need faf95."""
    best = 0.0
    for key in ("exome", "genome"):
        s = bulk_data.get(key) or {}
        an, ac = s.get("an") or 0, s.get("ac") or 0
        if an:
            best = max(best, ac / an)
        for pop in (s.get("populations") or {}).values():
            pan, pac = pop.get("an") or 0, pop.get("ac") or 0
            if pan:
                best = max(best, pac / pan)
    return best


# ------------------------------------------------------ targeted per-variant faf95
async def fetch_faf(ids: list[str], concurrency: int, t0: float) -> tuple[dict, set]:
    gn = GnomadClient()
    sem = asyncio.Semaphore(concurrency)
    lookup: dict[str, dict] = {}
    failed: set[str] = set()

    async def one(vid: str):
        async with sem:
            sr = await gn.fetch_by_id(vid)
            n = 0
            while sr.is_unavailable and n < 25:
                await asyncio.sleep(4 + n)  # lengthening backoff to clear the rate window
                sr = await gn.fetch_by_id(vid)
                n += 1
        if sr.is_ok:
            lookup[vid] = sr.data
        else:
            failed.add(vid)  # empty (absent) or fail-loud -> can't confirm faf95 -> could-not-evaluate

    tasks = [one(v) for v in ids]
    done = 0
    for c in asyncio.as_completed(tasks):
        await c
        done += 1
        if done % 25 == 0 or done == len(tasks):
            print(f"    faf95 {done}/{len(tasks)}  ({time.perf_counter()-t0:.0f}s)")
    return lookup, failed


# ------------------------------------------------------------------- evaluation
def gn_source(vid, bulk_status, bulk, faf_lookup, faf_failed) -> SourceResult:
    if not vid:
        return SourceResult.error("gnomAD v4", message="no hg38 coords to build a gnomAD id")
    if vid in faf_lookup:
        return SourceResult.ok("gnomAD v4", faf_lookup[vid])           # real faf95 (common subset)
    if vid in faf_failed:
        return SourceResult.error("gnomAD v4", message="per-variant faf95 fetch failed")
    if bulk_status != "ok":
        return SourceResult.error("gnomAD v4", message="gnomAD gene-bulk unavailable")
    if vid in bulk:
        return SourceResult.ok("gnomAD v4", bulk[vid])                 # rare: bulk AC/AN (faf95 null -> PM2 by raw)
    return SourceResult.empty("gnomAD v4", message=f"not in gnomAD {SETTINGS.gnomad_dataset}: {vid}")


_EMPTY_TV = SourceResult.empty("Turkish Variome", message="not fetched (not used in these metrics)")


def offline_eval(hit: dict, gene: str, bulk_status, bulk, faf_lookup, faf_failed) -> EvaluationResult:
    mv_data = _normalize(hit)
    mv_sr = SourceResult.ok("MyVariant.info", mv_data)
    hg = mv_data.get("hg38") or {}
    q = VariantQuery(raw=hit.get("_id", "?"), gene=gene,
                     chrom=hg.get("chrom"), pos=hg.get("pos"), ref=hg.get("ref"), alt=hg.get("alt"))
    gn_sr = gn_source(q.gnomad_variant_id(), bulk_status, bulk, faf_lookup, faf_failed)
    freq = assess_frequency(gn_sr, gene)
    ins = assess_insilico(mv_sr, gene)
    cv = read_clinvar(mv_sr)
    bundle = aggregate_evidence(freq, ins, cv, gene)
    return EvaluationResult(q, gene, mv_sr, gn_sr, _EMPTY_TV, freq, ins, cv, bundle)


def row_of(ev: EvaluationResult, gene: str, gt_rank: int, gt_class: str) -> dict:
    return {
        "gene": gene, "variant_id": ev.query.raw, "gnomad_id": ev.query.gnomad_variant_id(),
        "gt_star": STAR.get(REVIEW_ORDER[gt_rank]), "gt_class": gt_class,
        "gt_dir": "path" if gt_class in PATH_CLASSES else "ben",
        "mv_ok": ev.myvariant.is_ok, "gn_status": ev.gnomad.status.value,
        "engine_class": ev.bundle.acmg_class.value,
        "freq_crit": ev.frequency.criterion.value if ev.frequency.criterion else None,
        "faf95": ev.frequency.grpmax_faf, "grpmax_pop": ev.frequency.grpmax_pop,
        "insilico_crit": ev.insilico.criterion.value if ev.insilico.criterion else None,
        "clinvar_sig": list(ev.bundle.clinvar.significances),
    }


# ------------------------------------------------------------------ parity gate
def _gn_bucket(status: str) -> str:
    return {"ok": "present", "empty": "absent"}.get(status, "unavailable")


async def parity_gate(sample, bulk_status, bulk, faf_lookup, faf_failed) -> bool:
    print("\n=== PARITY GATE: hybrid-offline vs online per-variant evaluate_variant ===")
    mv_c, gn_c, tv_c = MyVariantClient(), GnomadClient(), TurkishVariomeClient()
    ok_all = True
    for hit, gene, rank, cls in sample:
        off = row_of(offline_eval(hit, gene, bulk_status, bulk, faf_lookup, faf_failed), gene, rank, cls)
        q = VariantQuery(raw=hit.get("_id", "?"), hgvs=hit.get("_id"), gene=gene)
        ev_on = await evaluate_variant(q, myvariant_client=mv_c, gnomad_client=gn_c, turkish_variome_client=tv_c)
        n = 0
        while ev_on.gnomad.is_unavailable and n < 10:
            await asyncio.sleep(4)
            ev_on = await evaluate_variant(q, myvariant_client=mv_c, gnomad_client=gn_c, turkish_variome_client=tv_c)
            n += 1
        on = row_of(ev_on, gene, rank, cls)
        diffs = {k: (off[k], on[k]) for k in ("engine_class", "freq_crit") if off[k] != on[k]}
        if not ev_on.gnomad.is_unavailable and _gn_bucket(off["gn_status"]) != _gn_bucket(on["gn_status"]):
            diffs["gn_bucket"] = (_gn_bucket(off["gn_status"]), _gn_bucket(on["gn_status"]))
        # faf95 only matters where the hybrid USED real per-variant faf95 (screened-in);
        # for rare variants the bulk placeholder (0.0) differs immaterially and both -> PM2.
        used_real = off["gnomad_id"] in faf_lookup
        faf_bad = used_real and ev_on.gnomad.is_ok and off["faf95"] is not None and on["faf95"] is not None and abs(off["faf95"] - on["faf95"]) > 1e-9
        tag = "OK  " if not diffs and not faf_bad else "MISMATCH"
        print(f"  [{tag}] {gene} {off['variant_id']} ({off['gnomad_id']}) class={off['engine_class']} freq={off['freq_crit']} faf95={off['faf95']}")
        if diffs or faf_bad:
            print(f"        diffs={diffs} faf_off={off['faf95']} faf_on={on['faf95']}")
            ok_all = False
    print(f"  parity: {'PASS' if ok_all else 'FAIL'}")
    return ok_all


# ------------------------------------------------------------------- summary
def bucket_of(r: dict) -> str:
    if (not r["mv_ok"]) or r["gn_status"] in ("error", "timeout"):
        return "could_not_evaluate"
    if r["engine_class"] in BENIGN_ENGINE:
        return "benign_or_lb"
    if r["gn_status"] == "empty":
        return "vus_absent_from_gnomad"
    return "vus_has_freq_data"


def summarize(rows, tier: str) -> dict:
    by_dir, by_cls = defaultdict(Counter), defaultdict(Counter)
    for r in rows:
        b = bucket_of(r)
        by_dir[r["gt_dir"]][b] += 1
        by_cls[r["gt_class"]][b] += 1
    path_rows = [r for r in rows if r["gt_dir"] == "path"]
    breakers = [r for r in path_rows if bucket_of(r) == "benign_or_lb"]
    ben_rows = [r for r in rows if r["gt_dir"] == "ben"]
    ben_correct = [r for r in ben_rows if bucket_of(r) == "benign_or_lb"]
    cne = [r for r in rows if bucket_of(r) == "could_not_evaluate"]
    return {
        "tier": tier, "retrieved": RETRIEVED, "n_total": len(rows),
        "n_by_gene": dict(Counter(r["gene"] for r in rows)),
        "n_by_class": dict(Counter(r["gt_class"] for r in rows)),
        "path": {
            "n": len(path_rows),
            "n_evaluated": len(path_rows) - int(by_dir["path"]["could_not_evaluate"]),
            "buckets": dict(by_dir["path"]),
            "SAFE_DIRECTION_breakers": len(breakers),
            "breaker_variants": [{k: r[k] for k in ("gene", "variant_id", "gnomad_id", "gt_star",
                                  "gt_class", "engine_class", "freq_crit", "faf95", "grpmax_pop",
                                  "insilico_crit", "clinvar_sig")} for r in breakers],
        },
        "benign": {"n": len(ben_rows), "n_correct_direction": len(ben_correct), "buckets": dict(by_dir["ben"])},
        "could_not_evaluate_reasons": dict(Counter(
            ("myvariant_unavailable" if not r["mv_ok"] else r["gn_status"]) for r in cne)),
        "by_class": {k: dict(v) for k, v in by_cls.items()},
    }


def print_report(s, wall):
    print("\n" + "=" * 74)
    print(f"GROUND-TRUTH SAFETY VALIDATION - tier {s['tier']}  (deterministic engine, no LLM)")
    print("=" * 74)
    print(f"  ground-truth variants: {s['n_total']}   by gene: {s['n_by_gene']}")
    print(f"  by class: {s['n_by_class']}")
    p, b = s["path"], s["path"]["buckets"]
    print("\n  --- PRIMARY: safe-direction guarantee (known Pathogenic/Likely-path) ---")
    print(f"    known P/LP: {p['n']}   evaluated: {p['n_evaluated']}")
    print(f"    >>> called Benign/Likely-benign by the engine: {p['SAFE_DIRECTION_breakers']}  (claim = 0)")
    print(f"          benign_or_lb (DANGER) ....... {b.get('benign_or_lb', 0)}")
    print(f"          VUS, has frequency data ..... {b.get('vus_has_freq_data', 0)}")
    print(f"          VUS, absent from gnomAD ..... {b.get('vus_absent_from_gnomad', 0)}")
    print(f"          could-not-evaluate .......... {b.get('could_not_evaluate', 0)}")
    for v in p["breaker_variants"]:
        faf = v["faf95"]
        faf_s = f"{faf:.3g}" if faf is not None else str(faf)
        print(f"    !!! BREAKER {v['gene']} {v['variant_id']} ({v['gnomad_id']}) [{v['gt_star']} {v['gt_class']}]"
              f" -> {v['engine_class']} via {v['freq_crit']} faf95={faf_s} ({v['grpmax_pop']}); ClinVar={v['clinvar_sig']}")
    bn, bb = s["benign"], s["benign"]["buckets"]
    print("\n  --- DIRECTIONAL + benign-machinery liveness (known Benign/Likely-benign) ---")
    print(f"    known B/LB: {bn['n']}   correctly called Benign/LB: {bn['n_correct_direction']}")
    print(f"          benign_or_lb (correct) ...... {bb.get('benign_or_lb', 0)}")
    print(f"          VUS, has frequency data ..... {bb.get('vus_has_freq_data', 0)}")
    print(f"          VUS, absent from gnomAD ..... {bb.get('vus_absent_from_gnomad', 0)}")
    print(f"          could-not-evaluate .......... {bb.get('could_not_evaluate', 0)}")
    print(f"\n  could-not-evaluate reasons: {s['could_not_evaluate_reasons']}")
    print("\n  --- per exact ClinVar class ---")
    print(f"    {'class':6} {'n':>5} {'ben/LB':>7} {'VUS-data':>9} {'VUS-absent':>11} {'cant-eval':>10}")
    for cls in ("P", "LP", "P/LP", "B", "LB", "B/LB"):
        v = s["by_class"].get(cls)
        if not v:
            continue
        print(f"    {cls:6} {sum(v.values()):>5} {v.get('benign_or_lb', 0):>7} {v.get('vus_has_freq_data', 0):>9}"
              f" {v.get('vus_absent_from_gnomad', 0):>11} {v.get('could_not_evaluate', 0):>10}")
    print(f"\n  (wall {wall:.0f}s; gene-bulk + targeted faf95, deterministic, $0)")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["3star", "2star"], default="2star")
    ap.add_argument("--write", default=None)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--screen-only", action="store_true")
    args = ap.parse_args()
    print(f"GROUND-TRUTH SAFETY VALIDATION — tier={args.tier}, deterministic only, no LLM\n")
    t0 = time.perf_counter()

    print("=== 1. derive ground truth (MyVariant scroll + strongest-gold-RCV) ===")
    max_rank = TIER_MAX_RANK[args.tier]
    working = []
    for g in GENES:
        hits = await scroll(f"clinvar.gene.symbol:{g} AND {CLASSIFIED}")
        kept = [(h, g, r, c) for h in hits for (r, c) in [ground_truth(h)]
                if r is not None and c is not None and r <= max_rank]
        working += kept
        print(f"  {g}: {len(hits)} classified -> {len(kept)} at tier {args.tier}")
    n_path = sum(1 for _, _, _, c in working if c in PATH_CLASSES)
    print(f"  WORKING SET: {len(working)}  (path={n_path}, benign={len(working) - n_path})")

    print("\n=== 2. gnomAD gene-bulk (2 requests, no throttle) ===")
    bulk_status, bulk = {}, {}
    for g in GENES:
        st, lk = await gene_bulk(g)
        bulk_status[g], bulk[g] = st, lk
        print(f"  {g}: status={st} variants={len(lk)}")

    print("\n=== 3. screen: which variants COULD be common enough to need faf95 ===")
    need_ids = set()
    for hit, gene, _, _ in working:
        hg = (_normalize(hit).get("hg38")) or {}
        q = VariantQuery(raw="", gene=gene, chrom=hg.get("chrom"), pos=hg.get("pos"), ref=hg.get("ref"), alt=hg.get("alt"))
        vid = q.gnomad_variant_id()
        if vid and vid in bulk.get(gene, {}):
            if screen_af(bulk[gene][vid]) >= SCREEN_MARGIN * frequency_spec(gene).bs1:
                need_ids.add(vid)
    print(f"  potentially-common (need per-variant faf95): {len(need_ids)} of {len(working)}"
          f"  (~{len(need_ids) / 11:.0f} min at ~11/min)")
    if args.screen_only:
        print("\n(--screen-only: stopping before per-variant faf95 fetch)")
        return

    print(f"\n=== 4. targeted per-variant faf95 (concurrency={args.concurrency}) ===")
    faf_lookup, faf_failed = await fetch_faf(sorted(need_ids), args.concurrency, t0)
    print(f"  faf95: got={len(faf_lookup)} failed={len(faf_failed)} of {len(need_ids)}")

    # flatten bulk to a single id->data map + single status (both genes ok expected)
    flat_bulk = {**bulk.get("ATM", {}), **bulk.get("PALB2", {})}
    bulk_ok = "ok" if all(bulk_status[g] == "ok" for g in GENES) else "error"

    sample = []
    for g in GENES:
        gr = [w for w in working if w[1] == g]
        # include some common (need faf95) + some rare, to exercise both paths
        common = [w for w in gr if VariantQuery(raw="", gene=g,
                  chrom=(_normalize(w[0]).get("hg38") or {}).get("chrom"),
                  pos=(_normalize(w[0]).get("hg38") or {}).get("pos"),
                  ref=(_normalize(w[0]).get("hg38") or {}).get("ref"),
                  alt=(_normalize(w[0]).get("hg38") or {}).get("alt")).gnomad_variant_id() in need_ids]
        sample += common[:2] + gr[:2]
    passed = await parity_gate(sample, bulk_ok, flat_bulk, faf_lookup, faf_failed)
    if not passed:
        print("\nABORT: hybrid path diverges from the online engine. Not scoring.")
        return

    print("\n=== 5. score all ground-truth variants (same functions as the demo) ===")
    rows = [row_of(offline_eval(h, g, bulk_ok, flat_bulk, faf_lookup, faf_failed), g, r, c)
            for (h, g, r, c) in working]
    summary = summarize(rows, args.tier)
    print_report(summary, time.perf_counter() - t0)

    if args.write:
        out = Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
        print(f"\n(written to {out})")


if __name__ == "__main__":
    asyncio.run(main())

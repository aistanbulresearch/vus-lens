"""FastAPI app for the VUS-Lens demo UI.

Two endpoints do the work:
- POST /api/evaluate: runs the DETERMINISTIC pipeline + auditor and returns the
  evidence card, the confidence warnings, and a reasoning *plan* (which layers
  will reason vs degrade) — all with no LLM call.
- GET  /api/reason (SSE): streams the Claude reasoning layers token-by-token for
  a previously-evaluated variant.

The split mirrors the product: the card + warnings stand on their own (auditor
OFF/ON); the plain-language reasoning is credential-gated and streams on top.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:  # load ANTHROPIC_API_KEY from the gitignored repo-root .env, if present
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from ..auditor.core import audit as run_audit
from ..clients.gnomad import ancestry_allele_number
from ..models.variant import VariantQuery
from ..pipeline import evaluate_variant
from ..reasoning.client import credentials_available
from ..reasoning.layers import reason_over_stream, reasoning_plan
from .variants import PRESETS

# Deploy-friendly config (all optional; defaults keep local same-origin behavior):
# - VUS_ROOT_PATH: ASGI root_path when served behind a reverse proxy sub-path.
# - VUS_PUBLIC_BASE: URL prefix the browser must prepend to /api/* calls (e.g.
#   "/vuslens" when nginx maps a sub-path). Injected into live.html at serve time.
ROOT_PATH = os.environ.get("VUS_ROOT_PATH", "")
PUBLIC_BASE = os.environ.get("VUS_PUBLIC_BASE", "")

app = FastAPI(title="VUS-Lens", root_path=ROOT_PATH)
STATIC = Path(__file__).parent / "static"

# Small in-memory cache so the SSE /api/reason reuses the evaluation the card was
# built from (no double network fetch, and the reasoning sees the same substrate).
_CACHE: dict[str, tuple] = {}


def _card(ev, au) -> dict:
    b = ev.bundle
    gnomad = None
    if ev.gnomad.is_ok:
        mid = ancestry_allele_number(ev.gnomad.data, "mid")
        gnomad = {
            "global_af": ev.frequency.global_af,
            "grpmax_faf": ev.frequency.grpmax_faf,
            "grpmax_af": ev.frequency.grpmax_af,
            "grpmax_pop": ev.frequency.grpmax_pop,
            "mid_an": mid["total_an"],
            "mid_ac": (mid["exome_ac"] or 0) + (mid["genome_ac"] or 0),
        }
    return {
        "query": ev.query.raw,
        "gene": ev.gene,
        "sources": {
            "myvariant": ev.myvariant.status.value,
            "gnomad": ev.gnomad.status.value,
            "turkish_variome": ev.turkish_variome.status.value,
        },
        "acmg_class": b.acmg_class.value,
        "class_basis": b.class_basis,
        "criteria": [
            {
                "criterion": i.criterion.value,
                "strength": (i.strength.value if i.strength else None),
                "source": i.source,
                "reason": i.reason,
                "citation": i.citation,
            }
            for i in b.criteria
        ],
        "insilico": {
            "revel": ev.insilico.revel,
            "band": ev.insilico.band,
            "spec_source": ev.insilico.spec_source,
            "tool": ev.insilico.tool,
            "crosscheck_note": ev.insilico.crosscheck_note,
        },
        "clinvar": {
            "significances": list(ev.clinvar.significances),
            "review_status": list(ev.clinvar.review_status),
            "has_pathogenic": ev.clinvar.has_pathogenic,
            "has_benign": ev.clinvar.has_benign,
            "is_conflicting": ev.clinvar.is_conflicting,
            "summary": ev.clinvar.summary,
        },
        "gnomad": gnomad,
        "warnings": [
            {
                "trigger": w.trigger,
                "severity": w.severity,
                "message": w.message,
                "detail": w.detail,
                "citation": w.citation,
            }
            for w in au.warnings
        ],
        "reasoning_plan": reasoning_plan(ev, au),
        "credentials": credentials_available(),
    }


_COHORT_RESULT = Path(__file__).resolve().parents[3] / "data" / "cohort" / "cohort_result.json"


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/cohort")
async def cohort_panel() -> HTMLResponse:
    return HTMLResponse((STATIC / "cohort.html").read_text(encoding="utf-8"))


@app.get("/validation")
async def validation_panel() -> HTMLResponse:
    return HTMLResponse((STATIC / "validation.html").read_text(encoding="utf-8"))


@app.get("/live")
async def live_shell() -> HTMLResponse:
    html = (STATIC / "live.html").read_text(encoding="utf-8")
    # Inject the browser-side API base (empty by default -> same-origin /api/*).
    html = html.replace("__API_BASE__", PUBLIC_BASE)
    return HTMLResponse(html)


@app.get("/api/cohort")
async def cohort_data() -> JSONResponse:
    if not _COHORT_RESULT.exists():
        return JSONResponse({"error": "cohort result not generated; run scripts/cohort_batch.py --full"}, status_code=404)
    return JSONResponse(json.loads(_COHORT_RESULT.read_text(encoding="utf-8")))


@app.get("/api/variants")
async def variants() -> JSONResponse:
    return JSONResponse(
        [
            {"id": k, "label": v["label"], "tag": v["tag"], "note": v["note"], "gene": v["query"].gene}
            for k, v in PRESETS.items()
        ]
    )


@app.post("/api/evaluate")
async def evaluate(payload: dict = Body(...)) -> JSONResponse:
    pid = payload.get("id")
    if pid and pid in PRESETS:
        q = PRESETS[pid]["query"]
        key = pid
    else:
        rsid = (payload.get("rsid") or "").strip()
        if not rsid:
            return JSONResponse({"error": "provide a preset id or an rsID"}, status_code=400)
        q = VariantQuery(
            raw=rsid, rsid=rsid,
            gene=(payload.get("gene") or None),
            ref=(payload.get("ref") or None),
            alt=(payload.get("alt") or None),
        )
        key = "free:" + rsid
    try:
        ev = await evaluate_variant(q)
    except Exception as e:  # fail loud to the UI, never a blank card
        return JSONResponse({"error": f"evaluation failed: {type(e).__name__}: {e}"}, status_code=502)
    au = run_audit(ev)
    _CACHE[key] = (ev, au)
    card = _card(ev, au)
    card["key"] = key
    return JSONResponse(card)


@app.get("/api/reason")
async def reason(key: str):
    cached = _CACHE.get(key)
    if not cached:
        # Cache miss (e.g. the process restarted) — re-evaluate preset keys so the
        # stream stays robust. Free-text keys can't be reconstructed here.
        if key in PRESETS:
            ev = await evaluate_variant(PRESETS[key]["query"])
            au = run_audit(ev)
            _CACHE[key] = (ev, au)
            cached = (ev, au)
        else:
            return JSONResponse({"error": "unknown key; evaluate first"}, status_code=404)
    ev, au = cached

    async def gen():
        try:
            async for evt in reason_over_stream(ev, au):
                yield f"data: {json.dumps(evt)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {e}'})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["app"]

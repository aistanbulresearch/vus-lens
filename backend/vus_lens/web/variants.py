"""The four locked demo variants, as ready-to-run presets for the web UI.

Each is the exact VariantQuery the pipeline consumes; the display metadata drives
the selector chips. These are the storyboard: hero (VCEP path, in-silico withheld
+ ancestry), HFE (common-but-pathogenic, Layer 1+2), ATN1 (repeat locus, Layer 3),
MLH1 (generic path, REVEL resolves to PP3 + AM discordance, Layer 2).
"""

from __future__ import annotations

from ..models.variant import VariantQuery

PRESETS: dict[str, dict] = {
    "atm-hero": {
        "query": VariantQuery(raw="ATM p.Arg248Gly", rsid="rs730881336", gene="ATM", ref="C", alt="G"),
        "label": "ATM p.Arg248Gly",
        "tag": "hero",
        "note": "oncology / HRR · VCEP path",
    },
    "hfe-c282y": {
        "query": VariantQuery(raw="HFE p.Cys282Tyr (C282Y)", rsid="rs1800562", gene="HFE", ref="G", alt="A"),
        "label": "HFE p.Cys282Tyr",
        "tag": "C282Y",
        "note": "common but pathogenic · generic path",
    },
    "atn1-cag17": {
        "query": VariantQuery(raw="ATN1 CAG[17] (normal-range)", hgvs="chr12:g.7045894GCA[17]", gene="ATN1"),
        "label": "ATN1 CAG[17]",
        "tag": "repeat",
        "note": "repeat-expansion locus · input triage",
    },
    "mlh1-lynch": {
        "query": VariantQuery(raw="MLH1 rs35045067 (Lynch)", rsid="rs35045067", gene="MLH1", ref="A", alt="G"),
        "label": "MLH1 rs35045067",
        "tag": "Lynch",
        "note": "REVEL resolves to PP3 · generic path",
    },
}

__all__ = ["PRESETS"]

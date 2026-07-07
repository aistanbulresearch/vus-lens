"""Turkish Variome client — local demo-gene subset index.

Queries the small ``subset.parquet`` built by
``data/turkish_variome/build_index.py`` from the CC BY Turkish Variome
(Kars et al. 2021). This is a **declared subset**: only the demo genes are
indexed. The client is scrupulous about three distinct outcomes so none is
mistaken for another (build brief Sections 5, 6.1, 6.3):

* gene **outside** the indexed subset  -> EMPTY, "outside indexed subset"
  (NOT "absent in the Turkish population" — we simply did not index it)
* gene indexed but this variant **not found** -> EMPTY, "not observed in subset"
* index file **missing / unreadable**  -> ERROR (fail loud)

No frequency is ever synthesized; only real indexed rows are returned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..config import SETTINGS
from ..models.evidence import SourceResult
from ..models.variant import VariantQuery
from .base import AsyncSourceClient

SOURCE = "Turkish Variome (Kars 2021)"
LICENSE = "CC BY 4.0"
DEFAULT_PARQUET = Path(__file__).resolve().parents[3] / "data" / "turkish_variome" / "subset.parquet"


def _key(chrom: str, pos: Any, ref: str, alt: str) -> str:
    return f"{str(chrom).removeprefix('chr')}:{int(pos)}:{ref}:{alt}"


def _num(row: dict[str, Any], col: str) -> Any:
    v = row.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v


class TurkishVariomeClient(AsyncSourceClient):
    """Look up a variant's Turkish-population allele frequency in the subset."""

    def __init__(self, parquet_path: Path | None = None) -> None:
        super().__init__(SOURCE, timeout=0.0, license_note=LICENSE)
        self.parquet_path = parquet_path or DEFAULT_PARQUET
        self._index: dict[str, dict[str, Any]] | None = None
        self._load_error: str | None = None
        self._skipped_no_hg38 = 0

    def _ensure_loaded(self) -> None:
        if self._index is not None or self._load_error is not None:
            return
        if not self.parquet_path.exists():
            self._load_error = f"index not built: {self.parquet_path} missing (run build_index.py)"
            return
        try:
            df = pd.read_parquet(self.parquet_path)
            index: dict[str, dict[str, Any]] = {}
            skipped = 0
            for row in df.to_dict("records"):
                pos, ref, alt = row.get("GRCh38Pos"), row.get("REF"), row.get("ALT")
                # Some source rows lack a GRCh38 mapping; they can't be keyed by
                # hg38 coordinates. Skip them (counted) rather than crash.
                if pd.isna(pos) or pd.isna(ref) or pd.isna(alt):
                    skipped += 1
                    continue
                index[_key(row["CHROM"], pos, ref, alt)] = row
            self._index = index
            self._skipped_no_hg38 = skipped
        except Exception as exc:  # noqa: BLE001 - surfaced as fail-loud ERROR
            self._load_error = f"failed to read index: {exc!r}"

    async def fetch(self, query: VariantQuery) -> SourceResult:
        prov = self.provenance(str(self.parquet_path), query.raw)
        boundary = list(SETTINGS.demo_genes)

        # Declared-boundary check first — it is defined by config, not the index,
        # and outside the subset is NOT "absent in Turks".
        if query.gene and query.gene not in SETTINGS.demo_genes:
            return SourceResult.empty(
                SOURCE,
                prov,
                f"gene {query.gene} is outside the indexed Turkish Variome subset "
                f"(subset covers {boundary}) - not evidence of absence",
            )

        self._ensure_loaded()
        if self._load_error:
            return SourceResult.error(SOURCE, prov, self._load_error)

        if not (query.chrom and query.pos and query.ref and query.alt):
            return SourceResult.error(SOURCE, prov, "no hg38 chrom/pos/ref/alt to query the subset")

        row = (self._index or {}).get(_key(query.chrom, query.pos, query.ref, query.alt))
        if row is None:
            gene = query.gene or "the indexed genes"
            return SourceResult.empty(
                SOURCE,
                prov,
                f"variant not observed in Turkish Variome subset for {gene} "
                f"(subset covers {boundary})",
            )

        data = {
            "variant_id": query.gnomad_variant_id(),
            "gene": row.get("GeneName"),
            "turkish": {
                "af": _num(row, "AF"),
                "ac": _num(row, "AC"),
                "an": _num(row, "AN"),
                "hom": _num(row, "Hom"),
                "het": _num(row, "Het"),
            },
            "comparison": {
                "gnomad_wes_af": _num(row, "AF_gnomAD_WES"),
                "gnomad_wgs_af": _num(row, "AF_gnomAD_WGS"),
                "gme_af": _num(row, "GME_AF"),
                "kg_af": _num(row, "1000GP_AF"),
                "esp_af": _num(row, "ESP_AF"),
            },
            "subset_boundary": boundary,
        }
        return SourceResult.ok(SOURCE, data, prov)


__all__ = ["TurkishVariomeClient"]

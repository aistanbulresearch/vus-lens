"""Build the Turkish Variome **demo-gene subset** index.

Downloads the CC BY ``TurkishVariome.tsv.gz`` from figshare in sequential,
retriable HTTP Range chunks, decompresses it on the fly, and keeps only rows
whose ``GeneName`` is one of the demo genes (``SETTINGS.demo_genes`` is the
single source of truth). Writes a small ``subset.parquet``. The full raw file is
never stored to disk.

Robustness / integrity (learned the hard way — see below):
- The source is **multi-member gzip (BGZF)**: hundreds of gzip members per few
  MB. A single ``zlib.decompressobj`` decodes only the *first* member, so we
  chain a fresh decompressor at every member boundary. (A naive single-stream
  decode silently yields ~245 rows and misses everything else.)
- Filtering is done in **bytes** so the ~7 GB of non-matching rows are never
  decoded — only the header and matched rows are.
- The whole file is verified against figshare's published **size and MD5**. A
  truncated or corrupt download fails loud and writes nothing — never a partial
  subset masquerading as complete.
- No allele frequency is invented; only real rows are kept.

Usage:  uv run python data/turkish_variome/build_index.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import zlib
from pathlib import Path

import httpx
import pandas as pd

from vus_lens.config import SETTINGS

# --- Provenance (Kars et al. 2021, PNAS) -----------------------------------
FIGSHARE_ARTICLE = (
    "https://figshare.com/articles/dataset/"
    "The_genetic_structure_of_the_Turkish_population_reveals_high_levels_of_"
    "variation_and_admixture/15147642"
)
FIGSHARE_DOI = "10.6084/m9.figshare.15147642.v8"
DOWNLOAD_URL = "https://ndownloader.figshare.com/files/30739108"
LICENSE = "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
CITATION = (
    "Kars ME, et al. The genetic structure of the Turkish population reveals "
    "high levels of variation and admixture. PNAS 2021;118(36):e2026076118."
)
N_INDIVIDUALS = 3362
SOURCE_VARIANT_COUNT = 46_739_479
# Published by figshare for this file — the integrity anchor.
RAW_MD5 = "b4e5f63d771332d5d0c942045045ddd1"

DATA_DIR = Path(__file__).resolve().parent
OUT_PARQUET = DATA_DIR / "subset.parquet"
GENES_TXT = DATA_DIR / "demo_genes.txt"
PROVENANCE_JSON = DATA_DIR / "provenance.json"

GENE_COL = "GeneName"
NUMERIC_COLS = [
    "GRCh37Pos", "GRCh38Pos", "AF", "AC", "AN", "Hom", "Het", "QUAL", "DP",
    "GERP_RS", "CADD_phred", "AF_gnomAD_WES", "AF_gnomAD_WGS", "GME_AF",
    "1000GP_AF", "ESP_AF",
]
CHUNK = 1 << 25  # 32 MiB range requests — short-lived, retriable
MAX_RETRIES = 6
_SPLIT = re.compile(r"[;,|]")


def _gene_matches(field: str, genes: set[str]) -> bool:
    return field in genes or any(part in genes for part in _SPLIT.split(field))


def _total_size(client: httpx.Client) -> int:
    r = client.get(DOWNLOAD_URL, headers={"Range": "bytes=0-0"})
    r.raise_for_status()
    content_range = r.headers.get("Content-Range", "")  # 'bytes 0-0/2036111477'
    return int(content_range.split("/")[-1])


def _get_chunk(client: httpx.Client, start: int, end: int) -> bytes:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            r = client.get(DOWNLOAD_URL, headers={"Range": f"bytes={start}-{end}"})
            if r.status_code in (200, 206) and r.content:
                return r.content
            last_err = f"HTTP {r.status_code}, {len(r.content)} bytes"
        except httpx.HTTPError as exc:
            last_err = repr(exc)
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"range {start}-{end} failed after {MAX_RETRIES} tries: {last_err}")


def _decode_members(dec: zlib._Decompress, data: bytes) -> tuple[bytes, zlib._Decompress]:
    """Decompress possibly-many gzip members from ``data``; return (bytes, dec).

    ``dec`` may be mid-member from a previous chunk; the returned ``dec`` holds
    state for a trailing partial member (if any) to continue on the next chunk.
    """
    out: list[bytes] = []
    while data:
        out.append(dec.decompress(data))
        if dec.eof:
            data = dec.unused_data
            dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
        else:
            data = b""
    return b"".join(out), dec


def main() -> int:
    genes = set(SETTINGS.demo_genes)
    genes_b = [g.encode() for g in genes]
    print(f"Demo-gene subset boundary: {sorted(genes)}", file=sys.stderr, flush=True)

    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    md5 = hashlib.md5()
    header: list[str] | None = None
    gene_idx: int | None = None
    matched: list[list[str]] = []
    pending = b""  # partial trailing line (bytes)
    scanned = 0
    offset = 0
    t0 = time.time()
    next_report = 256 << 20

    with httpx.Client(follow_redirects=True, timeout=120) as client:
        total = _total_size(client)
        print(f"Streaming {total:,} bytes (~2 GB, CC BY); expecting md5 {RAW_MD5}", file=sys.stderr, flush=True)
        while offset < total:
            end = min(offset + CHUNK, total) - 1
            raw = _get_chunk(client, offset, end)
            md5.update(raw)
            offset += len(raw)
            decoded, dec = _decode_members(dec, raw)
            block = pending + decoded
            lines = block.split(b"\n")
            pending = lines.pop()
            for line in lines:
                if header is None:
                    header = line.rstrip(b"\r").decode("utf-8").split("\t")
                    gene_idx = header.index(GENE_COL)
                    continue
                scanned += 1
                if not any(g in line for g in genes_b):
                    continue
                cols = line.rstrip(b"\r").decode("utf-8", "replace").split("\t")
                if len(cols) > gene_idx and _gene_matches(cols[gene_idx], genes):
                    matched.append(cols)
            if offset >= next_report:
                rate = offset / 1e6 / (time.time() - t0)
                print(
                    f"  {offset // (1 << 20)}/{total // (1 << 20)} MB "
                    f"({100 * offset // total}%) | scanned {scanned:,} | "
                    f"matched {len(matched):,} | {rate:.1f} MB/s",
                    file=sys.stderr,
                    flush=True,
                )
                next_report += 256 << 20

    if pending and header is not None and gene_idx is not None:
        cols = pending.rstrip(b"\r").decode("utf-8", "replace").split("\t")
        if len(cols) > gene_idx and _gene_matches(cols[gene_idx], genes):
            matched.append(cols)

    elapsed = time.time() - t0
    print(f"Scanned {scanned:,} rows in {elapsed:.0f}s; matched {len(matched):,}", file=sys.stderr, flush=True)

    # --- integrity: fail loud, never write a partial/corrupt subset ---------
    if offset != total:
        print(f"ERROR: truncated download {offset:,} != {total:,} — nothing written.", file=sys.stderr)
        return 1
    digest = md5.hexdigest()
    if digest != RAW_MD5:
        print(f"ERROR: md5 mismatch {digest} != {RAW_MD5} — refusing to write.", file=sys.stderr)
        return 1
    print(f"Integrity OK: {offset:,} bytes, md5 {digest}", file=sys.stderr, flush=True)
    if header is None or not matched:
        print("ERROR: no header / 0 matched rows — refusing to write.", file=sys.stderr)
        return 1

    width = len(header)
    rows = [c + [None] * (width - len(c)) if len(c) < width else c[:width] for c in matched]
    df = pd.DataFrame(rows, columns=header)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.to_parquet(OUT_PARQUET, index=False)
    counts = {str(k): int(v) for k, v in df[GENE_COL].value_counts().items()}

    GENES_TXT.write_text(
        "# Turkish Variome demo-gene subset — genes actually indexed (with row counts)\n"
        + "\n".join(f"{g}\t{counts.get(g, 0)}" for g in sorted(genes))
        + "\n",
        encoding="utf-8",
    )
    PROVENANCE_JSON.write_text(
        json.dumps(
            {
                "source": "Turkish Variome",
                "citation": CITATION,
                "figshare_article": FIGSHARE_ARTICLE,
                "figshare_doi": FIGSHARE_DOI,
                "download_url": DOWNLOAD_URL,
                "license": LICENSE,
                "raw_md5": RAW_MD5,
                "raw_bytes": total,
                "n_individuals": N_INDIVIDUALS,
                "source_variant_count": SOURCE_VARIANT_COUNT,
                "assembly_columns": ["GRCh37Pos", "GRCh38Pos"],
                "subset_boundary_genes": sorted(genes),
                "subset_row_counts": counts,
                "subset_total_rows": int(len(df)),
                "columns": list(df.columns),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {OUT_PARQUET} ({len(df):,} rows); per-gene {counts}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

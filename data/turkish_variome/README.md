# Turkish Variome — demo-gene subset

This directory holds a **small, declared subset** of the Turkish Variome,
indexed locally so the demo does not depend on a live 2 GB download.

## Source & attribution (CC BY 4.0)

> Kars ME, Başak AN, Onat OE, *et al.* **The genetic structure of the Turkish
> population reveals high levels of variation and admixture.** *PNAS*
> 2021;118(36):e2026076118.

- **Dataset:** figshare — *The genetic structure of the Turkish population…*
  [article 15147642](https://figshare.com/articles/dataset/The_genetic_structure_of_the_Turkish_population_reveals_high_levels_of_variation_and_admixture/15147642)
- **DOI:** `10.6084/m9.figshare.15147642.v8`
- **License:** **CC BY 4.0** — https://creativecommons.org/licenses/by/4.0/
- **Full release:** 46,739,479 variants from **3,362** unrelated Turkish
  individuals (static, 2021).

Use of this data complies with CC BY 4.0: the source is attributed above and no
endorsement is implied.

## What is in the subset

`subset.parquet` contains **only** variants annotated (by the source's own
`GeneName` column) to the demo genes:

```
ATN1   HTT   ATM   PALB2
```

The gene list is driven by `SETTINGS.demo_genes` (single source of truth);
`demo_genes.txt` and `provenance.json` are written by the build and record the
exact genes and per-gene row counts actually indexed.

The subset preserves the source's columns, including both `GRCh37Pos` and
`GRCh38Pos` (we key lookups on **GRCh38**, matching gnomAD/MyVariant), the
Turkish `AF`/`AC`/`AN`/`Hom`/`Het`, and the source's comparison frequencies
(gnomAD WES/WGS, GME, 1000GP, ESP).

## Declared boundary — read this

This is a **subset**, not the whole Turkish Variome. Therefore:

- A gene **not** in the list above is simply **not indexed here**. That is
  **never** evidence that a variant is absent in the Turkish population.
- A variant **absent from the subset** means "not observed in this indexed
  slice", not "benign".

The client (`backend/vus_lens/clients/turkish_variome.py`) enforces this
distinction: out-of-subset genes and not-found variants return `EMPTY` with an
explicit message, and a missing/broken index returns `ERROR` (fail loud) —
never a silent blank.

## Rebuilding

```bash
uv run python data/turkish_variome/build_index.py
```

Streams the CC BY `.tsv.gz` from figshare, filters to the demo genes on the
fly (the full raw file is never stored — it is git-ignored), and writes
`subset.parquet`, `demo_genes.txt`, and `provenance.json`.

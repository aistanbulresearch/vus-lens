# VUS Confidence Auditor (`vus-lens`)

Clinical-genetics decision support that aggregates evidence for a genetic
variant from **open public sources**, maps it to ACMG criteria
**deterministically**, and then does what most aggregators don't: it **audits
the reliability of its own evidence** and declares where that evidence is
weak for *this* patient's ancestry.

> **Decision support — not a classifier, not a diagnosis.**
> The final interpretation is always the clinician's.

## Status

**Day 1** — repository scaffold, integrity charter, and live public-data
clients (MyVariant.info, gnomAD GraphQL v4 with ancestry breakdown,
ClinicalTrials.gov v2), plus the Turkish Variome demo-gene subset index.
No ACMG logic and no LLM yet — those come on later days.

Built from scratch for the *Built with Claude: Life Sciences* hackathon.
MIT licensed.

## Data sources (all open, no API key)

| Source | Provides | License |
|---|---|---|
| MyVariant.info | ClinVar, REVEL, AlphaMissense, dbNSFP | open aggregation of public data |
| gnomAD GraphQL v4 | allele frequency + ancestry breakdown (incl. Middle Eastern) | open |
| Turkish Variome (Kars et al. 2021) | Turkish-population allele frequency | CC BY |
| ClinicalTrials.gov v2 | trials for a gene/condition (optional context) | public domain (U.S. Gov) |

## Repository layout

```
backend/vus_lens/   FastAPI app + public-data clients + models
data/turkish_variome/  demo-gene subset index + provenance
frontend/           reserved for the Day-5 result screen
scripts/            live source-verification harness
tests/              unit + live tests
```

See [`SCIENTIFIC_INTEGRITY.md`](SCIENTIFIC_INTEGRITY.md) for the integrity
commitments that govern every commit.

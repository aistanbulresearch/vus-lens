# VUS Confidence Auditor (`vus-lens`)

Clinical-genetics decision support that aggregates the evidence for a genetic
variant from **open public sources**, maps it to ACMG criteria
**deterministically** (no LLM in the call), and then does what most aggregators
don't: it **audits the reliability of its own evidence** and declares where that
evidence is too weak to trust for *this* patient's ancestry.

> **Decision support — not a classifier, not a diagnosis.**
> The final interpretation, and the clinical decision, belong to the clinician.

**Live demo:** <https://vuslens.aistanbulresearch.com/live>
Prepared for the **2026 _Built with Claude: Life Sciences_ Hackathon**.

---

## What it does

1. **Deterministic ACMG engine (no LLM).** Frequency criteria (PM2 / BS1 / BA1)
   from allele frequency; in-silico (PP3 / BP4) from REVEL read on the
   canonical / MANE transcript, with AlphaMissense carried only as a Layer-2
   cross-check (never scored into the class); ClinVar significance read directly.
   Same input always yields the same output, and every step is inspectable.

2. **Ancestry-aware confidence auditing.** When a frequency criterion is assigned,
   the tool reads the *actual* allele number for the patient's ancestry (gnomAD v4
   Middle-Eastern `mid` group + the Turkish Variome) and flags — by the rule of 3
   — when the sample is too small to support the call. This is the axis that tools
   built on Western reference data omit.

3. **Claude audits; it never decides.** `claude-opus-4-8` reasons over the
   deterministic output in three layers (evidence self-audit, cross-source
   reconciliation, input triage) and explains it in plain language, streamed live
   per variant. The class is handed to the model as a fixed fact, and an output
   guardrail flags any self-classification: the model informs; the engine and the
   clinician decide.

**The confidence flags it raises** (surfaced as capability badges on the page):

- **Ancestry-confidence** — a rarity call rests on too few alleles for this
  ancestry to be trusted.
- **Repeat-expansion** — a short-read-WES-blind STR locus, where a normal-range
  result does not exclude the disorder.
- **Cross-source conflict / empty ≠ clean** — disagreeing or unreachable sources
  are surfaced, never read as benign.

---

## Measured safe

The same deterministic engine was run against **known-classified** ATM/PALB2
ClinVar variants (2★+: criteria provided, multiple submitters, no conflicts, or
expert panel) to test one property directly: *does the tool ever give false
reassurance?*

- **0 of 1,277 known-pathogenic variants were ever called benign** — the
  safe-direction guarantee (the 3★ expert-panel core reproduces it).
- The benign machinery is demonstrably live: **58 of 94 definitively-benign
  variants were correctly called Benign** — so the zero is a real safety property,
  not disabled logic.

Deterministic, no LLM, \$0, and **parity-gated** against the live per-variant
pipeline. Full method and the honest under-call caveats are in
[`SCIENTIFIC_INTEGRITY.md`](SCIENTIFIC_INTEGRITY.md) §7; the result lives in
`data/validation/gt_2star.json` and regenerates via
`scripts/ground_truth_validation.py`. The same engine also runs across a live
**10,747-variant** ATM/PALB2 VUS cohort (`/cohort`), parity-gated end to end.

---

## Data sources (all open, no API key)

| Source | Provides | License |
|---|---|---|
| MyVariant.info | ClinVar significance + review status, REVEL, AlphaMissense, dbNSFP | open aggregation of public data |
| gnomAD GraphQL v4 | allele frequency + ancestry breakdown (incl. Middle Eastern `mid`) | open |
| Turkish Variome (Kars et al. 2021) | Turkish-population allele frequency (3,362 individuals) | CC BY |
| ClinicalTrials.gov v2 | trials for a gene / condition (optional context) | public domain (U.S. Gov) |

**Standards — adoption, not full conformance.** Frequency and in-silico thresholds
adopt the ClinGen HBOP VCEP specs for **ATM** (CSpec GN020 v1.5.0) and **PALB2**
(CSpec GN077 v1.2.0) on gnomAD v4; every other gene falls back to ACMG-AMP /
ClinGen-SVI defaults, explicitly labeled *"generic default, not gene-specific."*
The tool never implies VCEP authority it does not have (see
[`SCIENTIFIC_INTEGRITY.md`](SCIENTIFIC_INTEGRITY.md) §2).

---

## Run it

Requires **Python 3.12**.

```bash
uv sync                 # or: python -m venv .venv && .venv/bin/pip install -e .

cp .env.example .env    # set ANTHROPIC_API_KEY to stream the Claude reasoning
                        # layer. The deterministic engine + auditor run fully
                        # without a key (only the plain-language layer is withheld).

uv run uvicorn vus_lens.web.app:app --host 127.0.0.1 --port 8000
```

Then open **<http://127.0.0.1:8000/live>** (the live auditor). Other routes:
`/` four-variant demo · `/cohort` cohort panel · `/validation` safety panel.

Regenerate the safety validation: `uv run python scripts/ground_truth_validation.py`.

---

## Repository layout

```
backend/vus_lens/
  pipeline.py        orchestrates a single-variant evaluation
  clients/           live public-data clients (MyVariant, gnomAD, Turkish Variome, ClinicalTrials)
  acmg/              deterministic criteria, frequency + in-silico thresholds, aggregation
  auditor/           confidence triggers (ancestry-frequency, repeat-expansion, empty-not-clean)
  reasoning/         Claude audit layers + output guardrail
  web/               FastAPI app + static UI (static/live.html is the live page)
data/
  turkish_variome/   demo-gene subset index + provenance
  cohort/            cohort batch result
  validation/        ground-truth safety results (gt_2star / gt_3star)
deploy/              isolated deploy package (systemd unit, nginx server-block, runbook)
scripts/             cohort batch, ground-truth validation, source verification
tests/               unit + live tests
SCIENTIFIC_INTEGRITY.md   the integrity charter that governs every commit
```

---

## Credits

- **Directed by** AIstanbul Research Group
- **Scientific Advisor** — Prof. Aysegul Kuskucu, Yeditepe University, Department of Medical Genetics
- **Built with Claude** — reasoning by `claude-opus-4-8`; developed with Claude Code
- Prepared for the **2026 _Built with Claude: Life Sciences_ Hackathon**

Governed by [`SCIENTIFIC_INTEGRITY.md`](SCIENTIFIC_INTEGRITY.md) — if any commit
conflicts with those commitments, the commitment wins. **MIT** licensed.

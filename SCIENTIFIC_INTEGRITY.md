# Scientific Integrity

*The integrity charter for the VUS Confidence Auditor. It states how the tool
earns trust: through declared limits, transparent sourcing, and deterministic
logic. This is the **Day-1 skeleton**, finalized on Days 5–6 once every source
version is pinned and the demo variant's real output is captured. The sections
describe the tool's design; the deterministic engine and self-audit layer are
implemented over Days 2–4. The commitments below are already binding on every
commit.*

---

## 0. The stance, in one line

Most variant-interpretation tools aggregate evidence and project confidence.
This one aggregates evidence **and declares where that evidence is not
trustworthy for the patient in front of you.** Declaring the limits of our own
confidence *is* the product — not a caveat bolted on at the end.

---

## 1. What the tool does, and why the design is sound

**Value first.** The tool is built on three deliberate strengths:

- **Deterministic ACMG authority.** Evidence criteria and the final class are
  computed by testable, reproducible code — never by a language model.
  Frequency criteria (PM2 / BS1 / BA1) come from allele frequency; in-silico
  criteria (PP3 / BP4) from calibrated scores (REVEL, AlphaMissense) read on the
  **canonical / MANE transcript**, not the maximum across transcripts; ClinVar
  significance is read directly. The same input always yields the same output,
  and every step is inspectable.

- **Transparent, cited evidence.** Every item on the result card carries its
  source and the ACMG criterion it maps to, with the reason it maps there.
  Nothing is asserted without a traceable origin.

- **Ancestry-aware confidence auditing.** When a frequency-based criterion is
  assigned, the tool reads the *actual* allele number (sample size) for the
  relevant ancestry from gnomAD v4 — including the Middle Eastern (`mid`) group —
  and from the Turkish Variome, and warns when that sample is too small to
  support the criterion. This is the axis that tools built on Western reference
  data omit.

**Claude audits; it never decides.** After the deterministic layer runs, Claude
cross-checks the assigned evidence against the raw public data for *defined,
real* inconsistencies and explains them in plain language for the clinician. It
does not assign or alter the classification. This is both a scientific-integrity
rule and a safety rule.

---

## 2. Deliberate limits — a design choice, not a gap

A tool that declares what it cannot see is more mature than one that quietly
returns "nothing found." These limits are chosen, and stated up front:

- **Splice effect is not machine-scored.** There is no reliable, openly-licensed
  live splice-prediction source we are willing to stand behind (the Broad
  SpliceAI lookup was unstable in testing). Rather than emit a fragile or
  fabricated splice score, the tool states plainly: *in-silico splice effect not
  scored; manual / expert splice assessment required.* Declared, not hidden.

- **Repeat-expansion loci are flagged as WES-blind.** For genes where disease is
  driven by a repeat expansion that short-read exome sequencing cannot reliably
  size (e.g. `ATN1` / DRPLA), a normal-range result does **not** exclude the
  disorder. The tool raises this from a small, source-cited locus table and
  states that targeted repeat-sizing is required — *regardless* of the computed
  class.

- **The Turkish Variome index is a declared subset.** For the demo it indexes
  only the demo genes (`ATN1`, `HTT`, `ATM`, `PALB2`), not the full 2021
  release. The boundary is stated wherever the source is used; absence from the
  subset is never read as "absent in the Turkish population."

None of these is an apology. Each is the tool refusing to imply knowledge it
does not have.

### Standards conformance — adoption, not full conformance

The tool adopts the **frequency thresholds** of the ClinGen Hereditary Breast,
Ovarian and Pancreatic Cancer (HBOP) Variant Curation Expert Panel for the genes
it covers — **ATM** (CSpec GN020 v1.5.0) and **PALB2** (CSpec GN077 v1.2.0),
both on gnomAD v4 — and the VCEP / Pejaver-calibrated **REVEL & AlphaMissense
PP3/BP4** thresholds for in-silico evidence. Every other gene falls back to
general ACMG-AMP / ClinGen-SVI defaults, explicitly labeled *"generic default,
not gene-specific"* in the output, so the tool never implies VCEP authority it
does not have.

This is **adoption of specific, cited criteria — not full VCEP conformance.**
The tool deliberately does not implement the parts of the protocols outside its
scope: no PM3 bi-allelic / in-trans logic, no PVS1 loss-of-function decision
tree, and no functional-assay (PS3/BS3), segregation (PP1/BS4), or de novo
(PS2/PM6) evidence. It also honors gene-specific exclusions: the ATM VCEP does
not use PM1, PP2, or PS2, and the tool never applies them to ATM. Likewise, the
PALB2 VCEP does not establish missense pathogenicity — its PP3/BP4 are
SpliceAI-based — so the tool deliberately **withholds** protein-level REVEL
PP3/BP4 for PALB2 missense variants. This is gene-aware rigor, not a gap: a naive
tool that applied a REVEL PP3 to a PALB2 missense would be making a call the
expert panel explicitly declines to make.

**Splice, declared:** the PALB2 v1.2.0 spec adds SpliceAI PP3/BP4 thresholds.
Because we do not run a live splice predictor, splice-relevant variants receive
an explicit *"in-silico splice effect not scored; manual / expert splice
assessment required"* flag rather than a silently-missing criterion — the same
fail-loud stance as everywhere else.

These boundaries are stated up front, not discovered later.

---

## 3. Source and license transparency

The tool uses **only openly-licensed, public data**, with no API keys — and
therefore **no secrets in this repository**. License-restricted or closed
sources (OMIM, NCCN, ESMO, OncoKB) are deliberately excluded.

| Source | Provides | Access | License / terms |
|---|---|---|---|
| **MyVariant.info** | ClinVar significance + review status, REVEL, AlphaMissense, dbNSFP | REST, no key | open aggregation; underlying sources cited per record |
| **gnomAD GraphQL v4** | allele frequency + ancestry breakdown incl. Middle Eastern (`mid`) | GraphQL, no key | open (gnomAD terms of use) |
| **Turkish Variome** (Kars et al. 2021) | Turkish-population allele frequency (3,362 individuals) | figshare | **CC BY** |
| **ClinicalTrials.gov v2** | trials for a gene / condition (optional context) | REST, no key | U.S. Government public domain |

*In-silico scores (REVEL, AlphaMissense) are used on the canonical / MANE
transcript, never the maximum across transcripts — a deliberate scientific
choice. Per-variant ClinVar / dbNSFP sub-source citations are surfaced on the
evidence card. Exact source-version pins are added on finalization (Days 5–6).*

---

## 4. How the tool flags what it does not know

Fail-loud is the **core mechanism**, not error handling bolted on:

- **Empty ≠ clean.** A source that returns no record for a variant is reported
  as *no data*, never as evidence of benignity. This is enforced in the type
  system: every data client returns an explicit status (`OK` / `EMPTY` /
  `ERROR` / `TIMEOUT`) with provenance, so downstream code cannot silently treat
  a miss as a negative result.

- **A failed source is visible.** If a source is unreachable or times out, the
  tool raises an *evidence unavailable — not the same as benign* flag and
  reflects it in the confidence summary. A degraded run says so, loudly.

- **No fabrication, ever.** No frequency, score, PMID, or citation is invented.
  If a number is shown — an ancestry sample size, an allele frequency — it was
  read live from the source at query time. No threshold, score, or output is
  tuned to make the demo look better. An inconvenient result stands.

**Proven on our own pipeline.** On Day 1 the Turkish Variome loader hit this
exact failure mode from the inside: the source file is multi-member gzip, and a
naive decoder silently read 245 of 46,739,479 rows *while reporting success*.
The fail-loud guard refused to write, and an MD5 + size integrity gate now makes
a truncated decode impossible to ship as a "complete" dataset. A tool that
quietly accepts 245 of 46.7M rows is the same defect as one that quietly treats
a failed lookup as benign — see [`NOTES/anecdotes.md`](NOTES/anecdotes.md).

---

## 5. The reasoning-and-audit layer — how "Claude audits, never decides" is enforced

Section 1 states the rule; this is the mechanism (Day 4). The plain-language
reasoning is produced by Claude (`claude-opus-4-8`) in three layers — evidence
self-audit (Layer 1), cross-source reconciliation (Layer 2), and input triage
(Layer 3) — and the design makes the integrity rule **structural**, not a matter
of prompt etiquette:

- **The model can only explain what the deterministic engine actually found.**
  Each layer receives a fixed substrate — the computed class, the assigned
  criteria, and the real detections/warnings — assembled *verbatim* from the
  no-LLM output. It never sees the raw variant or open-ended context. A finding
  the deterministic layer did not produce is never placed in front of the model,
  so it cannot explain (or invent) one. "Every explanation traces to a real
  detection" is therefore a property of the data path, enforced by a test, not a
  hope.

- **The class is fixed input, never output.** The class is handed to the model as
  a stated fact it may restate but must not change. An output guardrail flags any
  self-classification language (e.g. "reclassify", "the correct classification
  is") as a rule violation. The model informs; the deterministic engine and the
  clinician decide.

- **Calibrated, not dramatic; and no manufactured layers.** A layer with nothing
  to explain says so. Input triage (Layer 3) is *dropped* when it carries no
  material input-adequacy concern — a clean SNV never receives a filler "the input
  looks fine" paragraph — and kept only for a real issue (a repeat-locus assay
  mismatch, a call withheld for transcript ambiguity, or an unreachable required
  source).

- **Credential-gated, never faked.** The reasoning layer calls the Claude API at
  runtime and requires a credential. With no key, the deterministic evaluation and
  auditor still run in full; only the plain-language layer is withheld — and it
  says so — never replaced with canned or fabricated text.

---

## 6. Honest at scale — the cohort batch

The same deterministic engine runs across a whole cohort, and the same rules hold
at 10,747 variants as at one.

- **Cohort.** ATM/PALB2 germline VUS derived live from ClinVar via MyVariant
  (ClinVar significance = "Uncertain significance"), retrieved 2026-07-11: 10,747
  variants (ATM 7,824 + PALB2 2,923). The set is **predominantly germline — a
  ClinVar significance filter, not a clean germline/somatic split** — and is stated
  as such. (An earlier ESMO-poster snapshot was 9,534; the count grows with ClinVar.)

- **The same engine, proven.** The batch calls the *identical* deterministic
  functions the single-variant tool uses (frequency / in-silico / ClinVar /
  aggregation / auditor) — no reimplementation. A **parity gate** checks the batch
  path against the online per-variant pipeline on sampled variants and aborts on any
  divergence, before the full run.

- **Empty ≠ clean, at scale.** Variants that cannot be evaluated are bucketed
  explicitly, never as "clean": 6,544 of this cohort are absent from gnomAD entirely
  (no ancestry data), and the disparity rate is reported over the gnomAD-covered
  subset only — never the whole cohort.

- **A declared performance boundary.** gnomAD's per-variant API is rate-limited, so
  the batch reads each gene's frequency + ancestry in one gene-level request. That
  endpoint omits the faf95 filtering-AF, so the batch does not compute BA1/BS1
  (benign frequency calls) — immaterial to a VUS cohort and to the reported axes:
  rigor uses REVEL / AlphaMissense, and disparity uses the Middle-Eastern allele
  number, which the gene-bulk returns identically to the per-variant path (verified).
  No number is tuned; the buckets are fixed and cited before the run.

---

## 7. What this tool is not

**Decision support — not a classifier, not a diagnosis.** It surfaces and
organizes evidence and audits its own confidence. The interpretation, and the
clinical decision, belong to the clinician.

---

*Governed by the operating principles in the project brief. If any commit is
found to conflict with the commitments above, the commitment wins.*

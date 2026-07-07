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

---

## 5. What this tool is not

**Decision support — not a classifier, not a diagnosis.** It surfaces and
organizes evidence and audits its own confidence. The interpretation, and the
clinical decision, belong to the clinician.

---

*Governed by the operating principles in the project brief. If any commit is
found to conflict with the commitments above, the commitment wins.*

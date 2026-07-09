"""ACMG frequency thresholds — gene-specific ClinGen VCEP specs with a labeled
generic fallback.

These are load-bearing scientific choices, so each set is documented with its
source and version and is never tuned to a specific variant. Values were pulled
from the ClinGen Criteria Specification Registry (cross-checked against the
published ATM specification). Metric per spec text: **BA1/BS1 use the grpmax
filtering AF (gnomAD v4 faf95); PM2 uses the raw grpmax AF.** Verified per gene:
both ATM (GN020) and PALB2 (GN077) word PM2 as "Frequency <= X" (raw point
estimate), while BA1/BS1 are worded "Grpmax Filtering AF".

Scope: we adopt VCEP *frequency* thresholds, not full VCEP conformance.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrequencySpec:
    """One gene's (or the generic) frequency thresholds, with provenance."""

    gene: str | None
    source: str  # "VCEP" or "generic"
    label: str  # citation, including spec version
    ba1: float  # grpmax filtering AF (faf95) above this -> BA1
    bs1: float  # grpmax filtering AF (faf95) above this -> BS1
    pm2: float  # raw grpmax AF at or below this -> PM2


# General ACMG-AMP 2015 / ClinGen SVI defaults — used for any gene without a
# VCEP override. Explicitly labeled so the output never implies false authority.
GENERIC_SPEC = FrequencySpec(
    gene=None,
    source="generic",
    label="ACMG-AMP 2015 / ClinGen SVI general defaults (not gene-specific)",
    ba1=0.05,
    bs1=0.01,
    pm2=1e-4,
)

# Gene-specific ClinGen HBOP VCEP thresholds (CSpec Registry).
VCEP_SPECS: dict[str, FrequencySpec] = {
    "ATM": FrequencySpec(
        gene="ATM",
        source="VCEP",
        label="ClinGen HBOP VCEP ATM specs, CSpec GN020 v1.5.0 (2025-11-07); gnomAD v4",
        ba1=0.005,   # grpmax filtering AF > 0.5%
        bs1=0.0005,  # grpmax filtering AF > 0.05%
        pm2=1e-5,    # raw grpmax AF <= 0.001%
    ),
    "PALB2": FrequencySpec(
        gene="PALB2",
        source="VCEP",
        label="ClinGen HBOP VCEP PALB2 specs, CSpec GN077 v1.2.0 (2025-07-14); gnomAD v4",
        ba1=0.001,          # grpmax filtering AF > 0.1%
        bs1=0.0001,         # grpmax filtering AF > 0.01%
        pm2=1.0 / 300_000,  # raw grpmax AF <= 1/300,000 (0.000333%)
    ),
}

# Raw-grpmax adequacy floor for PM2: ignore an ancestry's point estimate if its
# allele number is below this (tiny, noisy sample). gnomAD's faf95 already
# accounts for sample size, so this applies only to the PM2 raw-AF path.
GRPMAX_AN_FLOOR = 2000


def frequency_spec(gene: str | None) -> FrequencySpec:
    """Return the gene-specific VCEP spec, or the labeled generic default."""
    if gene and gene in VCEP_SPECS:
        return VCEP_SPECS[gene]
    return GENERIC_SPEC


__all__ = ["FrequencySpec", "GENERIC_SPEC", "VCEP_SPECS", "GRPMAX_AN_FLOOR", "frequency_spec"]

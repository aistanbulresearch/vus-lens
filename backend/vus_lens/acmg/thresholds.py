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

from .criteria import EvidenceStrength


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


# --- In-silico PP3/BP4 (REVEL only; AlphaMissense is a Layer-2 cross-check) ---
# Per ClinGen/Pejaver: ONE pre-defined calibrated tool; correlated predictors are
# not counted independently. Bands are cited; a score in the indeterminate gap
# yields neither PP3 nor BP4 (never read mid-range REVEL as benign).
_ES = EvidenceStrength


@dataclass(frozen=True)
class InSilicoSpec:
    gene: str | None
    source: str
    label: str
    tool: str  # "REVEL" or "SpliceAI"
    protein_predictor_used: bool  # False for genes whose VCEP uses SpliceAI only
    pp3: tuple[tuple[float, EvidenceStrength], ...]  # (min REVEL, strength), high->low
    bp4: tuple[tuple[float, EvidenceStrength], ...]  # (max REVEL, strength), low->high


# Pejaver et al. 2022 (AJHG) Table 2 — general REVEL calibration.
PEJAVER_GENERIC_INSILICO = InSilicoSpec(
    gene=None,
    source="generic",
    label="Pejaver et al. 2022 (Am J Hum Genet) ClinGen PP3/BP4 REVEL calibration",
    tool="REVEL",
    protein_predictor_used=True,
    pp3=((0.932, _ES.STRONG), (0.773, _ES.MODERATE), (0.644, _ES.SUPPORTING)),
    bp4=((0.003, _ES.VERY_STRONG), (0.016, _ES.STRONG), (0.183, _ES.MODERATE), (0.290, _ES.SUPPORTING)),
)

VCEP_INSILICO_SPECS: dict[str, InSilicoSpec] = {
    "ATM": InSilicoSpec(
        gene="ATM",
        source="VCEP",
        label="ClinGen HBOP VCEP ATM GN020 v1.5.0; missense REVEL, Supporting only",
        tool="REVEL",
        protein_predictor_used=True,
        pp3=((0.7333, _ES.SUPPORTING),),  # REVEL > 0.7333
        bp4=((0.249, _ES.SUPPORTING),),   # REVEL <= 0.249
    ),
    # PALB2 VCEP uses SpliceAI as the sole PP3/BP4 predictor; protein-level REVEL
    # is not applied to missense. We do not run live SpliceAI -> declared gap.
    "PALB2": InSilicoSpec(
        gene="PALB2",
        source="VCEP",
        label="ClinGen HBOP VCEP PALB2 GN077 v1.2.0; SpliceAI-only PP3/BP4 (protein REVEL not applied)",
        tool="SpliceAI",
        protein_predictor_used=False,
        pp3=(),
        bp4=(),
    ),
}


def insilico_spec(gene: str | None) -> InSilicoSpec:
    """Return the gene-specific VCEP in-silico spec, or the generic Pejaver one."""
    if gene and gene in VCEP_INSILICO_SPECS:
        return VCEP_INSILICO_SPECS[gene]
    return PEJAVER_GENERIC_INSILICO


__all__ = [
    "FrequencySpec",
    "GENERIC_SPEC",
    "VCEP_SPECS",
    "GRPMAX_AN_FLOOR",
    "frequency_spec",
    "InSilicoSpec",
    "PEJAVER_GENERIC_INSILICO",
    "VCEP_INSILICO_SPECS",
    "insilico_spec",
]

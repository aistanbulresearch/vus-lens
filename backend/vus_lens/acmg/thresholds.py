"""Cited ACMG frequency thresholds — general (non-gene-specific) defaults.

These are load-bearing scientific choices, so they live in one place, are
documented with their source, and are never tuned to a specific variant.
Gene/disease-specific values (e.g. ClinGen VCEP thresholds) would override these
where available; absent that, these documented defaults apply.
"""

from __future__ import annotations

# BA1 (benign standalone): grpmax AF above this is standalone benign evidence.
BA1_AF = 0.05
# BS1 (benign strong): grpmax AF above this (but <= BA1) is strong benign
# evidence. 1% is a general default; a gene/disease-specific value is preferred.
BS1_AF = 0.01
# PM2 (rare/absent): grpmax AF below this, or absent from gnomAD, supports PM2.
PM2_AF = 1e-4
# grpmax adequacy floor: an ancestry's AF only counts toward grpmax if its
# allele number is at least this. Prevents a tiny, noisy sample from inflating
# grpmax. Ties into the Day-3 ancestry-confidence auditor.
GRPMAX_AN_FLOOR = 2000

CITATION_BA1 = "ACMG-AMP 2015 (Richards et al.); ClinGen SVI — BA1 at MAF > 5%"
CITATION_BS1 = "ACMG-AMP 2015 BS1; general 1% default (gene/disease-specific preferred)"
CITATION_PM2 = "ACMG-AMP 2015 PM2; ClinGen SVI 2020 PM2_Supporting (absent/ultra-rare)"

__all__ = [
    "BA1_AF",
    "BS1_AF",
    "PM2_AF",
    "GRPMAX_AN_FLOOR",
    "CITATION_BA1",
    "CITATION_BS1",
    "CITATION_PM2",
]

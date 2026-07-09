"""ACMG criterion identifiers and evidence strengths."""

from __future__ import annotations

from enum import Enum


class ACMGCriterion(str, Enum):
    """The subset of ACMG-AMP criteria this tool assigns deterministically."""

    # Benign
    BA1 = "BA1"  # standalone — too common
    BS1 = "BS1"  # strong — more common than expected for the disorder
    BP4 = "BP4"  # supporting — in-silico predicts benign
    # Pathogenic
    PM2 = "PM2"  # rare/absent in population databases
    PP3 = "PP3"  # supporting — in-silico predicts damaging


class EvidenceStrength(str, Enum):
    STANDALONE = "standalone"
    VERY_STRONG = "very_strong"
    STRONG = "strong"
    MODERATE = "moderate"
    SUPPORTING = "supporting"


__all__ = ["ACMGCriterion", "EvidenceStrength"]

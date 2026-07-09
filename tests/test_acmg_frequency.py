"""Tests for deterministic ACMG frequency criteria (PM2 / BS1 / BA1).

Thresholds are scientifically load-bearing, so they are pinned here, not tuned.
The gnomAD input is constructed as a real SourceResult (not a mock).
"""

from __future__ import annotations

from vus_lens.acmg.criteria import ACMGCriterion
from vus_lens.acmg.frequency import assess_frequency
from vus_lens.models.evidence import SourceResult


def _gnomad(exome_pops, genome_pops=None):
    """Build a gnomAD-shaped SourceResult.ok from {pop: (an, ac)} dicts."""

    def sample(pops):
        if pops is None:
            return None
        an = sum(a for a, _ in pops.values())
        ac = sum(c for _, c in pops.values())
        return {
            "an": an,
            "ac": ac,
            "af": (ac / an if an else 0.0),
            "populations": {p: {"an": a, "ac": c} for p, (a, c) in pops.items()},
        }

    data = {"variant_id": "test", "exome": sample(exome_pops), "genome": sample(genome_pops)}
    return SourceResult.ok("gnomAD v4", data)


def test_common_variant_gets_ba1():
    # nfe AF = 10% (well above the 5% BA1 threshold)
    result = assess_frequency(_gnomad({"nfe": (100_000, 10_000)}))
    assert result.criterion is ACMGCriterion.BA1
    assert result.applied is True
    assert result.grpmax_af == 0.10
    assert result.data_available is True


def test_moderately_common_variant_gets_bs1():
    # grpmax AF = 2% (above BS1 1%, below BA1 5%)
    result = assess_frequency(_gnomad({"nfe": (100_000, 2_000)}))
    assert result.criterion is ACMGCriterion.BS1
    assert result.applied is True


def test_rare_variant_gets_pm2():
    # grpmax AF = 2e-5 (below PM2 1e-4)
    result = assess_frequency(_gnomad({"nfe": (100_000, 2)}))
    assert result.criterion is ACMGCriterion.PM2
    assert result.applied is True


def test_intermediate_frequency_gets_no_criterion():
    # grpmax AF = 0.5% (between PM2 1e-4 and BS1 1%) -> no frequency criterion
    result = assess_frequency(_gnomad({"nfe": (100_000, 500)}))
    assert result.criterion is None
    assert result.applied is False


def test_absent_from_gnomad_supports_pm2():
    # gnomAD reached, no record -> absent -> PM2 (not benign)
    result = assess_frequency(SourceResult.empty("gnomAD v4", message="not in gnomAD"))
    assert result.criterion is ACMGCriterion.PM2
    assert result.applied is True
    assert result.data_available is True
    assert result.grpmax_af == 0.0


def test_gnomad_unavailable_is_fail_loud_not_pm2():
    # gnomAD unreachable -> evidence UNAVAILABLE, never treated as absent/benign
    result = assess_frequency(SourceResult.error("gnomAD v4", message="HTTP 503"))
    assert result.criterion is None
    assert result.applied is False
    assert result.data_available is False
    assert "unavailable" in result.reason.lower()


def test_grpmax_ignores_tiny_ancestry_sample():
    # nfe looks common (AF 0.5) but AN=100 < floor -> ignored; afr is the
    # adequately-sampled group and is rare -> PM2, not BA1 off the noisy nfe.
    result = assess_frequency(_gnomad({"nfe": (100, 50), "afr": (50_000, 1)}))
    assert result.grpmax_pop == "afr"
    assert result.criterion is ACMGCriterion.PM2

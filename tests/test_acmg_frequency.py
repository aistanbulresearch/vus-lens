"""Tests for deterministic ACMG frequency criteria (PM2 / BS1 / BA1).

Thresholds are scientifically load-bearing, so they are pinned here, not tuned.
Per the ClinGen VCEP specs: BA1/BS1 use the **grpmax filtering AF (faf95)**;
PM2 uses the **raw grpmax AF**. Gene-specific VCEP thresholds apply to ATM and
PALB2; every other gene falls back to labeled generic SVI defaults.
"""

from __future__ import annotations

from vus_lens.acmg.criteria import ACMGCriterion
from vus_lens.acmg.frequency import assess_frequency
from vus_lens.models.evidence import SourceResult


def _gnomad(exome_pops, genome_pops=None, exome_faf=None, genome_faf=None):
    """gnomAD-shaped SourceResult.ok from {pop: (an, ac)} dicts.

    faf95_popmax defaults to the sample's raw grpmax AF unless given explicitly
    (real gnomAD faf95 down-weights small samples; tests set it directly).
    """

    def sample(pops, faf):
        if pops is None:
            return None
        an = sum(a for a, _ in pops.values())
        ac = sum(c for _, c in pops.values())
        raw_grpmax = max((c / a if a else 0.0) for a, c in pops.values())
        return {
            "an": an, "ac": ac, "af": (ac / an if an else 0.0),
            "faf95_popmax": raw_grpmax if faf is None else faf,
            "faf95_pop": None,
            "populations": {p: {"an": a, "ac": c} for p, (a, c) in pops.items()},
        }

    return SourceResult.ok(
        "gnomAD v4",
        {"variant_id": "t", "exome": sample(exome_pops, exome_faf), "genome": sample(genome_pops, genome_faf)},
    )


# --- generic ladder --------------------------------------------------------
def test_common_variant_gets_ba1_generic():
    r = assess_frequency(_gnomad({"nfe": (100_000, 10_000)}))  # faf 0.10
    assert r.criterion is ACMGCriterion.BA1
    assert r.spec_source == "generic"
    assert r.data_available is True


def test_moderately_common_variant_gets_bs1_generic():
    r = assess_frequency(_gnomad({"nfe": (100_000, 2_000)}))  # faf 0.02
    assert r.criterion is ACMGCriterion.BS1


def test_rare_variant_gets_pm2_generic():
    r = assess_frequency(_gnomad({"nfe": (100_000, 2)}))  # raw 2e-5
    assert r.criterion is ACMGCriterion.PM2


def test_intermediate_frequency_gets_no_criterion():
    r = assess_frequency(_gnomad({"nfe": (100_000, 500)}))  # 0.5%
    assert r.criterion is None
    assert r.applied is False


# --- fail loud -------------------------------------------------------------
def test_absent_from_gnomad_supports_pm2():
    r = assess_frequency(SourceResult.empty("gnomAD v4", message="not in gnomAD"))
    assert r.criterion is ACMGCriterion.PM2
    assert r.data_available is True
    assert r.grpmax_af == 0.0


def test_gnomad_unavailable_is_fail_loud_not_pm2():
    r = assess_frequency(SourceResult.error("gnomAD v4", message="HTTP 503"))
    assert r.criterion is None
    assert r.data_available is False
    assert "unavailable" in r.reason.lower()


# --- metric correctness ----------------------------------------------------
def test_ba1_bs1_use_filtering_af_not_raw():
    # raw grpmax 0.02 (would be BS1 on raw) but filtering AF only 0.005 -> no BS1
    r = assess_frequency(_gnomad({"nfe": (100_000, 2_000)}, exome_faf=0.005))
    assert r.criterion is None


def test_pm2_uses_raw_grpmax_with_adequacy_floor():
    # nfe common but AN=100 < floor -> ignored; afr adequately sampled & rare -> PM2
    r = assess_frequency(_gnomad({"nfe": (100, 50), "afr": (50_000, 1)}, exome_faf=2e-5))
    assert r.criterion is ACMGCriterion.PM2
    assert r.grpmax_pop == "afr"


# --- gene-specific VCEP overrides (the point of this change) ---------------
def test_atm_vcep_pm2_is_stricter_than_generic():
    # raw grpmax 5e-5: generic PM2 (< 1e-4) fires, but ATM PM2 (<= 1e-5) does NOT
    g = _gnomad({"nfe": (100_000, 5)})  # raw 5e-5, faf 5e-5
    assert assess_frequency(g, gene="ATM").criterion is None
    assert assess_frequency(g, gene=None).criterion is ACMGCriterion.PM2


def test_palb2_vcep_bs1_is_stricter_than_generic():
    # filtering AF 5e-4: PALB2 BS1 (> 1e-4) fires; generic BS1 (> 1e-2) does not
    g = _gnomad({"nfe": (100_000, 50)}, exome_faf=5e-4)  # faf 5e-4
    assert assess_frequency(g, gene="PALB2").criterion is ACMGCriterion.BS1
    assert assess_frequency(g, gene=None).criterion is None


def test_spec_provenance_labels_vcep_vs_generic():
    g = _gnomad({"nfe": (100_000, 5)})
    atm = assess_frequency(g, gene="ATM")
    assert atm.spec_source == "VCEP"
    assert "GN020" in atm.spec_label
    other = assess_frequency(g, gene="SOMEGENE")
    assert other.spec_source == "generic"
    assert "not gene-specific" in other.spec_label.lower()

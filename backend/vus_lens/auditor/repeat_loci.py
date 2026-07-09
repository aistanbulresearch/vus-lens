"""Curated, source-cited repeat-expansion locus table (build brief trigger 6.2).

Built from scratch, one citation per row, no recurrence percentages without a
verifiable source. Short-read WES cannot reliably size these tandem repeats, so
a normal-range read does NOT exclude the disorder — trigger 6.2 fires on any
variant whose gene is here, regardless of the computed class.

This is a **declared subset** (like the Turkish Variome index): it currently
covers the demo-relevant loci, verified this build; it is extended only with
additional cited rows, never guessed ones.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepeatLocus:
    gene: str
    disorder: str
    motif: str
    chrom: str
    inheritance: str
    normal_max: int  # upper bound of the normal repeat count
    pathogenic_min: int  # lower bound of the (full-penetrance) pathogenic count
    citation: str


# Ranges are the GeneReviews consensus values; exact intermediate/reduced-
# penetrance bands are described in the cited GeneReviews chapters.
REPEAT_LOCI: dict[str, RepeatLocus] = {
    "ATN1": RepeatLocus(
        gene="ATN1",
        disorder="Dentatorubral-pallidoluysian atrophy (DRPLA)",
        motif="CAG",
        chrom="12",
        inheritance="autosomal dominant",
        normal_max=35,
        pathogenic_min=48,
        citation="GeneReviews NBK1491 (DRPLA): normal ~6-35, pathogenic ~48-93 CAG",
    ),
    "HTT": RepeatLocus(
        gene="HTT",
        disorder="Huntington disease",
        motif="CAG",
        chrom="4",
        inheritance="autosomal dominant",
        normal_max=26,
        pathogenic_min=40,
        citation="GeneReviews NBK1305 (Huntington disease): normal <=26, "
        "reduced-penetrance 36-39, full-penetrance >=40 CAG",
    ),
}


def repeat_locus(gene: str | None) -> RepeatLocus | None:
    """Return the repeat-expansion locus for a gene, or None if not a known STR locus."""
    if not gene:
        return None
    return REPEAT_LOCI.get(gene)


__all__ = ["RepeatLocus", "REPEAT_LOCI", "repeat_locus"]

"""The variant a clinician asks about.

Kept deliberately permissive: the user's raw query is preserved verbatim, and
each client uses whichever identifier it needs (rsID for MyVariant, a
chrom-pos-ref-alt id for gnomAD, a gene symbol for ClinicalTrials.gov). Fields
resolved from one source (e.g. hg38 coordinates from MyVariant) can be filled
in and passed to the next.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Assembly(str, Enum):
    """Genome assembly. gnomAD v4 and AlphaMissense are GRCh38 / hg38."""

    HG38 = "hg38"
    HG19 = "hg19"


class VariantQuery(BaseModel):
    """A variant lookup request.

    At minimum ``raw`` (what the user typed) is required. Structured fields are
    optional and get populated as sources resolve them.
    """

    raw: str
    gene: str | None = None
    rsid: str | None = None
    hgvs: str | None = None
    chrom: str | None = None
    pos: int | None = None
    ref: str | None = None
    alt: str | None = None
    assembly: Assembly = Assembly.HG38

    def gnomad_variant_id(self) -> str | None:
        """gnomAD variant id ``chrom-pos-ref-alt`` (no 'chr'), if coords are known."""
        if self.chrom and self.pos and self.ref and self.alt:
            chrom = self.chrom.removeprefix("chr")
            return f"{chrom}-{self.pos}-{self.ref}-{self.alt}"
        return None


__all__ = ["Assembly", "VariantQuery"]

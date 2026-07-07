"""Public-data clients.

One module per source. Every client returns a typed ``SourceResult`` with an
explicit status, so a failed or empty source can never be silently mistaken for
"no evidence / benign" (build brief Sections 0 and 6.3).
"""

from .base import AsyncSourceClient, HttpResult
from .clinicaltrials import ClinicalTrialsClient
from .gnomad import ANCESTRY_LABELS, GnomadClient, ancestry_allele_number
from .myvariant import MyVariantClient
from .turkish_variome import TurkishVariomeClient

__all__ = [
    "AsyncSourceClient",
    "HttpResult",
    "MyVariantClient",
    "GnomadClient",
    "ancestry_allele_number",
    "ANCESTRY_LABELS",
    "ClinicalTrialsClient",
    "TurkishVariomeClient",
]

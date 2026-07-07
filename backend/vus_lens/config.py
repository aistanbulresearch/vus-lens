"""Central, immutable configuration for the VUS Confidence Auditor.

Every external endpoint, timeout, and the demo-gene boundary lives here so the
rest of the codebase never hard-codes a URL or a magic number. All endpoints
are the public, no-key sources verified in the build brief (Section 5), so no
secret ever enters this repository.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Immutable application settings.

    Frozen so no code path can mutate a URL or threshold at runtime.
    """

    # --- Public data source endpoints (all no-key, open access) ---
    myvariant_base_url: str = "https://myvariant.info/v1"
    gnomad_graphql_url: str = "https://gnomad.broadinstitute.org/api"
    clinicaltrials_base_url: str = "https://clinicaltrials.gov/api/v2"

    # gnomAD dataset version — the ancestry breakdown incl. `mid`
    # (Middle Eastern) lives in v4. This is the disparity evidence (Section 6.1).
    gnomad_dataset: str = "gnomad_r4"

    # --- Per-source timeouts (seconds). Fail loud rather than hang. ---
    myvariant_timeout: float = 10.0
    gnomad_timeout: float = 20.0
    clinicaltrials_timeout: float = 10.0

    # --- Demo-gene boundary (Section 5) ---
    # The Turkish Variome subset is restricted to exactly these genes. The
    # boundary is declared honestly and never silently exceeded.
    demo_genes: tuple[str, ...] = ("ATN1", "HTT", "ATM", "PALB2")

    # Optional contact email sent to public APIs as etiquette. Never a secret;
    # left None unless the operator chooses to set it.
    contact_email: str | None = None


# Single shared instance imported across the app.
SETTINGS = Settings()

__all__ = ["Settings", "SETTINGS"]

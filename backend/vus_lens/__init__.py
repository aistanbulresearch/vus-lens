"""VUS Confidence Auditor — clinical-genetics decision support.

Aggregates evidence from open public sources, maps it to ACMG criteria
deterministically, and audits the reliability of its own evidence for a
specific patient's ancestry.

Decision support only — never a classifier, never a diagnosis. The final
interpretation is always the clinician's.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]

"""The Confidence Auditor — one mechanism, three triggers.

Inspects the deterministic evidence and raises visible, source-anchored warnings
(build brief Section 6). Each trigger fires from real data, never from a
condition hard-coded to a demo variant. The auditor never changes the class; it
surfaces where the evidence is unreliable for this specific patient.
"""

__all__: list[str] = []

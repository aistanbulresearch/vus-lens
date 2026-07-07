"""Public-data clients.

One module per source. Every client returns a typed ``SourceResult`` with an
explicit status, so a failed or empty source can never be silently mistaken for
"no evidence / benign" (build brief Sections 0 and 6.3).
"""

from .base import AsyncSourceClient, HttpResult

__all__ = ["AsyncSourceClient", "HttpResult"]

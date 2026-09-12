"""GO AI: GO-owned multi-model orchestration layer.

Provider brands are intentionally hidden from consumer-facing responses.
"""

from .service import go_ai_service

__all__ = ["go_ai_service"]

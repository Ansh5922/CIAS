"""
CIAS Preprocessing Deduplication Sub-module.

Exports:
    - DuplicateDetector
    - DuplicateResult
"""

from app.preprocessing.deduplication.duplicate_detector import DuplicateDetector, DuplicateResult

__all__ = [
    "DuplicateDetector",
    "DuplicateResult",
]

"""
Legacy compatibility wrapper.

The project now uses the class-diagram-aligned raw/processed/serving packages.
`Article` is kept as an alias to `RawNews` for older imports.
"""

from app.raw.models import RawNews as Article

__all__ = ["Article"]

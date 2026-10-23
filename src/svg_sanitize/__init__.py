"""Build purely visual SVG output from untrusted SVG/XML."""

from .sanitizer import Limits, SVGValidationError, sanitize_svg

__all__ = ["Limits", "SVGValidationError", "sanitize_svg"]

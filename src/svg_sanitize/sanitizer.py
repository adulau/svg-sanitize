"""Strict, visual-only SVG sanitizer.

This is intentionally not a general-purpose SVG optimizer. It constructs a
new XML tree from a small whitelist. Unsupported elements, attributes, and
attribute values do not reach the result.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Literal

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
import tinycss2

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


class SVGValidationError(ValueError):
    """The input SVG is invalid, prohibited XML, or exceeds resource limits."""


@dataclass(frozen=True)
class Limits:
    max_input_bytes: int = 1_048_576
    max_output_bytes: int = 1_048_576
    max_nodes: int = 10_000
    max_depth: int = 64
    max_attributes_per_node: int = 64
    max_attribute_chars: int = 65_536
    max_text_chars: int = 100_000
    max_path_chars: int = 65_536
    max_marker_nodes: int = 128
    max_marker_references: int = 256


DEFAULT_LIMITS = Limits()

# Strict mode deliberately excludes: script, style, a, use, image, foreignObject, animate,
# set, filter, mask, clipPath, pattern, gradients, defs, metadata, etc.
CONTAINERS = frozenset({"svg", "g"})
SHAPES = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"})
TEXT_TAGS = frozenset({"text", "tspan"})
ALLOWED_TAGS = CONTAINERS | SHAPES | TEXT_TAGS
VISUAL_TAGS = ALLOWED_TAGS | {"defs", "marker"}
MARKER_PROPERTIES = frozenset({"marker-start", "marker-mid", "marker-end"})
MARKER_GEOMETRY = frozenset({
    "refX", "refY", "markerWidth", "markerHeight", "markerUnits", "orient",
    "viewBox", "preserveAspectRatio", "overflow",
})
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
LOCAL_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)
MARKER_URL_RE = re.compile(r'''url\(\s*(["']?)\#([A-Za-z_][A-Za-z0-9_.-]{0,127})\1\s*\)\Z''', re.IGNORECASE | re.ASCII)

PRESENTATION = frozenset({
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
    "stroke-opacity", "stroke-linecap", "stroke-linejoin",
    "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset",
    "opacity", "display", "visibility", "vector-effect",
    "font-family", "font-size", "font-style", "font-weight",
    "text-anchor", "dominant-baseline", "letter-spacing", "word-spacing",
    "shape-rendering", "text-rendering",
})

GEOMETRY = {
    "svg": frozenset({"x", "y", "width", "height", "viewBox", "preserveAspectRatio", "transform"}),
    "g": frozenset({"transform"}),
    "rect": frozenset({"x", "y", "width", "height", "rx", "ry", "transform"}),
    "circle": frozenset({"cx", "cy", "r", "transform"}),
    "ellipse": frozenset({"cx", "cy", "rx", "ry", "transform"}),
    "line": frozenset({"x1", "x2", "y1", "y2", "transform"}),
    "polyline": frozenset({"points", "transform"}),
    "polygon": frozenset({"points", "transform"}),
    "path": frozenset({"d", "transform"}),
    "text": frozenset({"x", "y", "dx", "dy", "transform"}),
    "tspan": frozenset({"x", "y", "dx", "dy", "rotate"}),
}

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
NUMBER_RE = re.compile(NUMBER)
LENGTH_RE = re.compile(rf"({NUMBER})(px|%)?\Z", re.ASCII)
COLOR_HEX_RE = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{1})?(?:[0-9a-fA-F]{2})?(?:[0-9a-fA-F]{2})?\Z")
COLOR_FUNC_RE = re.compile(r"(rgb|rgba)\(\s*([^()]*)\s*\)\Z", re.IGNORECASE)
PATH_TOKEN_RE = re.compile(rf"{NUMBER}|[MmLlHhVvCcSsQqTtAaZz]", re.ASCII)
TRANSFORM_RE = re.compile(
    r"\s*(matrix|translate|scale|rotate|skewX|skewY)\s*\(\s*([^()]*)\s*\)",
    re.IGNORECASE,
)
SAFE_SEPARATORS_RE = re.compile(r"[\s,]*\Z")
TEXT_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")

COLORS = frozenset({
    "none", "transparent", "black", "white", "red", "green", "blue",
    "yellow", "orange", "purple", "gray", "grey", "silver", "navy",
    "teal", "lime", "aqua", "fuchsia", "maroon", "olive", "pink",
    "brown", "cyan", "magenta", "gold", "indigo", "coral",
})
FONT_FAMILIES = {
    "arial": "Arial", "helvetica": "Helvetica", "verdana": "Verdana",
    "tahoma": "Tahoma", "georgia": "Georgia",
    "times new roman": "Times New Roman", "courier new": "Courier New",
    "serif": "serif", "sans-serif": "sans-serif", "monospace": "monospace",
    "system-ui": "system-ui",
}
VISUAL_FONTS = {
    **FONT_FAMILIES,
    "dejavu sans": "DejaVu Sans", "dejavu sans condensed": "DejaVu Sans Condensed",
    "dejavu serif": "DejaVu Serif", "dejavu sans mono": "DejaVu Sans Mono",
    "liberation sans": "Liberation Sans", "liberation serif": "Liberation Serif",
    "liberation mono": "Liberation Mono",
}
ATTRIBUTE_OPTIONS = {
    "fill-rule": {"evenodd", "nonzero"},
    "stroke-linecap": {"butt", "round", "square"},
    "stroke-linejoin": {"miter", "round", "bevel"},
    "display": {"inline", "none"},
    "visibility": {"visible", "hidden", "collapse"},
    "vector-effect": {"none", "non-scaling-stroke"},
    "font-style": {"normal", "italic", "oblique"},
    "text-anchor": {"start", "middle", "end"},
    "dominant-baseline": {"auto", "alphabetic", "middle", "central", "hanging", "text-before-edge", "text-after-edge"},
    "shape-rendering": {"auto", "optimizeSpeed", "crispEdges", "geometricPrecision"},
    "text-rendering": {"auto", "optimizeSpeed", "optimizeLegibility", "geometricPrecision"},
}
COORD_ATTRS = frozenset({"x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "dx", "dy"})
NONNEG_LENGTH_ATTRS = frozenset({"width", "height", "r", "rx", "ry", "stroke-width", "font-size"})
OPACITY_ATTRS = frozenset({"opacity", "fill-opacity", "stroke-opacity"})
OTHER_LENGTH_ATTRS = frozenset({"stroke-dashoffset", "letter-spacing", "word-spacing"})


def _number(value: str, *, minimum: float = -10_000_000, maximum: float = 10_000_000) -> bool:
    if len(value) > 40 or not NUMBER_RE.fullmatch(value):
        return False
    number = float(value)
    return math.isfinite(number) and minimum <= number <= maximum


def _length(value: str, *, minimum: float = -10_000_000) -> bool:
    match = LENGTH_RE.fullmatch(value)
    return bool(match and _number(match.group(1), minimum=minimum))


def _number_list(value: str, *, limit: int, minimum: float = -10_000_000) -> list[str] | None:
    """Parse whitespace/comma-separated finite numbers, never arbitrary CSS."""
    values: list[str] = []
    previous_end = 0
    for match in NUMBER_RE.finditer(value):
        between = value[previous_end:match.start()]
        if not SAFE_SEPARATORS_RE.fullmatch(between):
            return None
        # Adjacent numbers are allowed only if a sign starts the next one.
        if previous_end == match.start() and values and not match.group().startswith(("+", "-")):
            return None
        if not _number(match.group(), minimum=minimum):
            return None
        values.append(match.group())
        if len(values) > limit:
            return None
        previous_end = match.end()
    if not SAFE_SEPARATORS_RE.fullmatch(value[previous_end:]):
        return None
    return values or None


def _color(value: str) -> bool:
    if value.lower() in COLORS:
        return True
    if COLOR_HEX_RE.fullmatch(value) and len(value) in {4, 5, 7, 9}:
        return True
    match = COLOR_FUNC_RE.fullmatch(value)
    if not match:
        return False
    mode, body = match.groups()
    parts = [part.strip() for part in body.split(",")]
    if len(parts) != (3 if mode.lower() == "rgb" else 4):
        return False
    for component in parts[:3]:
        if component.endswith("%"):
            if not _number(component[:-1], minimum=0, maximum=100):
                return False
        elif not _number(component, minimum=0, maximum=255):
            return False
    if len(parts) == 4 and not _number(parts[3], minimum=0, maximum=1):
        return False
    return True


def _path(value: str, max_chars: int) -> bool:
    if not value or len(value) > max_chars:
        return False
    offset = 0
    have_move = False
    tokens = 0
    for match in PATH_TOKEN_RE.finditer(value):
        if not SAFE_SEPARATORS_RE.fullmatch(value[offset:match.start()]):
            return False
        token = match.group()
        if token.isalpha():
            if not have_move:
                if token not in "Mm":
                    return False
                have_move = True
        elif not _number(token):
            return False
        tokens += 1
        if tokens > 20_000:
            return False
        offset = match.end()
    return have_move and SAFE_SEPARATORS_RE.fullmatch(value[offset:]) is not None


def _transform(value: str) -> bool:
    if not value or len(value) > 512:
        return False
    counts = {"matrix": {6}, "translate": {1, 2}, "scale": {1, 2}, "rotate": {1, 3}, "skewx": {1}, "skewy": {1}}
    offset = 0
    functions = 0
    while offset < len(value):
        match = TRANSFORM_RE.match(value, offset)
        if not match:
            return False
        parts = _number_list(match.group(2), limit=6)
        if parts is None or len(parts) not in counts[match.group(1).lower()]:
            return False
        functions += 1
        if functions > 16:
            return False
        offset = match.end()
        if not value[offset:].strip():
            return True
    return functions > 0


def _viewbox(value: str) -> bool:
    values = _number_list(value, limit=4)
    return bool(values and len(values) == 4 and float(values[2]) > 0 and float(values[3]) > 0)


def _aspect_ratio(value: str) -> bool:
    parts = value.split()
    if parts and parts[0] == "defer":
        parts = parts[1:]
    return (len(parts) == 1 and parts[0] == "none") or (
        len(parts) in (1, 2)
        and parts[0] in {
            "xMinYMin", "xMidYMin", "xMaxYMin",
            "xMinYMid", "xMidYMid", "xMaxYMid",
            "xMinYMax", "xMidYMax", "xMaxYMax",
        }
        and (len(parts) == 1 or parts[1] in {"meet", "slice"})
    )


def _attribute(name: str, value: str, limits: Limits) -> str | None:
    """Return a safe (possibly normalized) attribute value, or None."""
    if not value or len(value) > limits.max_attribute_chars:
        return None
    value = value.strip()
    if not value or TEXT_CONTROL_RE.search(value):
        return None

    if name in {"fill", "stroke"}:
        return value if _color(value) else None
    if name in OPACITY_ATTRS:
        return value if _number(value, minimum=0, maximum=1) else None
    if name in COORD_ATTRS | OTHER_LENGTH_ATTRS:
        return value if _length(value) else None
    if name in NONNEG_LENGTH_ATTRS:
        return value if _length(value, minimum=0) else None
    if name == "stroke-miterlimit":
        return value if _number(value, minimum=1) else None
    if name == "stroke-dasharray":
        if value == "none":
            return value
        # Dasharray supports numbers and a very limited unit syntax here.
        values = _number_list(value, limit=64, minimum=0)
        return value if values else None
    if name in ATTRIBUTE_OPTIONS:
        return value if value in ATTRIBUTE_OPTIONS[name] else None
    if name == "font-weight":
        if value in {"normal", "bold", "bolder", "lighter"}:
            return value
        return value if value in {str(n) for n in range(100, 1000, 100)} else None
    if name == "font-family":
        parts = [part.strip().strip("\"'").lower() for part in value.split(",")]
        if not (1 <= len(parts) <= 5) or any(part not in FONT_FAMILIES for part in parts):
            return None
        return ", ".join(FONT_FAMILIES[part] for part in parts)
    if name == "viewBox":
        return value if _viewbox(value) else None
    if name == "preserveAspectRatio":
        return value if _aspect_ratio(value) else None
    if name == "points":
        numbers = _number_list(value, limit=20000)
        return value if numbers is not None and len(numbers) >= 2 and len(numbers) % 2 == 0 else None
    if name == "d":
        return value if _path(value, limits.max_path_chars) else None
    if name == "transform":
        return value if _transform(value) else None
    if name == "rotate":  # tspan rotation, one numeric angle only
        return value if _number(value) else None
    return None


def _tag_parts(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        namespace, name = tag[1:].split("}", 1)
        return namespace, name
    return None, tag


def _clean_text(value: str | None) -> str | None:
    return TEXT_CONTROL_RE.sub("", value) if value is not None else None


def _check_complexity(root: ET.Element, limits: Limits) -> None:
    stack = [(root, 1)]
    nodes = text_chars = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_nodes or depth > limits.max_depth:
            raise SVGValidationError("SVG exceeds element-count or nesting-depth limits")
        if len(node.attrib) > limits.max_attributes_per_node:
            raise SVGValidationError("SVG exceeds per-element attribute count limit")
        if any(len(key) > 256 or len(value) > limits.max_attribute_chars for key, value in node.attrib.items()):
            raise SVGValidationError("SVG has oversized attributes")
        text_chars += len(node.text or "") + len(node.tail or "")
        if text_chars > limits.max_text_chars:
            raise SVGValidationError("SVG contains too much text")
        stack.extend((child, depth + 1) for child in node)


def _can_contain(parent: str, child: str, visual: bool = False, resource: bool = False) -> bool:
    if visual:
        if parent == "defs":
            return child == "marker"
        if parent == "marker":
            return child in ({"g"} | SHAPES | {"text"})
        if parent in CONTAINERS and child == "defs":
            return not resource
    if parent in CONTAINERS:
        return child in (CONTAINERS | SHAPES | {"text"})
    if parent in TEXT_TAGS:
        return child == "tspan"
    return False


def _marker_ids(root: ET.Element, namespace: str | None) -> dict[str, str]:
    """Register only reachable markers with unambiguous, bounded local IDs."""
    counts: dict[str, int] = {}
    for node in root.iter():
        identifier = node.get("id", "")
        counts[identifier] = counts.get(identifier, 0) + 1
    markers: dict[str, str] = {}
    stack = [(root, "svg", False)]
    while stack:
        node, tag, resource = stack.pop()
        if tag == "marker":
            identifier = node.get("id", "")
            if counts[identifier] == 1 and LOCAL_ID_RE.fullmatch(identifier):
                markers[identifier] = f"svg-sanitize-marker-{len(markers)}"
        children = []
        for child in node:
            child_ns, child_tag = _tag_parts(child.tag)
            if (child_ns == namespace and child_tag in VISUAL_TAGS
                    and _can_contain(tag, child_tag, True, resource)):
                children.append((child, child_tag, resource or child_tag == "defs"))
        stack.extend(reversed(children))
    return markers


def _visual_attribute(
    name: str, value: str, limits: Limits, markers: dict[str, str], resource: bool,
) -> str | None:
    if not value or len(value) > limits.max_attribute_chars or TEXT_CONTROL_RE.search(value):
        return None
    value = value.strip()
    if name in MARKER_PROPERTIES:
        if value == "none":
            return value
        match = MARKER_URL_RE.fullmatch(value)
        if not resource and match and match.group(2) in markers:
            return f"url(#{markers[match.group(2)]})"
        return None
    if name == "font-family":
        parts = [part.strip().strip("\"'").lower() for part in value.split(",")]
        if not (1 <= len(parts) <= 5) or any(part not in VISUAL_FONTS for part in parts):
            return None
        return ", ".join(VISUAL_FONTS[part] for part in parts)
    if name == "font-stretch":
        return value if value in {"normal", "condensed", "semi-condensed", "expanded", "semi-expanded"} else None
    if name == "overflow":
        return value if value in {"visible", "hidden"} else None
    if name == "markerUnits":
        return value if value in {"strokeWidth", "userSpaceOnUse"} else None
    if name == "orient":
        return value if value in {"auto", "auto-start-reverse"} or _number(value) else None
    length_name = name
    if name in {"refX", "refY"}:
        length_name = "x"
    elif name in {"markerWidth", "markerHeight"}:
        length_name = "width"
    safe = _attribute(length_name, value, limits)
    if safe is not None:
        return safe
    # Physical/font-relative units remain finite numbers, never CSS expressions.
    if length_name in (COORD_ATTRS | OTHER_LENGTH_ATTRS | NONNEG_LENGTH_ATTRS):
        match = re.fullmatch(rf"({NUMBER})(pt|pc|mm|cm|in|em|ex)", value, re.ASCII)
        minimum = 0 if length_name in NONNEG_LENGTH_ATTRS else -10_000_000
        if match and _number(match.group(1), minimum=minimum):
            return value
    return None


def _style_declarations(style: str):
    """Parse inline declarations; never emit CSS or serialize nested expressions."""
    flat = {"ident", "number", "dimension", "percentage", "whitespace", "literal", "hash", "string", "url"}
    for declaration in tinycss2.parse_declaration_list(style, skip_comments=True, skip_whitespace=True):
        if declaration.type != "declaration":
            continue
        tokens = [token for token in declaration.value if token.type != "comment"]
        valid = True
        for token in tokens:
            if token.type == "function":
                if (token.lower_name not in {"rgb", "rgba", "url"}
                        or any(part.type not in flat - {"url"} for part in token.arguments)):
                    valid = False
                    break
            elif token.type not in flat:
                valid = False
                break
        if valid:
            yield declaration.lower_name, tinycss2.serialize(tokens).strip(), declaration.important


def _copy_attributes(
    original: ET.Element, clean: ET.Element, tag: str, limits: Limits,
    visual: bool, markers: dict[str, str], resource: bool,
) -> None:
    presentation = PRESENTATION | (MARKER_PROPERTIES | {"font-stretch"} if visual else set())
    geometry = MARKER_GEOMETRY if tag == "marker" else GEOMETRY.get(tag, frozenset())
    if tag == "marker":
        clean.set("id", markers[original.attrib["id"]])
        # Block references inherited from an ancestor svg/g as well as explicit
        # references in the definition, so marker contents cannot recurse.
        for key in ("marker-start", "marker-mid", "marker-end"):
            clean.set(key, "none")
    for key, value in original.attrib.items():
        if visual and key == XML_SPACE and value in {"default", "preserve"}:
            clean.set(key, value)
            continue
        if key.startswith("{") or ":" in key or (key not in presentation and key not in geometry):
            continue
        safe = (_visual_attribute(key, value, limits, markers, resource) if visual
                else _attribute(key, value, limits))
        if safe is not None:
            clean.set(key, safe)
    if visual:
        important = set()
        for key, value, priority in _style_declarations(original.get("style", "")):
            if key not in presentation and not (tag == "marker" and key == "overflow"):
                continue
            safe = _visual_attribute(key, value, limits, markers, resource)
            if safe is not None and (priority or key not in important):
                clean.set(key, safe)
                if priority:
                    important.add(key)


def sanitize_svg(
    data: str | bytes, *, limits: Limits = DEFAULT_LIMITS,
    mode: Literal["strict", "visual"] = "strict",
) -> str:
    """Return a rebuilt, self-contained, passive SVG document.

    Strict mode (default) retains only the original minimal primitive subset.
    Visual mode converts validated inline presentation CSS to attributes and
    allows bounded, sanitized local markers, additional local fonts and units.
    Neither mode retains scripts, events, CSS stylesheets, external resources,
    embedded images, links, animation, foreign elements, or XML entities.
    Unsupported subtrees are removed; arbitrary SVG rendering is not preserved.
    Malformed XML, DTDs, entities, wrong roots, and oversized inputs are rejected.

    This is defense-in-depth, not a browser isolation boundary. Prefer rendering
    sanitized output in an <img> with a restrictive CSP and untrusted origin.
    """
    if not isinstance(data, (str, bytes)):
        raise TypeError("data must be str or bytes")
    if mode not in ("strict", "visual"):
        raise ValueError("mode must be 'strict' or 'visual'")
    if len(data if isinstance(data, bytes) else data.encode("utf-8")) > limits.max_input_bytes:
        raise SVGValidationError("SVG input exceeds byte limit")

    try:
        root = SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ET.ParseError, DefusedXmlException, UnicodeError) as exc:
        raise SVGValidationError("Malformed or forbidden SVG/XML document") from exc

    namespace, name = _tag_parts(root.tag)
    if name != "svg" or namespace not in {None, SVG_NS}:
        raise SVGValidationError("Input must have an SVG root element")

    _check_complexity(root, limits)
    visual = mode == "visual"
    markers = _marker_ids(root, namespace) if visual else {}
    allowed = VISUAL_TAGS if visual else ALLOWED_TAGS
    clean_root = ET.Element(f"{{{SVG_NS}}}svg")
    stack = [(root, clean_root, "svg", False)]
    marker_references = 0
    while stack:
        original, clean, current_tag, resource = stack.pop()
        _copy_attributes(original, clean, current_tag, limits, visual, markers, resource)
        marker_references += sum(clean.get(key, "").startswith("url(") for key in MARKER_PROPERTIES)
        if marker_references > limits.max_marker_references:
            raise SVGValidationError("SVG exceeds marker reference limit")

        if current_tag in TEXT_TAGS:
            clean.text = _clean_text(original.text)

        children_to_visit = []
        for child in original:
            child_ns, child_name = _tag_parts(child.tag)
            if (child_ns == namespace and child_name in allowed
                    and _can_contain(current_tag, child_name, visual, resource)
                    and (child_name != "marker" or child.get("id") in markers)):
                child_out = ET.SubElement(clean, f"{{{SVG_NS}}}{child_name}")
                children_to_visit.append((child, child_out, child_name, resource or child_name == "defs"))

            # 'tail' belongs to the parent text flow, not to a removed element.
            # Preserve that harmless visible text; never copy removed subtree text.
            if current_tag in TEXT_TAGS and child.tail:
                tail = _clean_text(child.tail)
                if len(clean):
                    previous = clean[-1]
                    previous.tail = (previous.tail or "") + (tail or "")
                else:
                    clean.text = (clean.text or "") + (tail or "")

        stack.extend(reversed(children_to_visit))

    if visual:
        for node in clean_root.iter():
            if node.tag == f"{{{SVG_NS}}}marker" and sum(1 for _ in node.iter()) > limits.max_marker_nodes:
                raise SVGValidationError("SVG marker exceeds element-count limit")
            for child in list(node):
                if child.tag == f"{{{SVG_NS}}}defs" and not len(child):
                    node.remove(child)

    output = ET.tostring(clean_root, encoding="unicode", short_empty_elements=True)
    if len(output.encode("utf-8")) > limits.max_output_bytes:
        raise SVGValidationError("Sanitized SVG exceeds output byte limit")
    return output

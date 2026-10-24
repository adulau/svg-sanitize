from dataclasses import replace
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from svg_sanitize import Limits, SVGValidationError, sanitize_svg

SVG = "http://www.w3.org/2000/svg"
NS = {"svg": SVG}


def svg(body, attributes=""):
    return f'<svg xmlns="{SVG}" {attributes}>{body}</svg>'


def visual(body, attributes="", **kwargs):
    return ET.fromstring(sanitize_svg(svg(body, attributes), mode="visual", **kwargs))


def test_strict_is_still_the_default():
    source = svg('<rect width="10" height="5" style="fill:red;stroke:blue"/>')
    default = sanitize_svg(source)
    assert default == sanitize_svg(source, mode="strict")
    assert "fill=" not in default and "stroke=" not in default
    result = ET.fromstring(sanitize_svg(source, mode="visual"))[0]
    assert result.get("fill") == "red" and result.get("stroke") == "blue"


@pytest.mark.parametrize("mode", ["unsafe", "", None, 1, []])
def test_unknown_mode_is_rejected(mode):
    with pytest.raises(ValueError, match="mode must be"):
        sanitize_svg(svg(""), mode=mode)


def test_inline_cascade_preserves_important_and_validated_values():
    root = visual('''<rect fill="blue" width="10" height="5"
        style="fill:red; fill:rgb(12, 34, 56) !important; fill:green;
               stroke:/* comment */#abc; opacity:0.5; width:999; unknown:yes"/>''')
    assert root[0].attrib == {
        "fill": "rgb(12, 34, 56)", "width": "10", "height": "5",
        "stroke": "#abc", "opacity": "0.5",
    }


@pytest.mark.parametrize("declaration", [
    "fill:url(https://example.invalid/x.svg#paint)",
    "fill:expression(document.title='SVG_TEST')", "fill:var(--paint)",
    "fill:red;background:url(https://example.invalid/x)",
    "@import url(https://example.invalid/x.css)",
    "fill:url(data:image/svg+xml,SVG_TEST)",
    "fill:url(#not-a-paint-server)", "behavior:url(https://example.invalid/x.htc)",
    "font-family:'url(https://example.invalid/font.woff)'",
    "filter:url(https://example.invalid/x.svg#filter)",
])
def test_css_does_not_allow_active_or_external_content(declaration):
    source = svg(f'<rect width="10" height="5" style="{declaration}"/>')
    output = sanitize_svg(source, mode="visual")
    assert "style=" not in output
    assert "url(" not in output and "example.invalid" not in output
    assert "expression" not in output and "var(" not in output


def test_nested_css_functions_are_dropped_without_recursive_serialization():
    nested = "rgb(" * 4000 + "0" + ")" * 4000
    root = visual(f'<rect width="10" height="5" style="fill:{nested}"/>')
    assert root[0].attrib == {"width": "10", "height": "5"}


def test_local_fonts_units_and_text_spacing():
    root = visual('''<text xml:space="preserve" x="1cm" y="2em"
        style="font-family:'DejaVu Sans Condensed', sans-serif; font-size:12pt;
               font-stretch:condensed; stroke-width:0.5mm"> A  B </text>''')
    text = root[0]
    assert text.text == " A  B "
    assert text.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
    assert text.get("font-family") == "DejaVu Sans Condensed, sans-serif"
    assert text.get("font-size") == "12pt" and text.get("stroke-width") == "0.5mm"
    assert text.get("x") == "1cm" and text.get("y") == "2em"


MARKER = '''<defs><marker id="arrow" orient="auto" refX="0" refY="0"
    markerWidth="5" markerHeight="5" markerUnits="strokeWidth" viewBox="0 0 5 5"
    style="overflow:visible"><path d="M0 0 L5 2 L0 4 Z" fill="red"/></marker></defs>'''


@pytest.mark.parametrize("reference", ["url(#arrow)", "url('#arrow')", "url(&quot;#arrow&quot;)"])
def test_forward_local_marker_reference_is_rewritten(reference):
    source = svg(f'<path d="M0 0 L10 10" marker-end="{reference}"/>' + MARKER)
    output = sanitize_svg(source, mode="visual")
    root = ET.fromstring(output)
    marker = root.find(".//svg:marker", NS)
    assert marker is not None
    assert marker.get("id") == "svg-sanitize-marker-0"
    assert root[0].get("marker-end") == "url(#svg-sanitize-marker-0)"
    assert marker.get("overflow") == "visible"
    assert all(marker.get(key) == "none" for key in ("marker-start", "marker-mid", "marker-end"))
    assert sanitize_svg(output, mode="visual") == output


@pytest.mark.parametrize("reference", [
    "url(https://example.invalid/map.svg#arrow)", "url(//example.invalid/map.svg#arrow)",
    "url(data:image/svg+xml,SVG_TEST)", "url(#missing)", "javascript:SVG_TEST",
])
def test_invalid_marker_references_are_dropped(reference):
    root = visual(MARKER + f'<path d="M0 0 L1 1" marker-end="{reference}"/>')
    assert "marker-end" not in root[-1].attrib


def test_marker_contents_cannot_recurse_or_execute():
    marker = '''<defs><marker id="arrow" marker-end="url(#arrow)"
        style="marker-mid:url(#arrow)"><script>SVG_TEST</script>
        <foreignObject><text>SVG_TEST</text></foreignObject>
        <image href="https://example.invalid/x"/>
        <path d="M0 0 L1 1" onload="SVG_TEST" marker-start="url(#arrow)"/>
        <defs><marker id="nested"/></defs><use href="#arrow"/>
        </marker></defs>'''
    root = visual(marker, 'marker-mid="url(#arrow)"')
    definition = root.find(".//svg:marker", NS)
    assert definition is not None
    assert len(definition) == 1 and definition[0].tag == f"{{{SVG}}}path"
    assert definition[0].attrib == {"d": "M0 0 L1 1"}
    assert all(definition.get(key) == "none" for key in ("marker-start", "marker-mid", "marker-end"))
    assert "SVG_TEST" not in ET.tostring(root, encoding="unicode")


@pytest.mark.parametrize("extra", [MARKER, '<g id="arrow"/>'])
def test_ambiguous_duplicate_ids_disable_marker_references(extra):
    root = visual(MARKER + extra + '<path d="M0 0 L1 1" marker-end="url(#arrow)"/>')
    assert not root.findall(".//svg:marker", NS)
    assert "marker-end" not in root[-1].attrib


def test_hidden_or_foreign_marker_does_not_resolve():
    root = visual('<unknown>' + MARKER + '</unknown><path d="M0 0 L1 1" marker-end="url(#arrow)"/>')
    assert len(root) == 1 and "marker-end" not in root[0].attrib


def test_marker_complexity_and_reference_budgets():
    with pytest.raises(SVGValidationError, match="marker exceeds element-count"):
        visual(MARKER, limits=replace(Limits(), max_marker_nodes=1))
    root = visual(MARKER, limits=replace(Limits(), max_marker_nodes=2))
    assert root.find(".//svg:marker", NS) is not None
    source = MARKER + '<path d="M0 0 L1 1" marker-start="url(#arrow)" marker-end="url(#arrow)"/>'
    with pytest.raises(SVGValidationError, match="marker reference limit"):
        visual(source, limits=replace(Limits(), max_marker_references=1))
    visual(source, limits=replace(Limits(), max_marker_references=2))


def test_luxembourg_visual_details_and_hidden_layers():
    source = (Path(__file__).parent / "fixtures" / "luxembourg" / "source.svg").read_bytes()
    output = sanitize_svg(source, mode="visual")
    root = ET.fromstring(output)
    paths = root.findall(".//svg:path", NS)
    assert len(paths) == 143  # The original rendered paths plus the railway marker.
    assert {"#d5dc76", "#71b37b", "#4f93c0"} <= {node.get("fill") for node in paths}
    assert len([node for node in root.iter() if node.get("display") == "none"]) >= 2
    assert any(node.get("font-family") == "DejaVu Sans Condensed" for node in root.iter())
    assert any(node.get("marker-mid") == "url(#svg-sanitize-marker-0)" for node in paths)
    assert not any(node.tag in {f"{{{SVG}}}image", f"{{{SVG}}}style"} for node in root.iter())
    assert sanitize_svg(output, mode="visual") == output

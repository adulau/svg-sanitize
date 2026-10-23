import re
import xml.etree.ElementTree as ET

import pytest

from svg_sanitize import Limits, SVGValidationError, sanitize_svg

SVG = "http://www.w3.org/2000/svg"
PREFIX = f'<svg xmlns="{SVG}">'


def svg(body: str, extra: str = "") -> str:
    return f'<svg xmlns="{SVG}" {extra}>{body}</svg>'


def tags(xml: str) -> list[str]:
    return [element.tag.split("}")[-1] for element in ET.fromstring(xml).iter()]


def test_basic_geometry_and_presentation_survive():
    source = svg('''<g transform="translate(1, 2)" opacity="0.9">
        <rect width="100" height="50" fill="#abc"/>
        <circle cx="20" cy="20" r="8" stroke="rgb(12, 34, 56)"/>
        <path d="M0 0 L10 10 Z" fill="none" stroke-width="2"/>
    </g>''', 'width="200" height="100" viewBox="0 0 200 100"')
    clean = sanitize_svg(source)
    assert tags(clean) == ["svg", "g", "rect", "circle", "path"]
    assert 'viewBox="0 0 200 100"' in clean
    assert 'transform="translate(1, 2)"' in clean
    assert 'stroke="rgb(12, 34, 56)"' in clean


@pytest.mark.parametrize("payload,needle", [
    ('<script>alert(1)</script><rect width="5" height="5"/>', "script"),
    ('<style>@import url(https://bad.example/a.css)</style>', "style"),
    ('<foreignObject><script xmlns="http://www.w3.org/1999/xhtml">bad()</script></foreignObject>', "foreignObject"),
    ('<a href="javascript:alert(1)"><text>Clickable</text></a>', "a"),
    ('<use href="https://bad.example/x.svg#thing"/>', "use"),
    ('<image href="data:image/svg+xml;base64,xyz"/>', "image"),
    ('<animate attributeName="href" to="javascript:alert(1)"/>', "animate"),
    ('<set attributeName="onload" to="alert(1)"/>', "set"),
    ('<filter><feImage href="https://bad.example/"/></filter>', "filter"),
    ('<defs><linearGradient id="g"/></defs>', "defs"),
    ('<metadata><script>alert(1)</script></metadata>', "metadata"),
])
def test_executable_or_ref_elements_removed(payload, needle):
    result = sanitize_svg(svg(payload))
    assert tags(result) == (["svg", "rect"] if '<rect width="5"' in payload else ["svg"])
    assert needle not in result
    assert "bad.example" not in result
    assert "javascript:" not in result


def test_event_handlers_and_unknown_attrs_removed():
    result = sanitize_svg(svg('<rect width="5" height="6" onload="alert(1)" '
                              'onclick="alert(2)" data-a="1" class="x" id="foo"/>', 'onload="alert(1)"'))
    assert tags(result) == ["svg", "rect"]
    for value in ("onload", "onclick", "alert", "data-a", "class", "id="):
        assert value not in result


def test_discard_css_and_url_values():
    result = sanitize_svg(svg('''<rect width="12" height="13"
        style="fill:url(http://bad.example/img);background:url(javascript:evil())"
        fill="url(https://bad.example/fill.svg#f)"
        stroke="url(#foo)"
        filter="url(https://bad.example/svg#filter)"
        font-family="url(http://bad.example/font.woff)"/>
    '''))
    for item in ("url(", "style=", "filter=", "stroke=", "fill=", "font-family=", "bad.example"):
        assert item not in result
    assert 'width="12"' in result


def test_foreign_and_namespaced_attributes_removed():
    source = f'''<svg xmlns="{SVG}" xmlns:xlink="http://www.w3.org/1999/xlink">
        <rect width="2" height="2" xlink:href="javascript:alert(1)" xml:base="https://bad.example"/>
        <script xmlns="http://www.w3.org/1999/xhtml">evil()</script>
    </svg>'''
    result = sanitize_svg(source)
    assert tags(result) == ["svg", "rect"]
    assert "xlink" not in result and "xml:base" not in result
    assert "bad.example" not in result and "script" not in result


def test_text_and_tspan_survive_escaped():
    result = sanitize_svg(svg('<text x="2" y="14">Hi &amp; <tspan font-weight="bold">&lt;svg&gt;</tspan>!</text>'))
    assert tags(result) == ["svg", "text", "tspan"]
    assert "Hi &amp;" in result
    assert "&lt;svg&gt;" in result
    assert "!</text>" in result


def test_removed_text_descendant_does_not_propagate_active_content():
    output = sanitize_svg(svg('<text>Hello<script>alert(1)</script> World</text>'))
    assert tags(output) == ["svg", "text"]
    assert "Hello World" in output
    assert "alert" not in output


def test_dtd_and_entities_rejected():
    malicious = (f'<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
                 f'<svg xmlns="{SVG}"><text>&xxe;</text></svg>')
    with pytest.raises(SVGValidationError):
        sanitize_svg(malicious)
    with pytest.raises(SVGValidationError):
        sanitize_svg(f'<!DOCTYPE svg><svg xmlns="{SVG}"/>')


def test_processing_instructions_are_not_forwarded():
    doc = f'''<?xml version="1.0"?>
    <?xml-stylesheet href="https://bad.example/style.css" type="text/css"?>
    <svg xmlns="{SVG}"><circle r="3"/></svg>'''
    result = sanitize_svg(doc)
    assert "xml-stylesheet" not in result
    assert "bad.example" not in result
    assert tags(result) == ["svg", "circle"]


def test_invalid_xml_and_wrong_root_rejected():
    for payload in ("<svg><g></svg>", "<html></html>", '<svg xmlns="http://evil.example/svg"/>'):
        with pytest.raises(SVGValidationError):
            sanitize_svg(payload)


def test_resource_limits():
    with pytest.raises(SVGValidationError):
        sanitize_svg(svg(' ' * 200), limits=Limits(max_input_bytes=30))
    with pytest.raises(SVGValidationError):
        sanitize_svg(svg('<g/>' * 5), limits=Limits(max_nodes=3))
    with pytest.raises(SVGValidationError):
        sanitize_svg(svg('<g><g><g/></g></g>'), limits=Limits(max_depth=3))
    with pytest.raises(SVGValidationError):
        sanitize_svg(svg('<text>123456</text>'), limits=Limits(max_text_chars=4))
    with pytest.raises(SVGValidationError):
        sanitize_svg(svg('<rect width="2" height="3"/>'), limits=Limits(max_output_bytes=20))


def test_invalid_geometry_is_dropped():
    result = sanitize_svg(svg('<rect x="1e309" width="-5" height="50" opacity="2" '
                              'transform="translate(0);evil()" fill="expression(alert(1))"/>'))
    assert tags(result) == ["svg", "rect"]
    assert 'height="50"' in result
    assert all(x not in result for x in (' x=', 'width=', 'opacity=', 'transform=', 'fill=', 'evil'))


def test_path_and_polyline_validation():
    good = sanitize_svg(svg('<path d="M0 0 L50 50 Z"/><polyline points="0,0 20,20 40,0"/>'))
    assert 'd="M0 0 L50 50 Z"' in good and 'points="0,0 20,20 40,0"' in good
    bad = sanitize_svg(svg('<path d="M0 0 javascript:alert(1)"/><polygon points="0,0 1,evil"/>'))
    assert ' d=' not in bad and ' points=' not in bad


def test_font_family_whitelist():
    result = sanitize_svg(svg('<text font-family="Arial, sans-serif">A</text>'
                              '<text font-family="local(https://bad.example)">B</text>'))
    assert 'font-family="Arial, sans-serif"' in result
    assert "bad.example" not in result


def test_non_namespaced_input_is_rewritten_into_svg_namespace():
    cleaned = sanitize_svg('<svg><rect width="10" height="20"/></svg>')
    assert f'xmlns="{SVG}"' in cleaned
    assert tags(cleaned) == ["svg", "rect"]


def test_idempotence():
    doc = svg('<g transform="rotate(20 10 10)"><circle r="15" fill="blue"/></g>'
              '<text x="20" y="30">A &amp; B</text>')
    assert sanitize_svg(sanitize_svg(doc)) == sanitize_svg(doc)


def test_no_suspicious_active_content_can_survive_sample():
    from pathlib import Path
    input_file = Path(__file__).parent.parent / "examples" / "malicious.svg"
    result = sanitize_svg(input_file.read_bytes())
    assert tags(result) == ["svg", "rect", "text"]
    for danger in ("script", "style", "foreignObject", "image", "alert(", "onload", "onclick",
                   "http://example.invalid", "href", "url(", "javascript:"):
        assert danger not in result
    assert "Harmless visible text" in result


def test_control_bidi_removed_from_visible_text():
    clean = sanitize_svg(svg('<text>ABC\u202eDEF</text>'))
    assert "ABCDEF" in clean and "\u202e" not in clean


def test_types():
    with pytest.raises(TypeError):
        sanitize_svg(10)
    assert '<circle' in sanitize_svg(svg('<circle r="5"/>').encode("utf-8"))

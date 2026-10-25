"""Offline regressions using the Wikimedia Luxembourg map and attack variants."""

from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET
import pytest

from svg_sanitize import Limits, SVGValidationError, sanitize_svg

FIXTURES = Path(__file__).parent / "fixtures" / "luxembourg"
SVG = "http://www.w3.org/2000/svg"
NS = {"svg": SVG}
REGION_IDS = ("path4517", "path4519", "path4521")
SOURCE_SHA256 = "072eda1ef64aad298a6c3c28498bebb2142d8bbcbc0bd771a604875aff531eac"
SANITIZED = (
    "inline-script.svg", "external-script.svg", "event-handlers.svg", "links.svg",
    "images.svg", "use-and-defs.svg", "foreign-object.svg", "animation.svg",
    "namespace-spoofing.svg", "xml-base-and-xinclude.svg", "hidden-subtrees.svg",
    "css.svg", "processing-instructions.svg", "text-controls.svg", "invalid-values.svg",
)
REJECTED = {
    "doctype.svg": "Malformed or forbidden",
    "external-dtd.svg": "Malformed or forbidden",
    "file-entity.svg": "Malformed or forbidden",
    "remote-entity.svg": "Malformed or forbidden",
    "entity-expansion.svg": "Malformed or forbidden",
    "malformed.svg": "Malformed or forbidden",
    "wrong-namespace.svg": "SVG root",
    "deep-nesting.svg": "element-count or nesting-depth",
    "too-many-nodes.svg": "element-count or nesting-depth",
    "too-many-attributes.svg": "attribute count",
    "oversized-attribute.svg": "oversized attributes",
    "oversized-text.svg": "too much text",
}


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def assert_passive(output: str) -> ET.Element:
    root = SafeET.fromstring(output, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    allowed = {"svg", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "tspan"}
    for element in root.iter():
        assert element.tag.startswith(f"{{{SVG}}}")
        assert element.tag.split("}")[1] in allowed
        for key, value in element.attrib.items():
            assert not key.lower().startswith("on")
            assert not key.startswith("{") and ":" not in key
            assert key not in {"href", "src", "style", "id", "class", "filter", "mask", "clip-path"}
            assert not any(needle in value.lower() for needle in ("url(", "javascript:", "data:", "https:", "file:"))
    return root


@pytest.fixture(scope="module")
def original() -> ET.Element:
    data = read("source.svg")
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA256
    return SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def test_original_wikimedia_map_preserves_real_geometry_and_labels(original):
    output = sanitize_svg(read("source.svg"))
    root = assert_passive(output)
    assert root.get("width") == "891.26068"
    assert root.get("height") == "1161.7325"
    path_nodes = root.findall(".//svg:path", NS)
    assert len(path_nodes) == 142
    paths = {element.get("d") for element in path_nodes}
    for region_id in REGION_IDS:
        source_path = original.find(f".//*[@id='{region_id}']")
        assert source_path is not None
        assert source_path.attrib["d"] in paths
    assert "Luxembourg" in "".join(root.itertext())
    assert sanitize_svg(output) == output


def test_compact_map_is_derived_from_source_and_retains_colors(original):
    root = assert_passive(sanitize_svg(read("clean.svg")))
    assert root.attrib == {
        "width": "891.26068", "height": "1161.7325",
        "viewBox": "0 0 891.26068 1161.7325",
    }
    paths = root.findall(".//svg:path", NS)
    assert len(paths) == 3
    for path, region_id, color in zip(paths, REGION_IDS, ("#d5dc76", "#71b37b", "#4f93c0")):
        source_path = original.find(f".//*[@id='{region_id}']")
        assert source_path is not None
        assert path.attrib == {
            "d": source_path.attrib["d"], "fill": color,
            "stroke": "#e8e8e8", "stroke-width": "2",
        }
    labels = root.findall(".//svg:text", NS)
    assert len(labels) == 1
    assert labels[0].text == "Luxembourg"
    assert labels[0].get("x") == "229.58531"
    assert labels[0].get("y") == "926.14178"


@pytest.mark.parametrize("filename", SANITIZED)
@pytest.mark.parametrize("as_text", [False, True], ids=["bytes", "str"])
@pytest.mark.parametrize("mode", ["strict", "visual"])
def test_attack_removed_without_losing_map(filename, as_text, mode):
    data = read(filename)
    assert data != read("clean.svg")
    output = sanitize_svg(data.decode("utf-8") if as_text else data, mode=mode)
    assert_passive(output)
    # A sanitizer that drops the entire map must not pass these regressions.
    assert output == sanitize_svg(read("clean.svg"), mode=mode)
    assert sanitize_svg(output, mode=mode) == output


@pytest.mark.parametrize("filename,reason", REJECTED.items())
@pytest.mark.parametrize("as_text", [False, True], ids=["bytes", "str"])
@pytest.mark.parametrize("mode", ["strict", "visual"])
def test_invalid_or_excessive_map_rejected(filename, reason, as_text, mode):
    data = read(filename)
    with pytest.raises(SVGValidationError, match=reason):
        sanitize_svg(data.decode("utf-8") if as_text else data, mode=mode)


@pytest.mark.parametrize("mode", ["strict", "visual"])
def test_escaped_markup_is_text_and_never_becomes_an_element(mode):
    output = sanitize_svg(read("escaped-text.svg"), mode=mode)
    root = assert_passive(output)
    label = root.find(".//svg:text", NS)
    assert label is not None
    assert label.text == "Luxembourg & <script>SVG_TEST_TEXT</script>"
    assert len(label) == 0
    assert "&lt;script&gt;" in output and "&amp;" in output
    assert len(root.findall(".//svg:path", NS)) == 3
    assert sanitize_svg(output, mode=mode) == output


def test_map_input_byte_limit_boundary():
    data = read("clean.svg").decode("utf-8").replace("Luxembourg</text>", "Lëtzebuerg</text>")
    size = len(data.encode("utf-8"))
    assert size > len(data)
    expected = sanitize_svg(data)
    for value in (data, data.encode("utf-8")):
        assert sanitize_svg(value, limits=replace(Limits(), max_input_bytes=size)) == expected
        with pytest.raises(SVGValidationError, match="input exceeds byte limit"):
            sanitize_svg(value, limits=replace(Limits(), max_input_bytes=size - 1))


def test_map_output_byte_limit_boundary():
    data = read("clean.svg").decode("utf-8").replace("Luxembourg</text>", "Lëtzebuerg</text>")
    output = sanitize_svg(data)
    size = len(output.encode("utf-8"))
    assert size > len(output)
    assert sanitize_svg(data, limits=replace(Limits(), max_output_bytes=size)) == output
    with pytest.raises(SVGValidationError, match="output byte limit"):
        sanitize_svg(data, limits=replace(Limits(), max_output_bytes=size - 1))


def test_path_budget_drops_only_overlong_geometry():
    source = SafeET.fromstring(read("clean.svg"))
    paths = source.findall(".//svg:path", NS)
    budget = len(paths[0].attrib["d"])
    output = sanitize_svg(read("clean.svg"), limits=replace(Limits(), max_path_chars=budget))
    result = assert_passive(output).findall(".//svg:path", NS)
    assert len(result) == 3
    assert result[0].get("d") == paths[0].attrib["d"]
    assert all("d" not in node.attrib for node in result[1:])
    assert all(node.get("fill") == original.get("fill") for node, original in zip(result, paths))


@pytest.mark.parametrize("filename,exit_code", [
    ("clean.svg", 0), ("inline-script.svg", 0), ("css.svg", 0),
    ("file-entity.svg", 1), ("malformed.svg", 1), ("deep-nesting.svg", 1),
])
@pytest.mark.parametrize("mode", ["strict", "visual"])
def test_cli_map_files(tmp_path, filename, exit_code, mode):
    destination = tmp_path / "sanitized.svg"
    result = subprocess.run(
        [sys.executable, "-m", "svg_sanitize", str(FIXTURES / filename), "--mode", mode, "-o", str(destination)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == exit_code, result.stderr
    if exit_code == 0:
        assert not result.stderr and not result.stdout
        assert destination.read_text(encoding="utf-8").rstrip("\n") == sanitize_svg(read("clean.svg"), mode=mode)
    else:
        assert not destination.exists()
        assert not result.stdout
        assert result.stderr.startswith("svg-sanitize: ")


@pytest.mark.parametrize("mode", ["strict", "visual"])
def test_cli_rejection_preserves_existing_output(tmp_path, mode):
    destination = tmp_path / "existing.svg"
    destination.write_bytes(b"previous output")
    result = subprocess.run(
        [sys.executable, "-m", "svg_sanitize", str(FIXTURES / "remote-entity.svg"), "--mode", mode, "-o", str(destination)],
        capture_output=True, timeout=10,
    )
    assert result.returncode == 1
    assert destination.read_bytes() == b"previous output"


def test_fixture_inventory_and_reproducibility():
    assert {path.name for path in FIXTURES.glob("*.svg")} == {
        "source.svg", "clean.svg", "escaped-text.svg", *SANITIZED, *REJECTED,
    }
    result = subprocess.run(
        [sys.executable, str(FIXTURES / "generate.py"), "--check"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr

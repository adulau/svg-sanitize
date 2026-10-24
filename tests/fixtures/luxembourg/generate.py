"""Rebuild the standalone Luxembourg SVG fixtures without network access.

This generator does not call the sanitizer: expected map geometry is extracted
directly from the pinned source. SVG artwork is CC BY-SA 4.0; see README.md.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET

HERE = Path(__file__).resolve().parent
SOURCE_SHA256 = "072eda1ef64aad298a6c3c28498bebb2142d8bbcbc0bd771a604875aff531eac"
SVG = "http://www.w3.org/2000/svg"
REGION_IDS = ("path4517", "path4519", "path4521")
HEADER = '''<?xml version="1.0" encoding="UTF-8"?>
<!-- Test fixture; treat as untrusted SVG.
Map: Shaund (Shaundd), Russian translation by Peter Fitzgerald.
Source: https://commons.wikimedia.org/wiki/File:Luxembourg.svg
License: https://creativecommons.org/licenses/by-sa/4.0/
Changes: regional outlines and capital label extracted; CSS presentation
converted to attributes; test payload added where indicated by filename.
See README.md and generate.py in this directory.
-->
'''


def map_document() -> str:
    source = (HERE / "source.svg").read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source SVG checksum mismatch")
    original = SafeET.fromstring(source, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    by_id = {node.get("id"): node for node in original.iter() if node.get("id")}
    ET.register_namespace("", SVG)
    root = ET.Element(f"{{{SVG}}}svg", {
        "width": original.attrib["width"],
        "height": original.attrib["height"],
        "viewBox": f'0 0 {original.attrib["width"]} {original.attrib["height"]}',
    })
    regions = ET.SubElement(root, f"{{{SVG}}}g", {"id": "map-regions"})
    for region_id in REGION_IDS:
        region = by_id[region_id]
        presentation = dict(item.split(":", 1) for item in region.attrib["style"].split(";"))
        ET.SubElement(regions, f"{{{SVG}}}path", {
            "id": region_id,
            "d": region.attrib["d"],
            **{key: presentation[key] for key in ("fill", "stroke", "stroke-width")},
        })
    names = ET.SubElement(root, f"{{{SVG}}}g", {
        "transform": by_id["layer7"].attrib["transform"],
    })
    capital = by_id["text10724"]
    label = ET.SubElement(names, f"{{{SVG}}}text", {
        "x": capital.attrib["x"], "y": capital.attrib["y"],
        "font-size": "28", "font-family": "sans-serif", "fill": "black",
    })
    label.text = "".join(capital.itertext())
    ET.indent(root, space="  ")
    return HEADER + ET.tostring(root, encoding="unicode") + "\n"


def append(document: str, payload: str) -> str:
    return document.replace("</svg>", f"{payload}\n</svg>")


def doctype(document: str, declaration: str, payload: str = "") -> str:
    return append(document.replace("<svg ", declaration + "\n<svg ", 1), payload)


def fixtures() -> dict[str, str]:
    clean = map_document()
    documents = {"clean.svg": clean}
    payloads = {
        "inline-script.svg": '''<script><![CDATA[
document.documentElement.setAttribute("data-svg-test", "inline-script");
]]></script>''',
        "external-script.svg": '''<script href="https://example.invalid/svg-test.js"/>
<script xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://example.invalid/svg-test.js"/>
<script src="https://example.invalid/svg-test.js"/>''',
        "links.svg": '''<a href="javascript:document.documentElement.setAttribute('data-svg-test','link')"><text>SVG_TEST_LINK</text></a>
<a href="java&#x09;script:document.documentElement.setAttribute('data-svg-test','encoded-link')"><text>SVG_TEST_ENCODED_LINK</text></a>
<a xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://example.invalid/svg-test"><text>SVG_TEST_XLINK</text></a>
<a href="data:text/html,%3Cscript%3Edocument.title='SVG_TEST'%3C/script%3E"><text>SVG_TEST_DATA_LINK</text></a>''',
        "images.svg": '''<image href="https://example.invalid/svg-test.png" width="10" height="10"/>
<image xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://example.invalid/svg-test.svg"/>
<image href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20onload=%22document.documentElement.setAttribute('data-svg-test','image')%22/%3E"/>
<image href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxzY3JpcHQ+ZG9jdW1lbnQudGl0bGU9J1NWR19URVNUJzs8L3NjcmlwdD48L3N2Zz4="/>''',
        "use-and-defs.svg": '''<defs>
  <g id="svg-test-clone"><path d="M0 0 L1 1" onload="document.title='SVG_TEST'"/></g>
  <symbol id="svg-test-symbol"><script>document.title='SVG_TEST';</script></symbol>
  <filter id="svg-test-filter"><feImage href="https://example.invalid/svg-test.svg"/></filter>
  <pattern id="svg-test-pattern"><image href="https://example.invalid/svg-test.png"/></pattern>
  <linearGradient id="svg-test-gradient"><stop offset="0" stop-color="red"/></linearGradient>
</defs>
<use href="#svg-test-clone"/>
<use href="https://example.invalid/svg-test.svg#payload"/>
<use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#svg-test-symbol"/>
<use href="javascript:document.title='SVG_TEST'"/>''',
        "foreign-object.svg": '''<foreignObject width="200" height="100">
  <div xmlns="http://www.w3.org/1999/xhtml">
    <script>document.title='SVG_TEST';</script>
    <iframe src="https://example.invalid/svg-test"/>
    <form action="https://example.invalid/svg-test"><input name="svg-test"/></form>
    <img src="https://example.invalid/svg-test.png" onerror="document.title='SVG_TEST'"/>
  </div>
</foreignObject>''',
        "animation.svg": '''<animate href="#path4517" attributeName="href" to="javascript:document.title='SVG_TEST'" dur="1s"/>
<set href="#path4517" attributeName="onload" to="document.title='SVG_TEST'"/>
<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="1s"/>
<animateMotion dur="1s"><mpath href="https://example.invalid/svg-test.svg#path"/></animateMotion>''',
        "namespace-spoofing.svg": '''<fake:path xmlns:fake="https://example.invalid/svg-test" d="M0 0 L1 1" onload="document.title='SVG_TEST'"/>
<svg xmlns="http://www.w3.org/1999/xhtml"><script>document.title='SVG_TEST';</script><path d="M0 0 L1 1"/></svg>
<g xmlns=""><path d="M0 0 L1 1"/><script>document.title='SVG_TEST';</script></g>''',
        "xml-base-and-xinclude.svg": '''<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="https://example.invalid/svg-test.xml"/>
<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="file:///__svg_sanitize_test__/never-read.txt" parse="text"/>''',
        "hidden-subtrees.svg": '''<metadata><g><text>SVG_TEST_METADATA</text><script>document.title='SVG_TEST';</script></g></metadata>
<unknown><g><path d="M0 0 L1 1"/><text>SVG_TEST_UNKNOWN</text></g></unknown>
<symbol><text>SVG_TEST_SYMBOL</text></symbol>''',
        "css.svg": '''<style><![CDATA[
@import url("https://example.invalid/svg-test.css");
@font-face { font-family: svg-test; src: url("https://example.invalid/svg-test.woff"); }
path { fill: url("https://example.invalid/svg-test.svg#paint"); }
]]></style>''',
    }
    for name, payload in payloads.items():
        documents[name] = append(clean, payload)
    documents["event-handlers.svg"] = clean.replace(
        "<svg ", '<svg onload="document.documentElement.setAttribute(\'data-svg-test\',\'load\')" ', 1,
    ).replace(
        'id="path4517"',
        'id="path4517" onclick="document.title=\'SVG_TEST\'" onmouseover="&#x64;ocument.title=\'SVG_TEST\'"',
        1,
    )
    documents["css.svg"] = documents["css.svg"].replace(
        "<svg ", '<svg fill="url(https://example.invalid/svg-test.svg#paint)" stroke="url(#svg-test-gradient)" ', 1,
    ).replace('id="path4517"', 'id="path4517" style="fill:url(https://example.invalid/svg-test.svg#paint)"', 1)
    documents["namespace-spoofing.svg"] = documents["namespace-spoofing.svg"].replace(
        "<svg ", '<svg xmlns:fake="https://example.invalid/svg-test" fake:onload="document.title=\'SVG_TEST\'" ', 1,
    )
    documents["xml-base-and-xinclude.svg"] = documents["xml-base-and-xinclude.svg"].replace(
        "<svg ", '<svg xml:base="https://example.invalid/svg-test/" ', 1,
    )
    documents["processing-instructions.svg"] = clean.replace(
        "<svg ", '<?xml-stylesheet type="text/css" href="https://example.invalid/svg-test.css"?>\n'
        '<?xml-model href="https://example.invalid/svg-test.rng"?>\n<svg ', 1,
    )
    documents["text-controls.svg"] = clean.replace(
        ">Luxembourg</text>", ">Lux\u202eembourg\u2066\u0085</text>", 1,
    )
    documents["invalid-values.svg"] = clean.replace(
        "<svg ", '<svg x="1e309" y="NaN" transform="translate(0);SVG_TEST()" opacity="2" ', 1,
    ).replace(
        'id="path4517"',
        'id="path4517" stroke-dasharray="1,evil" font-family="url(https://example.invalid/svg-test.woff)"', 1,
    )
    documents["escaped-text.svg"] = clean.replace(
        ">Luxembourg</text>", ">Luxembourg &amp; &lt;script&gt;SVG_TEST_TEXT&lt;/script&gt;</text>", 1,
    )
    documents["doctype.svg"] = doctype(clean, "<!DOCTYPE svg>")
    documents["external-dtd.svg"] = doctype(clean, '<!DOCTYPE svg SYSTEM "https://example.invalid/svg-test.dtd">')
    documents["file-entity.svg"] = doctype(
        clean, '<!DOCTYPE svg [<!ENTITY probe SYSTEM "file:///__svg_sanitize_test__/never-read.txt">]>',
        "<text>&probe;</text>",
    )
    documents["remote-entity.svg"] = doctype(
        clean, '<!DOCTYPE svg [<!ENTITY probe SYSTEM "https://example.invalid/svg-test.txt">]>',
        "<text>&probe;</text>",
    )
    # Deliberately bounded: only 16 copies if an unsafe parser expands these.
    documents["entity-expansion.svg"] = doctype(
        clean, '<!DOCTYPE svg [<!ENTITY a "SVG_TEST"><!ENTITY b "&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;">]>', "<text>&c;</text>",
    )
    documents["malformed.svg"] = clean.replace("</svg>", "</g>")
    documents["wrong-namespace.svg"] = clean.replace(f'xmlns="{SVG}"', 'xmlns="https://example.invalid/svg-test"', 1)
    # Complexity is checked even inside a subtree that would otherwise be dropped.
    documents["deep-nesting.svg"] = append(clean, "<metadata>" + "<g>" * 64 + "</g>" * 64 + "</metadata>")
    documents["too-many-nodes.svg"] = append(clean, "<metadata>" + "<g/>" * 10_000 + "</metadata>")
    attributes = " ".join(f'data-test-{i}="x"' for i in range(65))
    documents["too-many-attributes.svg"] = append(clean, f"<metadata {attributes}/>")
    documents["oversized-attribute.svg"] = append(clean, '<metadata data-test="' + "x" * 65_537 + '"/>')
    documents["oversized-text.svg"] = append(clean, "<metadata>" + "x" * 100_001 + "</metadata>")
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify fixtures without writing files")
    args = parser.parse_args()
    stale = []
    for name, content in fixtures().items():
        path = HERE / name
        expected = content.encode("utf-8")
        if args.check:
            if not path.exists() or path.read_bytes() != expected:
                stale.append(name)
        else:
            path.write_bytes(expected)
    if stale:
        print("Out-of-date fixtures: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

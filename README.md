# svg-sanitize — restrictive, visual-only SVG sanitizer (prototype)

`svg-sanitize` rebuilds untrusted SVG as **static vector graphics only**. It does
not simply search and replace `script` tags. It parses XML with `defusedxml`,
checks resource limits, and constructs an entirely new XML tree from a small,
explicit allowlist of elements, attributes, and valid values.

**Prototype, not a formally verified security boundary.** Review, fuzz and test
against your target SVG renderers before using this in a security-sensitive
production system.

## Why svg-sanitize?

The **svg-sanitize** project started following security reviews conducted by **Jeroen Pinoy**, which highlighted the potential security risks associated with handling untrusted SVG files. This initial prototype was done during the hack.lu 2026 hackathon after the hot ones interview ;-)

Although SVG is primarily an image format, it can contain active content, including JavaScript, event handlers, external resource references, and other potentially malicious elements. This makes SVG a potential attack vector, particularly when displaying user-supplied images in web applications.

**svg-sanitize** is a lightweight Python library designed to transform untrusted SVG files into passive, visual-only SVG documents. Instead of attempting to identify every possible malicious payload, the library follows a strict allowlist approach, preserving only elements and attributes required for static vector graphics.

The objective is to provide a simple, reusable, and open-source security component that reduces the attack surface when processing SVG files, without requiring applications to implement their own SVG sanitization logic.

## Installation

```bash
python -m pip install -e './svg-sanitize[test]'
# or, when inside the extracted directory:
python -m pip install -e '.[test]'
```

Python 3.10+; runtime dependencies are `defusedxml` for XML parsing and `tinycss2`
for parsing inline declarations in visual mode.

## Python usage

```python
from svg_sanitize import sanitize_svg, SVGValidationError

untrusted_svg = b'''<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">
  <script>alert(1)</script>
  <rect width="80" height="40" fill="red"/>
</svg>'''

try:
    passive_svg = sanitize_svg(untrusted_svg)
except SVGValidationError as exc:
    print(f"SVG rejected: {exc}")
else:
    print(passive_svg)
    # <svg xmlns="http://www.w3.org/2000/svg"><rect width="80" height="40" fill="red" /></svg>
```

For custom input and rendering limits:

```python
from svg_sanitize import Limits, sanitize_svg

output = sanitize_svg(untrusted_svg, limits=Limits(max_input_bytes=100_000, max_nodes=1_000))
```

## Choosing a mode

`mode="strict"` is the default and preserves the original minimal policy.
Use `mode="visual"` for artwork that stores its presentation in inline styles,
such as the Luxembourg map:

```python
output = sanitize_svg(untrusted_svg, mode="visual")
```

| Feature | `strict` (default) | `visual` |
| --- | --- | --- |
| Validated primitive geometry and presentation attributes | Preserved | Preserved |
| Inline `style` declarations | Removed | Allowlisted values converted to presentation attributes; declaration order and `!important` are respected |
| Local markers (arrowheads, railway ticks) | Removed | Sanitized `defs`/`marker` subset, rewritten IDs and same-document marker references |
| Fonts, units, text spacing | Minimal subset | Additional known local font families, physical/font-relative units, `font-stretch`, and `xml:space` |
| Scripts, events, links, animation, external resources, embedded images, CSS stylesheets | Removed | Removed |
| Gradients, patterns, filters, clipping, masks, symbols, `<use>` | Removed | Removed |

Visual mode does not copy CSS or arbitrary markup through. Unsupported
declarations, selectors, CSS variables and expressions are dropped. Marker
definitions cannot reference other resources or inherit marker references;
duplicate/invalid IDs and unresolved references are discarded. Additional
`Limits` fields bound each marker to 128 sanitized nodes and the document to 256
explicit marker reference attributes by default. These bounds do not constitute
a renderer resource sandbox.

The full Luxembourg map has a [rendered comparison](tests/fixtures/luxembourg/README.md#visual-comparison)
and an Inkscape regression test. Visual mode restores its styling and markers;
it does not promise identical appearance for arbitrary SVGs or renderers.

## CLI

```bash
svg-sanitize examples/malicious.svg -o clean.svg
# alternatively:
python -m svg_sanitize examples/malicious.svg -o clean.svg
# preserve validated inline styling and local markers:
svg-sanitize map.svg --mode visual -o map.clean.svg
```

Run tests:

```bash
python -m pytest -q
```

To run the optional full-map render comparison, install Inkscape and DejaVu fonts
(on Debian/Ubuntu: `apt-get install inkscape fonts-dejavu-core`), then:

```bash
python -m pip install -e '.[test,render]'
python -m pytest -q tests/test_visual_rendering.py
```

The regular test matrix skips this comparison when Pillow or Inkscape is absent;
a dedicated CI job installs them and runs it. The comparison renders only the
checksum-pinned original and sanitizer outputs, never the attack fixtures.

## CI and PyPI releases

The [GitHub Actions workflow](.github/workflows/ci.yml) runs the tests on Python
3.10–3.14 for pull requests, pushes to `main`, and published GitHub releases.
After the tests pass, it builds and checks both the source distribution and wheel.
Only a published release triggers an upload to PyPI, using those checked artifacts.
Publishing also requires the dedicated visual comparison job to pass.

Before the first release:

1. Create a GitHub Actions environment named `pypi` in this repository. Add any
   desired deployment protection rules there.
2. Configure a [PyPI trusted publisher](https://docs.pypi.org/trusted-publishers/)
   for the `svg-sanitize` project with owner `adulau`, repository `svg-sanitize`,
   workflow filename `ci.yml`, and environment name `pypi`. If the project does not
   exist yet, configure a pending publisher in your PyPI account instead.

No PyPI API token or GitHub repository secret is required. For each release,
update `project.version` in `pyproject.toml`, merge the change, then create and
publish a GitHub release from that commit with a matching tag, such as `v0.1.0`
or `0.1.0`. A mismatched tag fails before publishing. Each upload must use a new
version because PyPI does not allow replacing previously uploaded files.
Published prereleases also run this workflow; drafts do not.

## Luxembourg SVG regression corpus

The [fixture corpus](tests/fixtures/luxembourg/README.md) includes the original
Wikimedia Luxembourg map and standalone attack variants derived from its region
outlines. It covers active content, external references, XML attacks, invalid
values, and resource limits, with offline library and CLI regression tests:

```bash
python -m pytest -q tests/test_luxembourg.py
```

Treat the attack fixtures as untrusted SVG. The map artwork and derivatives are
CC BY-SA 4.0; attribution and license details are included with the corpus.

## What is allowed

Strict mode allows `svg`, `g`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`,
`path`, `text`, and `tspan`. Numeric dimensions and coordinates, path data,
point lists, limited transforms, limited named/hex/rgb colors, static stroke/
fill and selected text formatting properties are validated individually.

SVGs using gradients, filters, clipping paths, `<use>`, images, embedded fonts,
CSS, masks, symbols, hyperlinks, animation or scripting **will lose those
features**. In particular, gradient fills `fill="url(#id)"` are discarded,
including local URLs. Visual mode additionally allows the validated styling and
marker subset described above; the remaining unsupported features are dropped
in both modes.

## What is forbidden

- JavaScript and scriptable elements; `onload`, `onclick`, and all event handlers.
- CSS stylesheets (`<style>`), `@import`, and expressions. Strict mode removes
  `style=`; visual mode converts only supported inline declarations.
- All links and resources, including `href`, `xlink:href`, external and internal
  references, `data:` URLs, `<image>`, `<use>`, embedded fonts, filters and gradients,
  except visual mode's validated same-document marker references.
- `<foreignObject>` and arbitrary/HTML/XML namespace elements.
- SVG animation and SMIL (`animate`, `set`, `animateTransform`, etc.).
- DTDs, XML entity declarations, external entity references, malformed XML.
- Unknown attributes (including `class` and `xml:base`). Input IDs are removed;
  visual mode assigns new IDs to permitted marker definitions.

Unknown elements are removed **with their complete subtrees**; the input is
never copied wholesale to output. The implementation also enforces limits on
input bytes, output bytes, node count, depth, attribute sizes and text sizes.

## Deployment advice

For untrusted-user uploads, make the sanitized document only one defense layer:

1. Keep the original SVG out of any publicly served directory.
2. Serve the sanitized output with `Content-Type: image/svg+xml`, ideally from
   a separate cookieless domain with `Content-Disposition: attachment` for
   downloads. For display, prefer `<img src="...">` rather than inline SVG.
3. Use CSP restricting `script-src 'none'; object-src 'none'; base-uri 'none';
   default-src 'none'; img-src 'self' data:` on the serving endpoint where
   appropriate, and ensure application CSP is also restrictive.
4. Treat the output as untrusted in any subsequent XML/SVG manipulation pipeline;
   downstream software might add back risky features. If preserving more complex
   SVG features is necessary, consider rasterizing with a hardened, resource-
   isolated renderer instead of broadening the allowlist.
5. Use browser-based regression tests, fuzz tests, and multiple-engine testing
   before relying on the package for production security.

**No SVG sanitizer can promise protection against all future rendering-engine
vulnerabilities.** This prototype targets active-content injection and external
resource-loading pathways, not malicious graphical impersonation or renderer
memory-corruption bugs.

Python code is MIT licensed (see `LICENSE`); the Luxembourg artwork, derivatives,
and comparison images are CC BY-SA 4.0 as documented with the corpus.

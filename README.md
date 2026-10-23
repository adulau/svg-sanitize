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

Python 3.10+; the only runtime dependency is `defusedxml`.

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

## CLI

```bash
svg-sanitize examples/malicious.svg -o clean.svg
# alternatively:
python -m svg_sanitize examples/malicious.svg -o clean.svg
```

Run tests:

```bash
python -m pytest -q
```

## What is allowed

Only `svg`, `g`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`,
`path`, `text`, and `tspan`. Numeric dimensions and coordinates, path data,
point lists, limited transforms, limited named/hex/rgb colors, static stroke/
fill and selected text formatting properties are validated individually.

SVGs using gradients, filters, clipping paths, `<use>`, images, embedded fonts,
CSS, masks, symbols, hyperlinks, animation or scripting **will lose those
features**. In particular, gradient fills `fill="url(#id)"` are discarded,
including local URLs. This is an explicit security/functionality tradeoff.

## What is forbidden

- JavaScript and scriptable elements; `onload`, `onclick`, and all event handlers.
- CSS (`<style>`, `style=`), including `@import`, `url(...)`, and expressions.
- All links and resources, including `href`, `xlink:href`, external and internal
  references, `data:` URLs, `<image>`, `<use>`, fonts, filters and gradients.
- `<foreignObject>` and arbitrary/HTML/XML namespace elements.
- SVG animation and SMIL (`animate`, `set`, `animateTransform`, etc.).
- DTDs, XML entity declarations, external entity references, malformed XML.
- Unknown attributes (including `id`, `class`, `xml:base`, and `xmlns:xlink`).

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

MIT licensed (see `LICENSE`).

"""Render the pinned map and both sanitizer modes for a visual comparison.

Requires Inkscape and the project's `render` extra. Only the checksum-pinned
original and sanitizer outputs are rendered, never the attack fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageChops, ImageStat

from svg_sanitize import sanitize_svg

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "luxembourg"
SOURCE_SHA256 = "072eda1ef64aad298a6c3c28498bebb2142d8bbcbc0bd771a604875aff531eac"


def compare(output_dir: Path) -> dict:
    source = (CORPUS / "source.svg").read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Refusing to render a modified source fixture")
    inkscape = shutil.which("inkscape")
    if not inkscape:
        raise RuntimeError("Install Inkscape to render the visual comparison")
    documents = {"original": source}
    for mode in ("strict", "visual"):
        documents[mode] = sanitize_svg(source, mode=mode).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="svg-sanitize-render-") as directory:
        staging = Path(directory)
        for name, data in documents.items():
            svg = staging / f"{name}.svg"
            png = staging / f"{name}.png"
            svg.write_bytes(data)
            result = subprocess.run(
                [inkscape, str(svg), "--export-type=png", "--export-width=450",
                 f"--export-filename={png}"],
                env={**os.environ, "INKSCAPE_PROFILE_DIR": str(staging / "profile"),
                     "XDG_CACHE_HOME": str(staging / "cache")},
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode or not png.is_file():
                raise RuntimeError(f"Inkscape failed for {name}: {result.stderr}")
        with Image.open(staging / "original.png") as image:
            reference = image.convert("RGBA")
        metrics = {}
        for mode in ("strict", "visual"):
            with Image.open(staging / f"{mode}.png") as image:
                actual = image.convert("RGBA")
            if actual.size != reference.size:
                raise AssertionError("Rendered dimensions changed")
            delta = ImageChops.difference(reference, actual)
            channels = delta.split()
            maximum = channels[0]
            for channel in channels[1:]:
                maximum = ImageChops.lighter(maximum, channel)
            histogram = maximum.histogram()
            metrics[mode] = {
                "mean_channel_error": sum(ImageStat.Stat(delta).mean) / (4 * 255),
                "changed_pixel_fraction": sum(histogram[9:]) / (actual.width * actual.height),
            }
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in documents:
            shutil.copyfile(staging / f"{name}.png", output_dir / f"{name}.png")
        for mode in ("strict", "visual"):
            shutil.copyfile(staging / f"{mode}.svg", output_dir / f"{mode}.svg")
        (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=CORPUS / "preview")
    args = parser.parse_args()
    print(json.dumps(compare(args.output_dir), indent=2))


if __name__ == "__main__":
    main()

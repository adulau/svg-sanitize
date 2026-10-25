"""Optional render regression; CI installs Inkscape and the render extra."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("PIL", reason="Install the render extra for image comparison")


@pytest.mark.skipif(shutil.which("inkscape") is None, reason="Inkscape is required for rendering")
def test_luxembourg_visual_mode_matches_original_render(tmp_path):
    script = Path(__file__).resolve().parents[1] / "tools" / "render_luxembourg.py"
    result = subprocess.run(
        [sys.executable, str(script), "--output-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=100,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    # Compare both outputs with the original in the SAME renderer/font environment.
    # A small tolerance accommodates antialiasing and renderer version differences.
    assert metrics["visual"]["mean_channel_error"] < 0.005
    assert metrics["visual"]["changed_pixel_fraction"] < 0.02
    assert metrics["visual"]["mean_channel_error"] < metrics["strict"]["mean_channel_error"] / 100

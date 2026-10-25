"""Fixture bytes must survive Git checkout even when automatic CRLF is enabled."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required for checkout regression")
def test_svg_fixture_bytes_survive_autocrlf_checkout(tmp_path):
    root = Path(__file__).resolve().parents[1]
    corpus = root / "tests" / "fixtures" / "luxembourg"
    files = sorted(path.relative_to(root) for path in corpus.rglob("*.svg"))
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True, capture_output=True)
    attributes = root / ".gitattributes"
    if attributes.exists():
        shutil.copyfile(attributes, repository / ".gitattributes")
    for path in files:
        destination = repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((root / path).read_bytes())
    # Stage the exact original bytes, then ask Git to export with CRLF enabled.
    # The repository under test and its real index are never modified.
    subprocess.run(
        ["git", "-C", str(repository), "-c", "core.autocrlf=false", "add", "."],
        check=True, capture_output=True,
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(
        ["git", "-C", str(repository), "-c", "core.autocrlf=true", "-c", "core.eol=crlf",
         "checkout-index", "--all", f"--prefix={checkout.as_posix()}/"],
        check=True, capture_output=True,
    )
    for path in files:
        assert (checkout / path).read_bytes() == (root / path).read_bytes(), str(path)

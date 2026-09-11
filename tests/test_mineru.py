"""Optional MinerU engine tests without installing MinerU models."""

from pathlib import Path

import pytest

from toolbox.core.errors import ConversionFailedError
from toolbox.engines.mineru import MinerUEngine


def _fake_mineru(path: Path, body: str = "# Parsed") -> None:
    path.write_text(
        "#!/bin/sh\n"
        'mkdir -p "$4/result"\n'
        f"printf '%s\\n' {body!r} > \"$4/result/source.md\"\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def test_mineru_is_optional_and_uses_whitelisted_markdown_output(tmp_path, monkeypatch):
    binary = tmp_path / "mineru"
    _fake_mineru(binary)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    destination = tmp_path / "out.md"
    monkeypatch.setenv("TOOLBOX_MINERU_BIN", str(binary))

    engine = MinerUEngine()
    assert engine.available
    engine.convert(source, destination, "pdf", "md")

    assert destination.read_text(encoding="utf-8").strip() == "# Parsed"


def test_mineru_failure_is_conversion_error(tmp_path, monkeypatch):
    binary = tmp_path / "mineru-fail"
    binary.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    binary.chmod(0o700)
    monkeypatch.setenv("TOOLBOX_MINERU_BIN", str(binary))

    with pytest.raises(ConversionFailedError, match="exit code 9"):
        MinerUEngine().convert(tmp_path / "source.pdf", tmp_path / "out.md", "pdf", "md")


def test_mineru_does_not_claim_non_markdown_targets():
    engine = MinerUEngine()
    assert engine.edges()
    with pytest.raises(ConversionFailedError):
        engine.convert(Path("source.pdf"), Path("out.html"), "pdf", "html")

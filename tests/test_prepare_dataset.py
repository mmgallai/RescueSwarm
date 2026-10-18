import importlib.util
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prepare_dataset.py"
spec = importlib.util.spec_from_file_location("prepare_dataset", SCRIPT)
prepare_dataset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_dataset)


def make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_extracts_zip_contents(tmp_path):
    zip_path = make_zip(tmp_path / "ds.zip", {"images/a.jpg": b"jpg", "labels/a.txt": b"0 0.5 0.5 0.1 0.1"})
    dest = tmp_path / "out"
    prepare_dataset.extract(zip_path, dest)
    assert (dest / "images" / "a.jpg").read_bytes() == b"jpg"


def test_skips_existing_extraction_unless_forced(tmp_path):
    dest = tmp_path / "out"
    prepare_dataset.extract(make_zip(tmp_path / "v1.zip", {"a.txt": b"v1"}), dest)
    prepare_dataset.extract(make_zip(tmp_path / "v2.zip", {"a.txt": b"v2"}), dest)
    assert (dest / "a.txt").read_bytes() == b"v1"
    prepare_dataset.extract(tmp_path / "v2.zip", dest, force=True)
    assert (dest / "a.txt").read_bytes() == b"v2"


def test_rejects_non_zip_file(tmp_path):
    html = tmp_path / "captcha.zip"
    html.write_text("<html>Confirm you're not a robot</html>")
    with pytest.raises(ValueError, match="not a zip"):
        prepare_dataset.extract(html, tmp_path / "out")


def test_rejects_paths_that_escape_destination(tmp_path):
    zip_path = make_zip(tmp_path / "evil.zip", {"../escaped.txt": b"x"})
    with pytest.raises(ValueError, match="unsafe"):
        prepare_dataset.extract(zip_path, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()

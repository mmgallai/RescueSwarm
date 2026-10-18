"""Unpack the SAR-DAG_raycast dataset into data/sar-dag/.

The repository protects downloads with a CAPTCHA, so the zip must be
downloaded manually in a browser first:

    https://repository.inf.uniri.hr/object/infri:1071/FILE0

Then run, from the repository root:

    python scripts/prepare_dataset.py ~/Downloads/<downloaded-file>.zip
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

DEFAULT_DEST = Path(__file__).resolve().parent.parent / "data" / "sar-dag"


def extract(zip_path: Path, dest: Path, force: bool = False) -> None:
    """Extract zip_path into dest, refusing to overwrite an existing extraction unless forced."""
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"{zip_path} is not a zip file (did the browser save the CAPTCHA page instead?)")
    if dest.exists() and any(dest.iterdir()):
        if not force:
            print(f"{dest} already contains files; skipping extraction (use --force to redo it).")
            return
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            # Refuse entries that would escape dest (e.g. "../../etc/passwd").
            if not (dest / name).resolve().is_relative_to(dest.resolve()):
                raise ValueError(f"unsafe path in zip: {name}")
        archive.extractall(dest)
    print(f"Extracted {zip_path.name} into {dest}")


def summarize(dest: Path) -> None:
    """Print file counts by extension so we can see what the dataset contains."""
    files = [p for p in dest.rglob("*") if p.is_file()]
    counts = Counter(p.suffix.lower() or "(none)" for p in files)
    total_mb = sum(p.stat().st_size for p in files) / 1e6
    print(f"{len(files)} files, {total_mb:.1f} MB")
    for suffix, count in counts.most_common():
        print(f"  {suffix:10} {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip_path", type=Path, help="manually downloaded SAR-DAG zip")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--force", action="store_true", help="delete and re-extract an existing copy")
    args = parser.parse_args()
    try:
        extract(args.zip_path.expanduser(), args.dest, args.force)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    summarize(args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

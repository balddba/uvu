#!/usr/bin/env python3
"""Generate resized copies of the master uvu logo.

Reads assets/uvu-logo.png by default and writes width-suffixed PNGs
(e.g. uvu-logo-220.png) into assets/. Aspect ratio is preserved.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

DEFAULT_SIZES = (64, 128, 220, 440, 512)
DEFAULT_INPUT = Path("assets/uvu-logo.png")
DEFAULT_OUTPUT_DIR = Path("assets")


def parse_sizes(raw: str) -> list[int]:
    """Parse a comma-separated list of positive widths.

    Args:
        raw (str): Comma-separated widths, e.g. '64,220,512'.

    Returns:
        list[int]: Sorted unique positive widths.

    Raises:
        argparse.ArgumentTypeError: If any value is not a positive integer.
    """
    sizes: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid size {part!r}") from exc
        if value <= 0:
            raise argparse.ArgumentTypeError(f"size must be positive: {value}")
        sizes.add(value)
    if not sizes:
        raise argparse.ArgumentTypeError("at least one size is required")
    return sorted(sizes)


def resize_logo(
    source: Path,
    output_dir: Path,
    sizes: list[int],
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Resize the master logo to each requested width.

    Args:
        source (Path): Path to the master logo PNG.
        output_dir (Path): Directory for resized outputs.
        sizes (list[int]): Target widths in pixels.
        dry_run (bool): If True, report paths without writing files.

    Returns:
        list[Path]: Paths that were (or would be) written.

    Raises:
        FileNotFoundError: If source does not exist.
        ValueError: If source is not a readable image.
    """
    if not source.is_file():
        raise FileNotFoundError(f"logo not found: {source}")

    with Image.open(source) as image:
        master = image.convert("RGBA")
        src_w, src_h = master.size
        written: list[Path] = []

        output_dir.mkdir(parents=True, exist_ok=True)
        stem = source.stem

        for width in sizes:
            if width > src_w:
                print(f"skip {width}px (larger than master {src_w}px)")
                continue
            height = max(1, round(src_h * (width / src_w)))
            out_path = output_dir / f"{stem}-{width}.png"
            if dry_run:
                print(f"would write {out_path} ({width}x{height})")
            else:
                resized = master.resize((width, height), Image.Resampling.LANCZOS)
                resized.save(out_path, format="PNG", optimize=True)
                print(f"wrote {out_path} ({width}x{height})")
            written.append(out_path)

    return written


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Generate resized copies of the master uvu logo."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"master logo path (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "-s",
        "--sizes",
        type=parse_sizes,
        default=list(DEFAULT_SIZES),
        help=f"comma-separated widths (default: {','.join(map(str, DEFAULT_SIZES))})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned outputs without writing files",
    )
    return parser


def main() -> int:
    """Run the logo resize CLI.

    Returns:
        int: Process exit code (0 on success).
    """
    args = build_parser().parse_args()
    try:
        resize_logo(args.input, args.output_dir, args.sizes, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

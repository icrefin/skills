#!/usr/bin/env python3
"""Optimize README images: at most 1600 px wide and about 500 KB or less.

A 3000x2000 Retina screenshot is slow to clone, GitHub blurs it on downscale, and
its EXIF block can leak the machine, a device serial number or GPS coordinates.
This tool downscales (never up), recompresses, strips that metadata, and prints
what it changed. RGBA/LA PNGs keep their alpha (never flattened to black);
animated GIF/WebP are left alone; ``<name>.orig<ext>`` backups are never re-scanned.

Worked example
--------------
    uv run --with pillow python scripts/optimize_images.py docs/images --out /tmp/opt
    uv run --with pillow python scripts/optimize_images.py docs/images --report audit/images.md
    uv run --with pillow python scripts/optimize_images.py shot.png --max-kb 200

A 3000x2000 gradient PNG becomes 1600x1067 (143 KiB -> 33 KiB); a JPEG with
EXIF/GPS becomes 1600x1067 (1.37 MiB -> 277 KiB); an already-small icon is
reported ``skipped``. An image that already fits --width is left alone only when
recompression would save less than 10% *and* less than 8 KiB, so a second run is a
no-op (idempotent). Exit codes: 0 ok (skips included), 1 error, 2 usage.
"""

from __future__ import annotations

import argparse, glob as globlib, io, shutil, sys
from pathlib import Path
from typing import Any, NamedTuple, Sequence

SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2
BACKUP_MARK = ".orig"  # suffix of --in-place-backup copies; never re-scanned
LOSSY = {"JPEG", "JPG", "WEBP"}  # formats that honour quality/progressive
MIN_GAIN_BYTES, MIN_GAIN_PCT = 8 * 1024, 10.0  # marginal gain: skip only if under both
PILLOW_HINT = ("error: Pillow is not installed in this interpreter.\n"
               "This workspace manages Python environments with uv, so run:\n"
               "    uv run --with pillow python scripts/optimize_images.py <PATH> [options]\n")

class Job(NamedTuple):
    src: Path
    rel: Path

class Result(NamedTuple):
    path: str
    before_size: int
    after_size: int
    before_dims: tuple[int, int] | None = None
    after_dims: tuple[int, int] | None = None
    action: str = ""
    error: str = ""

def _human(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    return f"{size / 1048576:.2f} MiB" if size >= 1048576 else f"{size / 1024:.0f} KiB"

def collect_jobs(paths: Sequence[str]) -> tuple[list[Job], list[str]]:
    """Expand files, directories and globs into deduplicated jobs."""
    found: list[Job] = []
    missing: list[str] = []
    for raw in paths:
        magic = any(char in raw for char in "*?[")
        matches = sorted(globlib.glob(raw, recursive=True)) if magic else [raw]
        picked: list[Job] = []
        for item in matches:
            path = Path(item).expanduser()
            root = path.resolve() if path.is_dir() else path.parent
            entries = sorted(root.rglob("*")) if path.is_dir() else [path]
            picked += [Job(entry, entry.relative_to(root)) for entry in entries
                       if entry.is_file() and entry.suffix.lower() in SUFFIXES
                       and not entry.stem.endswith(BACKUP_MARK)]  # our backups are not inputs
        if picked:
            found += picked
        else:
            missing.append(raw)
    return list({job.src: job for job in found}.values()), missing

def _encode(Image: Any, image: Any, fmt: str, strip: bool,
            info: dict[str, Any]) -> tuple[bytes, str]:
    """Encode the image; an opaque PNG may get a palette when that is smaller."""
    pairs: list[tuple[Any, str]] = [(image, "recompressed")]
    if fmt == "PNG" and image.mode in {"RGBA", "LA"}:
        pairs = [(image.convert("RGBA"), "recompressed (alpha preserved)")]  # no flattening
    elif fmt == "PNG":
        rgb = image.convert("RGB")
        pairs = [(rgb, "recompressed")]
        if rgb.getcolors(256) is not None:  # at most 256 distinct colours
            pairs.append((rgb.convert("P", palette=Image.ADAPTIVE, colors=256), "palette/256"))
    elif fmt in {"JPEG", "JPG"} and image.mode not in {"RGB", "L", "CMYK"}:
        pairs = [(image.convert("RGB"), "recompressed")]  # JPEG has no alpha
    kwargs: dict[str, Any] = {"optimize": True}
    if fmt in LOSSY:
        kwargs.update(quality=82, progressive=True)
    kwargs.update({"exif": b"", "icc_profile": None} if strip else info)
    best: tuple[bytes, str] = (b"", "recompressed")
    for candidate, action in pairs:
        buffer = io.BytesIO()
        candidate.save(buffer, format=fmt, **kwargs)
        if not best[0] or len(buffer.getvalue()) < len(best[0]):
            best = (buffer.getvalue(), action)
    return best

def process(job: Job, args: argparse.Namespace, Image: Any, out_dir: Path | None) -> Result:
    """Optimize one image, writing it only when that is an improvement."""
    rel, before_size = str(job.rel), job.src.stat().st_size
    try:
        with Image.open(job.src) as handle:
            handle.load()
            fmt = (handle.format or job.src.suffix.lstrip(".")).upper()
            frames = int(getattr(handle, "n_frames", 1))
            info = {k: v for k, v in handle.info.items() if k in {"exif", "icc_profile"}}
            source = handle.copy()
    except Image.UnidentifiedImageError:
        return Result(rel, before_size, 0, error="not a recognised image")
    except OSError as error:
        return Result(rel, before_size, 0, error=f"unreadable: {error}")
    before_dims = source.size
    if frames > 1:
        return Result(rel, before_size, before_size, before_dims, before_dims,
                      f"skipped (animated, {frames} frames left untouched)")
    ratio = min(1.0, args.width / max(before_dims))  # longest side down to --width
    target = (max(1, round(before_dims[0] * ratio)), max(1, round(before_dims[1] * ratio)))
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    working = source.resize(target, resample) if target != before_dims else source
    try:
        payload, action = _encode(Image, working, fmt, args.strip_metadata, info)
    except (OSError, ValueError) as error:
        return Result(rel, before_size, 0, before_dims, error=f"encode failed: {error}")
    after_dims, saved = working.size, before_size - len(payload)
    gain = saved / before_size * 100.0
    if saved <= 0 or (target == before_dims and saved < MIN_GAIN_BYTES and gain < MIN_GAIN_PCT):
        note = ("optimized form is not smaller" if saved <= 0
                else f"only {gain:.1f}% smaller — already optimized")
        return Result(rel, before_size, before_size, before_dims, after_dims, f"skipped ({note})")
    if target != before_dims:
        action = "resized" if action == "recompressed" else f"resized + {action}"
    destination = job.src if out_dir is None else (out_dir / job.rel).resolve()
    if out_dir is not None and not destination.is_relative_to(out_dir.resolve()):
        return Result(rel, before_size, before_size, before_dims, after_dims,
                      error=f"refusing to write outside --out: {destination}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination == job.src and args.in_place_backup:
            backup = job.src.with_name(f"{job.src.stem}{BACKUP_MARK}{job.src.suffix}")
            if not backup.exists():
                shutil.copy2(job.src, backup)
        destination.write_bytes(payload)
    except OSError as error:
        return Result(rel, before_size, before_size, before_dims, after_dims, error=str(error))
    return Result(rel, before_size, len(payload), before_dims, after_dims, action)

def _row(result: Result) -> tuple[str, ...]:
    if result.error:
        return (result.path, _human(result.before_size), "-", "-", "-", result.error)
    first, last = result.before_dims, result.after_dims
    dims = f"{first[0]}x{first[1]} -> {last[0]}x{last[1]}" if first and last else "-"
    pct = (result.before_size - result.after_size) / result.before_size * 100.0
    left_alone = not result.error and result.action.startswith("skipped")
    return (result.path, _human(result.before_size), _human(result.after_size),
            "-" if left_alone else f"{pct:.1f}%", dims, result.action)

def render_table(results: Sequence[Result]) -> str:
    """Render the console table."""
    row = "{:<30} {:>9} {:>9} {:>7} {:<25} {}"
    head = [row.format("path", "before", "after", "saved", "dimensions", "action"),
            row.format(*["-" * 8] * 6)]
    return "\n".join([*head, *[row.format(*_row(r)) for r in results]])

def render_report(results: Sequence[Result], max_kb: int, width: int) -> str:
    """Render the Markdown report, including the files still over budget."""
    before = sum(r.before_size for r in results)
    after = sum(r.after_size for r in results if not r.error) or before
    written = sum(1 for r in results if not (r.error or r.action.startswith("skipped")))
    saved = f"({(before - after) / before * 100.0:.1f}% saved)" if before else ""
    over = [r for r in results if not r.error and r.after_size > max_kb * 1024]
    out = ["# Image optimization report", "",
           "| path | before | after | saved | dimensions | action |",
           "| --- | --- | --- | --- | --- | --- |",
           *["| `%s` | %s | %s | %s | %s | %s |" % _row(r) for r in results],
           "", "## Totals", "",
           f"- files: **{len(results)}** ({written} rewritten, {len(results) - written} left alone)",
           f"- size: **{_human(before)} -> {_human(after)}** {saved}",
           f"- budget: **{max_kb} KB** per file, longest side **{width} px**", "",
           f"## Still over {max_kb} KB ({len(over)})", ""]
    if over:
        out += ["Re-run each one with a smaller width:", "", "```console",
                *[f'uv run --with pillow python scripts/optimize_images.py "{r.path}" '
                  f"--width {max(400, width // 2)} --max-kb {max_kb}" for r in over], "```", ""]
    else:
        out += [f"Every processed image is at or under {max_kb} KB.", ""]
    return "\n".join(out)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optimize_images.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Downscale and recompress README images (<=1600 px wide, ~<=500 KB).",
        epilog="EXIF, GPS and ICC metadata is stripped by default: a screenshot can carry a "
               "device serial or GPS coordinates; pass --no-strip-metadata to keep it.")
    add = parser.add_argument
    add("paths", nargs="+", metavar="PATH", help="image files, directories (recursed) or globs")
    add("--width", type=int, default=1600, help="longest-side cap in px (default: 1600)")
    add("--max-kb", type=int, default=500, help="size budget per file in KB (default: 500)")
    add("--out", metavar="DIR", help="write optimized copies here, preserving structure")
    add("--report", metavar="FILE", help="write a Markdown report to FILE")
    add("--quiet", action="store_true", help="suppress the table")
    add("--strip-metadata", action=argparse.BooleanOptionalAction, default=True,
        help="strip EXIF/GPS/ICC metadata (default: strip)")
    add("--in-place-backup", action="store_true", help="keep the original as <name>.orig<ext>")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - environment dependent
        sys.stderr.write(PILLOW_HINT)
        return EXIT_ERROR
    if args.width < 1 or args.max_kb < 1:
        sys.stderr.write("error: --width and --max-kb must be positive integers\n")
        return EXIT_USAGE
    jobs, missing = collect_jobs(args.paths)
    for item in missing:
        sys.stderr.write(f"error: no images found for: {item}\n")
    if missing:
        return EXIT_USAGE
    out_dir = Path(args.out).expanduser() if args.out else None
    results = [process(job, args, Image, out_dir) for job in jobs]
    if not args.quiet:
        print(render_table(results))
    if args.report:
        try:
            target = Path(args.report).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render_report(results, args.max_kb, args.width), encoding="utf-8")
            if not args.quiet:
                print(f"report: {target}")
        except OSError as error:
            sys.stderr.write(f"error: cannot write report: {error}\n")
            return EXIT_ERROR
    sys.stdout.flush()  # keep the stderr errors after the table when piped
    for result in [r for r in results if r.error]:
        sys.stderr.write(f"error: {result.path}: {result.error}\n")
    return EXIT_ERROR if any(r.error for r in results) else EXIT_OK

if __name__ == "__main__":
    raise SystemExit(main())
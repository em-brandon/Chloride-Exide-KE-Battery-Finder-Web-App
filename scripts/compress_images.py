"""
Convert images to WebP for web display and save them to a chosen output folder.

Scans frontend/src/assets, frontend/public, and static/ for JPG/PNG/WebP images,
converts each to WebP, and writes the output to the directory you specify at runtime.
If you press Enter without typing a path, it defaults to <project_root>/assets/.
Original files are never modified.

Usage:
    python scripts/compress_images.py
"""

from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow not installed. Run: pip install Pillow")

# Project root is one level above the scripts/ folder
ROOT = Path(__file__).resolve().parent.parent

# Directories to scan for source images (searched recursively)
SCAN_DIRS = [
    ROOT / "frontend" / "src" / "assets",
    ROOT / "frontend" / "public",
    ROOT / "static",
]

# Default output folder when the user presses Enter without typing a path
DEFAULT_OUTPUT_DIR = ROOT / "assets"

# WebP quality (0–100). 85 is visually lossless for photos; logos compress
# even smaller at this level because WebP handles flat colours very efficiently.
WEBP_QUALITY = 85


def prompt_output_dir() -> Path:
    """
    Ask the user where to save the WebP files.
    Accepts an absolute path, a path relative to the current working directory,
    or just Enter to use the default (project root/assets).
    """
    print(f"\nOutput directory (press Enter for default: {DEFAULT_OUTPUT_DIR})")
    raw = input("  Path: ").strip()

    if not raw:
        # User pressed Enter — use the default
        return DEFAULT_OUTPUT_DIR

    candidate = Path(raw)

    # If the user typed a relative path, resolve it from cwd so it behaves
    # exactly as they would expect in their terminal.
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    return candidate.resolve()


def to_webp(src: Path, dest: Path) -> None:
    """
    Open any supported image and save it as WebP at WEBP_QUALITY.
    Images with an alpha channel (RGBA, LA, PA) keep their transparency;
    everything else is converted to RGB before encoding.
    method=6 is the slowest/best WebP compression method — fine for a batch script.
    """
    img = Image.open(src)

    if img.mode in ("RGBA", "LA", "PA"):
        # Preserve transparency — WebP supports alpha natively
        img = img.convert("RGBA")
        img.save(dest, format="WEBP", quality=WEBP_QUALITY, method=6, lossless=False)
    else:
        # Flatten to RGB (drops any stray palette or greyscale modes)
        img = img.convert("RGB")
        img.save(dest, format="WEBP", quality=WEBP_QUALITY, method=6, lossless=False)


def fmt(size: int) -> str:
    """Format a byte count as a human-readable string (KB or MB)."""
    if size >= 1_000_000:
        return f"{size / 1_000_000:.2f} MB"
    return f"{size / 1_000:.1f} KB"


def main() -> None:
    # Image formats this script will pick up from the scan directories
    extensions = {".jpg", ".jpeg", ".png", ".webp"}

    # Ask the user where to save output before doing any work
    output_dir = prompt_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving WebP files to: {output_dir}\n")

    rows = []          # one row per processed image, used to build the summary table
    total_before = 0   # cumulative original size in bytes
    total_after = 0    # cumulative WebP size in bytes

    for scan_dir in SCAN_DIRS:
        # Skip scan directories that don't exist (e.g. static/ on a fresh checkout)
        if not scan_dir.exists():
            continue

        for src in sorted(scan_dir.rglob("*")):
            # Skip directories and unsupported file types
            if not src.is_file() or src.suffix.lower() not in extensions:
                continue

            before = src.stat().st_size

            # Output file name: same stem as the source, always .webp extension.
            # Files from different subdirectories with the same stem will overwrite
            # each other — intentional, since assets/ is a flat web-serve folder.
            dest = output_dir / (src.stem + ".webp")

            try:
                to_webp(src, dest)
                after = dest.stat().st_size

                # Compute size reduction for the summary table
                saved = before - after
                pct = saved / before * 100 if before else 0
                savings_str = (
                    f"-{pct:.0f}%  (saved {fmt(saved)})"
                    if saved > 0
                    else f"+{abs(pct):.0f}%  (larger)"
                )
                total_before += before
                total_after += after

            except Exception as e:
                # Don't abort the whole run for one bad file — log it and continue
                after = before
                savings_str = f"ERROR: {e}"

            rows.append((
                str(src.relative_to(ROOT)),  # source path relative to project root
                dest.name,                   # output filename
                fmt(before),
                fmt(after),
                savings_str,
            ))

    if not rows:
        print("No image files found in the scan directories.")
        return

    # ------------------------------------------------------------------
    # Print aligned summary table
    # ------------------------------------------------------------------
    col_w = [max(len(r[i]) for r in rows) for i in range(5)]
    col_w[0] = max(col_w[0], len("Source"))
    header = ("Source", "Output", "Before", "After", "Savings")
    sep = "  ".join("-" * w for w in col_w)

    print("  ".join(h.ljust(col_w[i]) for i, h in enumerate(header)))
    print(sep)
    for row in rows:
        print("  ".join(row[i].ljust(col_w[i]) for i in range(5)))

    total_saved = total_before - total_after
    total_pct = total_saved / total_before * 100 if total_before else 0
    print(sep)
    print(f"\nTotal: {fmt(total_before)} -> {fmt(total_after)}  ({fmt(total_saved)} saved, -{total_pct:.0f}%)")
    print(f"WebP files written to: {output_dir}")


if __name__ == "__main__":
    main()

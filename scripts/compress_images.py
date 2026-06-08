"""
Compress all images in assets/ and frontend asset directories in-place.
Originals are backed up to _originals/ subdirectories before any changes.
Run once, or re-run when new assets are added (already-backed-up originals are skipped).

Usage:
    python scripts/compress_images.py
"""

import shutil
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow not installed. Run: pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = [
    ROOT / "assets",
    ROOT / "frontend" / "src" / "assets",
    ROOT / "frontend" / "public",
    ROOT / "static",
]

JPG_QUALITY = 82
# PNGs larger than this threshold get palette quantization (flat-art logos)
PNG_QUANTIZE_THRESHOLD = 200_000  # 200 KB


def backup_original(src: Path) -> None:
    originals_dir = src.parent / "_originals"
    originals_dir.mkdir(exist_ok=True)
    dest = originals_dir / src.name
    if not dest.exists():
        shutil.copy2(src, dest)


def compress_jpg(path: Path) -> None:
    img = Image.open(path).convert("RGB")
    img.save(path, format="JPEG", quality=JPG_QUALITY, optimize=True, progressive=True)


def compress_png(path: Path) -> None:
    img = Image.open(path)
    original_mode = img.mode
    file_size = path.stat().st_size

    if file_size > PNG_QUANTIZE_THRESHOLD and original_mode in ("RGB", "RGBA", "P"):
        colors = 256
        if original_mode == "RGBA":
            # RGBA quantization requires FASTOCTREE
            quantized = img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
            quantized = quantized.convert("RGBA")
        else:
            quantized = img.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        quantized.save(path, format="PNG", optimize=True)
    else:
        img.save(path, format="PNG", optimize=True)


def fmt(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1_000_000:.2f} MB"
    return f"{size / 1_000:.1f} KB"


def main() -> None:
    extensions = {".jpg", ".jpeg", ".png"}
    rows = []
    total_before = 0
    total_after = 0

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for path in sorted(scan_dir.iterdir()):
            if path.suffix.lower() not in extensions:
                continue

            before = path.stat().st_size
            backup_original(path)

            try:
                if path.suffix.lower() in (".jpg", ".jpeg"):
                    compress_jpg(path)
                else:
                    compress_png(path)
                after = path.stat().st_size
                # Restore from backup if compression made the file larger
                if after >= before:
                    originals_dir = path.parent / "_originals"
                    shutil.copy2(originals_dir / path.name, path)
                    after = before
                saved = before - after
                pct = saved / before * 100 if before else 0
                savings_str = f"-{pct:.0f}%  (saved {fmt(saved)})" if saved > 0 else "no savings (restored)"
                total_before += before
                total_after += after
            except Exception as e:
                after = before
                savings_str = f"ERROR: {e}"

            rows.append((
                str(path.relative_to(ROOT)),
                fmt(before),
                fmt(after),
                savings_str,
            ))

    if not rows:
        print("No image files found.")
        return

    col_w = [max(len(r[i]) for r in rows) for i in range(4)]
    col_w[0] = max(col_w[0], len("File"))
    header = ("File", "Before", "After", "Savings")
    sep = "  ".join("-" * w for w in col_w)

    print("  ".join(h.ljust(col_w[i]) for i, h in enumerate(header)))
    print(sep)
    for row in rows:
        print("  ".join(row[i].ljust(col_w[i]) for i in range(4)))

    total_saved = total_before - total_after
    total_pct = total_saved / total_before * 100 if total_before else 0
    print(sep)
    print(f"\nTotal: {fmt(total_before)} -> {fmt(total_after)}  ({fmt(total_saved)} saved, -{total_pct:.0f}%)")
    print("Originals backed up to _originals/ subdirectories.")


if __name__ == "__main__":
    main()

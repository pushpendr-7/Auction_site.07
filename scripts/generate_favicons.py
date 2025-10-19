#!/usr/bin/env python3
"""
Generate a complete favicon set from a source image.

Outputs (to the --out directory):
  - favicon.ico (multi-size: 16, 32, 48, 64)
  - favicon-16x16.png
  - favicon-32x32.png
  - apple-touch-icon.png (180x180)
  - android-chrome-192x192.png
  - android-chrome-512x512.png
  - site.webmanifest (referencing 192 and 512 icons)

Requires Pillow.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Tuple

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate favicon assets from an image")
    parser.add_argument("--src", required=True, help="Path to source image (png/jpg/svg if rasterized)")
    parser.add_argument("--out", default="static", help="Output directory (defaults to ./static)")
    return parser.parse_args()


def ensure_square(im: Image.Image, size: Tuple[int, int]) -> Image.Image:
    """Return a square, letterboxed version of the image sized to the given dimensions.

    Preserves transparency when present.
    """
    target_w, target_h = size
    target_size = min(target_w, target_h)

    # Convert to RGBA to ensure transparency is preserved
    image_rgba = im.convert("RGBA")

    # Compute scaling to fit within square
    src_w, src_h = image_rgba.size
    scale = min(target_size / src_w, target_size / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = image_rgba.resize((new_w, new_h), Image.LANCZOS)

    # Center on square canvas
    canvas = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
    offset = ((target_size - new_w) // 2, (target_size - new_h) // 2)
    canvas.paste(resized, offset, resized)
    return canvas


def save_png(im: Image.Image, size: int, out_dir: Path, name: str) -> Path:
    out_path = out_dir / name
    ensure_square(im, (size, size)).save(out_path, format="PNG")
    return out_path


def save_ico(im: Image.Image, sizes: Iterable[int], out_dir: Path) -> Path:
    out_path = out_dir / "favicon.ico"
    # Generate frames for all sizes
    frames = [ensure_square(im, (s, s)) for s in sizes]
    # ICO expects a single image with multiple sizes provided via the 'sizes' arg
    # Save the largest frame, pass sizes to embed all; Pillow will downscale as needed
    largest = max(sizes)
    base = ensure_square(im, (largest, largest)).convert("RGBA")
    base.save(out_path, format="ICO", sizes=[(s, s) for s in sizes])
    return out_path


def write_manifest(out_dir: Path) -> Path:
    manifest = {
        "name": "Auction Site",
        "short_name": "Auctions",
        "icons": [
            {
                "src": "android-chrome-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": "android-chrome-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
            },
        ],
        "theme_color": "#111111",
        "background_color": "#111111",
        "display": "standalone",
    }

    import json

    out_path = out_dir / "site.webmanifest"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    args = parse_args()
    src = Path(args.src)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    image = Image.open(src)

    # Core sizes
    save_png(image, 16, out_dir, "favicon-16x16.png")
    save_png(image, 32, out_dir, "favicon-32x32.png")

    # Apple & PWA sizes
    save_png(image, 180, out_dir, "apple-touch-icon.png")
    save_png(image, 192, out_dir, "android-chrome-192x192.png")
    save_png(image, 512, out_dir, "android-chrome-512x512.png")

    # ICO with common sizes
    save_ico(image, sizes=[16, 32, 48, 64], out_dir=out_dir)

    write_manifest(out_dir)

    print(f"Favicon assets written to: {out_dir}")


if __name__ == "__main__":
    main()

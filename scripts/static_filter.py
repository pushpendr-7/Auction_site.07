#!/usr/bin/env python3
import argparse
import os
from PIL import Image, ImageChops
import random


def generate_static_noise(size, intensity=1.0):
    width, height = size
    noise_img = Image.new("L", (width, height))
    # Generate grayscale noise
    pixels = bytearray(random.getrandbits(8) for _ in range(width * height))
    noise_img.frombytes(bytes(pixels))

    if intensity < 1.0:
        # Reduce contrast of noise
        noise_img = noise_img.point(lambda p: int(127 + (p - 127) * intensity))
    return noise_img


def apply_tv_static(input_path: str, output_path: str, amount: float = 0.35, monochrome: bool = True):
    base = Image.open(input_path).convert("RGBA")
    noise_gray = generate_static_noise(base.size, intensity=1.0)

    if monochrome:
        noise_rgba = Image.merge("RGBA", [noise_gray, noise_gray, noise_gray, Image.new("L", base.size, 255)])
    else:
        # Slightly different noise per channel for color static
        r = noise_gray
        g = generate_static_noise(base.size, intensity=1.0)
        b = generate_static_noise(base.size, intensity=1.0)
        noise_rgba = Image.merge("RGBA", [r, g, b, Image.new("L", base.size, 255)])

    # Blend noise with base using screen-like effect via lighten + amount
    blended = ImageChops.blend(base, ImageChops.add(base, noise_rgba, scale=1.0, offset=0), amount)

    # Optional subtle scanlines for CRT feel
    scanline = Image.new("L", base.size, 0)
    scan_pixels = scanline.load()
    for y in range(0, base.size[1], 2):
        for x in range(base.size[0]):
            scan_pixels[x, y] = 30  # darker line every other row
    scan_rgba = Image.merge("RGBA", [scanline, scanline, scanline, Image.new("L", base.size, 255)])
    blended = ImageChops.subtract(blended, scan_rgba)

    # Small vignette to focus center
    vignette = Image.radial_gradient("L").resize(base.size)
    vignette = vignette.point(lambda p: int(p * 0.8))
    vignette_rgba = Image.merge("RGBA", [vignette, vignette, vignette, Image.new("L", base.size, 255)])
    blended = ImageChops.multiply(blended, vignette_rgba)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    blended.convert("RGB").save(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply TV static noise filter to an image.")
    parser.add_argument("input", help="Path to input image")
    parser.add_argument("output", help="Path to output image")
    parser.add_argument("--amount", type=float, default=0.35, help="Blend amount of static (0-1)")
    parser.add_argument("--color", action="store_true", help="Use color noise instead of monochrome")
    args = parser.parse_args()

    apply_tv_static(args.input, args.output, amount=max(0.0, min(1.0, args.amount)), monochrome=not args.color)

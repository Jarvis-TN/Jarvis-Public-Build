"""Draw dexter.ico (a Pokedex-red badge with the blue lens) with Pillow.
Run by setup.bat so the desktop shortcut has a proper icon."""

from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    d.rounded_rectangle([pad, pad, size - pad, size - pad],
                        radius=size // 5, fill=(200, 16, 46, 255),
                        outline=(92, 7, 20, 255), width=max(1, size // 32))
    # blue lens, upper-left like the real thing
    cx = cy = int(size * 0.38)
    r = int(size * 0.24)
    d.ellipse([cx - r - pad, cy - r - pad, cx + r + pad, cy + r + pad],
              fill=(232, 238, 245, 255))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(29, 111, 242, 255))
    hr = max(1, int(r * 0.4))
    d.ellipse([cx - hr - r // 3, cy - hr - r // 3, cx - r // 3, cy - r // 3],
              fill=(190, 225, 255, 255))
    # three tiny LEDs
    if size >= 32:
        lr = max(1, size // 24)
        for i, color in enumerate([(255, 59, 48), (255, 204, 0), (52, 199, 89)]):
            x = int(size * 0.62) + i * (lr * 3)
            y = int(size * 0.22)
            d.ellipse([x - lr, y - lr, x + lr, y + lr], fill=color + (255,))
    return img


if __name__ == "__main__":
    imgs = [draw(s) for s in SIZES]
    imgs[-1].save("dexter.ico", sizes=[(s, s) for s in SIZES],
                  append_images=imgs[:-1])
    print("wrote dexter.ico")

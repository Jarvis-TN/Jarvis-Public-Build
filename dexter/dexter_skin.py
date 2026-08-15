"""Pre-rendered Pokedex 'skin', matched to the show's open clamshell dex.

Left panel: raised top plate with the glossy blue lens and three LEDs, a
white TV-style bezel around the main screen (red dots, speaker grille,
clipped corner), mic button, red/blue pills, green button, black D-pad.
Center: hinge column. Right panel (clipped corner): black secondary display
(Dexter's console), blue button grid, white double key, yellow dome button,
two black slots (search bar + status).

Everything is drawn with PIL — gradients, bevels, drop shadows, domed glass,
gem buttons — so the device looks molded and lit like the show. Fully
procedural: no binary assets in the repo. dexter.py calls render_body() once
for static chrome, lens_frames() for the talking glow, led() for indicators.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter


def _c(hexs):
    return tuple(int(hexs[i:i + 2], 16) for i in (1, 3, 5))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _scale(col, f):
    return tuple(max(0, min(255, int(v * f))) for v in col)


def _vgrad(w, h, top, bot):
    img = Image.new("RGB", (max(1, w), max(1, h)))
    d = ImageDraw.Draw(img)
    for y in range(img.height):
        d.line([(0, y), (img.width, y)],
               fill=_lerp(top, bot, y / max(1, img.height - 1)))
    return img


def _paste_grad(base, box, top, bot, radius=0):
    x1, y1, x2, y2 = [int(v) for v in box]
    grad = _vgrad(x2 - x1, y2 - y1, top, bot).convert("RGBA")
    if radius:
        mask = Image.new("L", grad.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, grad.width - 1, grad.height - 1], radius, fill=255)
        base.paste(grad, (x1, y1), mask)
    else:
        base.paste(grad, (x1, y1))


def _sphere(size, edge, center, offset=0.20):
    """Shaded ball: dark at the rim, bright toward an upper-left highlight."""
    size = int(size)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size / 2.0
    steps = max(3, int(r))
    for i in range(steps, 0, -1):
        t = i / steps
        shift = r * offset * (1 - t)
        col = _lerp(center, edge, t)
        d.ellipse([r - i - shift, r - i - shift,
                   r + i - shift, r + i - shift], fill=col + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    img.putalpha(mask)
    return img


def _specular(img, cx, cy, rx, ry, alpha=170, blur=3):
    spec = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(spec).ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                                 fill=(255, 255, 255, alpha))
    img.alpha_composite(spec.filter(ImageFilter.GaussianBlur(blur)))
    return img


def _shadow(base, shape_fn, blur=9, alpha=140, dx=6, dy=8):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shape_fn(ImageDraw.Draw(sh), (0, 0, 0, alpha), dx, dy)
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))


def _gem(base, box, top_col, bot_col, radius=7, outline_a=120):
    x1, y1, x2, y2 = [int(v) for v in box]
    _paste_grad(base, box, top_col, bot_col, radius)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([x1, y1, x2, y2], radius,
                        outline=(0, 0, 0, outline_a), width=1)
    hi = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(hi).rounded_rectangle(
        [x1 + 2, y1 + 2, x2 - 2, y1 + max(4, (y2 - y1) // 2)],
        max(1, radius - 3), fill=(255, 255, 255, 60))
    base.alpha_composite(hi)


def render_body(w, h, T, L):
    """Static chrome. L (layout) carries the same coordinates dexter.py uses
    for dynamic items and click zones, so everything lines up."""
    body = _c(T["body"])
    base = Image.new("RGBA", (w, h), _c(T["room"]) + (255,))
    d = ImageDraw.Draw(base)

    lx1, ly1, lx2, ly2 = L["left_panel"]
    rx1, ry1, rx2, ry2 = L["right_panel"]
    hx1, hy1, hx2, hy2 = L["hinge"]

    # ---- drop shadows for both halves and the hinge -------------------------
    def shape(dd, fill, dx, dy):
        dd.rounded_rectangle([lx1 + dx, ly1 + dy, lx2 + dx, ly2 + dy], 24,
                             fill=fill)
        dd.rounded_rectangle([rx1 + dx, ry1 + dy, rx2 + dx, ry2 + dy], 24,
                             fill=fill)
    _shadow(base, shape)

    # ---- left panel shell ----------------------------------------------------
    _paste_grad(base, (lx1, ly1, lx2, ly2), _scale(body, 1.16),
                _scale(body, 0.60), radius=24)
    d.rounded_rectangle([lx1, ly1, lx2, ly2], 24,
                        outline=_scale(body, 0.35) + (255,), width=3)
    d.rounded_rectangle([lx1 + 3, ly1 + 3, lx2 - 3, ly2 - 3], 21,
                        outline=(255, 255, 255, 60), width=1)

    # raised top plate with the stepped diagonal edge (holds lens + LEDs)
    plate = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pts = L["plate_pts"]
    grad = _vgrad(lx2 - lx1, 130, _scale(body, 1.32), _scale(body, 0.98))
    pm = Image.new("L", (w, h), 0)
    ImageDraw.Draw(pm).polygon(pts, fill=255)
    plate.paste(grad.convert("RGBA"), (lx1, ly1), pm.crop((lx1, ly1,
                                                           lx2, ly1 + 130)))
    base.alpha_composite(plate)
    # seam shadow under the plate edge
    d.line([(pts[2][0], pts[2][1]), (pts[3][0], pts[3][1]),
            (pts[4][0], pts[4][1]), (pts[5][0], pts[5][1])],
           fill=(0, 0, 0, 110), width=3)
    d.line([(pts[2][0], pts[2][1] - 3), (pts[3][0], pts[3][1] - 3),
            (pts[4][0], pts[4][1] - 3), (pts[5][0], pts[5][1] - 3)],
           fill=(255, 255, 255, 55), width=1)

    # lens socket (dark well the glass dome sits in)
    cx, cy = L["lens_center"]
    socket_r = L["lens_r"] + 12
    base.alpha_composite(_sphere(socket_r * 2, _scale(body, 1.0),
                                 _scale(body, 0.45), offset=-0.15),
                         (int(cx - socket_r), int(cy - socket_r)))

    # LED wells
    for lcx, lcy in L["led_centers"]:
        base.alpha_composite(_sphere(24, _scale(body, 1.05),
                                     _scale(body, 0.4), offset=-0.15),
                             (int(lcx - 12), int(lcy - 12)))

    # ---- white TV bezel around the main screen ------------------------------
    bx1, by1, bx2, by2 = L["bezel"]
    _shadow(base, lambda dd, f, dx, dy: dd.rounded_rectangle(
        [bx1 + dx, by1 + dy, bx2 + dx, by2 + dy], 16, fill=f),
        blur=6, alpha=120, dx=3, dy=5)
    _paste_grad(base, (bx1, by1, bx2, by2), (238, 238, 241), (196, 199, 205),
                radius=16)
    d.rounded_rectangle([bx1, by1, bx2, by2], 16,
                        outline=(90, 94, 102, 255), width=2)
    # clipped bottom-left corner, filled back with body red
    d.polygon([(bx1, by2 - 42), (bx1, by2), (bx1 + 46, by2)],
              fill=_scale(body, 0.78) + (255,))
    d.line([(bx1, by2 - 42), (bx1 + 46, by2)], fill=(90, 94, 102, 255),
           width=2)
    # two red dots above the screen
    mid = (bx1 + bx2) // 2
    for dot_x in (mid - 14, mid + 14):
        base.alpha_composite(_sphere(9, _scale(body, 0.6), _scale(body, 1.3)),
                             (dot_x - 4, by1 + 10))
    # speaker grille lines, bottom-right of the bezel
    for i in range(4):
        gy = by2 - 36 + i * 7
        d.line([(bx2 - 74, gy), (bx2 - 26, gy)], fill=(120, 124, 132, 255),
               width=3)
        d.line([(bx2 - 74, gy + 1), (bx2 - 26, gy + 1)],
               fill=(60, 62, 68, 255), width=1)
    # the dark screen inset
    sx1, sy1, sx2, sy2 = L["screen"]
    d.rounded_rectangle([sx1 - 4, sy1 - 4, sx2 + 4, sy2 + 4], 8,
                        fill=(24, 26, 30, 255))
    d.rectangle([sx1, sy1, sx2, sy2], fill=_c(T["screen"]) + (255,))
    ish = Image.new("RGBA", base.size, (0, 0, 0, 0))
    di = ImageDraw.Draw(ish)
    di.rectangle([sx1, sy1, sx2, sy1 + 8], fill=(0, 0, 0, 150))
    di.rectangle([sx1, sy1, sx1 + 8, sy2], fill=(0, 0, 0, 110))
    base.alpha_composite(ish.filter(ImageFilter.GaussianBlur(3)))

    # ---- left panel controls -------------------------------------------------
    mx, my, mr = L["mic"]
    base.alpha_composite(_sphere(mr * 2 + 8, (4, 5, 7), (52, 60, 72)),
                         (int(mx - mr - 4), int(my - mr - 4)))
    d.ellipse([mx - mr - 4, my - mr - 4, mx + mr + 4, my + mr + 4],
              outline=(255, 255, 255, 40), width=1)
    for box, col in L["pills"]:
        _gem(base, box, _lerp(_c(col), (255, 255, 255), 0.35),
             _scale(_c(col), 0.6), radius=5)
    _gem(base, L["green_btn"], (96, 205, 122), (26, 92, 44), radius=8)
    # D-pad: near-black beveled cross with domed center
    dx_, dy_, arm, thick = L["dpad"]
    dark, lite = (8, 14, 11), (52, 66, 58)
    for box in ([dx_ - arm - thick // 2, dy_ - thick // 2,
                 dx_ + arm + thick // 2, dy_ + thick // 2],
                [dx_ - thick // 2, dy_ - arm - thick // 2,
                 dx_ + thick // 2, dy_ + arm + thick // 2]):
        _paste_grad(base, box, lite, dark, radius=6)
        d.rounded_rectangle(box, 6, outline=(0, 0, 0, 160), width=2)
        d.line([box[0] + 3, box[1] + 2, box[2] - 3, box[1] + 2],
               fill=(255, 255, 255, 60), width=1)
    base.alpha_composite(_sphere(26, dark, lite), (dx_ - 13, dy_ - 13))

    # ---- hinge column ---------------------------------------------------------
    _shadow(base, lambda dd, f, dx, dy: dd.rounded_rectangle(
        [hx1 + dx - 2, hy1 + dy, hx2 + dx + 2, hy2 + dy], 22, fill=f),
        blur=6, alpha=110, dx=2, dy=4)
    hgrad = _vgrad(hx2 - hx1, hy2 - hy1, _scale(body, 1.05),
                   _scale(body, 0.55)).rotate(90, expand=True) \
        .resize((hx2 - hx1, hy2 - hy1))
    hm = Image.new("L", hgrad.size, 0)
    ImageDraw.Draw(hm).rounded_rectangle([0, 0, hgrad.width - 1,
                                          hgrad.height - 1], 22, fill=255)
    base.paste(hgrad.convert("RGBA"), (hx1, hy1), hm)
    d.rounded_rectangle([hx1, hy1, hx2, hy2], 22,
                        outline=_scale(body, 0.35) + (255,), width=2)
    for band_y in (hy1 + 26, hy2 - 26):
        d.line([(hx1 + 3, band_y), (hx2 - 3, band_y)], fill=(0, 0, 0, 90),
               width=2)
        d.line([(hx1 + 3, band_y + 2), (hx2 - 3, band_y + 2)],
               fill=(255, 255, 255, 50), width=1)

    # ---- right panel shell (clipped top-right corner) ------------------------
    rshell = _vgrad(rx2 - rx1, ry2 - ry1, _scale(body, 1.10),
                    _scale(body, 0.58)).convert("RGBA")
    rmask = Image.new("L", rshell.size, 0)
    dm = ImageDraw.Draw(rmask)
    dm.rounded_rectangle([0, 0, rshell.width - 1, rshell.height - 1], 24,
                         fill=255)
    dm.polygon([(rshell.width - 95, 0), (rshell.width, 0),
                (rshell.width, 58)], fill=0)
    base.paste(rshell, (rx1, ry1), rmask)
    d.rounded_rectangle([rx1, ry1, rx2, ry2], 24,
                        outline=_scale(body, 0.35) + (255,), width=3)
    d.polygon([(rx2 - 97, ry1 - 2), (rx2 + 2, ry1 - 2), (rx2 + 2, ry1 + 60)],
              fill=_c(T["room"]) + (255,))
    d.line([(rx2 - 95, ry1), (rx2, ry1 + 58)],
           fill=_scale(body, 0.35) + (255,), width=3)
    d.line([(rx2 - 92, ry1 + 2), (rx2 + 1, ry1 + 58)],
           fill=(255, 255, 255, 55), width=1)

    # console (black secondary display)
    cx1, cy1, cx2, cy2 = L["console"]
    d.rounded_rectangle([cx1 - 4, cy1 - 4, cx2 + 4, cy2 + 4], 10,
                        fill=(20, 22, 20, 255))
    d.rounded_rectangle([cx1, cy1, cx2, cy2], 6,
                        fill=_c(T["console_bg"]) + (255,))
    ish2 = Image.new("RGBA", base.size, (0, 0, 0, 0))
    di2 = ImageDraw.Draw(ish2)
    di2.rectangle([cx1, cy1, cx2, cy1 + 6], fill=(0, 0, 0, 140))
    base.alpha_composite(ish2.filter(ImageFilter.GaussianBlur(2)))

    # blue button grid
    for box in L["grid_buttons"]:
        _gem(base, box, (98, 196, 250), (18, 108, 190), radius=6)

    # white double key
    wx1, wy1, wx2, wy2 = L["white_btns"]
    midx = (wx1 + wx2) // 2
    _gem(base, (wx1, wy1, midx - 2, wy2), (250, 250, 252), (168, 172, 180),
         radius=6)
    _gem(base, (midx + 2, wy1, wx2, wy2), (250, 250, 252), (168, 172, 180),
         radius=6)

    # yellow dome button
    yx, yy, yr = L["yellow"]
    _shadow(base, lambda dd, f, dx, dy: dd.ellipse(
        [yx - yr + dx, yy - yr + dy, yx + yr + dx, yy + yr + dy], fill=f),
        blur=4, alpha=120, dx=2, dy=3)
    dome = _sphere(yr * 2, (150, 108, 8), (255, 226, 92), offset=0.25)
    _specular(dome, yr * 0.7, yr * 0.55, yr * 0.32, yr * 0.22, alpha=200,
              blur=1)
    base.alpha_composite(dome, (int(yx - yr), int(yy - yr)))

    # black slots along the bottom (search bar + status display)
    for box in L["black_slots"]:
        x1, y1, x2, y2 = box
        d.rounded_rectangle([x1 - 3, y1 - 3, x2 + 3, y2 + 3], 8,
                            fill=(20, 22, 20, 255))
        d.rounded_rectangle(box, 6, fill=(8, 10, 8, 255))
    return base


def lens_frames(T, size=100, halo=40, n=14):
    """The domed lens at n brightness levels, dim idle to full flash."""
    frames = []
    deep = _c(T["lens_blue_lo"])
    blue = _c(T["lens_blue"])
    hi = _c(T["lens_blue_hi"])
    full = size + 2 * halo
    ring_w = max(3, int(size * 0.07))
    for k in range(n):
        t = k / (n - 1)
        img = Image.new("RGBA", (full, full), (0, 0, 0, 0))
        g = Image.new("RGBA", (full, full), (0, 0, 0, 0))
        blur = halo // 3
        gr = int(size * 0.5 + halo * (0.25 + 0.60 * t))
        gr = min(gr, full // 2 - blur - 4)   # keep the bloom's blur inside
        ImageDraw.Draw(g).ellipse([full / 2 - gr, full / 2 - gr,
                                   full / 2 + gr, full / 2 + gr],
                                  fill=_lerp(blue, hi, t * 0.7)
                                  + (int(18 + 110 * t),))
        img.alpha_composite(g.filter(ImageFilter.GaussianBlur(blur)))
        ring = _sphere(size, (140, 150, 165), (246, 248, 252), offset=0.25)
        img.alpha_composite(ring, (halo, halo))
        dome = size - 2 * ring_w
        core = _lerp(_lerp(blue, hi, 0.35), (240, 251, 255), t)
        edge = _lerp(deep, blue, 0.25 + 0.30 * t)
        glass = _sphere(dome, edge, core, offset=0.24)
        _specular(glass, dome * 0.34, dome * 0.26, dome * 0.16, dome * 0.10,
                  alpha=int(150 + 90 * t))
        _specular(glass, dome * 0.68, dome * 0.74, dome * 0.10, dome * 0.06,
                  alpha=70, blur=2)
        img.alpha_composite(glass, (halo + ring_w, halo + ring_w))
        frames.append(img)
    return frames


def led(color_hex, on, size=16):
    col = _c(color_hex)
    if not on:
        img = _sphere(size, _scale(col, 0.18), _scale(col, 0.42), offset=0.2)
        return _specular(img, size * 0.36, size * 0.30, size * 0.14,
                         size * 0.10, alpha=60, blur=1)
    pad = 7
    full = size + pad * 2
    img = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    glow = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([1, 1, full - 1, full - 1],
                                 fill=col + (130,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)))
    gem = _sphere(size, _scale(col, 0.55), _lerp(col, (255, 255, 255), 0.6),
                  offset=0.22)
    _specular(gem, size * 0.36, size * 0.28, size * 0.15, size * 0.10,
              alpha=200, blur=1)
    img.alpha_composite(gem, (pad, pad))
    return img

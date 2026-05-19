"""
Generates icon.ico for ScreenBlind.
Run once: python generate_icon.py
Requires: pip install Pillow
"""
from PIL import Image, ImageDraw


def _eye_points(cx, cy, hw, hh, n=300):
    top, bottom = [], []
    for i in range(n + 1):
        t = -1 + 2 * i / n
        x = cx + t * hw
        top.append((x, cy - hh * (1 - t * t)))
        bottom.append((x, cy + hh * (1 - t * t)))
    return top, bottom


def _eye_mask(size, cx, cy, hw, hh):
    m = Image.new("L", (size, size), 0)
    top, bottom = _eye_points(cx, cy, hw, hh)
    ImageDraw.Draw(m).polygon(top + list(reversed(bottom)), fill=255)
    return m


def make_frame(size):
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark rounded-square background
    p = max(1, int(7 * s))
    r = int(56 * s)
    draw.rounded_rectangle([p, p, size - p, size - p], radius=r, fill=(10, 10, 18, 255))

    # Subtle bottom-gradient layer
    gl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(gl).rounded_rectangle(
        [p, size // 2, size - p, size - p], radius=r, fill=(20, 15, 38, 180)
    )
    img = Image.alpha_composite(img, gl)

    cx, cy = size // 2, int(size * 0.50)
    hw = int(98 * s)
    hh = int(50 * s)

    # Venetian blind slats clipped to eye shape
    SLATS = 5
    sl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sl)
    band = (hh * 2) / SLATS
    colors = [(99, 102, 241, 255), (67, 56, 202, 255)]   # indigo alternating
    hi     = (148, 163, 248, 255)                          # slat highlight

    for i in range(SLATS):
        y1 = cy - hh + int(i * band)
        y2 = cy - hh + int((i + 0.76) * band)
        sd.rectangle([cx - hw, y1, cx + hw, y2], fill=colors[i % 2])
        sd.rectangle([cx - hw, y1, cx + hw, y1 + max(1, int(2 * s))], fill=hi)

    sl.putalpha(_eye_mask(size, cx, cy, hw, hh))
    img = Image.alpha_composite(img, sl)

    # Eye outline
    draw = ImageDraw.Draw(img)
    lw = max(2, int(3.5 * s))
    outline = (165, 180, 252, 255)   # #a5b4fc light indigo
    top_pts, bot_pts = _eye_points(cx, cy, hw, hh)
    for pts in (top_pts, bot_pts):
        for j in range(len(pts) - 1):
            draw.line([pts[j], pts[j + 1]], fill=outline, width=lw)

    # Corner eyelash accents
    lash_len = int(14 * s)
    lash_w   = max(1, int(2 * s))
    lash_col = (165, 180, 252, 160)
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        tip_x = cx + dx * int(hw * 0.85)
        tip_y = cy + dy * int(hh * 0.15)
        draw.line(
            [tip_x, tip_y, tip_x + dx * lash_len, tip_y + dy * lash_len],
            fill=lash_col, width=lash_w,
        )

    # Rose pupil dot
    pr = max(2, int(13 * s))
    draw.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(225, 29, 72, 255))

    # Thin rose ring around pupil
    draw.ellipse(
        [cx - pr - int(2*s), cy - pr - int(2*s), cx + pr + int(2*s), cy + pr + int(2*s)],
        outline=(225, 29, 72, 120), width=max(1, int(1.5*s)),
    )

    return img


if __name__ == "__main__":
    sizes = [256, 48, 32, 16]
    imgs = [make_frame(s) for s in sizes]
    imgs[0].save(
        "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=imgs[1:],
    )
    print("icon.ico created.")

"""Find Minotaur Nest UI coordinates for Jitbit macro.

Run this script THREE times at different game states:
  1. Standing near the portal in town (ready to enter)
  2. At the loot screen after boss dies
  3. At the exit/retreat screen after looting

Each run saves a PNG + annotated PNG and prints candidate coordinates.
"""
import os
import sys
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

# -- Capture ---------------------------------------------------------------
try:
    import mss
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: pip install mss pillow")
    sys.exit(1)

REGION = {"left": 8, "top": 31, "width": 1024, "height": 768}
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class PixelMatch:
    label: str
    cx: int
    cy: int
    box: tuple  # (left, top, right, bottom)


def find_golden_buttons(pixels: Image.Image, quadrant: str = "any") -> list[PixelMatch]:
    """Find clusters of golden/yellow pixels (UI buttons in Dragon Nest).

    Golden pixels: R > 180, G > 140, B < 80, saturated warm tone.
    """
    w, h = pixels.size
    q_bounds = {
        "any":     (0, 0, w, h),
        "right":   (w // 2, 0, w, h),
        "bottom":  (0, h // 2, w, h),
        "center":  (w // 4, h // 4, 3 * w // 4, 3 * h // 4),
        "bottom_right": (w // 2, h // 2, w, h),
    }
    x1, y1, x2, y2 = q_bounds.get(quadrant, q_bounds["any"])

    matches: list[tuple[int, int]] = []
    for y in range(y1, y2, 2):  # sample every 2px
        for x in range(x1, x2, 2):
            r, g, b = pixels.getpixel((x, y))[:3]
            if r > 160 and g > 120 and b < 100 and r > g > b:
                matches.append((x, y))

    if not matches:
        return []

    # Cluster nearby pixels (20px radius)
    clusters: list[list[tuple[int, int]]] = []
    used = set()
    for px, py in matches:
        if (px, py) in used:
            continue
        cluster = [(px, py)]
        used.add((px, py))
        for qx, qy in matches:
            if (qx, qy) in used:
                continue
            if abs(qx - px) <= 30 and abs(qy - py) <= 30:
                cluster.append((qx, qy))
                used.add((qx, qy))
        if len(cluster) >= 5:  # filter noise
            clusters.append(cluster)

    results = []
    for i, cluster in enumerate(clusters):
        xs = [p[0] for p in cluster]
        ys = [p[1] for p in cluster]
        box = (min(xs), min(ys), max(xs), max(ys))
        bw, bh = box[2] - box[0], box[3] - box[1]
        # Buttons are roughly 80-250px wide, 20-60px tall
        if 60 <= bw <= 300 and 15 <= bh <= 80:
            results.append(PixelMatch(
                label=f"golden_btn_{i}",
                cx=(box[0] + box[2]) // 2,
                cy=(box[1] + box[3]) // 2,
                box=box,
            ))

    return results


def find_blue_text(pixels: Image.Image, quadrant: str = "any") -> list[PixelMatch]:
    """Find clusters of blue/cyan pixels (menu text, portal labels).

    Blue pixels: B > 180, R < 120, G < 180.
    """
    w, h = pixels.size
    q_bounds = {
        "any":     (0, 0, w, h),
        "bottom":  (0, h // 2, w, h),
        "center":  (w // 4, h // 4, 3 * w // 4, 3 * h // 4),
    }
    x1, y1, x2, y2 = q_bounds.get(quadrant, q_bounds["any"])

    matches = []
    for y in range(y1, y2, 3):
        for x in range(x1, x2, 3):
            r, g, b = pixels.getpixel((x, y))[:3]
            if b > 160 and r < 140 and b > r + 30:
                matches.append((x, y))

    if not matches:
        return []

    clusters = []
    used = set()
    for px, py in matches:
        if (px, py) in used:
            continue
        cluster = [(px, py)]
        used.add((px, py))
        for qx, qy in matches:
            if (qx, qy) in used:
                continue
            if abs(qx - px) <= 25 and abs(qy - py) <= 25:
                cluster.append((qx, qy))
                used.add((qx, qy))
        if len(cluster) >= 8:
            clusters.append(cluster)

    results = []
    for i, cluster in enumerate(clusters[:5]):
        xs = [p[0] for p in cluster]
        ys = [p[1] for p in cluster]
        box = (min(xs), min(ys), max(xs), max(ys))
        results.append(PixelMatch(
            label=f"blue_text_{i}",
            cx=(box[0] + box[2]) // 2,
            cy=(box[1] + box[3]) // 2,
            box=box,
        ))

    return results


def find_bright_glow(pixels: Image.Image) -> list[PixelMatch]:
    """Find bright glowing regions (portal glow, loot sparkle).

    Very bright pixels: all channels > 200, or specific glow patterns.
    """
    w, h = pixels.size
    matches = []
    for y in range(h // 4, 3 * h // 4, 3):
        for x in range(w // 4, 3 * w // 4, 3):
            r, g, b = pixels.getpixel((x, y))[:3]
            if r > 200 and g > 200 and b > 180:
                matches.append((x, y))

    if len(matches) < 50:
        return []

    xs = [p[0] for p in matches]
    ys = [p[1] for p in matches]
    return [PixelMatch(
        label="bright_glow",
        cx=sum(xs) // len(xs),
        cy=sum(ys) // len(ys),
        box=(min(xs), min(ys), max(xs), max(ys)),
    )]


def annotate_image(img: Image.Image, candidates: list[PixelMatch], save_path: str):
    """Draw green boxes + crosshairs on detected elements."""
    draw = ImageDraw.Draw(img)
    for c in candidates:
        x1, y1, x2, y2 = c.box
        draw.rectangle([x1 - 2, y1 - 2, x2 + 2, y2 + 2], outline="lime", width=2)
        # Crosshair at center
        draw.line([(c.cx - 8, c.cy), (c.cx + 8, c.cy)], fill="red", width=2)
        draw.line([(c.cx, c.cy - 8), (c.cx, c.cy + 8)], fill="red", width=2)
        # Label
        draw.text((c.cx + 10, c.cy - 8), c.label, fill="lime")
    img.save(save_path)


def main():
    print("=" * 60)
    print("Minotaur Nest Coordinate Finder")
    print("=" * 60)
    print()
    print("Posisikan game ke momen yang ingin dicari koordinatnya,")
    print("lalu pilih mode:")
    print()
    print("  1. Portal di town (sebelum masuk nest)")
    print("  2. Dialog Enter/Cancel")
    print("  3. Loot screen (setelah boss mati)")
    print("  4. Exit/Retreat screen")
    print("  5. Custom (analisis semua)")
    print()
    choice = input("Pilih [1-5]: ").strip() or "5"

    modes = {
        "1": ("portal", "Cari tombol portal + glow di tengah layar", "center"),
        "2": ("dialog_enter", "Analisis tombol Enter/Cancel di kanan bawah", "bottom_right"),
        "3": ("loot", "Cari tombol loot / chest glow", "center"),
        "4": ("exit", "Cari tombol keluar/retreat di bawah", "bottom"),
        "5": ("custom", "Analisis semua area", "any"),
    }
    label, desc, quadrant = modes.get(choice, modes["5"])

    print(f"\nMode: {desc}")
    print("Fokus jendela game dalam 3 detik...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    # Capture
    with mss.mss() as sct:
        screenshot = sct.grab(REGION)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(OUTPUT_DIR, f"macro_coord_{label}_{ts}.png")
    annotated_path = os.path.join(OUTPUT_DIR, f"macro_coord_{label}_{ts}_annotated.png")

    img.save(raw_path)
    print(f"\nRaw screenshot: {raw_path}")

    # Analyze
    golden = find_golden_buttons(img, quadrant)
    blue = find_blue_text(img, quadrant)
    glow = find_bright_glow(img)

    all_candidates = golden + blue + glow
    print(f"\nDetected {len(all_candidates)} candidates:")
    print(f"  Golden buttons: {len(golden)}")
    print(f"  Blue text:      {len(blue)}")
    print(f"  Bright glows:   {len(glow)}")

    if golden:
        print("\n  -- Golden/Yellow Buttons --")
        for g in golden:
            print(f"  [{g.cx:>4}, {g.cy:>4}] box=({g.box[0]},{g.box[1]})-({g.box[2]},{g.box[3]})")

    if blue:
        print("\n  -- Blue Text Regions --")
        for b in blue:
            print(f"  [{b.cx:>4}, {b.cy:>4}] box=({b.box[0]},{b.box[1]})-({b.box[2]},{b.box[3]})")

    if glow:
        print("\n  -- Bright Glows --")
        for gl in glow:
            print(f"  [{gl.cx:>4}, {gl.cy:>4}] box=({gl.box[0]},{gl.box[1]})-({gl.box[2]},{gl.box[3]})")

    # Annotate
    annotate_img = img.copy()
    annotate_image(annotate_img, all_candidates, annotated_path)
    print(f"\nAnnotated: {annotated_path}")
    print("Buka file annotated untuk verifikasi visual — crosshair merah = titik tengah.")

    # Summary table
    print("\n" + "=" * 60)
    print("SUMMARY — tambahkan ke .macro-notes.md:")
    print("=" * 60)
    coords = []
    if golden:
        best = golden[0]
        coords.append((f"Tombol (golden) #{label}", best.cx, best.cy))
    if glow:
        best = glow[0]
        coords.append((f"Glow center #{label}", best.cx, best.cy))
    if blue:
        best = blue[0]
        coords.append((f"Blue text #{label}", best.cx, best.cy))

    if coords:
        for name, cx, cy in coords:
            print(f"  {name:<35} [{cx:>4}, {cy:>4}]")
    else:
        print("  (Tidak ada kandidat terdeteksi — cek manual dari screenshot)")

    # Always include the known Enter coordinate
    if choice == "2":
        print(f"  Tombol Enter (referensi analisis sebelumnya) [ 729,  493]")

    print(f"\nScreenshot disimpan. Kalau kandidat tidak akurat,")
    print(f"buka {raw_path} di Paint, hover kursor ke target,")
    print(f"baca koordinat di status bar (kiri bawah).")


if __name__ == "__main__":
    main()

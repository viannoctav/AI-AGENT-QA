"""Persiapan gambar (murni kode, tanpa AI):
- papan alur (beberapa layar berjajar di atas latar polos) dipotong menjadi layar-layar;
- layar dengan latar diburamkan (ada modal/panel/menu di depan) dipotong ke area yang tajam saja;
- layar yang sama persis hanya dibaca sekali."""
import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageFilter, ImageStat

Image.MAX_IMAGE_PIXELS = None  # export satu halaman Figma bisa ratusan juta piksel; file milik QA sendiri

BLOCK = 16


def _is_bg(c, bg, tol=24):
    return all(abs(a - b) < tol for a, b in zip(c, bg))


def _runs(flags, minlen):
    """Rentang berturut-turut yang BUKAN latar (False) dan cukup panjang."""
    out, start = [], None
    for i, bg in enumerate(list(flags) + [True]):
        if not bg and start is None:
            start = i
        if bg and start is not None:
            if i - start >= minlen:
                out.append((start, i))
            start = None
    return out


def _split_once(im: Image.Image) -> List[Tuple[int, int, int, int]]:
    """Satu tingkat: kotak-kotak di atas latar polos (tepi gambar seluruhnya warna latar). Tidak ada -> []."""
    w, h = im.size
    f = max(1, math.ceil(max(w, h) / 1600))  # deteksi di versi kecil supaya cepat, lalu dirapikan di ukuran asli
    sm = im.reduce(f) if f > 1 else im
    sw, sh = sm.size
    if sw < 20 or sh < 20:
        return [], None
    px = sm.load()
    border = [px[x, 1] for x in range(0, sw, 3)] + [px[x, sh - 2] for x in range(0, sw, 3)] + \
             [px[1, y] for y in range(0, sh, 3)] + [px[sw - 2, y] for y in range(0, sh, 3)]
    counts = sorted(((sum(_is_bg(c, b) for c in border) / len(border), b) for b in set(border)), reverse=True)
    plain = counts[0][0] >= 0.9  # tepi polos satu warna -> papan alur biasa
    if not plain and max(w, h) <= 4000:
        return [], None  # tepi tidak polos dan gambar tidak besar -> ini layar, bukan papan
    cands, seen = [], []
    for share, b in counts:  # export besar (mis. satu halaman Figma): section bisa menempel ke tepi gambar
        if (share >= 0.2 or not cands) and not any(_is_bg(b, x) for x in seen):
            cands.append(b)
            seen.append(b)
        if max(w, h) <= 4000:
            break
    first = None
    for bg in cands:
        boxes = _boxes_on(im, sm, px, f, bg)
        if len(boxes) >= 2:
            return boxes, bg
        first = (boxes, bg) if first is None else first
    return first if plain else ([], None)


def _boxes_on(im, sm, px, f, bg):
    """Potong rekursif baris/kolom latar (XY-cut) di versi kecil, lalu rapikan tiap kotak di ukuran asli."""
    w, h = im.size
    minlen = max(3, 60 // f)
    regions = []

    def cut(x0, y0, x1, y1, depth=0):
        xs = range(x0, x1, 2)
        rows = [sum(_is_bg(px[x, y], bg) for x in xs) >= 0.98 * len(xs) for y in range(y0, y1)]
        runs = [(y0 + a, y0 + b) for a, b in _runs(rows, minlen)]
        if len(runs) >= 2 and depth < 12:
            for a, b in runs:
                cut(x0, a, x1, b, depth + 1)
            return
        if runs:
            y0, y1 = runs[0]
        ys = range(y0, y1, 2)
        cols = [sum(_is_bg(px[x, y], bg) for y in ys) >= 0.97 * len(ys) for x in range(x0, x1)]
        cruns = [(x0 + a, x0 + b) for a, b in _runs(cols, minlen)]
        if len(cruns) >= 2 and depth < 12:
            for a, b in cruns:
                cut(a, y0, b, y1, depth + 1)
            return
        if cruns:
            regions.append((cruns[0][0], y0, cruns[0][1], y1))

    cut(0, 0, sm.size[0], sm.size[1])
    boxes = []
    for x0, y0, x1, y1 in regions:
        box = _tighten(im, (max(0, (x0 - 1) * f), max(0, (y0 - 1) * f), min(w, (x1 + 1) * f), min(h, (y1 + 1) * f)), bg)
        if box[2] - box[0] >= 80 and box[3] - box[1] >= 40:
            boxes.append(box)
    return boxes


def _tighten(im, box, bg):
    """Rapatkan tepi kotak di ukuran asli: buang baris/kolom tepi yang masih warna latar."""
    x0, y0, x1, y1 = box
    px = im.load()
    line_bg = lambda pts: sum(_is_bg(px[x, y], bg) for x, y in pts) >= 0.98 * max(1, len(pts))
    while y1 - y0 > 2 and line_bg([(x, y0) for x in range(x0, x1, 3)]):
        y0 += 1
    while y1 - y0 > 2 and line_bg([(x, y1 - 1) for x in range(x0, x1, 3)]):
        y1 -= 1
    while x1 - x0 > 2 and line_bg([(x0, y) for y in range(y0, y1, 3)]):
        x0 += 1
    while x1 - x0 > 2 and line_bg([(x1 - 1, y) for y in range(y0, y1, 3)]):
        x1 -= 1
    return (x0, y0, x1, y1)


def _contrast(im, boxes, bg):
    """Rata-rata beda terang isi kotak dengan warna latar. Layar di atas section/kanvas: beda jelas.
    Potongan di dalam satu layar (kolom tabel, kartu): warnanya mirip latar layar itu sendiri."""
    g = sum(bg) / 3
    vals = []
    for b in boxes:
        c = im.crop(b)
        k = max(1, max(c.size) // 64)
        vals.append(abs(ImageStat.Stat((c.reduce(k) if k > 1 else c).convert("L")).mean[0] - g))
    return sum(vals) / max(1, len(vals))


def split_board(im: Image.Image, depth: int = 0) -> List[Tuple[int, int, int, int]]:
    """Kotak setiap layar, urut baris demi baris lalu kiri ke kanan. Papan bisa bertingkat (mis. export satu halaman
    Figma: kanvas -> section -> layar), jadi setiap kotak dicek lagi apakah berisi beberapa layar. Gambar biasa -> 1 kotak."""
    w, h = im.size
    boxes, bg = _split_once(im)
    if not boxes or (depth > 0 and (len(boxes) < 2 or _contrast(im, boxes, bg) < 40)):
        return [(0, 0, w, h)]
    if depth >= 3:
        return boxes
    out = []
    for b in boxes:
        sub = split_board(im.crop(b), depth + 1)
        area = (b[2] - b[0]) * (b[3] - b[1])
        if len(sub) >= 2 and sum((x[2] - x[0]) * (x[3] - x[1]) for x in sub) >= 0.25 * area:
            out += [(b[0] + x[0], b[1] + x[1], b[0] + x[2], b[1] + x[3]) for x in sub]
        else:
            out.append(b)
    return out


def focus_box(im: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """Bila latar diburamkan (modal/panel/menu di depan), kotak area yang tajam saja. Layar penuh tajam -> None."""
    B = BLOCK
    w, h = im.size
    if w < 500:
        return None
    e = im.convert("L").filter(ImageFilter.FIND_EDGES).load()
    top, nx, ny = int(h * 0.09) // B, w // B, h // B
    sharp = {(bx, by) for by in range(top, ny - 1) for bx in range(1, nx - 1)
             if sum(1 for y in range(by * B, by * B + B, 2) for x in range(bx * B, bx * B + B, 2) if e[x, y] > 40) >= 6}
    total = max(1, (ny - top) * nx)
    if not sharp or len(sharp) / total > 0.25:
        return None
    # latar BURAM (bukan sekadar area kosong): blok tanpa garis tajam tetapi warnanya bergradasi
    g = im.convert("L")
    blurred = sum(1 for by in range(top, ny - 1) for bx in range(1, nx - 1) if (bx, by) not in sharp
                  and ImageStat.Stat(g.crop((bx * B, by * B, bx * B + B, by * B + B))).stddev[0] > 2.5)
    if blurred / total < 0.2:  # layar yang memang banyak ruang kosong -> tidak dipotong
        return None
    seen, comps = set(), []
    for b in sharp:
        if b in seen:
            continue
        stack, comp = [b], []
        seen.add(b)
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    n = (x + dx, y + dy)
                    if n in sharp and n not in seen:
                        seen.add(n)
                        stack.append(n)
        comps.append(comp)

    def box(c):
        return [min(p[0] for p in c), min(p[1] for p in c), max(p[0] for p in c) + 1, max(p[1] for p in c) + 1]

    comps.sort(key=len, reverse=True)
    x0, y0, x1, y1 = box(comps[0])
    for c in comps[1:]:  # bagian lain yang segaris (mis. tombol Close di bawah panel) ikut
        a, b2, c2, d = box(c)
        if min(x1, c2) - max(x0, a) > 0.5 * (c2 - a):
            x0, y0, x1, y1 = min(x0, a), min(y0, b2), max(x1, c2), max(y1, d)
    box_ = (max(0, x0 * B - 24), max(0, y0 * B - 24), min(w, x1 * B + 24), min(h, y1 * B + 24))
    if (box_[2] - box_[0]) * (box_[3] - box_[1]) < 0.08 * w * h:  # terlalu kecil -> lebih aman tidak dipotong
        return None
    return box_


def load(path: Path) -> Image.Image:
    im = Image.open(path)
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] == 255:
        return im.convert("RGB")  # tidak ada bagian transparan
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bgim = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bgim.alpha_composite(im)
        im = bgim
    return im.convert("RGB")


def count_screens(path: Path) -> int:
    """Perkiraan jumlah layar dalam satu gambar (untuk estimasi waktu di dashboard)."""
    try:
        return len(split_board(load(path)))
    except Exception:
        return 1


def prepare(images: List[Dict[str, Any]], out_dir: Path, seen: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """images: [{"path", "name"}] urut sesuai unggahan. Hasil: daftar layar
    {"id", "image", "order", "path", "focused", "duplicate_of"} dengan potongan tersimpan di out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    screens = []
    seen = {} if seen is None else seen  # dibagi antar halaman: layar kembar di halaman lain juga dikenali
    for img in images:
        im = load(Path(img["path"]))
        stem = Path(img["name"]).stem
        boxes = split_board(im)
        for i, bx in enumerate(boxes, 1):
            crop = im.crop(bx)
            fb = focus_box(crop)
            if fb:
                crop = crop.crop(fb)
            digest = hashlib.sha1(crop.tobytes()).hexdigest()
            sid = f"{stem}_{i:02d}" if len(boxes) > 1 else stem
            p = out_dir / f"{sid}.png"
            crop.save(p)
            screens.append({"id": sid, "image": img["name"], "order": i, "of": len(boxes), "path": str(p),
                            "focused": bool(fb), "size": list(crop.size), "duplicate_of": seen.get(digest)})
            seen.setdefault(digest, sid)
    return screens

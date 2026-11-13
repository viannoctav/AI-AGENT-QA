"""Markdown -> PDF tanpa library tambahan (hanya Python bawaan).

Dipakai fitur MD Konversi ke PDF. Mendukung yang biasa ada di PRD:
judul (# sampai ######), paragraf, **tebal**, *miring*, `kode`, tautan, daftar berpoin dan bernomor (bertingkat),
kutipan (>), tabel, blok kode (```), dan garis pemisah (---). Halaman A4 dengan nomor halaman di bawah."""
import re
import unicodedata
from typing import List, Optional, Tuple

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 56.0, 60.0, 62.0
USABLE = PAGE_W - 2 * MARGIN_X

# lebar huruf Helvetica (1/1000 em) untuk karakter 32-126
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
        [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722,
         778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556,
         556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500,
         334, 260, 334, 584]

F_REG, F_BOLD, F_IT, F_MONO = "F1", "F2", "F3", "F4"
INK = (0.09, 0.10, 0.20)
HEAD = (0.08, 0.10, 0.25)
MUTED = (0.38, 0.40, 0.50)
LINE = (0.80, 0.80, 0.86)
FILL = (0.95, 0.95, 0.98)
CODE_FILL = (0.96, 0.96, 0.97)

_REPL = {"→": "->", "←": "<-", "⇒": "=>", "≤": "<=", "≥": ">=", "≠": "!=", "✓": "v", "✔": "v", "✗": "x", "✘": "x",
         "☐": "[ ]", "☑": "[x]", "Ǝ": "E", "ᗩ": "A", "−": "-", " ": " ", "\t": "    "}


def clean(s: str) -> str:
    """Huruf yang tidak ada di font standar PDF diganti padanan terdekat (é tetap é, “ ” tetap)."""
    for k, v in _REPL.items():
        s = s.replace(k, v)
    out = []
    for ch in s:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            base = unicodedata.normalize("NFKD", ch).encode("cp1252", "ignore").decode("cp1252")
            out.append(base or "?")
    return "".join(out)


def text_width(s: str, font: str, size: float) -> float:
    if font == F_MONO:
        return len(s) * 600 * size / 1000
    w = sum(_HELV[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in s)
    return w * size / 1000 * (1.06 if font == F_BOLD else 1.0)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


# ----------------------------------------------------------------------------- teks bergaya dalam satu baris
Run = Tuple[str, str]  # (teks, font)
_INLINE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|(?<![\w])_[^_\s][^_]*_(?![\w])|\[[^\]]+\]\([^)]+\))")


def inline_runs(text: str, base: str = F_REG) -> List[Run]:
    runs: List[Run] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], base))
        tok = m.group(0)
        if tok.startswith("`"):
            runs.append((tok[1:-1], F_MONO))
        elif tok.startswith(("**", "__")):
            runs.append((tok[2:-2], F_BOLD))
        elif tok.startswith("["):
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok).groups()
            runs.append((label if label == url else f"{label} ({url})", base))
        else:
            runs.append((tok[1:-1], F_BOLD if base == F_BOLD else F_IT))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], base))
    return [(clean(t), f) for t, f in runs if t]


def wrap_runs(runs: List[Run], size: float, width: float) -> List[List[Run]]:
    """Pecah teks bergaya menjadi baris-baris yang muat di lebar tertentu."""
    words: List[Tuple[str, str, bool]] = []  # (kata, font, ada spasi sebelumnya)
    space_before = False
    for text, font in runs:
        for part in re.split(r"(\s+)", text):
            if not part:
                continue
            if part.isspace():
                space_before = True
                continue
            words.append((part, font, space_before))
            space_before = False
    lines: List[List[Run]] = []
    line: List[Run] = []
    w = 0.0
    for word, font, sp in words:
        gap = text_width(" ", font, size) if (sp and line) else 0.0
        ww = text_width(word, font, size)
        if line and w + gap + ww > width:
            lines.append(line)
            line, w, gap = [], 0.0, 0.0
        while ww > width and len(word) > 1:  # kata yang sangat panjang (URL) dipotong paksa
            cut = len(word)
            while cut > 1 and text_width(word[:cut], font, size) > width - w:
                cut -= 1
            line.append((word[:cut], font))
            lines.append(line)
            line, w, gap = [], 0.0, 0.0
            word = word[cut:]
            ww = text_width(word, font, size)
        if gap:
            line.append((" ", font))
        line.append((word, font))
        w += gap + ww
    if line:
        lines.append(line)
    return lines or [[("", F_REG)]]


# ----------------------------------------------------------------------------- halaman
class Doc:
    def __init__(self):
        self.pages: List[List[str]] = []
        self.ops: List[str] = []
        self.y = 0.0
        self.new_page()

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)
        self.y = PAGE_H - MARGIN_TOP

    def need(self, h: float):
        if self.y - h < MARGIN_BOTTOM and self.y < PAGE_H - MARGIN_TOP - 1:
            self.new_page()

    def text(self, x: float, y: float, runs: List[Run], size: float, color=INK):
        parts = [f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg BT {x:.2f} {y:.2f} Td"]
        cur = None
        for t, f in runs:
            if f != cur:
                parts.append(f"/{f} {size:g} Tf")
                cur = f
            parts.append(f"({_esc(t)}) Tj")
        parts.append("ET")
        self.ops.append(" ".join(parts))

    def rect(self, x, y, w, h, fill=None, stroke=None, width=0.6):
        s = []
        if fill:
            s.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg")
        if stroke:
            s.append(f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG {width:g} w")
        s.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {'B' if fill and stroke else 'f' if fill else 'S'}")
        self.ops.append(" ".join(s))

    def line(self, x1, y1, x2, y2, color=LINE, width=0.6):
        self.ops.append(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG {width:g} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def paragraph(self, runs: List[Run], size=10.5, indent=0.0, color=INK, lead=1.45, after=5.0, bar=False):
        lines = wrap_runs(runs, size, USABLE - indent)
        for ln in lines:
            h = size * lead
            self.need(h)
            self.y -= h
            if bar:
                self.rect(MARGIN_X + indent - 10, self.y - size * 0.35, 2.2, h, fill=LINE)
            self.text(MARGIN_X + indent, self.y, ln, size, color)
        self.y -= after


HEADINGS = {1: (18, 10, 8), 2: (14.5, 14, 6), 3: (12.5, 10, 4), 4: (11.2, 8, 3), 5: (10.5, 6, 2), 6: (10.5, 6, 2)}


def _table(doc: Doc, rows: List[List[str]], has_header: bool):
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    size, pad = 9.2, 5.0
    cells = [[inline_runs(c, F_BOLD if (has_header and i == 0) else F_REG) for c in r] for i, r in enumerate(rows)]
    natural = [max(sum(text_width(t, f, size) for t, f in cells[i][j]) for i in range(len(rows))) + 2 * pad
               for j in range(ncol)]
    longest = [max((text_width(w, F_BOLD, size) for i in range(len(rows)) for t, _ in cells[i][j] for w in t.split()),
                   default=0) + 2 * pad for j in range(ncol)]
    if sum(natural) <= USABLE:
        widths = [n * USABLE / sum(natural) for n in natural]
    else:  # kolom pendek diberi selebar isinya, sisanya dibagi ke kolom panjang
        widths = [max(min(n, USABLE / ncol), min(l, USABLE * 0.35), 44) for n, l in zip(natural, longest)]
        rest = USABLE - sum(widths)
        extra = [max(0.0, n - w) for n, w in zip(natural, widths)]
        if rest > 0 and sum(extra):
            widths = [w + rest * e / sum(extra) for w, e in zip(widths, extra)]
        widths = [w * USABLE / sum(widths) for w in widths]
    lead = size * 1.35

    def layout(i):
        wrapped = [wrap_runs(cells[i][j], size, widths[j] - 2 * pad) for j in range(ncol)]
        return wrapped, max(len(w) for w in wrapped) * lead + 2 * pad - 2

    def draw(i, wrapped, h):
        x = MARGIN_X
        top = doc.y
        for j in range(ncol):
            doc.rect(x, top - h, widths[j], h, fill=FILL if (has_header and i == 0) else None, stroke=LINE)
            ty = top - pad - size * 0.95
            for ln in wrapped[j]:
                doc.text(x + pad, ty, ln, size, HEAD if (has_header and i == 0) else INK)
                ty -= lead
            x += widths[j]
        doc.y -= h

    header = layout(0) if has_header else None
    doc.y -= 2
    for i in range(len(rows)):
        wrapped, h = header if (has_header and i == 0) else layout(i)
        if doc.y - h < MARGIN_BOTTOM:
            doc.new_page()
            if has_header and i > 0:  # judul kolom diulang di halaman baru
                draw(0, *header)
        draw(i, wrapped, h)
    doc.y -= 8


def _code(doc: Doc, lines: List[str]):
    size, lead = 8.8, 8.8 * 1.4
    per_line = max(10, int((USABLE - 16) / (600 * size / 1000)))
    out: List[str] = []
    for ln in lines:
        ln = clean(ln.replace("\t", "    "))
        out.extend([ln[i:i + per_line] for i in range(0, len(ln), per_line)] or [""])
    doc.y -= 2
    i = 0
    while i < len(out):
        room = int((doc.y - MARGIN_BOTTOM - 8) // lead)
        if room < 1:
            doc.new_page()
            continue
        chunk = out[i:i + room]
        h = len(chunk) * lead + 8
        doc.rect(MARGIN_X, doc.y - h, USABLE, h, fill=CODE_FILL)
        y = doc.y - 4 - size
        for ln in chunk:
            doc.text(MARGIN_X + 8, y, [(ln, F_MONO)], size)
            y -= lead
        doc.y -= h
        i += len(chunk)
    doc.y -= 8


_LIST = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _cells(line: str) -> List[str]:
    t = line.strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|") and not t.endswith("\\|"):
        t = t[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", t)]


def markdown_to_pdf(md: str, title: str = "") -> bytes:
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not title:
        h = next((l for l in lines if re.match(r"^#\s+\S", l)), "")
        title = re.sub(r"^#\s+", "", h).strip()
    title = clean(re.sub(r"[*_`]", "", title))
    doc = Doc()
    para: List[str] = []

    def flush_para():
        if para:
            doc.paragraph(inline_runs(" ".join(s.strip() for s in para)))
            para.clear()

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s:
            flush_para()
            i += 1
            continue
        if s.startswith("```") or s.startswith("~~~"):
            flush_para()
            fence = s[:3]
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                block.append(lines[i])
                i += 1
            _code(doc, block)
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if m:
            flush_para()
            lvl = len(m.group(1))
            size, before, after = HEADINGS[lvl]
            doc.y -= before if doc.y < PAGE_H - MARGIN_TOP - 1 else 0
            doc.need(size * 1.4 + 24)  # judul tidak boleh sendirian di dasar halaman
            doc.paragraph(inline_runs(m.group(2), F_BOLD), size=size, color=HEAD, lead=1.3, after=0)
            if lvl <= 2:
                doc.y -= size * 0.45
                doc.line(MARGIN_X, doc.y, MARGIN_X + USABLE, doc.y,
                         color=(0.35, 0.15, 0.91) if lvl == 1 else LINE, width=1.2 if lvl == 1 else 0.6)
            doc.y -= after
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s.replace(" ", "")):
            flush_para()
            doc.need(14)
            doc.y -= 7
            doc.line(MARGIN_X, doc.y, MARGIN_X + USABLE, doc.y)
            doc.y -= 9
            i += 1
            continue
        if "|" in s and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush_para()
            rows = [_cells(s)]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            _table(doc, rows, True)
            continue
        if s.startswith(">"):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]).strip())
                i += 1
            doc.paragraph(inline_runs(" ".join(q for q in quote if q), F_IT), indent=14, color=MUTED, bar=True)
            continue
        m = _LIST.match(raw)
        if m:
            flush_para()
            depth = len(m.group(1).replace("\t", "    ")) // 2
            marker = m.group(2)
            body = m.group(3)
            cb = re.match(r"^\[([ xX])\]\s+(.*)$", body)
            if cb:
                marker, body = ("[x]" if cb.group(1).lower() == "x" else "[ ]"), cb.group(2)
            elif marker in "-*+":
                marker = "\u2022" if depth % 2 == 0 else "\u2013"  # titik poin, tingkat kedua memakai garis
            # baris lanjutan (menjorok, bukan poin baru) digabung ke poin ini
            j = i + 1
            while j < len(lines) and lines[j].strip() and not _LIST.match(lines[j]) and lines[j].startswith((" ", "\t")) \
                    and not lines[j].strip().startswith(("#", ">", "|", "```")):
                body += " " + lines[j].strip()
                j += 1
            indent = 6 + depth * 16
            size = 10.5
            mw = max(text_width(marker, F_REG, size) + 6, 14)
            wrapped = wrap_runs(inline_runs(body), size, USABLE - indent - mw)
            for k, ln in enumerate(wrapped):
                h = size * 1.45
                doc.need(h)
                doc.y -= h
                if k == 0:
                    doc.text(MARGIN_X + indent, doc.y, [(marker, F_REG)], size, HEAD)
                doc.text(MARGIN_X + indent + mw, doc.y, ln, size)
            doc.y -= 2.5
            i = j
            continue
        para.append(s)
        i += 1
    flush_para()

    # nomor halaman
    n = len(doc.pages)
    for k, ops in enumerate(doc.pages, 1):
        foot = f"Halaman {k} dari {n}"
        y = 32
        ops.append(f"{LINE[0]} {LINE[1]} {LINE[2]} RG 0.5 w {MARGIN_X} {y + 12} m {MARGIN_X + USABLE} {y + 12} l S")
        if title:
            t = title
            while t and text_width(t, F_REG, 8) > USABLE - 90:
                t = t[:-2]
            ops.append(f"{MUTED[0]} {MUTED[1]} {MUTED[2]} rg BT /F1 8 Tf {MARGIN_X} {y} Td ({_esc(t if t == title else t + '...')}) Tj ET")
        ops.append(f"{MUTED[0]} {MUTED[1]} {MUTED[2]} rg BT /F1 8 Tf {MARGIN_X + USABLE - text_width(foot, F_REG, 8):.2f} {y} Td ({_esc(foot)}) Tj ET")
    return _write(doc.pages, title)


def _write(pages: List[List[str]], title: str) -> bytes:
    fonts = [("Helvetica", F_REG), ("Helvetica-Bold", F_BOLD), ("Helvetica-Oblique", F_IT), ("Courier", F_MONO)]
    objs: List[bytes] = []
    n_pages = len(pages)
    first_page = 3 + len(fonts) + 1  # 1 katalog, 2 daftar halaman, font, info, lalu (halaman, isi)
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for base, _ in fonts:
        objs.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>".encode())
    objs.append(b"<< /Title <" + ("\ufeff" + title).encode("utf-16-be").hex().upper().encode()
                + b"> /Creator (TERA) /Producer (TERA) >>")
    font_res = " ".join(f"/{key} {3 + k} 0 R" for k, (_, key) in enumerate(fonts))
    for i, ops in enumerate(pages):
        content = "\n".join(ops).encode("cp1252", "replace")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:g} {PAGE_H:g}] "
                    f"/Resources << /Font << {font_res} >> >> /Contents {first_page + 2 * i + 1} 0 R >>".encode())
        objs.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for k, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    info = 3 + len(fonts)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def pdf_name(md_name: str) -> str:
    stem = re.sub(r"\.(md|markdown)$", "", str(md_name or "dokumen"), flags=re.I).strip() or "dokumen"
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", stem)[:120]
    return f"{stem}.pdf"


def first_heading(md: str) -> Optional[str]:
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else None

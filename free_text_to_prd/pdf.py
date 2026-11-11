"""PDF sederhana tanpa library tambahan (hanya Python bawaan).
Mengubah Markdown sederhana (#, ##, -, paragraf) menjadi PDF A4 berfont Helvetica dengan pindah baris dan halaman."""
import re
from typing import List, Tuple

# lebar huruf Helvetica (satuan 1/1000 em) untuk karakter 32-126; karakter lain dianggap 556
_W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
     [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
      667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
      278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
      260, 334, 584]

PAGE_W, PAGE_H, MARGIN = 595, 842, 56
_REPL = {"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "Ǝ": "E", "✓": "v", "•": "-",
         "\U0001f500": "->"}


def _clean(s: str) -> str:
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("cp1252", "replace").decode("cp1252")


def _width(s: str, size: float, bold: bool) -> float:
    w = sum(_W[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in s)
    return w * size / 1000 * (1.06 if bold else 1.0)


def _wrap(text: str, size: float, bold: bool, width: float) -> List[str]:
    out, line = [], ""
    for word in text.split():
        cand = f"{line} {word}".strip()
        if _width(cand, size, bold) <= width or not line:
            line = cand
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out or [""]


def _esc(s: str) -> bytes:
    b = s.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def markdown_to_pdf(md: str, title: str = "") -> bytes:
    """Markdown sederhana -> bytes PDF."""
    lines: List[Tuple[str, float, bool, float]] = []  # (teks, ukuran, tebal, indent)
    usable = PAGE_W - 2 * MARGIN
    for raw in md.splitlines():
        t = _clean(raw.rstrip())
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
        if not t.strip():
            lines.append(("", 6, False, 0))
            continue
        if t.startswith("# "):
            spec = (t[2:], 17, True, 0)
        elif t.startswith("## "):
            lines.append(("", 6, False, 0))
            spec = (t[3:], 13, True, 0)
        elif re.match(r"\s*[-*] ", t):
            body = re.sub(r"^\s*[-*] ", "", t)
            for i, w in enumerate(_wrap(body, 10.5, False, usable - 14)):
                lines.append((("- " if i == 0 else "") + w, 10.5, False, 0 if i == 0 else 9))
            continue
        else:
            spec = (t, 10.5, False, 0)
        for w in _wrap(spec[0], spec[1], spec[2], usable - spec[3]):
            lines.append((w, spec[1], spec[2], spec[3]))

    pages: List[bytes] = []
    y, ops = PAGE_H - MARGIN, []

    def flush():
        nonlocal ops
        num = len(pages) + 1
        footer = (f"BT /F1 8 Tf {MARGIN} 30 Td (".encode() + _esc(_clean(f"{title} - halaman {num}")) + b") Tj ET") \
            if title else b""
        pages.append(b"\n".join(ops + [footer]))
        ops = []

    for text, size, bold, ind in lines:
        lead = size * 1.45
        if y - lead < MARGIN:
            flush()
            y = PAGE_H - MARGIN
        y -= lead
        if text:
            font = "/F2" if bold else "/F1"
            ops.append(b"BT " + f"{font} {size} Tf {MARGIN + ind:.1f} {y:.1f} Td (".encode() + _esc(text) + b") Tj ET")
    flush()

    objs: List[bytes] = []
    n_pages = len(pages)
    # 1 catalog, 2 pages, 3 font regular, 4 font bold, lalu pasangan (page, content)
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    for i, content in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>".encode())
        objs.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)

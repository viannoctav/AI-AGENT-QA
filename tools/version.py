"""Nomor versi TƎRᗩ (file VERSION di folder utama) dan catatan perubahannya (CHANGELOG.md)."""
import re
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
_RX = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")


def current() -> str:
    try:
        v = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        return v if _RX.match(v) else "0.0.0"
    except Exception:
        return "0.0.0"


def changelog() -> str:
    try:
        return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    except Exception:
        return ""


def parse(v) -> Optional[Tuple[int, int, int]]:
    m = _RX.match(str(v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def older(a, b) -> bool:
    """True bila versi a lebih lama dari b. Versi yang tidak terbaca dianggap paling lama."""
    pb = parse(b)
    if not pb:
        return False
    pa = parse(a)
    return pa is None or pa < pb

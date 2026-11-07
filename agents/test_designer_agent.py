# agents/test_designer_agent.py
"""
Test Designer (v2): atom -> OBLIGATION (kerangka test case dengan nilai uji pasti).

Teknik dipilih deterministik dari kind atom (BVA, EP, Decision Table, State Transition, ...).
Nilai uji dibuat KODE (tools/data_synthesizer) dan diverifikasi sendiri (len == klaim),
sehingga LLM tidak lagi diminta menghitung boundary.

polarity:
  Positive : sistem menerima / berhasil
  Negative : sistem menolak / memblokir / gagal
  Auto     : bergantung aturan lain (LLM menentukan, verifier mengecek)
"""

import itertools
import re
from typing import Any, Dict, List, Optional

from agents.rule_atomizer_agent import tokens
from tools.ui import ui
from tools.data_synthesizer import (
    DATA_LABEL, baseline_valid, fmt_duration, invalid_email_variants, make_value,
    password_missing_class, with_non_digit, with_symbol,
)

KIND_LABEL = {
    "length_range": "Batas Panjang", "length_max": "Batas Panjang Maksimum", "length_min": "Batas Panjang Minimum",
    "length_exact": "Panjang Tepat", "count_max": "Batas Jumlah Percobaan", "count_trigger": "Ambang Percobaan",
    "duration_expiry": "Masa Berlaku", "duration_lock": "Durasi Penguncian", "duration_tolerance": "Toleransi Waktu",
    "perf": "Performa", "single_use": "Sekali Pakai", "required": "Field Wajib", "unique": "Keunikan Data",
    "format": "Format Data", "composition": "Komposisi Karakter", "whitespace": "Spasi Awal/Akhir",
    "enumeration": "Kelengkapan", "transition": "Transisi State", "invalid_transition": "Transisi Tidak Valid",
    "decision": "Decision Table", "edge": "Edge Case", "flow": "Alur Utama", "rule": "Aturan Bisnis",
}

_NUM = re.compile(r"\d+")


def _ints(*texts) -> List[int]:
    out = set()
    for t in texts:
        for m in _NUM.findall(str(t or "")):
            out.add(int(m))
    return sorted(out)


def feature_of(atom: Dict[str, Any], titles: Dict[str, str]) -> str:
    """Sub Module/Menu = fitur yang diuji: judul FR/NFR; decision table = judul tabelnya;
    edge case / state / acceptance criteria = judul FR terkait; tidak ada -> "-"."""
    itype = atom.get("item_type", "")
    if itype in ("FR", "NFR") and atom.get("item_title"):
        return atom["item_title"]
    if itype == "DT" and atom.get("item_title"):
        return atom["item_title"]
    rids = [str(r).upper() for r in atom.get("requirement_ids", [])]
    for prefix in ("FR", "NFR"):
        for r in rids:
            if r.startswith(prefix + "-") and titles.get(r):
                return titles[r]
    if itype == "ST" and atom.get("item_title"):
        return atom["item_title"]
    return "-"


class _Builder:
    def __init__(self, hints: Dict[str, str], module_name: str = "General", titles: Optional[Dict[str, str]] = None):
        self.hints = hints or {}
        self.module_name = module_name or "General"
        self.titles = titles or {}
        self.obs: List[Dict[str, Any]] = []

    def add(self, atom, scenario, polarity, technique, *, value=None, data_text=None, expect=None,
            priority="Medium", extra_numbers=(), precondition=None, derived=False, sub_label=None, flag_note=None,
            step_hint=None):
        ob = {
            "atom_id": atom["atom_id"],
            "kind": atom["kind"],
            "requirement_ids": list(atom["requirement_ids"]),
            "module": self.module_name,
            "sub_label": feature_of(atom, self.titles),
            "technique": technique,
            "polarity": polarity,
            "scenario": scenario,
            "rule_text": atom["text"],
            "aliases": [a["text"] for a in atom.get("aliases", [])],
            "value": value,
            "data_text": data_text,      # HANYA nilai yang diinput/dipilih QA -> kolom Test Data
            "step_hint": step_hint,      # fakta skenario yang wajib muncul di Test Steps (waktu, jumlah, urutan, pemicu)
            "expect_text": expect,
            "priority": priority,
            "precondition": precondition,
            "derived": bool(derived or atom.get("derived")),
            "flag_note": flag_note,
            "numbers_allowed": sorted(set(_ints(atom["text"], scenario, data_text, step_hint, *[a["text"] for a in atom.get("aliases", [])],
                                                list(atom.get("params", {}).values()) if atom.get("params") else "")
                                          + list(extra_numbers))),
        }
        self.obs.append(ob)
        return ob


def _label(dt: str) -> str:
    return DATA_LABEL.get(dt, "Nilai input")


def _value_ob(b: _Builder, atom, dt, n, unit, scenario, polarity, tech, valid_expect, invalid_expect,
              priority="High", value=None):
    """Buat obligation berbasis nilai dengan panjang n; verifikasi len(value)==n."""
    v = value if value is not None else make_value(dt, n, b.hints)
    ok = (len(v) == n) if value is None else True
    label = _label(dt)
    if not ok:
        v = None
    text = None
    if v is not None:
        text = f"{label}: {v}\nPanjang: {n} {unit}"
        if len(v) > 60:
            text = f"{label}: {v}\nPanjang: {n} {unit} (nilai lengkap di atas)"
    return b.add(atom, scenario, polarity, tech, value=v, data_text=text or f"{label}: (panjang {n} {unit})",
                 expect=valid_expect if polarity == "Positive" else invalid_expect, priority=priority,
                 extra_numbers=[n])


def design_atom(b: _Builder, atom: Dict[str, Any], all_atoms: List[Dict[str, Any]]):
    k, p = atom["kind"], atom.get("params", {})
    dt = atom.get("data_type") or "text"
    label = _label(dt).lower()

    if k == "length_range":
        lo, hi, unit = p["min"], p["max"], p["unit"]
        rej = f"Sistem menolak nilai karena panjang di luar batas {lo}-{hi} {unit}"
        acc = f"Nilai diterima karena panjang berada dalam batas {lo}-{hi} {unit}"
        pts = [(lo - 1, "Negative", "Boundary Value Analysis", f"{label} dengan panjang {lo - 1} {unit} (satu di bawah minimum)"),
               (lo, "Positive", "Boundary Value Analysis", f"{label} dengan panjang {lo} {unit} (tepat minimum)"),
               (hi, "Positive", "Boundary Value Analysis", f"{label} dengan panjang {hi} {unit} (tepat maksimum)"),
               (hi + 1, "Negative", "Boundary Value Analysis", f"{label} dengan panjang {hi + 1} {unit} (satu di atas maksimum)")]
        mid = lo + (hi - lo) // 2
        if lo < mid < hi:
            pts.insert(2, (mid, "Positive", "Equivalence Partitioning", f"{label} dengan panjang {mid} {unit} (nilai tengah rentang valid)"))
        for n, pol, tech, sc in pts:
            if n >= 0:
                _value_ob(b, atom, dt, n, unit, sc, pol, tech, acc, rej)
        if unit == "digit":
            n = lo
            v = with_non_digit(make_value(dt, n, b.hints))
            b.add(atom, f"{label} dengan panjang {n} {unit} tetapi mengandung karakter non-angka", "Negative",
                  "Equivalence Partitioning", value=v, data_text=f"{_label(dt)}: {v}",
                  expect="Sistem menolak nilai karena hanya angka yang diperbolehkan", extra_numbers=[n])

    elif k in ("length_max", "length_min"):
        unit = p["unit"]
        if k == "length_max":
            hi = p["max"]
            rej = f"Sistem menolak nilai karena melebihi {hi} {unit}"
            acc = f"Nilai diterima karena tidak melebihi {hi} {unit}"
            _value_ob(b, atom, dt, hi, unit, f"{label} dengan panjang {hi} {unit} (tepat batas maksimum)", "Positive",
                      "Boundary Value Analysis", acc, rej)
            _value_ob(b, atom, dt, hi + 1, unit, f"{label} dengan panjang {hi + 1} {unit} (satu di atas batas maksimum)",
                      "Negative", "Boundary Value Analysis", acc, rej)
            typ = max(1, min(hi // 2, 24))
            _value_ob(b, atom, dt, typ, unit, f"{label} dengan panjang {typ} {unit} (nilai umum dalam batas)", "Positive",
                      "Equivalence Partitioning", acc, rej, priority="Medium")
        else:
            lo = p["min"]
            rej = f"Sistem menolak nilai karena kurang dari {lo} {unit}"
            acc = f"Nilai diterima karena minimal {lo} {unit}"
            _value_ob(b, atom, dt, lo - 1, unit, f"{label} dengan panjang {lo - 1} {unit} (satu di bawah minimum)", "Negative",
                      "Boundary Value Analysis", acc, rej)
            _value_ob(b, atom, dt, lo, unit, f"{label} dengan panjang {lo} {unit} (tepat minimum)", "Positive",
                      "Boundary Value Analysis", acc, rej)

    elif k == "length_exact":
        n, unit = p["n"], p["unit"]
        if unit == "item" or atom.get("direction") == "output":
            b.add(atom, f"Verifikasi hasil yang dihasilkan sistem memenuhi aturan: tepat {n} {unit if unit == 'item' else unit + ' per nilai'}",
                  "Positive", "Equivalence Partitioning", step_hint=f"Periksa jumlah/panjang hasil yang dihasilkan sistem: {n} {unit}",
                  expect=f"Hasil yang dihasilkan sistem sesuai: {n} {unit}", extra_numbers=[n])
        else:
            rej = f"Sistem menolak nilai karena panjang bukan tepat {n} {unit}"
            acc = f"Nilai diterima karena panjang tepat {n} {unit}"
            _value_ob(b, atom, dt, n, unit, f"{label} dengan panjang tepat {n} {unit}", "Positive", "Boundary Value Analysis", acc, rej)
            _value_ob(b, atom, dt, n - 1, unit, f"{label} dengan panjang {n - 1} {unit} (satu di bawah)", "Negative", "Boundary Value Analysis", acc, rej)
            _value_ob(b, atom, dt, n + 1, unit, f"{label} dengan panjang {n + 1} {unit} (satu di atas)", "Negative", "Boundary Value Analysis", acc, rej)
            if unit == "digit":
                v = with_non_digit(make_value(dt, n, b.hints))
                b.add(atom, f"{label} dengan panjang {n} {unit} tetapi mengandung karakter non-angka", "Negative",
                      "Equivalence Partitioning", value=v, data_text=f"{_label(dt)}: {v}",
                      expect="Sistem menolak nilai karena hanya angka yang diperbolehkan", extra_numbers=[n])

    elif k == "count_max":
        n, w = p["n"], p.get("window_s")
        http = p.get("http_status")
        wtxt = f" dalam {fmt_duration(w)}" if w else ""
        blocked = f"Permintaan ke-{n + 1} ditolak" + (f" dengan HTTP {http}" if http else " karena melebihi batas")
        b.add(atom, f"{n} permintaan/percobaan{wtxt} (tepat batas maksimum)", "Positive", "Boundary Value Analysis",
              step_hint=f"Kirim permintaan sebanyak {n} kali" + (f" dalam {fmt_duration(w)}" if w else ""),
              expect=f"Seluruh {n} permintaan diproses", priority="High", extra_numbers=[n, w or 0])
        b.add(atom, f"{n + 1} permintaan/percobaan{wtxt} (satu di atas batas maksimum)", "Negative", "Boundary Value Analysis",
              step_hint=f"Kirim permintaan sebanyak {n + 1} kali" + (f" dalam {fmt_duration(w)}" if w else ""),
              expect=blocked, priority="High", extra_numbers=[n + 1, http or 0, w or 0])
        if w:
            b.add(atom, f"Permintaan baru setelah jendela {fmt_duration(w)} berlalu ({fmt_duration(w + 1)} sejak permintaan pertama)",
                  "Positive", "Edge Case", step_hint=f"Kirim {n} permintaan, tunggu {fmt_duration(w + 1)}, lalu kirim permintaan baru",
                  expect="Permintaan baru diproses karena batas sudah di-reset", extra_numbers=[n, w + 1])

    elif k == "count_trigger":
        n, cons = p["n"], p.get("consecutive")
        w = p.get("window_s")
        b.add(atom, f"{n - 1} percobaan gagal {'berturut-turut ' if cons else ''}(satu di bawah ambang)", "Positive",
              "Boundary Value Analysis", step_hint=f"Lakukan percobaan gagal sebanyak {n - 1} kali",
              expect=f"Ambang belum tercapai; sistem belum memblokir setelah {n - 1} kegagalan", priority="High", extra_numbers=[n - 1, n])
        b.add(atom, f"{n} percobaan gagal {'berturut-turut ' if cons else ''}(tepat ambang)", "Negative",
              "Boundary Value Analysis", step_hint=f"Lakukan percobaan gagal sebanyak {n} kali",
              expect=f"Sistem memblokir/mengunci setelah kegagalan ke-{n}", priority="High", extra_numbers=[n])
        b.add(atom, f"Percobaan ke-{n + 1} setelah ambang tercapai (saat sudah terblokir)", "Negative", "State Transition",
              step_hint=f"Lakukan percobaan gagal {n} kali sampai terblokir, lalu percobaan ke-{n + 1} dengan data yang benar",
              expect="Percobaan ditolak selama kondisi terblokir masih berlaku", priority="High", extra_numbers=[n + 1])
        if cons:
            b.add(atom, f"{n - 1} kegagalan, lalu 1 keberhasilan, lalu 1 kegagalan lagi (hitungan berturut-turut ter-reset)",
                  "Positive", "Edge Case",
                  step_hint=f"Lakukan {n - 1} percobaan gagal, lalu 1 percobaan berhasil, lalu 1 percobaan gagal",
                  expect="Sistem tidak memblokir karena hitungan kegagalan berturut-turut ter-reset oleh keberhasilan",
                  extra_numbers=[n - 1, 1])

    elif k in ("duration_expiry", "duration_lock"):
        t = p["t_s"]
        before, after = fmt_duration(t - 1), fmt_duration(t + 1)
        if k == "duration_expiry":
            b.add(atom, f"Penggunaan {before} setelah dibuat (satu detik sebelum batas {fmt_duration(t)})", "Positive",
                  "Boundary Value Analysis", step_hint=f"Gunakan {before} setelah dibuat/diterbitkan",
                  expect="Masih valid dan diterima", priority="High", extra_numbers=[t - 1, t])
            b.add(atom, f"Penggunaan {after} setelah dibuat (satu detik setelah batas {fmt_duration(t)})", "Negative",
                  "Boundary Value Analysis", step_hint=f"Gunakan {after} setelah dibuat/diterbitkan",
                  expect="Ditolak karena sudah kedaluwarsa", priority="High", extra_numbers=[t + 1, t])
        else:
            b.add(atom, f"Percobaan {before} setelah penguncian (satu detik sebelum {fmt_duration(t)})", "Negative",
                  "Boundary Value Analysis", step_hint=f"Coba lagi {before} setelah akun terkunci",
                  expect="Masih terkunci; percobaan ditolak", priority="High", extra_numbers=[t - 1, t])
            b.add(atom, f"Percobaan {after} setelah penguncian (satu detik setelah {fmt_duration(t)})", "Positive",
                  "Boundary Value Analysis", step_hint=f"Coba lagi {after} setelah akun terkunci",
                  expect="Penguncian berakhir; percobaan dengan data benar diproses", priority="High", extra_numbers=[t + 1, t])

    elif k == "duration_tolerance":
        iv, tol = p["interval_s"], p.get("tolerance", 1)
        b.add(atom, f"Kode dari {tol} interval ({fmt_duration(iv * tol)}) sebelum/sesudah interval saat ini (tepat batas toleransi)",
              "Positive", "Boundary Value Analysis", step_hint=f"Masukkan kode dari interval {fmt_duration(iv * tol)} sebelum/sesudah interval saat ini",
              expect="Kode diterima karena masih dalam toleransi", priority="High", extra_numbers=[iv, tol, iv * tol])
        b.add(atom, f"Kode dari {tol + 1} interval ({fmt_duration(iv * (tol + 1))}) dari interval saat ini (di luar toleransi)",
              "Negative", "Boundary Value Analysis", step_hint=f"Masukkan kode dari {fmt_duration(iv * (tol + 1))} sebelum/sesudah interval saat ini",
              expect="Kode ditolak karena di luar toleransi", priority="High", extra_numbers=[iv, tol + 1, iv * (tol + 1)])

    elif k == "single_use":
        w = p.get("window_s")
        b.add(atom, "Penggunaan pertama nilai/kode yang valid", "Positive", "Equivalence Partitioning",
              data_text="Kode/token valid yang belum pernah dipakai", expect="Penggunaan pertama berhasil", priority="High")
        b.add(atom, "Penggunaan kedua dengan nilai/kode yang sama setelah penggunaan pertama berhasil", "Negative", "Security",
              step_hint="Gunakan kode/token sekali sampai berhasil, lalu gunakan kode/token yang sama sekali lagi", expect="Penggunaan kedua ditolak", priority="High")
        if w:
            b.add(atom, f"Pengiriman ulang kode yang sama {fmt_duration(w - 1)} setelah penggunaan pertama (masih dalam jendela {fmt_duration(w)})",
                  "Negative", "Boundary Value Analysis", step_hint=f"Kirim ulang kode yang sama pada detik ke-{w - 1} setelah penggunaan pertama",
                  expect="Pengiriman ulang ditolak", priority="High", extra_numbers=[w - 1, w])
        b.add(atom, "Dua permintaan identik dengan kode/token yang sama dikirim bersamaan (race condition)", "Negative", "Edge Case",
              step_hint="Kirim dua permintaan dengan kode/token yang sama secara bersamaan", expect="Hanya satu permintaan yang berhasil; permintaan lainnya ditolak",
              priority="High")

    elif k == "perf":
        pc, ms = p["percent"], p["ms"]
        pcs = int(pc) if float(pc).is_integer() else pc
        b.add(atom, f"Ukur waktu respons sejumlah besar request di bawah beban normal; minimal {pcs}% selesai dalam {ms} ms",
              "Positive", "Performance", step_hint=f"Jalankan uji beban normal dan ukur waktu respons; target P{pcs} <= {ms} ms",
              expect=f"Minimal {pcs}% request selesai dalam {ms} ms", priority="Medium", extra_numbers=[pcs, ms])

    elif k == "required":
        for v, sc in (("", "kosong"), ("   ", "hanya berisi spasi")):
            b.add(atom, f"{label} {sc}", "Negative", "Equivalence Partitioning", value=v,
                  data_text=f"{_label(dt)}: \"{v}\"", expect="Sistem menolak karena field wajib diisi", priority="High")

    elif k == "unique":
        b.add(atom, f"{label} yang belum pernah terdaftar", "Positive", "Equivalence Partitioning",
              data_text=f"{_label(dt)}: nilai baru yang unik", expect="Nilai diterima karena unik")
        b.add(atom, f"{label} yang sudah terdaftar sebelumnya (duplikat)", "Negative", "Equivalence Partitioning",
              data_text=f"{_label(dt)}: nilai yang sama dengan data yang sudah ada", expect="Sistem menolak karena nilai sudah digunakan",
              priority="High")

    elif k == "format":
        fm, direction = p["format"], p.get("direction", "input")
        if direction == "output":
            b.add(atom, f"Verifikasi nilai yang dihasilkan sistem berformat {fm.upper()}", "Positive", "Equivalence Partitioning",
                  step_hint=f"Periksa format nilai yang dihasilkan sistem ({fm})", expect=f"Nilai yang dihasilkan sesuai format {fm}")
        elif fm == "email":
            valid = baseline_valid("email", b.hints)
            b.add(atom, "Email dengan format valid", "Positive", "Equivalence Partitioning", value=valid,
                  data_text=f"Email: {valid}", expect="Format email diterima")
            for var in invalid_email_variants()[:3]:
                b.add(atom, f"Email dengan format tidak valid ({var['label']})", "Negative", "Equivalence Partitioning",
                      value=var["value"], data_text=f"Email: {var['value']}", expect="Sistem menolak karena format email tidak valid")
        elif fm == "digits_only":
            valid = make_value(dt if dt in ("phone", "digits") else "digits", p.get("len", 12), b.hints)
            b.add(atom, "Nilai hanya berisi angka", "Positive", "Equivalence Partitioning", value=valid,
                  data_text=f"{_label(dt)}: {valid}", expect="Nilai diterima")
            for lab, v in (("mengandung huruf", with_non_digit(valid)), ("mengandung simbol", with_symbol(valid))):
                b.add(atom, f"Nilai {lab}", "Negative", "Equivalence Partitioning", value=v,
                      data_text=f"{_label(dt)}: {v}", expect="Sistem menolak karena hanya angka yang diperbolehkan")
        elif fm == "alnum":
            valid = make_value("alnum", 8)
            b.add(atom, "Nilai alfanumerik valid", "Positive", "Equivalence Partitioning", value=valid,
                  data_text=f"Kode: {valid}", expect="Nilai diterima")
            v = with_symbol(valid)
            b.add(atom, "Nilai mengandung simbol non-alfanumerik", "Negative", "Equivalence Partitioning", value=v,
                  data_text=f"Kode: {v}", expect="Sistem menolak karena hanya huruf dan angka yang diperbolehkan")
        else:
            b.add(atom, "Nilai dengan format valid sesuai aturan", "Positive", "Equivalence Partitioning",
                  data_text="Nilai sesuai format yang disyaratkan", expect="Nilai diterima")
            b.add(atom, "Nilai dengan format tidak valid", "Negative", "Equivalence Partitioning",
                  data_text="Nilai yang melanggar format", expect="Sistem menolak karena format tidak valid")

    elif k == "composition":
        classes = p["classes"]
        names = {"upper": "huruf besar", "lower": "huruf kecil", "digit": "angka", "special": "karakter khusus"}
        # panjang konteks: min dari length_range pada item yang sama, bila ada
        length = 12
        for a in all_atoms:
            if a.get("source") == atom.get("source") and a["kind"] == "length_range":
                length = a["params"]["min"]
        full = make_value("password", length, b.hints)
        b.add(atom, f"{label} memuat semua kelas karakter ({', '.join(names[c] for c in classes)})", "Positive",
              "Equivalence Partitioning", value=full, data_text=f"{_label(dt)}: {full}\nPanjang: {length} karakter",
              expect="Nilai diterima karena komposisi lengkap", extra_numbers=[length])
        for c in classes:
            v = password_missing_class(length, c)
            b.add(atom, f"{label} tanpa {names[c]}", "Negative", "Equivalence Partitioning", value=v,
                  data_text=f"{_label(dt)}: {v}\nPanjang: {length} karakter",
                  expect=f"Sistem menolak karena tidak memuat {names[c]}", priority="High", extra_numbers=[length])

    elif k == "whitespace":
        base = baseline_valid(dt if dt in ("email", "password") else "text", b.hints, 0)
        for pos, v in (("di awal", " " + base), ("di akhir", base + " ")):
            b.add(atom, f"Nilai dengan spasi {pos}", "Auto", "Edge Case", value=v,
                  data_text=f"{_label(dt)}: \"{v}\" (ada spasi {pos})",
                  precondition=None)

    elif k == "enumeration":
        items, mode, lab = p["items"], p["mode"], p["label"]
        if mode == "each":
            for it in items[:10]:
                b.add(atom, f"{lab}: kejadian/butir \"{it}\" tercatat/ditangani sesuai aturan", "Positive", "Equivalence Partitioning",
                      step_hint=f"Lakukan aksi yang memicu kejadian \"{it}\"", expect=f"\"{it}\" tercatat/ditangani sesuai aturan")
        else:
            b.add(atom, f"{lab} memuat seluruh butir: {', '.join(items)}", "Positive", "Equivalence Partitioning",
                  step_hint=f"Periksa bahwa tersedia: {', '.join(items)}", expect="Seluruh butir tersedia")

    elif k == "transition":
        fr, to, note, mach = p["from"], p["to"], p.get("note", ""), p.get("machine", "")
        b.add(atom, f"Transisi state {fr} -> {to}" + (f" ({note})" if note else ""), "Positive", "State Transition",
              step_hint=(f"Lakukan pemicu: {note}" if note else f"Lakukan aksi yang mengubah state {fr} menjadi {to}"),
              expect=f"State berubah dari {fr} menjadi {to}", priority="High", precondition=f"State awal = {fr}",
              flag_note=(None if note else "PRD tidak menyebut pemicu transisi secara eksplisit - konfirmasi"))

    elif k == "invalid_transition":
        fr, to = p["from"], p["to"]
        b.add(atom, f"Percobaan transisi tidak terdefinisi {fr} -> {to}", "Negative", "State Transition",
              step_hint=f"Coba ubah state langsung menjadi {to}", expect=f"Transisi ditolak; state tetap {fr}",
              priority="Medium", precondition=f"State awal = {fr}", derived=True)

    elif k == "decision":
        conds = p["conditions"]
        combos = _decision_rows(conds)
        for i, combo in enumerate(combos, 1):
            inputs = [(c["name"], v) for c, v in zip(conds, combo) if not _STATE_COND.search(c["name"])]
            states = [(c["name"], v) for c, v in zip(conds, combo) if _STATE_COND.search(c["name"])]
            lines = "\n".join(f"{nm} = {v}" for nm, v in inputs) or None
            pre = ("Kondisi: " + ", ".join(f"{nm} = {v}" for nm, v in states)) if states else None
            bad = [(c["name"], v) for c, v in zip(conds, combo) if _REJECT_VALUE.match(str(v).strip())]
            # kombinasi yang memuat nilai "pasti ditolak" -> polaritas dipastikan KODE; sisanya LLM + catatan PRD
            has_na = any(str(v).startswith("N/A") for v in combo)
            b.add(atom, f"Decision table [{p.get('title', '')}]: " + "; ".join(f"{c['name']}={v}" for c, v in zip(conds, combo)),
                  "Negative" if bad else "Auto", "Decision Table", data_text=lines, priority="High", precondition=pre,
                  expect=(f"Ditolak karena {bad[0][0]} bernilai {bad[0][1]}" if bad else None),
                  flag_note=("Kondisi bertanda N/A ditentukan otomatis dari ketergantungan antar kondisi - konfirmasi" if has_na else None))

    elif k == "edge":
        b.add(atom, f"Edge case: {atom['text']}", "Auto", "Edge Case", priority="High")

    elif k == "flow":
        # polaritas Auto: aturan lintas-fitur seperti "must enforce/prevent/log ..." bisa berujung penolakan
        b.add(atom, f"Alur utama berjalan normal: {atom['text']}", "Auto", "Positive / Happy Path",
              priority="High")

    else:  # rule
        tech = atom.get("technique") or "Equivalence Partitioning"
        b.add(atom, f"Aturan: {atom['text']}", "Auto", tech, priority="Medium")


# nilai kondisi yang SELALU berujung penolakan (token/kode/sesi tidak sah, akun terkunci, password melanggar kebijakan)
# kondisi decision table yang berupa KEADAAN (masuk Pre-condition), bukan nilai yang diinput/dipilih QA (Test Data)
_STATE_COND = re.compile(r"\b(state|status|count|history|attempt|lockout|riwayat|kondisi|jumlah percobaan)\b", re.I)

_REJECT_VALUE = re.compile(r"^(invalid|expired|revoked|locked|already used|non[- ]?compliant|in last)\b", re.I)


_OFF_VALUE = re.compile(r"^(disabled|off|inactive|not enrolled|nonaktif)\b", re.I)
_ON_VALUE = re.compile(r"^(enabled|on|active|enrolled|aktif|valid|unlocked|below|compliant|unique|correct|verified|yes)\b", re.I)


def _controllers(conds: List[Dict[str, Any]]) -> Dict[int, List[int]]:
    """Kondisi '<X> Status' (Enabled/Disabled) -> indeks kondisi lain yang namanya diawali '<X> ' dan bergantung padanya."""
    out: Dict[int, List[int]] = {}
    for i, c in enumerate(conds):
        m = re.match(r"^(.*?)\s+status$", c["name"], re.I)
        vals = [str(v) for v in c["values"]]
        if m and any(_OFF_VALUE.match(v) for v in vals) and any(re.match(r"^(enabled|on|active|aktif)\b", v, re.I) for v in vals):
            prefix = m.group(1).strip().lower()
            deps = [j for j, d in enumerate(conds) if j != i and d["name"].lower().startswith(prefix + " ")]
            if deps:
                out[i] = deps
    return out


def _decision_rows(conds: List[Dict[str, Any]], cap: int = 16) -> List[tuple]:
    """
    Kombinasi yang BERNILAI untuk decision table:
      1) baris baseline (tiap kondisi di nilai "normal/ON": Enabled, Valid, Unlocked, ...),
      2) kombinasi tanpa nilai "pasti ditolak" (logika keputusan sebenarnya, diputuskan LLM + catatan PRD),
      3) SATU kondisi bernilai "pasti ditolak", kondisi lain di baseline (penolakan mendominasi).
    Kondisi yang bergantung pada pengendali berstatus OFF (mis. 'MFA Verification Code' saat 'MFA Status = Disabled')
    menjadi "N/A (...)" sehingga kombinasi mustahil tidak dibuat.
    """
    bad = lambda v: bool(_REJECT_VALUE.match(str(v).strip()))

    def pick(c):
        vals = [v for v in c["values"] if not bad(v)]
        return next((v for v in vals if _ON_VALUE.match(str(v).strip())), vals[0] if vals else c["values"][0])

    baseline = tuple(pick(c) for c in conds)
    rows: List[tuple] = [baseline]
    for r in _combos(conds, cap=cap * 2):
        if not any(bad(v) for v in r) and r not in rows:
            rows.append(r)
    for i, c in enumerate(conds):
        for v in c["values"]:
            if bad(v):
                r = tuple(v if j == i else baseline[j] for j in range(len(conds)))
                if r not in rows:
                    rows.append(r)
    ctrl = _controllers(conds)
    out: List[tuple] = []
    for r in rows:
        r = list(r)
        for i, deps in ctrl.items():
            if _OFF_VALUE.match(str(r[i]).strip()):
                for j in deps:
                    r[j] = f"N/A ({conds[i]['name']} = {r[i]})"
        r = tuple(r)
        if r not in out:
            out.append(r)
    return out[:cap * 2]


def _combos(conds: List[Dict[str, Any]], cap: int = 16) -> List[tuple]:
    values = [c["values"] for c in conds]
    total = 1
    for v in values:
        total *= len(v)
    if total <= cap:
        return list(itertools.product(*values))
    # pairwise greedy: tiap pasangan (kondisi i, nilai a) x (kondisi j, nilai b) minimal sekali
    pairs = set()
    for i, j in itertools.combinations(range(len(values)), 2):
        for a in values[i]:
            for bb in values[j]:
                pairs.add((i, a, j, bb))
    rows: List[tuple] = []
    all_rows = list(itertools.product(*values))
    while pairs:
        best, best_cov = None, -1
        for r in all_rows:
            cov = sum(1 for (i, a, j, bb) in pairs if r[i] == a and r[j] == bb)
            if cov > best_cov:
                best, best_cov = r, cov
        rows.append(best)
        pairs = {(i, a, j, bb) for (i, a, j, bb) in pairs if not (best[i] == a and best[j] == bb)}
        if len(rows) >= cap:
            break
    return rows


def _related_rules(ob: Dict[str, Any], atoms: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    tk = tokens(ob["rule_text"] + " " + ob["scenario"])
    scored = []
    for a in atoms:
        if a["atom_id"] == ob["atom_id"] or a["kind"] in ("edge", "decision", "transition", "invalid_transition", "flow"):
            continue
        if ob["kind"] != "perf" and (a["kind"] == "perf" or any(str(r).upper().startswith("NFR") for r in a.get("requirement_ids", []))):
            continue  # aturan performa/NFR tidak relevan untuk obligation non-performa (penyebab TC-001 "500 ms")
        s = len(tk & tokens(a["text"]))
        if s >= 2:
            scored.append((s, a["text"]))
    scored.sort(reverse=True)
    out = []
    for _, t in scored:
        if t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def design_obligations(atoms: List[Dict[str, Any]], hints: Optional[Dict[str, str]] = None,
                       module_name: str = "General", titles: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    if titles is None:
        titles = {a["source"]: a["item_title"] for a in atoms
                  if a.get("item_type") in ("FR", "NFR") and a.get("source") and a.get("item_title")}
    b = _Builder(hints or {}, module_name, titles)
    for atom in atoms:
        design_atom(b, atom, atoms)
    obs = b.obs
    # dedupe kunci (atom, scenario)
    seen, uniq = set(), []
    for ob in obs:
        key = (ob["atom_id"], ob["scenario"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ob)
    note_of = {a["atom_id"]: (a.get("params") or {}).get("note", "") for a in atoms}
    for i, ob in enumerate(uniq, 1):
        ob["ob_id"] = f"OB-{i:03d}"
        if ob["polarity"] == "Auto" or ob["kind"] in ("rule", "edge", "decision", "whitespace", "flow"):
            ob["related_rules"] = _related_rules(ob, atoms)
        else:
            ob["related_rules"] = []
        if ob["kind"] == "decision" and note_of.get(ob["atom_id"]):
            ob["related_rules"].insert(0, note_of[ob["atom_id"]])  # "Expected outcome must permit low-risk ..."
    return uniq


def test_designer_node(state: dict) -> dict:
    atoms = state.get("atoms", [])
    st = state.get("prd_structure") or {}
    titles = {it["id"]: it["title"] for it in st.get("items", []) if it.get("type") in ("FR", "NFR")} or None
    obs = design_obligations(atoms, state.get("hints", {}), st.get("module_name") or "General", titles)
    by_tech: Dict[str, int] = {}
    for o in obs:
        by_tech[o["technique"]] = by_tech.get(o["technique"], 0) + 1
    ui.stage("design", f"{len(obs)} obligation")
    ui.event("designer", f"obligations={len(obs)} techniques={by_tech}")
    return {"obligations": obs, "ob_queue": list(obs)}
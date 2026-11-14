"""Pembaruan TƎRᗩ dari GitHub (repo publik): cek versi terbaru, unduh, lalu timpa file program saja.

Yang TIDAK pernah disentuh: hasil kerja (runs, outputs), dokumen PRD (knowledge/prd), akun dan token
(data, configs/sumber_ai.json, configs/kunci_referensi.json), dan lingkungan Python (.venv).
Pengaturan AI (configs/ai.json) digabung: pilihan pengguna dipertahankan, kunci baru ditambahkan.
File program lama dicadangkan dulu ke data/cadangan_update/.

Sumber pembaruan diatur di configs/update.json: {"repo": "pemilik/nama-repo", "branch": "master"}."""
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools import version as VER

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "configs" / "update.json"
BACKUP = ROOT / "data" / "cadangan_update"
# folder/file milik pengguna: tidak pernah ditimpa atau dihapus
PROTECTED_DIRS = ("runs", "outputs", "data", ".venv", ".git", ".vs", "__pycache__", "knowledge/prd")
PROTECTED_FILES = ("configs/sumber_ai.json", "configs/kunci_referensi.json", "configs/update.json", "pasang_tera.log", ".env")
KEEP_IF_EXISTS = ("knowledge/company_testcases/", "knowledge/forbidden_terms.json")  # hanya diisi bila belum ada
MERGE_JSON = ("configs/ai.json",)
CODE_EXT = (".py", ".js", ".css", ".html", ".bat", ".ps1")
MAX_ZIP = 300 * 1024 * 1024
_cache: Dict[str, Any] = {"time": 0.0, "info": None}


class UpdateError(Exception):
    pass


def source() -> Dict[str, str]:
    try:
        d = json.loads(CONF.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    repo, branch = str(d.get("repo") or "").strip().strip("/"), str(d.get("branch") or "master").strip()
    import re
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[A-Za-z0-9_./-]+", branch):
        raise UpdateError("Sumber pembaruan belum diatur dengan benar di configs\\update.json.")
    return {"repo": repo, "branch": branch}


def is_dev_copy() -> bool:
    """Folder dengan .git adalah salinan pengembang: diperbarui dengan git, bukan ditimpa dari sini."""
    return (ROOT / ".git").exists()


def _get(url: str, timeout: float, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"TERA/{VER.current()}", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Unduhan pembaruan terlalu besar.")
    return data


def check(force: bool = False) -> Dict[str, Any]:
    """{current, latest, available, changelog, dev, error}. Hasil disimpan 30 menit supaya tidak sering ke internet."""
    now = time.time()
    if not force and _cache["info"] and now - _cache["time"] < 1800:
        return _cache["info"]
    info: Dict[str, Any] = {"current": VER.current(), "latest": "", "available": False, "changelog": "",
                            "dev": is_dev_copy(), "error": "", "checked": now}
    try:
        src = source()
        info["repo"] = src["repo"]
        base = f"https://raw.githubusercontent.com/{src['repo']}/{src['branch']}"
        latest = _get(f"{base}/VERSION?t={int(now)}", 8, 64).decode("utf-8", "replace").strip()
        if not VER.parse(latest):
            raise UpdateError("Nomor versi di GitHub tidak terbaca.")
        info["latest"] = latest
        info["available"] = VER.older(info["current"], latest)
        if info["available"]:
            try:
                info["changelog"] = _get(f"{base}/CHANGELOG.md?t={int(now)}", 8, 400_000).decode("utf-8", "replace")
            except Exception:
                pass
    except UpdateError as e:
        info["error"] = str(e)
    except Exception:
        info["error"] = "Tidak bisa memeriksa pembaruan. Periksa koneksi internet."
    _cache.update(time=now, info=info)
    return info


def _protected(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return rel in PROTECTED_FILES or any(rel == d or rel.startswith(d + "/") for d in PROTECTED_DIRS) \
        or "/__pycache__/" in f"/{rel}"


def _merge(old: Any, new: Any) -> Any:
    """Pengaturan pengguna dipertahankan; kunci yang baru ada di versi baru ditambahkan."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(old)
        for k, v in new.items():
            out[k] = _merge(old[k], v) if k in old else v
        return out
    return old


def apply(log=None) -> Dict[str, Any]:
    say = log or (lambda m: None)
    if is_dev_copy():
        raise UpdateError("Ini salinan pengembang (ada folder .git). Perbarui dengan: git pull")
    info = check(force=True)
    if info["error"]:
        raise UpdateError(info["error"])
    if not info["available"]:
        return {"updated": False, "version": info["current"], "message": "TƎRᗩ sudah versi terbaru."}
    src = source()
    say(f"Mengunduh versi {info['latest']} ...")
    try:
        raw = _get(f"https://codeload.github.com/{src['repo']}/zip/refs/heads/{src['branch']}", 180, MAX_ZIP)
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except UpdateError:
        raise
    except Exception:
        raise UpdateError("Gagal mengunduh pembaruan. Periksa koneksi internet lalu coba lagi.")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        raise UpdateError("Isi pembaruan kosong.")
    prefix = names[0].split("/", 1)[0] + "/"
    files: Dict[str, bytes] = {}
    for n in names:
        if not n.startswith(prefix):
            raise UpdateError("Susunan file pembaruan tidak dikenali.")
        rel = n[len(prefix):]
        parts = rel.split("/")
        if not rel or rel.startswith("/") or ".." in parts or ":" in rel or "\\" in rel:
            raise UpdateError("File pembaruan berisi alamat yang tidak aman.")
        files[rel] = zf.read(n)
    new_ver = files.get("VERSION", b"").decode("utf-8", "replace").strip()
    if not VER.parse(new_ver) or not VER.older(VER.current(), new_ver):
        raise UpdateError("Versi di dalam unduhan bukan versi yang lebih baru.")
    if "dashboard.py" not in files or "requirements.txt" not in files:
        raise UpdateError("Unduhan bukan folder TƎRᗩ yang lengkap.")

    old_ver = VER.current()
    old_req = (ROOT / "requirements.txt").read_bytes() if (ROOT / "requirements.txt").exists() else b""
    backup = BACKUP / f"{old_ver}_{time.strftime('%Y%m%d-%H%M%S')}"
    written, kept, removed = [], [], []

    def save_old(rel: str) -> None:
        f = ROOT / rel
        if f.is_file():
            b = backup / rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, b)

    say("Memasang file program baru (hasil kerja dan pengaturanmu tidak diubah) ...")
    for rel, data in sorted(files.items()):
        if _protected(rel):
            kept.append(rel)
            continue
        target = ROOT / rel
        if any(rel == k or rel.startswith(k) for k in KEEP_IF_EXISTS) and target.exists():
            kept.append(rel)
            continue
        if rel.startswith("knowledge/company_testcases/") and any((ROOT / "knowledge" / "company_testcases").glob("*")):
            kept.append(rel)  # sudah punya referensi sendiri: tidak dicampur
            continue
        if rel in MERGE_JSON and target.exists():
            try:
                merged = _merge(json.loads(target.read_text(encoding="utf-8")), json.loads(data.decode("utf-8")))
                data = json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8")
            except Exception:
                kept.append(rel)
                continue
        if rel.lower().endswith((".bat", ".ps1")):  # file skrip Windows wajib berakhiran baris CRLF
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if target.is_file() and target.read_bytes() == data:
            continue
        save_old(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".baru")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        written.append(rel)
    # file program yang sudah dihapus di versi baru ikut dibuang (hanya di folder program, hanya jenis file program)
    tops = {r.split("/", 1)[0] for r in files if "/" in r and not _protected(r.split("/", 1)[0])}
    for top in tops:
        for f in (ROOT / top).rglob("*"):
            rel = f.relative_to(ROOT).as_posix()
            if f.is_file() and f.suffix.lower() in CODE_EXT and rel not in files and not _protected(rel):
                save_old(rel)
                f.unlink()
                removed.append(rel)
    pip = ""
    if files["requirements.txt"] != old_req:
        say("Memasang komponen Python yang baru ...")
        try:
            p = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")],
                               capture_output=True, text=True, timeout=1200,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if p.returncode != 0:
                pip = "Komponen Python baru gagal dipasang. Klik dua kali Pasang_Tera.bat untuk memasangnya."
        except Exception:
            pip = "Komponen Python baru gagal dipasang. Klik dua kali Pasang_Tera.bat untuk memasangnya."
    _cache.update(time=0.0, info=None)
    say(f"Selesai: versi {old_ver} -> {new_ver}.")
    return {"updated": True, "from": old_ver, "version": new_ver, "files": len(written), "removed": len(removed),
            "backup": str(backup.relative_to(ROOT)) if backup.exists() else "", "warning": pip,
            "message": f"TƎRᗩ diperbarui ke versi {new_ver}. Tutup lalu buka lagi TƎRᗩ."}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(f"TERA versi {VER.current()}. Memeriksa pembaruan ...")
    try:
        if is_dev_copy():
            print("Ini salinan pengembang (ada folder .git). Perbarui dengan: git pull")
            return 0
        info = check(force=True)
        if info["error"]:
            print("[!] " + info["error"])
            return 1
        if not info["available"]:
            print("Sudah versi terbaru.")
            return 0
        print(f"Versi baru tersedia: {info['latest']}.")
        res = apply(log=print)
        if res.get("warning"):
            print("[!] " + res["warning"])
        if res.get("backup"):
            print(f"File program lama dicadangkan di {res['backup']}")
        print("Buka lagi TERA lewat ikon TERA di Desktop.")
        return 0
    except UpdateError as e:
        print("[!] " + str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())

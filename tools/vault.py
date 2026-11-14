"""Kunci file referensi test case perusahaan (knowledge/company_testcases) dengan password.

File .xlsx dienkripsi menjadi .xlsx.terakunci; hanya versi terkunci yang ikut ke GitHub.
TƎRᗩ membuka kuncinya di memori saat membuat test case, setelah password diisi sekali di Pengaturan.

Kriptografi (hanya Python bawaan): kunci diturunkan dari password dengan scrypt; isi dienkripsi dengan
aliran kunci HMAC-SHA256 mode counter dan dilindungi tanda keaslian HMAC-SHA256 (encrypt-then-MAC).
Password tidak pernah disimpan. Yang disimpan di laptop (configs/kunci_referensi.json, tidak ikut GitHub)
adalah kunci turunannya, supaya password tidak perlu diketik setiap kali."""
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "knowledge" / "company_testcases"
VAULT = FOLDER / "kunci.json"           # garam + penguji password (aman dibagikan, bukan rahasia)
LOCAL_KEY = ROOT / "configs" / "kunci_referensi.json"  # kunci turunan di laptop ini (rahasia)
EXT = ".terakunci"
MAGIC = b"TERAKUNCI1"
_SCRYPT = dict(n=2 ** 15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)


class VaultError(Exception):
    pass


def _master(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def _verifier(master: bytes) -> str:
    return hmac.new(master, b"tera-penguji-password", hashlib.sha256).hexdigest()


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:n])


def _keys(master: bytes, nonce: bytes):
    return (hmac.new(master, b"enc" + nonce, hashlib.sha256).digest(),
            hmac.new(master, b"mac" + nonce, hashlib.sha256).digest())


def encrypt(data: bytes, master: bytes) -> bytes:
    nonce = secrets.token_bytes(16)
    ke, km = _keys(master, nonce)
    ct = bytes(a ^ b for a, b in zip(data, _stream(ke, nonce, len(data))))
    tag = hmac.new(km, MAGIC + nonce + ct, hashlib.sha256).digest()
    return MAGIC + nonce + ct + tag


def decrypt(blob: bytes, master: bytes) -> bytes:
    if len(blob) < len(MAGIC) + 48 or not blob.startswith(MAGIC):
        raise VaultError("File terkunci rusak atau bukan file kunci TƎRᗩ.")
    nonce, ct, tag = blob[len(MAGIC):len(MAGIC) + 16], blob[len(MAGIC) + 16:-32], blob[-32:]
    ke, km = _keys(master, nonce)
    if not hmac.compare_digest(tag, hmac.new(km, MAGIC + nonce + ct, hashlib.sha256).digest()):
        raise VaultError("Password salah atau file terkunci sudah berubah.")
    return bytes(a ^ b for a, b in zip(ct, _stream(ke, nonce, len(ct))))


# ----------------------------------------------------------------------------- keadaan
def plain_files() -> List[Path]:
    return sorted(p for p in FOLDER.glob("*.xlsx") if not p.name.startswith("~$")) if FOLDER.is_dir() else []


def locked_files() -> List[Path]:
    return sorted(FOLDER.glob(f"*{EXT}")) if FOLDER.is_dir() else []


def _vault() -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(VAULT.read_text(encoding="utf-8"))
        return d if d.get("salt") and d.get("verifier") else None
    except Exception:
        return None


def local_key() -> Optional[bytes]:
    """Kunci turunan yang tersimpan di laptop ini dan masih cocok dengan brankas."""
    v = _vault()
    if not v:
        return None
    try:
        key = bytes.fromhex(json.loads(LOCAL_KEY.read_text(encoding="utf-8"))["key"])
    except Exception:
        return None
    return key if hmac.compare_digest(_verifier(key), v["verifier"]) else None


def status() -> Dict[str, Any]:
    return {"plain": len(plain_files()), "locked": len(locked_files()), "has_vault": _vault() is not None,
            "unlocked": local_key() is not None}


def _save_local(master: bytes) -> None:
    LOCAL_KEY.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL_KEY.with_suffix(".tmp")
    tmp.write_text(json.dumps({"key": master.hex()}), encoding="utf-8")
    os.replace(tmp, LOCAL_KEY)


def _check(password: str) -> bytes:
    v = _vault()
    if not v:
        raise VaultError("Belum ada file referensi yang dikunci.")
    master = _master(password, bytes.fromhex(v["salt"]))
    if not hmac.compare_digest(_verifier(master), v["verifier"]):
        raise VaultError("Password salah.")
    return master


# ----------------------------------------------------------------------------- aksi
def lock(password: str) -> Dict[str, Any]:
    """Enkripsi semua .xlsx yang belum terkunci. File asli dihapus setelah hasil enkripsi teruji bisa dibuka lagi."""
    files = plain_files()
    if not files:
        raise VaultError("Tidak ada file .xlsx yang belum dikunci di knowledge\\company_testcases.")
    v = _vault()
    if v:
        master = _check(password)  # brankas sudah ada: harus password yang sama
    else:
        salt = secrets.token_bytes(16)
        master = _master(password, salt)
        FOLDER.mkdir(parents=True, exist_ok=True)
        VAULT.write_text(json.dumps({"salt": salt.hex(), "verifier": _verifier(master), "versi": 1}, indent=1), encoding="utf-8")
    done = []
    for f in files:
        data = f.read_bytes()
        target = f.with_name(f.name + EXT)
        blob = encrypt(data, master)
        if decrypt(blob, master) != data:  # jangan pernah menghapus file asli bila hasilnya tidak bisa dibuka
            raise VaultError(f"{f.name}: hasil enkripsi gagal diuji. File asli tidak diubah.")
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, target)
        f.unlink()
        done.append(f.name)
    _save_local(master)
    reset_cache()
    return {"locked": done}


def unlock(password: str) -> None:
    """Simpan kunci di laptop ini supaya file terkunci bisa dipakai sebagai referensi."""
    _save_local(_check(password))
    reset_cache()


def forget() -> None:
    LOCAL_KEY.unlink(missing_ok=True)
    reset_cache()


def restore(password: str) -> Dict[str, Any]:
    """Kembalikan file asli (.xlsx) dan hapus versi terkuncinya."""
    master = _check(password)
    files = locked_files()
    out = []
    for f in files:
        data = decrypt(f.read_bytes(), master)
        target = f.with_name(f.name[:-len(EXT)])
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        out.append(target.name)
    for f in files:
        f.unlink()
    VAULT.unlink(missing_ok=True)
    LOCAL_KEY.unlink(missing_ok=True)
    reset_cache()
    return {"restored": out}


def read_locked() -> List[tuple]:
    """[(nama asli, isi bytes)] untuk file terkunci, bila kunci tersedia di laptop ini. Hanya di memori."""
    key = local_key()
    if not key:
        return []
    out = []
    for f in locked_files():
        try:
            out.append((f.name[:-len(EXT)], decrypt(f.read_bytes(), key)))
        except VaultError:
            continue
    return out


def reset_cache() -> None:
    try:
        from tools import company_tc_retriever
        company_tc_retriever._REF_CACHE.clear()
    except Exception:
        pass

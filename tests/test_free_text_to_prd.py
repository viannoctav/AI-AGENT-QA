"""Tes cepat modul Catatan QA -> PRD dengan AI tiruan (tanpa Ollama):
    python tests/test_free_text_to_prd.py
Memeriksa: penjaga anti-karangan (kutipan palsu, angka karangan, role karangan), format PRD terbaca generator."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from free_text_to_prd.pipeline import run  # noqa: E402
from tools.prd_structure import parse_prd_markdown  # noqa: E402

NOTES = """Role :
1. Admin
   * User Management :
      * Field Nama, NIP (16), Status Active / Non Active
      * Login First Time -> Force Change Password
2. Operator
   * Riwayat : hanya dirinya sendiri
Pengajuan ada tahap Draft lalu Final.
Expired Token : 30 Menit"""

ANSWER = {"produk": "", "peran": ["Admin", "Operator", "Manager"], "items": [
    {"baris": 4, "kutipan": "Field Nama, NIP (16)", "fitur": "User Management", "jenis": "field", "pernyataan": "Panjang NIP tepat 16 karakter."},
    {"baris": 4, "kutipan": "Status Active / Non Active", "fitur": "User Management", "jenis": "field", "pernyataan": "Status user: Active atau Non Active."},
    {"baris": 5, "kutipan": "Login First Time -> Force Change Password", "fitur": "User Management", "jenis": "alur", "pernyataan": "Login pertama kali -> wajib Force Change Password."},
    {"baris": 5, "kutipan": "Login First Time -> Force Change Password", "fitur": "User Management", "jenis": "aturan", "pernyataan": "Password minimal 8 karakter."},
    {"baris": 7, "kutipan": "Riwayat : hanya dirinya sendiri", "fitur": "Riwayat", "jenis": "akses", "pernyataan": "Operator hanya dapat melihat riwayat miliknya sendiri.", "role": "Operator", "aksi": "Melihat riwayat", "boleh": True},
    {"baris": 2, "kutipan": "Admin", "fitur": "Riwayat", "jenis": "akses", "pernyataan": "Admin dapat melihat riwayat semua user.", "role": "Admin", "aksi": "Melihat riwayat semua user", "boleh": True},
    {"baris": 7, "kutipan": "Manager dapat menyetujui pengajuan", "fitur": "Pengajuan", "jenis": "akses", "pernyataan": "Manager dapat menyetujui pengajuan.", "role": "Manager", "aksi": "Menyetujui", "boleh": True},
    {"baris": 8, "kutipan": "Pengajuan ada tahap Draft lalu Final", "fitur": "Pengajuan", "jenis": "status", "pernyataan": "Pengajuan melalui tahap Draft lalu Final.", "objek": "Pengajuan", "dari": "Draft", "ke": "Final"},
    {"baris": 9, "kutipan": "Expired Token : 30 Menit", "fitur": "", "jenis": "nonfungsional", "pernyataan": "Token kedaluwarsa setelah 30 menit."},
]}
QUESTIONS = {"pertanyaan": [
    {"fitur": "User Management", "jenis": "belum jelas", "pertanyaan": "Apakah NIP hanya boleh angka?", "kutipan": ""},
    {"fitur": "Riwayat", "jenis": "bertentangan", "pertanyaan": "Admin bisa menghapus riwayat?", "kutipan": "Admin bisa menghapus riwayat"}]}


class FakeLLM:
    @staticmethod
    def generation_model():
        return "palsu"

    @staticmethod
    def chat_json(model, system, prompt, **kw):
        return QUESTIONS if "Draf PRD" in prompt else ANSWER


def main():
    r = run(NOTES, name="Tes Catatan", llm=FakeLLM, write=False, cb=lambda m: None)
    md, doc = r["markdown"], r["document"]
    why = {x["pernyataan"]: x["alasan"] for x in r["rejected"]}
    checks = [
        ("angka karangan ditolak", "angka 8" in why.get("Password minimal 8 karakter.", "")),
        ("kutipan karangan ditolak", "kutipan" in why.get("Manager dapat menyetujui pengajuan.", "")),
        ("role karangan tidak masuk Actors", "Manager" not in doc["roles"]),
        ("klaim bertentangan tanpa bukti diturunkan", all(q["jenis"] == "belum jelas" for q in doc["questions"])),
        ("panah di aturan tidak jadi transisi", "kemudian" in md),
        ("status jadi state model", "`DRAFT → FINAL`" in md),
        ("token jadi NFR", "### NFR-001" in md and "30 menit" in md),
    ]
    st = parse_prd_markdown(md)
    ids = [i["id"] for i in st["items"]]
    checks += [
        ("FR terbaca generator", sum(1 for i in ids if i.startswith("FR-")) == len(doc["features"])),
        ("Open Questions tidak jadi requirement", not any(i.startswith("OQ") for i in ids)),
        ("PRD bersih dari hal yang diragukan", not any(k in md for k in ("Open Questions", "Traceability", "TBD", "ditolak", "NIP hanya boleh angka"))),
        ("catatan review terpisah berisi pertanyaan & penolakan",
         "NIP hanya boleh angka" in r["review"] and "Password minimal 8" in r["review"] and "baris 4" in r["review"]),
        ("Module terbaca", st["module_name"] == "Tes Catatan"),
    ]
    ok = True
    for name, passed in checks:
        print(("LOLOS " if passed else "GAGAL ") + name)
        ok &= passed
    print("SEMUA LOLOS" if ok else "ADA YANG GAGAL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

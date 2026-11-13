"""AI hanya MEMBERI JENIS pada teks yang sudah dibaca OCR (tombol, field, label, ...).
AI menjawab dengan nomor, jadi tidak bisa menambah atau mengubah teks. Jawaban di luar daftar diabaikan kode."""
import re
from typing import Any, Dict, List, Optional

TYPES = ["judul", "teks", "label", "placeholder", "isian", "dropdown", "toggle", "checkbox", "radio", "tombol", "link",
         "menu", "tab", "pesan", "notifikasi", "status", "kolom_tabel", "isi_tabel", "ikon", "abaikan"]
STATES = ["nonaktif", "terpilih", "aktif", "merah"]
SCREEN_KINDS = ["halaman", "modal", "panel", "menu", "notifikasi"]

SYSTEM = ("Kamu membantu QA membaca desain aplikasi. Kamu HANYA memberi jenis pada teks yang sudah terbaca. "
          "Jangan menulis ulang teks, jangan menambah teks baru, jangan menebak perilaku. Jawab JSON saja.")

PROMPT = """Gambar ini satu layar desain aplikasi. Teks di bawah SUDAH terbaca dari gambar (nomor | posisi x,y | teks).
Beri JENIS untuk setiap nomor, berdasarkan tampilannya di gambar:
- judul: judul layar/modal/panel/bagian | teks: teks biasa/keterangan/angka info
- label: nama sebuah isian (di atas/samping kotak input)
- placeholder: teks abu-abu di DALAM kotak input yang masih kosong | isian: nilai yang sudah terisi di dalam kotak input
- dropdown: teks di dalam kotak pilihan (biasanya ada panah ke bawah) | toggle / checkbox / radio: teks di samping saklar/kotak centang/pilihan bulat
- tombol: teks di dalam tombol | link: teks yang bisa diklik tanpa bentuk tombol
- menu: pilihan menu navigasi atau daftar menu aksi | tab: pilihan tab
- pesan: teks bantuan/validasi/error di bawah kotak input | notifikasi: isi pesan pemberitahuan (toast/alert)
- status: label kecil berwarna (badge) seperti Active/Verified | kolom_tabel: judul kolom tabel | isi_tabel: isi sel tabel
- ikon: huruf/simbol yang sebenarnya ikon atau inisial avatar | abaikan: bagian bingkai browser/perangkat, bukan aplikasi
Tambahkan keadaan bila TERLIHAT jelas: nonaktif (abu-abu pucat dibanding sejenisnya), terpilih, aktif, merah.
Contoh nilai: "tombol", "placeholder nonaktif", "menu terpilih", "tombol merah".

{lines}

Jawab JSON: {{"jenis_layar": "halaman|modal|panel|menu|notifikasi", "judul": <nomor teks judul layar, 0 bila tidak ada>,
 "label": {{"1": "...", "2": "...", "...": "..."}}}}"""


def prompt_for(lines: List[Dict[str, Any]]) -> str:
    rows = "\n".join(f"{i} | x={ln['x']} y={ln['y']} | {ln['text']}" for i, ln in enumerate(lines, 1))
    return PROMPT.format(lines=rows)


def parse(data: Optional[Dict[str, Any]], n: int) -> Dict[str, Any]:
    """Jawaban AI -> {"kind", "title_no", "labels": {no: (jenis, [state])}, "ok"}; yang tidak valid dibuang."""
    out = {"kind": "", "title_no": 0, "labels": {}, "ok": isinstance(data, dict)}
    if not isinstance(data, dict):
        return out
    k = str(data.get("jenis_layar") or "").strip().lower()
    out["kind"] = next((s for s in SCREEN_KINDS if s in k), "")
    try:
        t = int(str(data.get("judul") or 0).strip())
        out["title_no"] = t if 1 <= t <= n else 0
    except ValueError:
        pass
    lab = data.get("label") or {}
    if isinstance(lab, list):  # bentuk lain: [{"no": 1, "jenis": "..."}]
        lab = {str(x.get("no")): x.get("jenis") for x in lab if isinstance(x, dict)}
    for key, val in (lab.items() if isinstance(lab, dict) else []):
        try:
            no = int(re.sub(r"\D", "", str(key)) or 0)
        except ValueError:
            continue
        if not 1 <= no <= n:
            continue  # nomor di luar daftar OCR -> diabaikan
        words = re.findall(r"[a-z_]+", str(val or "").lower())
        jenis = next((w for w in words if w in TYPES), None)
        if not jenis:
            jenis = "kolom_tabel" if "kolom" in words else "isi_tabel" if "isi" in words else "teks"
        states = [s for s in STATES if s in words]
        out["labels"][no] = (jenis, states)
    return out


def label_screen(llm, image_path: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not lines:
        return {"kind": "", "title_no": 0, "labels": {}, "ok": True}
    data = llm.chat_json(llm.generation_model(), SYSTEM, prompt_for(lines), temperature=0.0,
                         num_predict=min(3000, 200 + 14 * len(lines)), images=[image_path])
    return parse(data, len(lines))

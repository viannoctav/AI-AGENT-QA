# TƎRᗩ — Asisten QA berbasis AI

TƎRᗩ membantu QA:

- **Catatan Konversi ke PRD**: catatan QA yang berantakan (notulen, chat, poin-poin) disusun menjadi dokumen PRD yang rapi. TƎRᗩ tidak mengarang; hal yang belum jelas dikumpulkan di catatan review (PDF) terpisah.
- **Desain Konversi ke PRD**: gambar desain (export Figma atau screenshot) per halaman, plus penjelasan opsional, disusun menjadi PRD. Teks di gambar dibaca persis oleh pembaca teks bawaan Windows; AI hanya menentukan jenisnya (tombol, field, label, dan seterusnya).
- **Generator Test Case PRD**: dari dokumen PRD, TƎRᗩ membuat test case lengkap (Excel), lalu memeriksanya dengan AI kedua.

Semua berjalan **di laptop sendiri**. Data tidak dikirim ke internet, dan tidak perlu akun atau API key.

Panduan ini untuk pemula: tidak perlu VS Code dan tidak perlu bisa coding.

---

## 1. Spesifikasi laptop

| | Minimal |
|---|---|
| Sistem operasi | Windows 10 atau 11 |
| RAM | 16 GB (8 GB akan sangat lambat atau gagal) |
| Ruang kosong | sekitar 20 GB (sebagian besar untuk model AI) |
| Kartu grafis (GPU) | Tidak wajib. Tanpa GPU tetap jalan, tapi lebih lama |
| Internet | Hanya saat instalasi pertama |

Perkiraan waktu tanpa GPU: konversi catatan beberapa menit, pembuatan test case untuk PRD besar sekitar 2–3 jam.

---

## 2. Pemasangan sekali klik

1. Buka folder TƎRᗩ, lalu klik dua kali **`Pasang_Tera.bat`**.
2. Tunggu sampai tertulis **SELESAI**. Pertama kali bisa cukup lama (sekitar 15 GB unduhan model AI), jadi pastikan internet stabil dan laptop dicolok charger.
3. Di akhir, ketik **Y** lalu Enter untuk langsung membuka TƎRᗩ.

Yang dikerjakan otomatis (yang sudah ada akan dilewati):

| Langkah | Keterangan |
|---|---|
| Cek laptop | Windows 64-bit, RAM, ruang kosong minimal 20 GB, koneksi internet |
| Python | Dipasang kalau belum ada (lewat winget, atau unduh langsung dari python.org) |
| Ollama (mesin AI lokal) | Dipasang kalau belum ada, lalu dinyalakan |
| Komponen TƎRᗩ | Folder `.venv` dan komponen dari `requirements.txt` |
| Model AI | Nama model dibaca dari `configs\ai.json` (saat ini `gemma4:e4b` sebagai AI penulis dan `qwen2.5:7b` sebagai AI pemeriksa) |
| Bahasa OCR | Bahasa Inggris untuk pembaca teks Windows (fitur Desain Konversi ke PRD). Windows akan meminta izin admin sekali |
| Shortcut | Ikon **TERA** di Desktop untuk membuka TƎRᗩ berikutnya |

Kalau gagal di tengah jalan, baca pesan merahnya, perbaiki (biasanya internet atau ruang kosong), lalu klik dua kali `Pasang_Tera.bat` lagi. Unduhan model dilanjutkan, tidak mulai dari nol. Catatan lengkap pemasangan tersimpan di `pasang_tera.log`.

<details><summary>Pemasangan manual (kalau pemasang otomatis tidak bisa dipakai)</summary>

1. **Python**: unduh dari <https://www.python.org/downloads/>. Di layar pertama instalasi, centang **"Add python.exe to PATH"**, lalu **Install Now**.
2. **Ollama**: unduh dari <https://ollama.com/download> (Windows), lalu pasang sampai selesai.
3. **Model AI**: buka PowerShell, lalu ketik `ollama pull gemma4:e4b` dan `ollama pull qwen2.5:7b`.
4. Jalankan `Jalankan_Tera.bat`. Pertama kali ia membuat folder `.venv` dan memasang komponen sendiri.

</details>

---

## 3. Menjalankan TƎRᗩ

1. Pastikan **Ollama menyala**: ikon llama ada di taskbar. Kalau belum ada, buka aplikasi Ollama dari Start Menu.
2. Klik dua kali ikon **TERA** di Desktop (atau `Jalankan_Tera.bat` di folder TƎRᗩ).
3. Browser akan terbuka sendiri ke alamat **http://127.0.0.1:8765**. Itulah dashboard TƎRᗩ.
4. **Jangan tutup jendela hitam** (Command Prompt) selama TƎRᗩ dipakai. Browser boleh ditutup dan dibuka lagi lewat alamat di atas.
5. Untuk mematikan TƎRᗩ, klik jendela hitam itu lalu tekan **Ctrl + C**, atau tutup jendelanya.

Kalau Windows menampilkan peringatan **"Windows protected your PC"** saat membuka file `.bat`, klik **More info**, lalu **Run anyway**. File `.bat` ini hanya berisi perintah untuk menjalankan TƎRᗩ dan bisa dibuka dengan Notepad untuk dicek.

---

## 4. Cara pakai singkat

### Catatan ke PRD

1. Menu **Konversi Dokumen**, lalu **Catatan Konversi ke PRD**.
2. Isi **Nama modul** (misalnya `Berita Acara`), tempel catatan QA, lalu klik **Susun PRD**.
3. Setelah selesai:
   - Baca pertanyaannya, lalu klik **Unduh catatan review (PDF)** untuk ditanyakan ke tim.
   - Edit PRD bila perlu, lalu klik **Simpan perubahan**.
   - Klik **Buat test case dari PRD ini**.

### Desain ke PRD

1. Menu **Konversi Dokumen**, lalu **Desain Konversi ke PRD**.
2. Isi **Nama modul**.
3. Untuk setiap halaman atau fitur, isi satu kartu:
   - **Nama halaman / fitur**, misalnya `Add User`.
   - **Penjelasan** (opsional): aturan yang tidak terlihat di gambar, misalnya siapa yang boleh mengakses atau batas karakter.
   - **Gambar**: klik **Tambah gambar** atau seret file ke kotaknya. Boleh banyak. Satu gambar boleh berisi beberapa layar berjajar (papan alur); TƎRᗩ memotongnya sendiri dan membaca urutannya dari kiri ke kanan.
4. Klik **+ Tambah halaman / fitur** untuk kartu berikutnya. **Deskripsi tambahan** di bawah untuk aturan yang berlaku umum.
5. Klik **Susun PRD**. Perkiraan waktunya tampil di samping tombol (kira-kira 2–3 menit per layar di laptop tanpa GPU).
6. Setelah selesai, sama seperti Catatan ke PRD: baca hal yang perlu dicek, unduh catatan review (PDF), edit PRD bila perlu, lalu **Buat test case dari PRD ini**.

Tips gambar:
- Export dari Figma: pilih frame, di panel kanan bagian **Export** pilih **PNG** ukuran **2x**, lalu klik Export.
- Bagian yang diburamkan di belakang modal atau panel otomatis diabaikan.
- Fitur ini memakai pembaca teks bawaan Windows, jadi hanya berjalan di Windows.

### Membuat test case dari PRD

1. Menu **Generator Test Case PRD**, lalu **Mulai baru**.
2. Pilih dokumen PRD dari dropdown. PRD baru bisa ditambahkan dengan **Tambah dokumen PRD** (file `.md`).
3. Pastikan kartu **Kesiapan** semuanya hijau, lalu klik **Mulai buat test case**.
4. Pantau di **Sedang berjalan**. Selama proses, laptop dijaga agar tidak tidur otomatis, tapi **jangan tutup layar laptop**.
5. Setelah selesai:
   - **Hasil**: ringkasan dan tombol **Unduh Excel**.
   - **Perlu dicek**: test case yang ditandai AI untuk dicek manual.
   - **Cakupan**: memastikan semua bagian PRD sudah ada test case-nya.

Semua proses tercatat di menu **Riwayat**.

---

## 5. Di mana file-file saya?

| Isi | Folder |
|---|---|
| Dokumen PRD (termasuk hasil konversi catatan dan desain) | `knowledge\prd\` |
| Excel test case | `outputs\` |
| Hasil konversi catatan (PRD, catatan review PDF, catatan asli) | `outputs\free_text_to_prd\` |
| Hasil konversi desain (PRD, catatan review PDF, gambar asli, potongan layar) | `outputs\design_to_prd\` |
| Riwayat setiap proses pembuatan test case | `runs\` |
| Contoh test case perusahaan (acuan gaya penulisan AI) | `knowledge\company_testcases\` |

---

## 6. Kalau ada masalah

| Masalah | Solusi |
|---|---|
| `'python' is not recognized` | Python belum terpasang. Jalankan `Pasang_Tera.bat`. |
| Di dashboard tertulis **AI belum aktif** | Buka aplikasi Ollama, lalu klik **Periksa ulang** di halaman Mulai baru. |
| Di dashboard tertulis **AI belum lengkap** | Model belum diunduh. Jalankan `Pasang_Tera.bat`. |
| Di dashboard tertulis **TƎRᗩ tidak terhubung** | Jendela hitam TƎRᗩ tertutup. Klik dua kali `Jalankan_Tera.bat` lagi. |
| Browser tidak terbuka otomatis | Buka browser dan ketik `http://127.0.0.1:8765`. |
| `address already in use` / port dipakai | TƎRᗩ sudah berjalan di jendela lain. Pakai yang itu, atau tutup jendela lama dulu. |
| Pemasangan gagal di tengah jalan | Cek internet dan ruang kosong, lalu klik dua kali `Pasang_Tera.bat` lagi. Kalau masih gagal, hapus folder `.venv` lalu ulangi. Detailnya ada di `pasang_tera.log`. |
| Desain ke PRD: **"Tidak ada bahasa OCR terpasang"** | Pasang bahasa Inggris di Windows: Settings > Time & language > Language & region > Add a language > English. |
| Desain ke PRD: **"Pillow belum terpasang"** | Tutup TƎRᗩ, lalu jalankan `Pasang_Tera.bat` (komponennya dipasang otomatis, butuh internet). |
| Proses test case sangat lama | Wajar di laptop tanpa GPU. Tutup aplikasi berat lain, colokkan charger, dan biarkan berjalan. |

---

## 7. Untuk yang membagikan TƎRᗩ ke orang lain

Saat menyalin atau meng-zip folder TƎRᗩ untuk teman, **jangan ikut sertakan**:

- `.venv\` (besar dan khusus untuk laptop kamu; `Pasang_Tera.bat` di laptop teman akan membuatnya sendiri)
- `.env` (bisa berisi data rahasia)
- `runs\` dan `outputs\` (hasil kerja kamu)
- `__pycache__\`, `.vs\`, dan `pasang_tera.log` (file sementara)

Teman cukup menerima folder TƎRᗩ, lalu klik dua kali `Pasang_Tera.bat`.

Cek juga isi `knowledge\prd\` dan `knowledge\company_testcases\`. Kalau berisi dokumen internal kantor, pastikan memang boleh dibagikan sebelum ikut disalin.

---

## 8. Isi folder TƎRᗩ

| File / folder | Fungsi |
|---|---|
| `Pasang_Tera.bat` | Pemasang sekali klik (Python, Ollama, komponen, model AI, bahasa OCR, ikon Desktop) |
| `Jalankan_Tera.bat` | Membuka TƎRᗩ setiap kali mau dipakai |
| `setup\` | Script pemasang yang dipanggil `Pasang_Tera.bat` |
| `dashboard.py`, `dashboard\` | Dashboard TƎRᗩ (tampilan di browser) |
| `run.py`, `agents\`, `tc_workflows\` | Mesin Generator Test Case PRD |
| `free_text_to_prd\` | Mesin Catatan Konversi ke PRD |
| `design_to_prd\` | Mesin Desain Konversi ke PRD (potong layar, baca teks, susun PRD) |
| `tools\` | Bagian bersama: koneksi AI, pembaca PRD, aturan validasi isian, dan lainnya |
| `configs\ai.json` | Pengaturan AI (juga bisa diubah dari menu Pengaturan) |
| `knowledge\` | Dokumen PRD, contoh test case perusahaan, dan daftar istilah terlarang |
| `requirements.txt` | Daftar komponen Python yang dipasang otomatis |

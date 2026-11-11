# Tera — Asisten QA berbasis AI

Tera membantu QA:

- **Catatan Konversi ke PRD**: catatan QA yang berantakan (notulen, chat, poin-poin) disusun menjadi dokumen PRD yang rapi. Tera tidak mengarang; hal yang belum jelas dikumpulkan di catatan review (PDF) terpisah.
- **Generator Test Case PRD**: dari dokumen PRD, Tera membuat test case lengkap (Excel), lalu memeriksanya dengan AI kedua.

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

## 2. Yang perlu di-install (sekali saja)

### a. Python

1. Buka <https://www.python.org/downloads/> lalu klik tombol **Download Python** (versi terbaru).
2. Jalankan file yang terunduh.
3. **PENTING:** di layar pertama instalasi, centang **"Add python.exe to PATH"**, lalu klik **Install Now**.
4. Tunggu sampai selesai, lalu klik **Close**.

### b. Ollama (mesin AI lokal)

1. Buka <https://ollama.com/download> lalu pilih **Windows**.
2. Jalankan file yang terunduh, lalu ikuti sampai selesai.
3. Setelah terpasang, ikon Ollama (kepala llama) muncul di pojok kanan bawah taskbar. Artinya Ollama sudah menyala.

### c. Model AI

Model AI cukup diunduh sekali, ukurannya sekitar 15 GB.

- Cara mudah: klik dua kali file **`Siapkan_Model_AI.bat`** di folder Tera, lalu tunggu sampai tertulis selesai.
- Cara manual: buka **PowerShell** (tekan tombol Windows, ketik `PowerShell`, Enter), lalu ketik:

```
ollama pull gemma4:e4b
ollama pull qwen2.5:7b
```

`gemma4:e4b` bertugas sebagai **AI penulis**, sedangkan `qwen2.5:7b` bertugas sebagai **AI pemeriksa**.

---

## 3. Menjalankan Tera

1. Pastikan **Ollama menyala**: ikon llama ada di taskbar. Kalau belum ada, buka aplikasi Ollama dari Start Menu.
2. Buka folder Tera, lalu klik dua kali **`Jalankan_Tera.bat`**.
   - **Pertama kali:** Tera menyiapkan dirinya sendiri. Ia membuat folder `.venv` dan memasang komponen yang dibutuhkan. Proses ini butuh beberapa menit dan internet.
   - **Berikutnya:** langsung jalan.
3. Browser akan terbuka sendiri ke alamat **http://127.0.0.1:8765**. Itulah dashboard Tera.
4. **Jangan tutup jendela hitam** (Command Prompt) selama Tera dipakai. Browser boleh ditutup dan dibuka lagi lewat alamat di atas.
5. Untuk mematikan Tera, klik jendela hitam itu lalu tekan **Ctrl + C**, atau tutup jendelanya.

Kalau Windows menampilkan peringatan **"Windows protected your PC"** saat membuka file `.bat`, klik **More info**, lalu **Run anyway**. File `.bat` ini hanya berisi perintah untuk menjalankan Tera dan bisa dibuka dengan Notepad untuk dicek.

---

## 4. Cara pakai singkat

### Catatan ke PRD

1. Menu **Konversi Dokumen**, lalu **Catatan Konversi ke PRD**.
2. Isi **Nama modul** (misalnya `Berita Acara`), tempel catatan QA, lalu klik **Susun PRD**.
3. Setelah selesai:
   - Baca pertanyaannya, lalu klik **Unduh catatan review (PDF)** untuk ditanyakan ke tim.
   - Edit PRD bila perlu, lalu klik **Simpan perubahan**.
   - Klik **Buat test case dari PRD ini**.

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
| Dokumen PRD (termasuk hasil konversi catatan) | `knowledge\prd\` |
| Excel test case | `outputs\` |
| Hasil konversi catatan (PRD, catatan review PDF, catatan asli) | `outputs\free_text_to_prd\` |
| Riwayat setiap proses pembuatan test case | `runs\` |
| Contoh test case perusahaan (acuan gaya penulisan AI) | `knowledge\company_testcases\` |

---

## 6. Kalau ada masalah

| Masalah | Solusi |
|---|---|
| `'python' is not recognized` | Python belum terpasang atau "Add python.exe to PATH" lupa dicentang. Install ulang Python dan centang pilihan itu. |
| Di dashboard tertulis **AI belum aktif** | Buka aplikasi Ollama, lalu klik **Periksa ulang** di halaman Mulai baru. |
| Di dashboard tertulis **AI belum lengkap** | Model belum diunduh. Jalankan `Siapkan_Model_AI.bat`. |
| Di dashboard tertulis **Tera tidak terhubung** | Jendela hitam Tera tertutup. Klik dua kali `Jalankan_Tera.bat` lagi. |
| Browser tidak terbuka otomatis | Buka browser dan ketik `http://127.0.0.1:8765`. |
| `address already in use` / port dipakai | Tera sudah berjalan di jendela lain. Pakai yang itu, atau tutup jendela lama dulu. |
| Instalasi pertama gagal di tengah jalan | Cek internet, hapus folder `.venv`, lalu jalankan `Jalankan_Tera.bat` lagi. |
| Proses test case sangat lama | Wajar di laptop tanpa GPU. Tutup aplikasi berat lain, colokkan charger, dan biarkan berjalan. |

---

## 7. Untuk yang membagikan Tera ke orang lain

Saat menyalin atau meng-zip folder Tera untuk teman, **jangan ikut sertakan**:

- `.venv\` (besar dan khusus untuk laptop kamu; teman akan membuat sendiri secara otomatis)
- `.env` (bisa berisi data rahasia)
- `runs\` dan `outputs\` (hasil kerja kamu)
- `__pycache__\` (file sementara)

Cek juga isi `knowledge\prd\` dan `knowledge\company_testcases\`. Kalau berisi dokumen internal kantor, pastikan memang boleh dibagikan sebelum ikut disalin.

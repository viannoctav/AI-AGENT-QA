# TƎRᗩ — Asisten QA berbasis AI

TƎRᗩ berjalan di laptop kamu sendiri. Tidak perlu akun, tidak perlu API key, dan dokumenmu tidak dikirim ke internet.

Yang bisa dilakukan:

| Fitur | Gunanya |
|---|---|
| **Catatan Konversi ke PRD** | Catatan QA yang berantakan (notulen, chat, poin-poin) disusun menjadi PRD yang rapi. |
| **Desain Konversi ke PRD** | Gambar desain (export Figma atau screenshot) disusun menjadi PRD. |
| **MD Konversi ke PDF** | File PRD `.md` diubah menjadi PDF rapi untuk dibagikan. Tanpa AI, hitungan detik. |
| **Generator Test Case PRD** | Dari PRD, dibuatkan test case lengkap dalam Excel, lalu diperiksa AI kedua. |
| **Bandingkan Test Case** | Dua kumpulan test case dibandingkan: mana yang berpasangan, mana yang cuma ada di satu sisi, mana yang hasil harapannya bertentangan. |

Panduan ini untuk pemula: tidak perlu VS Code dan tidak perlu bisa coding. Ikuti langkahnya berurutan.

---

## Langkah 1 — Cek laptopmu

Ada dua cara memakai AI-nya. Pilih dulu yang mana, karena kebutuhan laptopnya berbeda:

- **AI di laptop sendiri** — semuanya jalan di laptopmu. Butuh laptop yang cukup kuat.
- **Server AI bersama** — AI dijalankan di komputer temanmu lewat jaringan pribadi terenkripsi (Tailscale). Laptop ringan pun cukup. Dokumenmu tetap di laptopmu; yang dikirim hanya permintaan ke AI.

| | AI di laptop sendiri | Server AI bersama |
|---|---|---|
| Sistem operasi | Windows 10 atau 11 | Windows 10 atau 11 |
| RAM | 16 GB (8 GB akan sangat lambat atau gagal) | 8 GB cukup |
| Ruang kosong | sekitar 20 GB (sebagian besar untuk model AI) | sekitar 3 GB |
| Kartu grafis (GPU) | Tidak wajib, tapi tanpa GPU lebih lama | Tidak perlu |
| Internet | Hanya saat pemasangan pertama | Selama memakai AI |
| Yang perlu disiapkan | — | Alamat server, nama pengguna, dan password dari pemilik server |

Perkiraan waktu tanpa GPU: konversi catatan beberapa menit; pembuatan test case untuk PRD besar sekitar 2–3 jam.

---

## Langkah 2 — Pasang TƎRᗩ

1. Buka folder TƎRᗩ, lalu klik dua kali **`Pasang_Tera.bat`**.
2. Saat ditanya cara memakai AI, ketik **1** (AI di laptop ini) atau **2** (Server AI bersama). Kalau ragu, tekan Enter saja (pilihan 1).
3. Tunggu sampai tertulis **SELESAI**. Pilihan 1 mengunduh sekitar 15 GB model AI, jadi pastikan internet stabil dan laptop dicolok charger.
4. Di akhir, ketik **Y** lalu Enter untuk langsung membuka TƎRᗩ.

Yang dikerjakan otomatis (yang sudah ada akan dilewati):

| Langkah | Keterangan |
|---|---|
| Cek laptop | Windows 64-bit, RAM, ruang kosong, koneksi internet |
| Python | Dipasang kalau belum ada |
| Ollama (mesin AI lokal) | Dipasang dan dinyalakan. Pilihan 2: diganti Tailscale |
| Komponen TƎRᗩ | Folder `.venv` dan komponen dari `requirements.txt` |
| Model AI | Pilihan 2: dilewati. Termasuk model kemiripan makna `nomic-embed-text` untuk Bandingkan Test Case |
| Bahasa OCR | Bahasa Inggris untuk pembaca teks Windows (dipakai Desain Konversi ke PRD). Windows minta izin admin sekali |
| Shortcut | Ikon **TERA** di Desktop |

Kalau gagal di tengah jalan: baca pesan merahnya, perbaiki (biasanya internet atau ruang kosong), lalu klik dua kali `Pasang_Tera.bat` lagi. Unduhan model dilanjutkan, bukan mulai dari nol. Catatan lengkapnya ada di `pasang_tera.log`.

<details><summary>Pemasangan manual (kalau pemasang otomatis tidak bisa dipakai)</summary>

1. **Python**: unduh dari <https://www.python.org/downloads/>. Di layar pertama, centang **"Add python.exe to PATH"**, lalu **Install Now**.
2. **Ollama**: unduh dari <https://ollama.com/download> (Windows), pasang sampai selesai.
3. **Model AI**: buka PowerShell, ketik `ollama pull gemma4:e4b`, `ollama pull qwen2.5:7b`, dan `ollama pull nomic-embed-text`.
4. Jalankan `Jalankan_Tera.bat`. Pertama kali ia membuat `.venv` dan memasang komponennya sendiri.

</details>

---

## Langkah 3 — Sambungkan ke Server AI bersama

**Lewati langkah ini kalau kamu memakai AI di laptop sendiri (pilihan 1).** Lanjut ke Langkah 4.

Kalau tadi memilih **2**, lakukan ini sekali saja:

1. **Pasang dan masuk ke Tailscale.** Tailscale sudah ikut dipasang oleh `Pasang_Tera.bat`. Buka aplikasinya, lalu masuk (bisa pakai akun Google).
2. **Terima undangan dari pemilik server.** Dia mengirim tautan undangan Tailscale. Buka tautannya, lalu setujui. Setelah ini komputernya muncul di daftar Tailscale-mu.
3. **Minta tiga hal ini ke pemilik server** (lewat chat pribadi, bukan grup):
   - alamat server, bentuknya seperti `http://100.101.102.103:11500`
   - nama pengguna
   - password
4. **Jalankan TƎRᗩ** (Langkah 4 di bawah), lalu buka **Pengaturan** → **Sumber AI**.
5. Pilih **Server AI bersama**, isi alamat, nama pengguna, dan password, lalu klik **Masuk**.

Kalau berhasil, di halaman Mulai baru akan tertulis AI siap dipakai. Login berlaku **30 hari**; setelah itu tinggal **Masuk** lagi di halaman yang sama.

Setiap kali mau memakai TƎRᗩ sesudah ini: pastikan **Tailscale menyala** dan **komputer pemilik server sedang hidup dengan servernya berjalan**. Kalau mau kembali memakai AI di laptop sendiri, pilih **AI di laptop ini** di halaman yang sama.

Yang perlu kamu tahu soal keamanannya: dokumen, PRD, catatan, desain, dan test case tetap tersimpan di laptopmu. Yang dikirim ke komputer pemilik server hanya permintaan ke AI, lewat jaringan terenkripsi, dan wajib login. Server tidak menyimpan isi dokumenmu.

---

## Langkah 4 — Jalankan TƎRᗩ

1. Pastikan AI siap:
   - **AI di laptop sendiri**: Ollama menyala (ikon llama di taskbar). Kalau belum, buka aplikasi Ollama dari Start Menu.
   - **Server AI bersama**: Tailscale menyala dan sudah masuk.
2. Klik dua kali ikon **TERA** di Desktop (atau `Jalankan_Tera.bat` di folder TƎRᗩ).
3. Browser terbuka sendiri ke **http://127.0.0.1:8765**. Itulah dashboard TƎRᗩ.
4. **Jangan tutup jendela hitam** (Command Prompt) selama TƎRᗩ dipakai. Browsernya boleh ditutup dan dibuka lagi lewat alamat di atas.
5. Untuk mematikan TƎRᗩ: klik jendela hitam itu lalu tekan **Ctrl + C**, atau tutup jendelanya.

Kalau Windows menampilkan **"Windows protected your PC"** saat membuka file `.bat`, klik **More info** lalu **Run anyway**. File `.bat` itu hanya berisi perintah untuk menjalankan TƎRᗩ dan bisa dibuka dengan Notepad untuk dicek.

---

## Langkah 5 — Pakai fiturnya

Menu samping: klik **Konversi Dokumen** atau **Generator Test Case PRD** untuk membuka/menutup daftar menunya. Klik **Ciutkan menu** di bawah supaya menunya tinggal ikon. Pilihan ini diingat browser.

Mau tahu apa yang terjadi di balik layar? Buka menu **Alur Kerja**: pilih fiturnya, lalu langkah-langkahnya tampil satu per satu beserta label **AI** (dikerjakan model AI) dan **Kode** (aturan pasti yang dicek program).

### A. Catatan ke PRD

1. **Konversi Dokumen** → **Catatan Konversi ke PRD**.
2. Isi **Nama modul** (mis. `Berita Acara`), tempel catatan QA, lalu **Susun PRD**.
3. Setelah selesai:
   - Baca daftar pertanyaannya, lalu **Unduh catatan review (PDF)** untuk ditanyakan ke tim.
   - Edit PRD bila perlu, lalu **Simpan perubahan**.
   - **Unduh PRD (.md)**, atau **Jadikan PDF**.
   - **Buat test case dari PRD ini**.

### B. Desain ke PRD

1. **Konversi Dokumen** → **Desain Konversi ke PRD**.
2. Isi **Nama modul**.
3. Untuk setiap halaman atau fitur, isi satu kartu:
   - **Nama halaman / fitur**, mis. `Add User`.
   - **Penjelasan** (opsional): aturan yang tidak terlihat di gambar, mis. siapa yang boleh mengakses atau batas karakter.
   - **Gambar**: klik **Tambah gambar** atau seret filenya. Boleh banyak. Satu gambar boleh berisi beberapa layar berjajar (papan alur); TƎRᗩ memotongnya sendiri dan membaca urutannya dari kiri ke kanan.
4. **+ Tambah halaman / fitur** untuk kartu berikutnya. **Deskripsi tambahan** di bawah untuk aturan yang berlaku umum.
5. Klik **Susun PRD**. Perkiraan waktunya tampil di samping tombol (sekitar 2–3 menit per layar di laptop tanpa GPU).
6. Setelah selesai, sama seperti Catatan ke PRD.

**Kalau prosesnya terhenti, bisa dilanjut.** Kartu diproses satu demi satu dan setiap fitur yang selesai langsung disimpan. Kalau laptop mati, TƎRᗩ ditutup, atau AI-nya putus, buka lagi menu ini: ada tulisan *"Ada penyusunan PRD yang terhenti: ..."* beserta tombol **Lanjutkan** (meneruskan dari fitur berikutnya, yang sudah selesai tidak dibaca ulang) dan **Buang** (hapus simpanannya, susun ulang dari awal). Di akhir semuanya tetap digabung menjadi **satu PRD**.

Tips gambar:
- Export dari Figma: pilih frame, panel kanan bagian **Export** → **PNG** ukuran **2x** → Export.
- Bagian yang diburamkan di belakang modal atau panel otomatis diabaikan.
- Supaya alurnya terbaca rapi, susun papan alur per skenario dan beri bingkai sampul di awal setiap skenario (bingkai berisi judul dan tanggal saja, mis. `Users - Create`). Bingkai itu menjadi nama alurnya.
- Fitur ini memakai pembaca teks bawaan Windows, jadi hanya berjalan di Windows.

### C. MD ke PDF

1. **Konversi Dokumen** → **MD Konversi ke PDF**.
2. Tambahkan file: **Pilih file .md** (boleh beberapa) atau seret filenya. Bisa juga memilih PRD yang sudah ada di TƎRᗩ, lalu **Tambahkan ke daftar**.
3. Per file: **Lihat PDF** atau **Unduh PDF**. Kalau banyak: **Unduh semua PDF** (bila browser bertanya, izinkan unduhan beberapa file).

PDF A4 lengkap dengan judul, daftar, tabel, kutipan, blok kode, dan nomor halaman. Tanpa AI, jadi tetap bisa dipakai saat proses lain berjalan. Batas 2 MB per file.

### D. Membuat test case dari PRD

1. **Generator Test Case PRD** → **Mulai baru**.
2. Pilih dokumen PRD dari dropdown, atau tambahkan dengan **Tambah dokumen PRD** (file `.md`).
3. Pastikan kartu **Kesiapan** hijau semua, lalu **Mulai buat test case**.
4. Pantau di **Sedang berjalan**. Laptop dijaga agar tidak tidur, tapi **jangan tutup layar laptop**.
5. Setelah selesai: **Hasil** (ringkasan + **Unduh Excel**), **Perlu dicek** (test case yang ditandai AI untuk dicek manual), dan **Cakupan** (memastikan semua bagian PRD sudah ada test case-nya).

### E. Bandingkan test case

1. Menu **Bandingkan Test Case**.
2. Untuk **Test case A** dan **B**: beri nama kumpulan (mis. `Dari desain` dan `Dari PRD`), lalu pilih sumbernya:
   - **Dari Riwayat**: hasil Generator Test Case PRD yang sudah selesai.
   - **Unggah file**: Excel (.xlsx) atau JSON, maks. 20 MB, termasuk test case buatan manual. TƎRᗩ mencari sendiri kolom judul, Test Data, Expected Result, dan lainnya.
3. Pilih mode **Lengkap** (±10–20 menit, memakai AI untuk pasangan yang masih ragu) atau **Cepat** (±1 menit, tanpa AI; yang ragu masuk **Perlu dicek**).
4. Klik **Bandingkan**. Hasilnya: persentase yang berpasangan, kesimpulan, serta tab **Berpasangan**, **Bertentangan**, **Perlu dicek**, **Hanya di A**, **Hanya di B**, dan **Kembar**. **Unduh Excel** untuk laporan lengkap.

Test case sumber tidak pernah diubah. Hasilnya bisa dibuka lagi di bagian **Perbandingan sebelumnya**.

Semua proses dari setiap menu tercatat di menu **Riwayat** beserta hasilnya.

---

## Bagaimana PRD-nya disusun

Berlaku untuk Catatan ke PRD maupun Desain ke PRD:

- **Tidak mengarang.** Setiap aturan wajib punya sumber: kutipan dari catatanmu, atau teks yang benar-benar terbaca di desain. Isian AI yang tidak lolos pemeriksaan ini dibuang dan dicatat di catatan review.
- **Bahasanya aturan bisnis, bukan laporan isi layar.** Nama tombol diterjemahkan menjadi maksudnya. Contoh: *Pengguna dapat menambahkan user dengan mengisi "Name", "Occupation", "Email", ... Bila berhasil, sistem menampilkan notifikasi "User added!".* Aturan yang berdiri sendiri tidak menyebut layar sama sekali: *New Password wajib memenuhi aturan "Password must contain at least 8 characters".*
- **Satu halaman/area menjadi satu `FR`, tiap alur menjadi sub-judul di dalamnya.** Sub-judul itu yang mengisi kolom **Sub Module/Menu** di test case, dan nama area mengisi **Module/Menu**.
- **Open Points, bukan tebakan.** Hal yang tidak terlihat di sumber tidak ditambahkan sendiri, melainkan ditulis sebagai pertanyaan untuk PO/tim (mis. *"Tombol X tampak nonaktif di desain — kapan bisa diklik?"*). Jadi tidak ada test case yang menguji hal yang belum tentu dibangun.
- **Rincian isi layar pindah ke catatan review**, bukan dibuang: aksi lain di layar, kolom tabel, menu navigasi, tab, daftar status, dan teks sapaan. Kalau ada yang memang perlu diuji, salin sendiri dari situ.

Kerangka PRD yang dihasilkan: Document Information, Actors, Feature Overview, Navigation Structure, Functional Requirements (`FR-001`, sub-judul per alur, ditutup Acceptance Criteria), Business Rules (tabel `BR-001`), Data & Field Reference, System Feedback & States, Key State Model, Edge-Case Areas, Expected QA Coverage, Test Data Guidance, Acceptance Criteria, dan Open Points. Bagian yang tidak ada dasarnya di sumber memang dikosongkan.

---

## Kalau referensi test case perusahaan terkunci

Di **Mulai baru** bisa muncul keterangan *"Referensi test case perusahaan terkunci"*. Itu contoh test case perusahaan yang gaya penulisannya ditiru AI, dan isinya dikunci dengan password.

Cukup sekali per laptop:

1. **Pengaturan** → **Referensi test case perusahaan** → **Isi password**.
2. Ketik password yang diberikan pemilik TƎRᗩ, lalu **Simpan**.

Tanpa password, test case tetap bisa dibuat, hanya tanpa contoh gaya penulisan perusahaan. Password diberikan lewat chat pribadi, jangan disebar.

---

## Memperbarui TƎRᗩ

Nomor versi ada di pojok kiri bawah dashboard. Klik untuk melihat **Apa yang baru**.

Kalau ada versi baru, muncul tanda **Ada versi baru** di pojok kiri bawah. Klik, lalu **Perbarui sekarang**, lalu tutup dan buka lagi TƎRᗩ. Bisa juga: tutup TƎRᗩ, lalu klik dua kali **`Perbarui_Tera.bat`**.

Yang diperbarui hanya file program. Hasil kerjamu (`runs\`, `outputs\`), dokumen PRD (`knowledge\prd\`), login, dan pilihan di Pengaturan tidak diubah. File program lama dicadangkan dulu di `data\cadangan_update\`.

Fitur ini ada mulai versi 1.3.0. Kalau kamu masih memakai 1.2.0 ke bawah, minta folder terbaru ke pemilik TƎRᗩ **sekali** (atau unduh ZIP dari GitHub dan timpa foldermu). Sesudah itu selalu bisa memperbarui sendiri.

---

## Kalau ada masalah

| Masalah | Solusi |
|---|---|
| `'python' is not recognized` | Python belum terpasang. Jalankan `Pasang_Tera.bat`. |
| Di dashboard tertulis **AI belum aktif** | Buka aplikasi Ollama, lalu klik **Periksa ulang** di halaman Mulai baru. |
| Di dashboard tertulis **AI belum lengkap** | Model belum diunduh. Jalankan `Pasang_Tera.bat`. |
| Di dashboard tertulis **TƎRᗩ tidak terhubung** | Jendela hitam TƎRᗩ tertutup. Klik dua kali `Jalankan_Tera.bat` lagi. |
| Browser tidak terbuka otomatis | Buka browser, ketik `http://127.0.0.1:8765`. |
| `address already in use` / port dipakai | TƎRᗩ sudah berjalan di jendela lain. Pakai yang itu, atau tutup jendela lama dulu. |
| Pemasangan gagal di tengah jalan | Cek internet dan ruang kosong, lalu ulangi `Pasang_Tera.bat`. Kalau masih gagal, hapus folder `.venv` lalu ulangi. Detailnya di `pasang_tera.log`. |
| Desain ke PRD: **"Tidak ada bahasa OCR terpasang"** | Settings Windows → Time & language → Language & region → Add a language → English. |
| Desain ke PRD: **"Pillow belum terpasang"** | Tutup TƎRᗩ, jalankan `Pasang_Tera.bat` (butuh internet). |
| **Belum masuk ke Server AI bersama** / **Sesi login habis** | Pengaturan → Sumber AI → isi alamat, nama pengguna, password → **Masuk**. Login berlaku 30 hari. |
| **Server AI bersama tidak terhubung** | Buka Tailscale, pastikan sudah masuk. Tanyakan ke pemilik server apakah komputernya menyala dan servernya berjalan. |
| **Terlalu banyak percobaan gagal** | Password salah 5 kali. Tunggu 15 menit, atau minta pemilik server mengganti password. |
| **Versi TƎRᗩ terlalu lama** | Pemilik server mewajibkan versi lebih baru. Perbarui TƎRᗩ (lihat bagian Memperbarui). |
| Proses test case sangat lama | Wajar di laptop tanpa GPU. Tutup aplikasi berat lain, colokkan charger, biarkan berjalan. |

---

## Di mana file-file saya?

| Isi | Folder |
|---|---|
| Dokumen PRD (termasuk hasil konversi catatan dan desain) | `knowledge\prd\` |
| Excel test case | `outputs\` |
| Hasil konversi catatan (PRD, catatan review PDF, catatan asli) | `outputs\free_text_to_prd\` |
| Hasil konversi desain (PRD, catatan review PDF, gambar asli, potongan layar) | `outputs\design_to_prd\` |
| Hasil Bandingkan Test Case (laporan Excel dan datanya) | `outputs\tc_compare\` |
| Riwayat setiap proses pembuatan test case | `runs\` |
| Riwayat MD ke PDF (PDF yang pernah dibuat) | `outputs\md_pdf\` |
| Contoh test case perusahaan (acuan gaya penulisan AI) | `knowledge\company_testcases\` |
| Cadangan file program sebelum pembaruan | `data\cadangan_update\` |
| Pilihan Sumber AI dan token login (rahasia, jangan dibagikan) | `configs\sumber_ai.json` |

---

## Isi folder TƎRᗩ

| File / folder | Fungsi |
|---|---|
| `Pasang_Tera.bat` | Pemasang sekali klik |
| `Jalankan_Tera.bat` | Membuka TƎRᗩ setiap kali mau dipakai |
| `Perbarui_Tera.bat` | Mengambil versi terbaru dari GitHub |
| `VERSION`, `CHANGELOG.md` | Nomor versi dan catatan perubahan |
| `setup\` | Script pemasang yang dipanggil `Pasang_Tera.bat` |
| `dashboard.py`, `dashboard\` | Dashboard TƎRᗩ (tampilan di browser) |
| `run.py`, `agents\`, `tc_workflows\` | Mesin Generator Test Case PRD |
| `free_text_to_prd\` | Mesin Catatan Konversi ke PRD |
| `design_to_prd\` | Mesin Desain Konversi ke PRD |
| `tc_compare\` | Mesin Bandingkan Test Case |
| `tools\` | Bagian bersama: koneksi AI, pembaca PRD, pembuat PDF, aturan validasi |
| `configs\ai.json` | Pengaturan AI (juga bisa diubah dari menu Pengaturan) |
| `knowledge\` | Dokumen PRD, contoh test case perusahaan, daftar istilah terlarang |
| `requirements.txt` | Daftar komponen Python yang dipasang otomatis |

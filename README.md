# TƎRᗩ — Asisten QA berbasis AI

TƎRᗩ membantu QA:

- **Catatan Konversi ke PRD**: catatan QA yang berantakan (notulen, chat, poin-poin) disusun menjadi dokumen PRD yang rapi. TƎRᗩ tidak mengarang; hal yang belum jelas dikumpulkan di catatan review (PDF) terpisah.
- **MD Konversi ke PDF**: file PRD `.md` diubah menjadi PDF yang rapi untuk dibagikan, tanpa AI dan dalam hitungan detik.
- **Desain Konversi ke PRD**: gambar desain (export Figma atau screenshot) per halaman, plus penjelasan opsional, disusun menjadi PRD. Teks di gambar dibaca persis oleh pembaca teks bawaan Windows; AI hanya menentukan jenisnya (tombol, field, label, dan seterusnya).
- **Generator Test Case PRD**: dari dokumen PRD, TƎRᗩ membuat test case lengkap (Excel), lalu memeriksanya dengan AI kedua.
- **Bandingkan test case**: dua kumpulan test case (mis. dari desain dan dari PRD, atau versi lama dan baru) dibandingkan: mana yang berpasangan, mana yang hanya ada di satu sisi, dan mana yang hasil harapannya bertentangan.

Ada dua cara memakai AI-nya:

- **AI di laptop sendiri** (bawaan): semuanya berjalan di laptop kamu. Data tidak dikirim ke internet, dan tidak perlu akun atau API key.
- **Server AI bersama**: laptop yang kurang kuat memakai AI di komputer teman lewat jaringan pribadi terenkripsi (Tailscale), dengan login. Dokumen tetap tersimpan di laptop masing-masing. Lihat [bagian 7](#7-server-ai-bersama-teman-memakai-ai-di-komputermu).

Panduan ini untuk pemula: tidak perlu VS Code dan tidak perlu bisa coding.

---

## 1. Spesifikasi laptop

| | AI di laptop sendiri | Pakai Server AI bersama |
|---|---|---|
| Sistem operasi | Windows 10 atau 11 | Windows 10 atau 11 |
| RAM | 16 GB (8 GB akan sangat lambat atau gagal) | 8 GB cukup |
| Ruang kosong | sekitar 20 GB (sebagian besar untuk model AI) | sekitar 3 GB |
| Kartu grafis (GPU) | Tidak wajib. Tanpa GPU tetap jalan, tapi lebih lama | Tidak perlu |
| Internet | Hanya saat instalasi pertama | Selama memakai AI (lewat Tailscale) |

Perkiraan waktu tanpa GPU: konversi catatan beberapa menit, pembuatan test case untuk PRD besar sekitar 2–3 jam.

---

## 2. Pemasangan sekali klik

1. Buka folder TƎRᗩ, lalu klik dua kali **`Pasang_Tera.bat`**.
2. Pilih cara memakai AI: ketik **1** (AI di laptop ini) atau **2** (Server AI bersama milik teman, tanpa unduh model AI; lihat bagian 7). Kalau ragu, tekan Enter saja (pilihan 1).
3. Tunggu sampai tertulis **SELESAI**. Pertama kali bisa cukup lama (sekitar 15 GB unduhan model AI), jadi pastikan internet stabil dan laptop dicolok charger.
4. Di akhir, ketik **Y** lalu Enter untuk langsung membuka TƎRᗩ.

Yang dikerjakan otomatis (yang sudah ada akan dilewati):

| Langkah | Keterangan |
|---|---|
| Cek laptop | Windows 64-bit, RAM, ruang kosong minimal 20 GB, koneksi internet |
| Python | Dipasang kalau belum ada (lewat winget, atau unduh langsung dari python.org) |
| Ollama (mesin AI lokal) | Dipasang kalau belum ada, lalu dinyalakan. Pilihan 2: diganti Tailscale |
| Komponen TƎRᗩ | Folder `.venv` dan komponen dari `requirements.txt` |
| Model AI | Pilihan 2: dilewati. Termasuk model kemiripan makna `nomic-embed-text` (sekitar 270 MB) untuk Bandingkan test case. Nama model dibaca dari `configs\ai.json` (saat ini `gemma4:e4b` sebagai AI penulis dan `qwen2.5:7b` sebagai AI pemeriksa) |
| Bahasa OCR | Bahasa Inggris untuk pembaca teks Windows (fitur Desain Konversi ke PRD). Windows akan meminta izin admin sekali |
| Shortcut | Ikon **TERA** di Desktop untuk membuka TƎRᗩ berikutnya |

Kalau gagal di tengah jalan, baca pesan merahnya, perbaiki (biasanya internet atau ruang kosong), lalu klik dua kali `Pasang_Tera.bat` lagi. Unduhan model dilanjutkan, tidak mulai dari nol. Catatan lengkap pemasangan tersimpan di `pasang_tera.log`.

<details><summary>Pemasangan manual (kalau pemasang otomatis tidak bisa dipakai)</summary>

1. **Python**: unduh dari <https://www.python.org/downloads/>. Di layar pertama instalasi, centang **"Add python.exe to PATH"**, lalu **Install Now**.
2. **Ollama**: unduh dari <https://ollama.com/download> (Windows), lalu pasang sampai selesai.
3. **Model AI**: buka PowerShell, lalu ketik `ollama pull gemma4:e4b`, `ollama pull qwen2.5:7b`, dan `ollama pull nomic-embed-text`.
4. Jalankan `Jalankan_Tera.bat`. Pertama kali ia membuat folder `.venv` dan memasang komponen sendiri.

</details>

---

## 3. Menjalankan TƎRᗩ

1. Pastikan AI siap:
   - **AI di laptop sendiri**: Ollama menyala (ikon llama ada di taskbar). Kalau belum ada, buka aplikasi Ollama dari Start Menu.
   - **Server AI bersama**: Tailscale menyala dan sudah masuk, dan Server AI temanmu sedang berjalan.
2. Klik dua kali ikon **TERA** di Desktop (atau `Jalankan_Tera.bat` di folder TƎRᗩ).
3. Browser akan terbuka sendiri ke alamat **http://127.0.0.1:8765**. Itulah dashboard TƎRᗩ.
4. **Jangan tutup jendela hitam** (Command Prompt) selama TƎRᗩ dipakai. Browser boleh ditutup dan dibuka lagi lewat alamat di atas.
5. Untuk mematikan TƎRᗩ, klik jendela hitam itu lalu tekan **Ctrl + C**, atau tutup jendelanya.

Kalau Windows menampilkan peringatan **"Windows protected your PC"** saat membuka file `.bat`, klik **More info**, lalu **Run anyway**. File `.bat` ini hanya berisi perintah untuk menjalankan TƎRᗩ dan bisa dibuka dengan Notepad untuk dicek.

---

## 4. Cara pakai singkat

Menu samping: klik **Konversi Dokumen** atau **Generator Test Case PRD** untuk membuka/menutup daftar menunya. Klik **Ciutkan menu** di bagian bawah supaya menu samping hanya menampilkan ikon (arahkan mouse ke ikon untuk melihat namanya); klik ikon yang sama lagi untuk melebarkannya. Pilihan ini diingat oleh browser.

### Catatan ke PRD

1. Menu **Konversi Dokumen**, lalu **Catatan Konversi ke PRD**.
2. Isi **Nama modul** (misalnya `Berita Acara`), tempel catatan QA, lalu klik **Susun PRD**.
3. Setelah selesai:
   - Baca pertanyaannya, lalu klik **Unduh catatan review (PDF)** untuk ditanyakan ke tim.
   - Edit PRD bila perlu, lalu klik **Simpan perubahan**.
   - Klik **Unduh PRD (.md)** untuk menyimpan file PRD-nya, atau **Jadikan PDF** untuk langsung membukanya di MD Konversi ke PDF.
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
6. Setelah selesai, sama seperti Catatan ke PRD: baca hal yang perlu dicek, unduh catatan review (PDF), edit PRD bila perlu, unduh PRD (.md) atau jadikan PDF bila perlu, lalu **Buat test case dari PRD ini**.

**Diproses per fitur, hasilnya tetap satu PRD.** Kartu diproses satu demi satu (dibaca, dikenali AI, dicatat), dan **setiap fitur yang selesai langsung disimpan**. Di akhir semua fitur digabung menjadi **satu PRD** dengan nomor urut yang bersih (`FR-001` dan seterusnya, tabel Business Rules tidak kembar). Jadi:
- Kalau laptop mati, TƎRᗩ ditutup, atau AI-nya putus di tengah, fitur yang sudah selesai **tidak dibaca ulang**. Buka lagi menu ini: ada tulisan *"Ada penyusunan PRD yang terhenti: ..."* beserta tombol **Lanjutkan** (meneruskan dari fitur berikutnya) dan **Buang** (hapus simpanannya, susun ulang dari awal).
- Gambar yang kamu unggah disalin ke folder hasil sebelum diproses, jadi proses tetap bisa dilanjut walau gambar aslinya sudah kamu hapus.
- Kalau nama atau penjelasan sebuah kartu kamu ubah, fitur itu dibaca ulang; fitur lain tetap memakai simpanannya.
- Simpanan ini hanya untuk proses yang terhenti. Begitu PRD-nya jadi, simpanannya dibersihkan sendiri.

PRD dari desain disusun **per alur bisnis**, bukan per elemen. Aturan bahasa bisnis ini juga berlaku untuk **Catatan Konversi ke PRD**: kalimat berbentuk langkah layar ("user klik tombol Simpan lalu muncul pesan Berhasil") otomatis diubah menjadi aturan ("Pengguna dapat menyimpan; bila berhasil sistem menampilkan pesan Berhasil."), setelah kalimat aslinya lolos penjaga kutipan.
- Bingkai sampul di papan alur (bingkai yang hanya berisi judul dan tanggal, misalnya `Users - Create`) menjadi nama alur. Layar sesudahnya menjadi langkah alur itu.
- Aturan ditulis sebagai **kalimat aturan bisnis**, bukan laporan isi layar: nama tombol diterjemahkan menjadi maksudnya (`Add user` → menambahkan user, `Save changes` di form `Edit user` → mengubah user). Contohnya: *Pengguna dapat menambahkan user dengan mengisi "Name", "Occupation", "Email", ... Bila berhasil, sistem menampilkan notifikasi "User added!".* Aturan yang berdiri sendiri tidak menyebut layar sama sekali: *New Password wajib memenuhi aturan "Password must contain at least 8 characters".*
- Urutan layar tetap dicatat, tetapi **hanya satu baris per alur** (`Alur ini melewati ...`), bukan di setiap kalimat.
- Aturan yang tertulis di desain ikut diambil apa adanya, misalnya "Password must contain at least 8 characters" atau "This password reset link will expire in 60 minutes".
- **Satu halaman/area menjadi satu `FR`, tiap alur menjadi sub-judul di dalamnya** (mis. `FR-002 — Other - User` berisi **Users - Create**, **Users - Edit**, dan seterusnya). Sub-judul ini yang mengisi kolom **Sub Module/Menu** di test case, sedangkan kolom **Module/Menu** diisi nama area-nya.
- Tiap `FR` ditutup **Acceptance Criteria** yang diambil dari hasil yang tertulis di alurnya sendiri, bukan dikarang.
- Tombol batal/kembali dan mockup aplikasi email (mis. Gmail) hanya diambil isi emailnya, menu aplikasinya diabaikan.
- **Rincian isi layar tidak masuk PRD**: aksi lain di layar, kolom tabel, menu navigasi, tab, daftar status, contoh isian, dan teks penjelasan/sapaan dipindah ke bagian *Rincian isi layar* di **catatan review**. PRD-nya berisi alur dan aturan saja, tetapi rinciannya tidak dibuang — kalau ada yang memang perlu diuji, salin sendiri dari catatan review.

PRD yang dihasilkan (baik dari catatan maupun dari desain) memakai kerangka PRD yang biasa dipakai QA: Document Information, Actors, Feature Overview, **Navigation Structure** (tabel menu yang terlihat), **Functional Requirements** (`FR-001`, sub-judul per alur, ditutup Acceptance Criteria), **Business Rules** (tabel `BR-001` berisi aturan yang bisa langsung diuji), **Data & Field Reference** (tabel tiap field beserta keterangan dan contoh isian yang tertulis di sumber), **System Feedback & States** (tabel notifikasi beserta pemicunya), Key State Model, Edge-Case Areas, Expected QA Coverage, Test Data Guidance, Acceptance Criteria, dan **Open Points**.

**Open Points** adalah bagian penting: hal yang tidak terlihat di sumber **tidak ditebak**, melainkan ditulis sebagai pertanyaan untuk PO/tim (misalnya "Tombol X tampak nonaktif di desain — kapan tombol ini bisa diklik?"). TƎRᗩ sengaja tidak menambahkan kebutuhan umum seperti "sistem harus memvalidasi format email" kalau aturan itu tidak tertulis di sumbernya, supaya tidak ada test case yang menguji hal yang belum tentu dibangun. Bagian lain yang tidak ada dasarnya di sumber juga tidak ditulis, jadi kalau desainmu tidak memuat aturan atau status, bagian itu memang kosong.
- Layar yang sama (misalnya halaman daftar yang muncul di awal setiap alur) hanya dijelaskan sekali.
- Supaya alurnya terbaca rapi, susun papan alur di Figma per skenario dan beri bingkai sampul di awal setiap skenario.

Tips gambar:
- Export dari Figma: pilih frame, di panel kanan bagian **Export** pilih **PNG** ukuran **2x**, lalu klik Export.
- Bagian yang diburamkan di belakang modal atau panel otomatis diabaikan.
- Fitur ini memakai pembaca teks bawaan Windows, jadi hanya berjalan di Windows.

### MD ke PDF

1. Menu **Konversi Dokumen**, lalu **MD Konversi ke PDF**.
2. Tambahkan file: klik **Pilih file .md** (boleh beberapa sekaligus) atau seret file ke kotaknya. Bisa juga memilih PRD yang sudah ada di TƎRᗩ, lalu **Tambahkan ke daftar**.
3. Untuk setiap file: **Lihat PDF** (terbuka di tab baru) atau **Unduh PDF**. Kalau banyak, klik **Unduh semua PDF**; bila browser bertanya, izinkan unduhan beberapa file.

PDF berukuran A4, lengkap dengan judul, daftar, tabel, kutipan, blok kode, dan nomor halaman. Fitur ini tidak memakai AI, jadi tetap bisa dipakai saat proses lain berjalan. PDF langsung diunduh ke folder Downloads dan tercatat di menu Riwayat, jadi bisa diunduh lagi. Batas ukuran 2 MB per file.

### Membuat test case dari PRD

1. Menu **Generator Test Case PRD**, lalu **Mulai baru**.
2. Pilih dokumen PRD dari dropdown. PRD baru bisa ditambahkan dengan **Tambah dokumen PRD** (file `.md`).
3. Pastikan kartu **Kesiapan** semuanya hijau, lalu klik **Mulai buat test case**.
4. Pantau di **Sedang berjalan**. Selama proses, laptop dijaga agar tidak tidur otomatis, tapi **jangan tutup layar laptop**.
5. Setelah selesai:
   - **Hasil**: ringkasan dan tombol **Unduh Excel**.
   - **Perlu dicek**: test case yang ditandai AI untuk dicek manual.
   - **Cakupan**: memastikan semua bagian PRD sudah ada test case-nya.

Semua proses dari setiap menu tercatat di menu **Riwayat** beserta hasilnya: pembuatan test case, konversi catatan, konversi desain, MD ke PDF (PDF-nya bisa diunduh lagi), dan perbandingan test case.

### Bandingkan test case

1. Menu **Bandingkan Test Case** (menu sendiri di sisi kiri).
2. Untuk **Test case A** dan **Test case B**: beri nama kumpulan (mis. `Dari desain` dan `Dari PRD`), lalu pilih sumbernya:
   - **Dari Riwayat**: hasil Generator Test Case PRD yang sudah selesai.
   - **Unggah file**: Excel (.xlsx) atau JSON, maks. 20 MB, termasuk test case buatan manual. TƎRᗩ mencari sendiri kolom judul test case, Test Data, Expected Result, dan lainnya; kolom yang dikenali ditampilkan setelah unggah.
3. Pilih mode:
   - **Lengkap**: kode, kemiripan makna, lalu AI untuk pasangan yang masih ragu. Biasanya ±10–20 menit, tergantung jumlah pasangan yang ragu.
   - **Cepat**: tanpa AI chat, ±1 menit. Pasangan yang ragu masuk **Perlu dicek** untuk kamu putuskan sendiri.
4. Klik **Bandingkan**. Hasilnya: persentase test case A dan B yang berpasangan, kesimpulan dan rekomendasi, serta tab **Berpasangan**, **Bertentangan**, **Perlu dicek**, **Hanya di A**, **Hanya di B**, dan **Kembar**. Klik **Unduh Excel** untuk laporan lengkapnya.

Cara kerjanya bertingkat supaya cepat: kode memutuskan yang sudah jelas (isi sama persis, sangat mirip, atau Test Data sama tapi hasil harapan berlawanan), model kemiripan makna `nomic-embed-text` menangkap kalimat beda kata tetapi sama maksud, dan AI hanya dipakai untuk sisa yang masih ragu. Test case sumber tidak pernah diubah. Hasil perbandingan disimpan di `outputs\tc_compare\` dan bisa dibuka lagi di bagian **Perbandingan sebelumnya**.

### Pengaturan

- **Sumber AI**: pilih **AI di laptop ini** atau **Server AI bersama** (isi alamat server, nama pengguna, dan password dari pemilik server, lalu **Masuk**). Bagian ini tidak bisa diganti selama ada proses yang berjalan.
- **Referensi test case perusahaan**: mengunci file contoh test case perusahaan dengan password (lihat bagian 9).
- **AI yang dipakai** dan **Cara kerja**: model AI dan pengaturan proses. Berlaku untuk proses berikutnya.

---

## 5. Di mana file-file saya?

| Isi | Folder |
|---|---|
| Dokumen PRD (termasuk hasil konversi catatan dan desain) | `knowledge\prd\` |
| Excel test case | `outputs\` |
| Hasil konversi catatan (PRD, catatan review PDF, catatan asli) | `outputs\free_text_to_prd\` |
| Hasil konversi desain (PRD, catatan review PDF, gambar asli, potongan layar) | `outputs\design_to_prd\` |
| Hasil Bandingkan test case (laporan Excel dan data hasil) | `outputs\tc_compare\` |
| Riwayat setiap proses pembuatan test case | `runs\` |
| Contoh test case perusahaan (acuan gaya penulisan AI), bisa dikunci dengan password | `knowledge\company_testcases\` |
| Riwayat MD ke PDF (PDF yang pernah dibuat) | `outputs\md_pdf\` |
| Cadangan file program sebelum pembaruan | `data\cadangan_update\` |
| Pilihan Sumber AI dan token login ke Server AI bersama (rahasia, jangan dibagikan) | `configs\sumber_ai.json` |
| Akun dan catatan pemakaian Server AI, hanya di komputer pemilik server (rahasia) | `data\server_ai\` |

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
| **Belum masuk ke Server AI bersama** / **Sesi login habis** | Pengaturan > Sumber AI > isi alamat, nama pengguna, password, lalu **Masuk**. Login berlaku 30 hari. |
| **Server AI bersama tidak terhubung** | Buka Tailscale dan pastikan sudah masuk. Tanyakan ke pemilik server apakah `Server_AI_dan_Admin_Akun.bat` sedang berjalan dan komputernya menyala. |
| **Terlalu banyak percobaan gagal** | Password salah 5 kali. Tunggu 15 menit, atau minta pemilik server mengganti password. |
| Proses test case sangat lama | Wajar di laptop tanpa GPU. Tutup aplikasi berat lain, colokkan charger, dan biarkan berjalan. |

---

## 7. Server AI bersama (teman memakai AI di komputermu)

Cocok bila teman tidak punya laptop yang kuat. Setiap orang tetap memasang TƎRᗩ di laptopnya sendiri, jadi **PRD, catatan, desain, dan test case tetap di laptop masing-masing**. Hanya permintaan ke AI yang dikirim ke komputermu, lewat **Tailscale** (jaringan pribadi terenkripsi, gratis sampai 6 orang).

```
Laptop teman (TƎRᗩ) --Tailscale, terenkripsi--> Komputermu: Server AI (wajib login) --> Ollama (hanya 127.0.0.1)
```

Keamanannya:
- Server hanya menerima koneksi dari jaringan Tailscale dan dari komputermu sendiri. Dari internet biasa atau Wi-Fi kantor ditolak.
- Setiap teman wajib login. Akun hanya dibuat oleh kamu (admin). Password disimpan teracak (tidak bisa dibaca balik).
- Salah password 5 kali: akun dan alamatnya dikunci 15 menit.
- Server tidak menyimpan isi dokumen. Yang dicatat hanya siapa, kapan, model apa, berapa lama, dan berapa token.
- Teman tidak bisa mengunduh, menghapus, atau mengganti model AI di komputermu.

### Untuk pemilik server (kamu)

File Server AI (`Server_AI_dan_Admin_Akun.bat` dan folder `ai_server\`) sengaja **tidak ikut naik ke GitHub**, jadi hanya ada di komputermu. Teman yang mengunduh TƎRᗩ dari GitHub tidak menerima halaman admin maupun servernya.

> Karena tidak ada di GitHub, **salinan satu-satunya ada di komputermu**. Perintah Git yang membersihkan file di luar daftar Git (misalnya `git clean`, atau "discard/clean untracked files" di Visual Studio) bisa menghapusnya. Simpan cadangan folder `ai_server\` dan file `Server_AI_dan_Admin_Akun.bat` di luar folder TƎRᗩ. Akun teman-teman aman di `data\server_ai\` dan tidak ikut terhapus. Fitur Perbarui tidak pernah menyentuh keduanya.

1. Pasang TƎRᗩ seperti biasa (pilihan **1**).
2. Pasang Tailscale dari <https://tailscale.com/download>, lalu masuk.
3. Klik dua kali **`Server_AI_dan_Admin_Akun.bat`**. Pertama kali Windows meminta izin admin untuk membuka pintu firewall khusus jaringan Tailscale: klik **Yes**.
4. Halaman admin terbuka di browser (`http://127.0.0.1:11500/admin`, hanya bisa dibuka dari komputermu). Buat akun untuk setiap teman, lalu kirim nama pengguna dan password lewat chat pribadi. Kalau jendela adminnya sudah tertutup, klik dua kali file yang sama lagi: bila server masih berjalan, yang terbuka hanya halaman adminnya. Bisa juga ketik `http://127.0.0.1:11500/admin` di browser.
5. Bagikan komputermu ke teman dari Tailscale: <https://login.tailscale.com> > **Machines** > titik tiga di komputermu > **Share**, lalu kirim tautannya ke teman.
6. Berikan **Alamat untuk teman** yang tertulis di halaman admin (contoh `http://100.101.102.103:11500`).

Jendela `Server_AI_dan_Admin_Akun.bat` harus tetap terbuka dan komputer menyala selama teman memakai AI. Dari halaman admin kamu bisa menonaktifkan akun, mengganti password (semua perangkat akun itu otomatis keluar), menghapus akun, dan melihat pemakaian 30 hari terakhir.

> **Jangan** mengubah Ollama supaya terbuka ke jaringan (`OLLAMA_HOST=0.0.0.0`). Itu melewati login. Halaman admin akan memberi peringatan merah bila ini terjadi.

### Untuk teman

1. Pasang TƎRᗩ dengan `Pasang_Tera.bat`, pilih **2**. Tailscale ikut dipasang.
2. Buka Tailscale, masuk, lalu terima undangan dari pemilik server.
3. Buka TƎRᗩ > **Pengaturan** > **Sumber AI** > **Server AI bersama**, isi alamat server, nama pengguna, dan password, lalu **Masuk**.

Untuk kembali memakai AI di laptop sendiri, pilih **AI di laptop ini** di bagian yang sama.

---

## 8. Versi TƎRᗩ

Nomor versi TƎRᗩ tampil di pojok kiri bawah dashboard. Klik untuk membuka halaman **Apa yang baru** (isi file `CHANGELOG.md`).

Nomor versi ditulis tiga angka, misalnya **1.2.3**:

| Angka | Naik bila | Contoh |
|---|---|---|
| Pertama (**1**.2.3) | Perubahan besar, versi lama tidak bisa dipakai bersama lagi | 1.4.2 → 2.0.0 |
| Kedua (1.**2**.3) | Ada fitur baru | 1.1.0 → 1.2.0 |
| Ketiga (1.2.**3**) | Hanya perbaikan | 1.2.0 → 1.2.1 |

### Merilis versi baru (pemilik TƎRᗩ)

1. Ubah angka di file **`VERSION`** (buka dengan Notepad, isinya hanya satu baris, misalnya `1.2.0`).
2. Di **`CHANGELOG.md`**, tambahkan bagian baru **paling atas** (di bawah penjelasan), dengan format yang sama:
   ```
   ## 1.2.0 — 20 November 2026

   ### Baru
   - Fitur yang ditambahkan.

   ### Perbaikan
   - Masalah yang diperbaiki.
   ```
3. Simpan, lalu tutup dan buka lagi TƎRᗩ (dan `Server_AI_dan_Admin_Akun.bat` bila sedang berjalan).

### Teman memakai versi lama

- Bila komputer server memakai versi lebih baru, TƎRᗩ teman menampilkan **Ada versi baru** di pojok kiri bawah.
- Di halaman admin Server AI, kolom **Versi** menunjukkan versi TƎRᗩ setiap teman (tanda **Lama** bila lebih lama dari server).
- Untuk mewajibkan update, isi **Versi TƎRᗩ minimal untuk teman** di halaman admin, lalu klik **Simpan versi minimal**. Teman dengan versi lebih lama tidak bisa memakai AI dan diminta memperbarui TƎRᗩ. Kosongkan untuk mencabut batasnya.

### Memperbarui TƎRᗩ tanpa mengirim ulang foldernya

TƎRᗩ mengambil versi baru langsung dari GitHub. Setelah kamu menaikkan versi baru ke branch `master` (dengan `VERSION` dan `CHANGELOG.md` yang sudah diubah), teman cukup:

- membuka TƎRᗩ: bila ada versi baru, muncul tanda **Ada versi baru** di pojok kiri bawah. Klik, lalu **Perbarui sekarang**, lalu tutup dan buka lagi TƎRᗩ; atau
- menutup TƎRᗩ, lalu klik dua kali **`Perbarui_Tera.bat`**.

Yang diperbarui hanya file program. Hasil kerja (`runs\`, `outputs\`), dokumen PRD (`knowledge\prd\`), akun dan token, serta pilihan di Pengaturan tidak diubah. File program lama dicadangkan dulu di `data\cadangan_update\`.

Catatan:
- Fitur ini baru ada mulai versi 1.3.0. Teman yang masih memakai versi 1.2.0 ke bawah perlu **sekali** menerima folder terbaru (atau mengunduh ZIP dari GitHub dan menimpa foldernya). Sesudah itu selalu bisa memperbarui sendiri.
- Folder milikmu sendiri terhubung ke Git, jadi tidak ditimpa otomatis. Kamu tetap memakai Git seperti biasa.
- Alamat repo dan branch sumber pembaruan ada di `configs\update.json`.

---

## 9. Untuk yang membagikan TƎRᗩ ke orang lain

Saat menyalin atau meng-zip folder TƎRᗩ untuk teman, **jangan ikut sertakan**:

- `.venv\` (besar dan khusus untuk laptop kamu; `Pasang_Tera.bat` di laptop teman akan membuatnya sendiri)
- `.env` (bisa berisi data rahasia)
- `runs\` dan `outputs\` (hasil kerja kamu)
- `knowledge\prd\` bila berisi PRD milikmu (saat memperbarui TƎRᗩ teman, PRD milik teman bisa tertimpa)
- `__pycache__\`, `.vs\`, dan `pasang_tera.log` (file sementara)
- `configs\sumber_ai.json` (token login Server AI kamu) dan `data\server_ai\` (akun Server AI teman-teman)

Teman cukup menerima folder TƎRᗩ, lalu klik dua kali `Pasang_Tera.bat`.

Cek juga isi `knowledge\prd\`. Kalau berisi dokumen internal kantor, pastikan memang boleh dibagikan sebelum ikut disalin.

### Mengunci file referensi test case perusahaan

File Excel di `knowledge\company_testcases\` adalah contoh test case perusahaan yang gaya penulisannya ditiru AI. Supaya tidak terbaca orang lain:

1. Simpan dulu salinan file aslinya di tempat aman di luar folder TƎRᗩ.
2. Buka **Pengaturan** > **Referensi test case perusahaan** > **Kunci dengan password**, isi password dua kali, lalu **Kunci file**.
3. File `.xlsx` berubah menjadi `.xlsx.terakunci`. Hanya versi terkunci ini (dan `kunci.json`, yang bukan rahasia) yang ikut naik ke GitHub; file `.xlsx` biasa di folder itu tidak akan ikut naik lagi.

Di laptopmu kuncinya langsung tersimpan, jadi TƎRᗩ tetap memakai referensi itu.

Di laptop teman, caranya (cukup sekali per laptop):

1. Buka **Pengaturan** > **Referensi test case perusahaan** > **Isi password**.
2. Ketik password yang kamu berikan, lalu **Simpan**. Kuncinya tersimpan di laptop itu (`configs\kunci_referensi.json`, tidak ikut ke GitHub).

Tanpa password, test case tetap bisa dibuat, hanya tanpa contoh gaya penulisan perusahaan, dan di **Mulai baru** muncul keterangan "Referensi test case perusahaan terkunci". Kirim passwordnya lewat chat pribadi, jangan ditulis di README atau di repo.

Yang perlu diketahui:
- Kalau password lupa, file terkunci tidak bisa dibuka oleh siapa pun. Karena itu simpan salinan aslinya.
- Siapa pun yang kamu beri password bisa memakai (dan pada akhirnya membaca) isinya. Beri hanya ke orang yang memang boleh.
- File asli yang **sudah pernah** naik ke GitHub masih ada di riwayat Git lama. Mengunci tidak menghapus riwayat itu.
- Teman yang sudah terlanjur menerima file `.xlsx` versi lama akan tetap memakai file itu, bukan versi terkuncinya. Minta mereka menghapus file `.xlsx` di `knowledge\company_testcases\`.
- **Buka kunci permanen** mengembalikan file menjadi `.xlsx` biasa.

---

## 10. Isi folder TƎRᗩ

| File / folder | Fungsi |
|---|---|
| `Pasang_Tera.bat` | Pemasang sekali klik (Python, Ollama, komponen, model AI, bahasa OCR, ikon Desktop) |
| `Jalankan_Tera.bat` | Membuka TƎRᗩ setiap kali mau dipakai |
| `Perbarui_Tera.bat` | Mengambil versi TƎRᗩ terbaru dari GitHub (bisa juga dari tombol di dalam TƎRᗩ) |
| `VERSION`, `CHANGELOG.md` | Nomor versi TƎRᗩ dan catatan perubahan setiap versi |
| `Server_AI_dan_Admin_Akun.bat`, `ai_server\` | Menyalakan Server AI bersama dan membuka halaman admin untuk membuat akun teman (hanya di komputer pemilik server) |
| `setup\` | Script pemasang yang dipanggil `Pasang_Tera.bat` |
| `dashboard.py`, `dashboard\` | Dashboard TƎRᗩ (tampilan di browser) |
| `run.py`, `agents\`, `tc_workflows\` | Mesin Generator Test Case PRD |
| `free_text_to_prd\` | Mesin Catatan Konversi ke PRD |
| `design_to_prd\` | Mesin Desain Konversi ke PRD (potong layar, baca teks, susun PRD) |
| `tc_compare\` | Mesin Bandingkan test case (rapikan, cocokkan, kemiripan makna, penilaian AI, laporan Excel) |
| `tools\` | Bagian bersama: koneksi AI, pembaca PRD, pembuat PDF (MD Konversi ke PDF), aturan validasi isian, dan lainnya |
| `configs\ai.json` | Pengaturan AI (juga bisa diubah dari menu Pengaturan) |
| `knowledge\` | Dokumen PRD, contoh test case perusahaan, dan daftar istilah terlarang |
| `requirements.txt` | Daftar komponen Python yang dipasang otomatis |

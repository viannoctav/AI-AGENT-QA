# Catatan perubahan TƎRᗩ

Nomor versi ditulis tiga angka, misalnya 1.2.3:

- angka pertama naik bila ada perubahan besar yang membuat versi lama tidak bisa dipakai bersama lagi;
- angka kedua naik bila ada fitur baru;
- angka ketiga naik bila hanya ada perbaikan.

Setiap rilis: ubah angka di file `VERSION`, lalu tulis perubahannya paling atas di file ini.

## 1.3.0 — 14 November 2026

### Baru
- **Bandingkan Test Case menjadi Gabungkan Test Case.** Mesin pencocokannya tetap sama (kode, kemiripan makna, AI hanya untuk yang ragu), tetapi hasil utamanya sekarang **satu file test case gabungan**: pasangan yang sama diambil satu dari kumpulan A, yang cuma mirip disimpan dua-duanya dan diberi tanda, yang bertentangan ditandai jelas, dan test case kembar dibuang. File-nya memakai template test case biasa plus kolom Asal dan Catatan gabung. Laporan perbandingan lama tetap ada di bagian Rincian perbandingan.
- Dua test case yang sama-sama ditandai Negative tetapi hasil harapannya berlawanan kini ikut terdeteksi sebagai bertentangan.
- Pembaruan dari GitHub: TƎRᗩ memberi tahu bila ada versi baru dan bisa memperbarui dirinya lewat tombol Perbarui sekarang atau file Perbarui_Tera.bat. Hasil kerja, dokumen PRD, akun, dan pengaturan tidak diubah; file program lama dicadangkan.
- Kunci file referensi test case perusahaan dengan password (Pengaturan). Yang ikut ke GitHub hanya versi terkunci.
- Riwayat mencatat semua proses dari setiap menu, termasuk MD ke PDF (PDF bisa diunduh lagi) dan perbandingan test case.
- Bandingkan Test Case menjadi menu sendiri di sisi kiri.

### Perbaikan
- Contoh Test Data di instruksi AI memakai field yang sedang ditulis (bila PRD tidak memuat contohnya, dipakai nilai menurut jenis field: email, nomor telepon, password, tanggal, angka), bukan contoh pertama yang kebetulan ada. Nama layar atau nama alur yang terbaca sebagai nama field juga tidak lagi ikut ke panduan data uji.
- Kolom **Test Data** tidak lagi berisi isian pengganti. Contoh di instruksi AI dulu memakai teks pengganti di dalam tanda kurung siku, dan model kecil menyalinnya mentah-mentah (64% baris pada percobaan terakhir). Contohnya sekarang memakai nilai sungguhan dari bagian Test Data Guidance pada PRD, dan penulisan isian pengganti dilarang.
- Nama tombol asli kembali ditulis di PRD dari desain ("... lalu menekan tombol \"Login\""), supaya langkah uji memakai tombol yang benar-benar ada, bukan terjemahannya.
- Baris urutan layar ("Alur ini melewati ...") ditulis miring sebagai konteks, jadi tidak lagi berubah menjadi test case campur aduk.
- **Mulai baru** punya pilihan **Jenis PRD**: PRD lengkap (ditulis manusia) atau PRD hasil konversi desain. Pada pilihan kedua, AI dilarang menambah aturan yang tidak tertulis di desain dan wajib memakai nama tombol serta kolom persis seperti tertulis.
- PRD (dari desain maupun dari catatan) ditulis sebagai **aturan bisnis**: subjek + dapat/harus/tidak boleh + akibatnya. Nama tombol diterjemahkan ke maksudnya ("Add user" -> "Pengguna dapat menambahkan user"), aturan isian tidak lagi menyebut nama form, dan urutan layar hanya ditulis satu baris per alur. Di Catatan ke PRD, kalimat berbentuk langkah layar dirapikan setelah lolos penjaga kutipan, jadi penjaganya tetap menilai kalimat asli.
- PRD dari desain ditulis sebagai kalimat kebutuhan yang mengalir, bukan daftar template. Isian, tombol, dan hasilnya digabung jadi satu kalimat ("Pada form "Add user" yang bertuliskan "Add a new user account", pengguna mengisi "Name", "Occupation", ..., lalu menekan "Add user". Setelah itu sistem menampilkan notifikasi "User added!"."). Satu `FR` per halaman/area dengan sub-judul per alur, sehingga kolom Module/Menu dan Sub Module/Menu di test case terisi benar.
- PRD mendapat bagian baru: Navigation Structure, Data & Field Reference, System Feedback & States, Acceptance Criteria per FR, dan Open Points (hal yang tidak terlihat di sumber ditulis sebagai pertanyaan untuk PO, bukan ditebak).
- Kolom Test Data tidak lagi berisi "<nama fitur>: <nilai uji>"; nama field diambil dari kalimat aturan dan contoh isiannya dari desain.
- Desain Konversi ke PRD diproses **per fitur** dan setiap fitur yang selesai langsung disimpan, lalu semuanya digabung menjadi satu PRD di akhir (nomor FR/BR tetap urut dan tidak kembar). Proses yang mati, ditutup, atau putus AI-nya bisa diteruskan lewat tombol Lanjutkan tanpa membaca ulang fitur yang sudah jadi; tombol Buang menghapus simpanannya. Gambar unggahan disalin ke folder hasil sebelum diproses supaya proses tetap bisa dilanjut.
- PRD hasil konversi (catatan maupun desain) kini lengkap seperti PRD yang biasa dipakai QA: tabel Business Rules (BR-001 dan seterusnya) berisi aturan yang bisa langsung diuji, Key State Model berisi status yang terlihat di sumber, Edge-Case Areas yang disusun dari isi PRD-nya sendiri, Expected QA Coverage, Test Data Guidance dari contoh isian yang tertulis di sumber, dan Acceptance Criteria per fitur. Bagian Actors selalu terisi.
- Desain Konversi ke PRD kini menyusun PRD per alur bisnis, bukan daftar elemen. Bingkai sampul di papan alur menjadi nama alur, dan tiap langkah ditulis sebagai aksi pengguna beserta jawaban sistem ("Di form X, pengguna mengisi A, lalu menekan B. Setelah itu sistem membuka C"). Notifikasi dikaitkan ke tombol yang memicunya, judul layar berupa sapaan diganti nama aksinya (mis. "Welcome back!" menjadi "Login"), tautan sampingan tidak lagi dianggap membawa ke layar berikutnya, dan mockup aplikasi email hanya diambil isi emailnya. Layar yang sama tidak diulang.
- PRD dari desain tidak lagi gemuk: satu alur bisnis menjadi satu `FR` (mis. `FR-003 — Authentication — Forgot Password`), dan rincian isi layar (aksi lain, kolom tabel, menu, tab, daftar status, contoh isian, teks sapaan/penjelasan) dipindah ke bagian "Rincian isi layar" di catatan review, bukan dibuang. Teks di layar hanya menjadi aturan PRD bila memang berbunyi aturan atau akibat.
- Desain Konversi ke PRD lebih cepat: layar dengan teks yang sama dan bingkai sampul tidak lagi ditanyakan ke AI. Tombol, teks petunjuk isian, dan kalimat aturan yang terlewat AI dilengkapi kode.
- File Server AI dan halaman admin akun tidak lagi ikut naik ke GitHub.

## 1.2.0 — 13 November 2026

### Baru
- MD Konversi ke PDF (menu Konversi Dokumen): file PRD .md diubah menjadi PDF A4 yang rapi, lengkap dengan tabel, daftar, dan nomor halaman. Tanpa AI, selesai dalam hitungan detik, tidak mengganggu proses lain.
- Tombol Unduh PRD (.md) dan Jadikan PDF di hasil Catatan Konversi ke PRD dan Desain Konversi ke PRD.
- Menu samping bisa diciutkan menjadi ikon saja (tombol Ciutkan menu di bawah), dan grup Konversi Dokumen serta Generator Test Case PRD bisa dibuka-tutup. Pilihan ini diingat di browser.
- Bandingkan test case (menu Generator Test Case PRD): dua kumpulan test case (dari Riwayat atau file Excel/JSON) dibandingkan bertingkat. Kode memutuskan yang sudah jelas, model kemiripan makna mempersempit sisanya, dan AI hanya menilai pasangan yang masih ragu. Hasil: berpasangan, hanya di A, hanya di B, bertentangan, kembar, perlu dicek, kesimpulan, dan Excel. Ada mode cepat tanpa AI chat.
- Tombol Hapus dokumen ini di Mulai baru untuk membuang PRD yang tidak dipakai lagi dari daftar.
- Model kemiripan makna (nomic-embed-text) ikut dipasang oleh Pasang_Tera.bat dan bisa dipakai lewat Server AI bersama.
- Menu Alur Kerja menjelaskan siapa yang mengatur alur (orkestrator): dari dashboard, manajer proses, orkestrator setiap fitur (LangGraph untuk Generator Test Case PRD), pekerja AI dan kode, sampai mesin AI.

## 1.1.0 — 13 November 2026

### Baru
- Server AI bersama: teman memakai AI di komputer pemilik server lewat Tailscale, wajib login. Dokumen tetap di laptop masing-masing.
- Halaman admin Server AI: buat, nonaktifkan, hapus akun, ganti password, dan lihat pemakaian 30 hari terakhir.
- Pengaturan > Sumber AI: pilih AI di laptop ini atau Server AI bersama.
- Pemasang sekali klik punya pilihan "Server AI bersama" (tanpa unduh model AI, Tailscale ikut dipasang).
- Nomor versi TƎRᗩ tampil di dashboard, beserta halaman Apa yang baru.
- Server AI bisa mewajibkan versi TƎRᗩ minimal untuk teman yang terhubung.

## 1.0.0 — 12 November 2026

### Baru
- Generator Test Case PRD: test case lengkap dalam Excel, diperiksa ulang oleh AI kedua, dengan halaman Hasil, Perlu dicek, dan Cakupan.
- Catatan Konversi ke PRD: catatan QA disusun menjadi PRD beserta catatan review (PDF).
- Desain Konversi ke PRD: gambar desain per halaman disusun menjadi PRD; papan alur dipotong per layar otomatis.
- Perkiraan waktu dan progres saat menyusun PRD dari desain.
- Menu Alur Kerja, layar pembuka, dan animasi halus.
- Pemasang sekali klik (Pasang_Tera.bat): Python, Ollama, komponen, model AI, bahasa OCR, dan ikon Desktop.
- Pemeriksaan isian yang salah di semua form.

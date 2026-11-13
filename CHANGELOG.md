# Catatan perubahan TƎRᗩ

Nomor versi ditulis tiga angka, misalnya 1.2.3:

- angka pertama naik bila ada perubahan besar yang membuat versi lama tidak bisa dipakai bersama lagi;
- angka kedua naik bila ada fitur baru;
- angka ketiga naik bila hanya ada perbaikan.

Setiap rilis: ubah angka di file `VERSION`, lalu tulis perubahannya paling atas di file ini.

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

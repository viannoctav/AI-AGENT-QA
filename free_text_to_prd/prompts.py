"""Instruksi untuk AI. Tidak memuat istilah dari PRD/catatan tertentu (contoh memakai pola X/Y)."""

SYSTEM = ("Kamu analis QA yang teliti. Tugasmu MENYUSUN ULANG catatan menjadi data terstruktur, BUKAN menambah. "
          "Semua isi wajib berasal dari catatan. Jawab HANYA JSON valid.")

EXTRACT = """Catatan QA (setiap baris diawali nomor baris [Ln]):
{notes}

Ambil SEMUA informasi kebutuhan dari catatan di atas, baris demi baris. Satu baris boleh menghasilkan beberapa item
(mis. satu baris menyebut tiga field). JANGAN menambah aturan, angka, role, status, pesan, atau fitur yang tidak tertulis.

Untuk setiap item isi:
- baris: nomor baris sumber (angka).
- kutipan: salin PERSIS potongan teks dari baris itu (tanpa nomor baris).
- fitur: nama fitur/menu/halaman yang dibahas, memakai kata dari catatan (lihat juga judul/induk poin di atasnya).
  Kosongkan "" bila informasi umum untuk seluruh aplikasi.
- jenis, salah satu:
  "field"   = isian/kolom form beserta format, panjang, pilihan, wajib/opsional,
  "aturan"  = batasan, validasi, nilai, batas waktu, perilaku sistem,
  "akses"   = siapa (role) boleh/tidak boleh melakukan apa, atau melihat data siapa,
  "status"  = tahap/status dan perpindahannya,
  "alur"    = urutan proses/langkah,
  "nonfungsional" = kinerja, keamanan umum, kapasitas,
  "info"    = gambaran umum aplikasi/fitur (bukan aturan).
- pernyataan: SATU kalimat requirement yang jelas dalam bahasa catatan. Pertahankan istilah, nama field, nama role,
  nama status, dan angka PERSIS seperti di catatan (jangan diterjemahkan). Perbaiki salah ketik yang jelas saja.
  Pola: "X wajib diisi", "Panjang X 8-12 karakter", "Role Y dapat melakukan Z", "Role Y tidak dapat melakukan Z".
  WAJIB ditulis sebagai ATURAN BISNIS: subjek (pengguna/role/sistem) + dapat / harus / tidak dapat / tidak boleh +
  apa yang terjadi. DILARANG menulis langkah memakai layar sebagai inti kalimat ("pengguna klik tombol X",
  "buka halaman Y lalu tekan Z"). Bila catatan berbentuk langkah layar, ubah menjadi kemampuan dan akibatnya,
  nama tombol/layar boleh disebut sebagai keterangan saja. Contoh perubahan:
  "user klik tombol Simpan lalu muncul pesan Berhasil" -> "Pengguna dapat menyimpan data; bila berhasil sistem
  menampilkan pesan \\"Berhasil\\"."; "di halaman Daftar ada tombol Export" -> "Pengguna dapat mengekspor data dari
  halaman Daftar."; "kalau salah 3x akun kekunci" -> "Akun terkunci setelah 3 kali percobaan gagal."
- khusus jenis "akses": role (nama role persis), aksi (apa yang dilakukan/dilihat, singkat), boleh (true/false),
  lingkup (data siapa yang boleh dilihat/diolah, bila disebut; selain itu "").
- khusus jenis "status": objek (apa yang berubah status), dari, ke (nama tahap persis), pemicu (bila disebut; selain itu "").

Isi juga:
- produk: nama aplikasi/produk bila disebut, selain itu "".
- peran: daftar semua role/aktor yang disebut di catatan.

FORMAT:
{{"produk":"","peran":["..."],"items":[{{"baris":1,"kutipan":"...","fitur":"...","jenis":"aturan","pernyataan":"...",
"role":"","aksi":"","boleh":true,"lingkup":"","objek":"","dari":"","ke":"","pemicu":""}}]}}"""

QUESTIONS = """Catatan QA asli:
{notes}

Draf PRD yang disusun dari catatan itu:
{draft}

Sebagai QA, daftar hal yang BELUM JELAS atau SALING BERTENTANGAN di catatan, yang perlu ditanyakan ke tim
sebelum test case dibuat. Contoh pola: format/panjang field X tidak disebut; pesan error saat Y gagal tidak disebut;
jumlah yang disebut tidak sama dengan jumlah yang didaftar; siapa yang boleh melakukan Z tidak disebut.
JANGAN menjawab pertanyaannya dan JANGAN menulis aturan baru.

Untuk setiap pertanyaan isi:
- fitur: nama fitur dari draf ("" bila umum),
- jenis: "belum jelas" atau "bertentangan",
- pertanyaan: kalimat tanya yang spesifik, Bahasa Indonesia,
- kutipan: untuk "bertentangan" salin PERSIS potongan catatan yang bertentangan; untuk "belum jelas" boleh "".
Maksimal 15 pertanyaan, yang paling penting untuk pengujian lebih dulu.

FORMAT: {{"pertanyaan":[{{"fitur":"","jenis":"belum jelas","pertanyaan":"...","kutipan":""}}]}}"""

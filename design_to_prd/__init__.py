"""Desain (gambar export Figma / screenshot) + penjelasan QA -> PRD Markdown dengan format yang dibaca generator test case.

Prinsip: TIDAK mengarang.
- Teks di layar dibaca oleh OCR bawaan Windows (persis, termasuk salah ketik), bukan diketik ulang oleh AI.
- AI hanya memberi JENIS pada teks yang sudah terbaca (tombol, field, label, ...); AI tidak bisa menambah teks baru.
- Latar buram di belakang modal/panel dipotong oleh kode sebelum dibaca.
- Penjelasan QA diproses dengan penjaga kutipan yang sama seperti Catatan Konversi ke PRD.
Hal yang diragukan masuk catatan review (PDF) terpisah. Modul ini berdiri sendiri: tidak mengubah alur lain.
"""
__version__ = "1.0"

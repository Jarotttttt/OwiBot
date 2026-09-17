# Kontribusi ke OwiBot

Terima kasih atas minat Anda untuk berkontribusi ke OwiBot.

## Alur kerja dasar

1. Fork repositori.
2. Buat branch baru untuk perubahan Anda.
3. Lakukan perubahan yang relevan.
4. Jalankan test lokal.
5. Buat pull request dengan deskripsi yang jelas.

## Persyaratan pengembangan

Pastikan Anda memiliki:

- Python 3.9+
- `pip` dan virtual environment
- Dependensi dev yang tersedia via:

```bash
pip install -e .[dev]
```

## Menjalankan test

```bash
pytest
```

## Pedoman coding

- Gunakan gaya Python yang jelas dan konsisten.
- Tambahkan test untuk perubahan yang besar atau bug fix.
- Hindari perubahan yang tidak relevan dengan scope PR.
- Dokumentasikan perubahan penting di README atau CHANGELOG bila perlu.

## Struktur PR

Berikan PR dengan deskripsi seperti:

- Tujuan perubahan
- Masalah yang ditangani
- Langkah verifikasi
- Dampak yang diharapkan

## Masalah dan saran

Buka issue baru jika ada bug, request fitur, atau saran penggunaan.

Pastikan laporan Anda berisi:

- Deskripsi masalah
- Langkah reproduksi
- Hasil yang diharapkan
- Lingkungan yang digunakan

## Lisensi

Dengan berkontribusi, Anda setuju bahwa perubahan Anda akan dilisensikan di bawah lisensi MIT.

## Catatan

Untuk proyek dengan bot Telegram dan integrasi LLM, penting untuk selalu memvalidasi konfigurasi `api_base`, `api_key`, dan `allow_from` sebelum membagikan patch ke lingkungan produksi.

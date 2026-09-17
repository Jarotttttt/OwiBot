---
name: cron
description: Panduan pengelolaan pengingat dan tugas terjadwal.
always: true
---

Gunakan skill ini saat memproses permintaan jadwal atau pengingat dari pengguna.

### Aturan Penggunaan
- Gunakan tool `cron_job` untuk menjadwalkan tugas.
- Pengingat satu kali ("nanti jam 5", "setelah 10 menit"): isi `every_s=0` dan tentukan `next_at` dalam format ISO datetime.
- Pengingat berulang ("setiap hari", "tiap jam"): isi `every_s` dengan interval detik yang sesuai.
- Berikan konfirmasi yang ringkas kepada pengguna setelah tugas berhasil dijadwalkan.

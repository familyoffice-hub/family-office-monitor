# Family Office Intelligence Monitoring System

Sistem otomatis yang memantau berita keuangan, regulasi, pasar, dan crypto 24/7,
lalu mengirim **alert terstruktur ke Telegram** untuk kebutuhan Family Office Anda.

Panduan ini ditulis untuk **founder yang tidak bisa coding**. Ikuti dari atas ke bawah.
Setiap perintah terminal tinggal di-copy-paste.

---

## DAFTAR ISI
1. Cara kerja sistem (gambaran sederhana)
2. Daftar tools + link daftar
3. Pilih cara hosting: GitHub Actions (gratis) vs Railway
4. Setup dari nol (Python, VS Code, GitHub, Telegram)
5. Test di laptop dulu
6. Deploy 24/7 — Cara A: GitHub Actions (disarankan, gratis)
7. Deploy 24/7 — Cara B: Railway
8. Checklist verifikasi
9. Daftar keyword & rumus skor
10. MVP vs Advanced
11. Rencana kerja 7 hari
12. Mengatasi error umum
13. Perawatan & langkah mulai hari ini

---

## 1. CARA KERJA SISTEM

Alurnya seperti ini:

```
Sumber data            Otak program            Pengiriman
-----------            ------------            ----------
RSS berita keuangan  →                       
Google News          →   1. baca semua       
The Fed / SEC RSS    →   2. saring keyword   →  Tulis alert  →  TELEGRAM
OJK/BI/DJP (GNews)   →   3. beri skor           rapi              (bot + grup)
Stooq (saham/emas)   →   4. cek duplikat     
CoinGecko (crypto)   →   5. cek ambang pasar 
```

Program berjalan **sekali tiap 1 jam**. Setiap jalan:
- mengambil berita & data pasar terbaru,
- membuang yang tidak relevan (skor 0),
- mengirim hanya yang penting,
- mengingat apa yang sudah dikirim (file `seen.json`) supaya **tidak mengirim berita yang sama dua kali**.

---

## 2. DAFTAR TOOLS + LINK

| Tool | Untuk apa | Link | Bayar? |
|---|---|---|---|
| **Python** | bahasa program yang dipakai | https://www.python.org/downloads/ | Gratis |
| **VS Code** | aplikasi untuk membuka & mengedit file | https://code.visualstudio.com/ | Gratis |
| **Akun GitHub** | menyimpan kode + menjalankan otomatis | https://github.com/signup | Gratis |
| **Telegram** | tempat menerima alert | https://telegram.org/ | Gratis |
| **BotFather** | membuat bot Telegram | buka Telegram, cari `@BotFather` | Gratis |
| **Stooq** | data saham/FX/emas/minyak (tanpa API key) | https://stooq.com | Gratis |
| **CoinGecko** | data crypto (tanpa API key utk MVP) | https://www.coingecko.com/en/api | Gratis |
| **Railway** (opsional) | alternatif hosting | https://railway.com | Trial $5, lalu berbayar |

> **Catatan penting soal biaya:** versi MVP ini **tidak butuh API key berbayar sama sekali**.
> Yang wajib hanya **token bot Telegram** (gratis). Stooq & CoinGecko dipakai tanpa key.

---

## 3. PILIH CARA HOSTING

Ada dua cara menjalankan sistem 24/7. Pilih salah satu.

| | **GitHub Actions** (Cara A) | **Railway** (Cara B) |
|---|---|---|
| Biaya | **Gratis selamanya** | Trial $5 (~9 hari), lalu ±$5/bln |
| Kartu kredit | Tidak perlu | Perlu (sejak 2023) |
| Cocok untuk | cek **per jam** (pas untuk kebutuhan Anda) | program yang nyala terus |
| Kesulitan | Mudah | Mudah |

**Rekomendasi: pakai Cara A (GitHub Actions).** Kebutuhan Anda hanya "cek tiap 1 jam",
dan itu persis yang dilakukan jadwal (cron) GitHub Actions — gratis, tanpa kartu kredit.
Railway saya sertakan sebagai alternatif kalau nanti Anda butuh sistem yang menyala non-stop.

---

## 4. SETUP DARI NOL

### 4.1 Install Python
1. Buka https://www.python.org/downloads/ → klik tombol **Download Python** (versi 3.11 atau lebih baru).
2. Jalankan file yang terunduh.
3. **PENTING (Windows):** centang kotak **"Add Python to PATH"** sebelum klik Install.
4. Klik **Install Now**, tunggu selesai.

**Cek berhasil:** buka Terminal (Mac) / Command Prompt (Windows), ketik:
```
python --version
```
Kalau muncul `Python 3.11.x` (atau lebih), berhasil.
> Di Mac kadang perintahnya `python3 --version`.

### 4.2 Install VS Code
1. Buka https://code.visualstudio.com/ → **Download**.
2. Install seperti biasa.
3. Buka VS Code → menu **Extensions** (ikon kotak di kiri) → cari **"Python"** (dari Microsoft) → Install.

### 4.3 Buat akun GitHub
1. Buka https://github.com/signup
2. Isi email, password, username. Verifikasi email.
3. Selesai — gratis.

### 4.4 Buat Bot Telegram (lewat BotFather)
1. Buka aplikasi Telegram. Di kolom pencarian ketik **`@BotFather`** → buka chat resminya (ada centang biru).
2. Ketik: `/newbot` lalu kirim.
3. BotFather minta **nama bot** (bebas), contoh: `Family Office Alert`.
4. Lalu minta **username bot**, harus diakhiri `bot`, contoh: `familyoffice_alert_bot`.
5. BotFather membalas dengan **token**, bentuknya seperti:
   ```
   123456789:AAExampleabcdefGHIjklMNOpqrSTUvwxyz
   ```
   **Simpan token ini baik-baik.** Inilah `TELEGRAM_TOKEN` Anda.

### 4.5 Dapatkan Chat ID (tujuan alert)
**Untuk chat pribadi Anda:**
1. Buka bot yang baru dibuat (klik link dari BotFather), tekan **Start**, kirim pesan apa saja, misalnya `halo`.
2. Buka browser, kunjungi link ini (ganti `<TOKEN>` dengan token Anda):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Cari bagian `"chat":{"id":12345678,...}`. Angka `12345678` itulah **Chat ID** pribadi Anda.

**Untuk grup internal Family Office:**
1. Buat grup di Telegram, **tambahkan bot Anda** sebagai anggota.
2. Kirim 1 pesan di grup (misalnya `/start@familyoffice_alert_bot`).
3. Buka lagi link `getUpdates` di atas → cari `"chat":{"id":-1001234567890,...}`.
   ID grup biasanya **diawali tanda minus** seperti `-1001234567890`.

Anda bisa mengirim ke beberapa tujuan sekaligus dengan memisahkan koma:
`12345678,-1001234567890`

### 4.6 Siapkan folder project
1. Letakkan folder **family-office-monitor** (yang berisi semua file dari paket ini) di tempat mudah, misalnya Desktop.
2. Buka VS Code → menu **File ▸ Open Folder** → pilih folder `family-office-monitor`.
3. Di VS Code, buka Terminal lewat menu **Terminal ▸ New Terminal**. Terminal akan otomatis berada di dalam folder project.

### 4.7 Buat file `.env` (berisi rahasia Anda)
1. Di VS Code, lihat panel kiri. Ada file `.env.example`.
2. Klik kanan `.env.example` → **Copy**, lalu **Paste**, ganti namanya menjadi **`.env`** (titik di depan, tanpa `.example`).
3. Buka file `.env`, isi nilainya:
   ```
   TELEGRAM_TOKEN=123456789:AAExampleabcdefGHIjklMNOpqrSTUvwxyz
   TELEGRAM_CHAT_IDS=12345678
   RUN_MODE=loop
   CHECK_INTERVAL_MINUTES=60
   MIN_SCORE_TO_ALERT=4
   DAILY_SUMMARY_HOUR=7
   ```
   > Saat tes di laptop pakai `RUN_MODE=loop`. (File `.env` ini **tidak akan** ter-upload ke GitHub karena sudah diblok oleh `.gitignore`.)

---

## 5. TEST DI LAPTOP DULU

Di Terminal VS Code (pastikan berada di folder project), jalankan:

**1) Install dependency** (sekali saja):
```
pip install -r requirements.txt
```
> Mac: kalau gagal, coba `pip3 install -r requirements.txt`.

**2) Jalankan program:**
```
python main.py
```
> Mac: `python3 main.py`.

**Yang seharusnya terjadi:**
- Terminal menampilkan `Mulai siklus: ...`
- Beberapa detik kemudian, **Telegram Anda menerima alert** (kalau ada berita yang lewat saringan).
- Karena `RUN_MODE=loop`, program akan menunggu 60 menit lalu cek lagi. Untuk **menghentikan**, tekan `Ctrl + C`.

**Cara cek cepat tanpa menunggu berita asli:** untuk memastikan jalur Telegram benar,
ubah sementara `MIN_SCORE_TO_ALERT=2` di `.env` agar lebih banyak berita lolos, jalankan lagi.
Setelah yakin, kembalikan ke `4`.

**Kalau Telegram tidak menerima apa-apa**, lihat bagian **12. Mengatasi error umum**.

---

## 6. DEPLOY 24/7 — CARA A: GITHUB ACTIONS (gratis, disarankan)

Ide dasarnya: kode disimpan di GitHub, lalu GitHub menjalankan `main.py` **otomatis tiap jam**.
Rahasia (token Telegram) disimpan di tempat aman bernama **Secrets**, bukan di dalam kode.

### 6.1 Upload project ke GitHub (lewat website, tanpa perintah git)
1. Login ke https://github.com → klik tombol **+** kanan atas → **New repository**.
2. Beri nama, misalnya `family-office-monitor`. Pilih **Private**. Klik **Create repository**.
3. Di halaman repo baru, klik **uploading an existing file**.
4. **Seret seluruh isi folder** `family-office-monitor` (termasuk folder `.github`) ke area upload.
   - Pastikan file `.env` **TIDAK** ikut (memang tidak boleh; rahasia disimpan di Secrets).
5. Klik **Commit changes**.

> Jika folder `.github` tidak ikut ter-upload lewat drag-and-drop (kadang browser menyembunyikan folder berawalan titik), buat manual:
> klik **Add file ▸ Create new file**, ketik nama: `.github/workflows/monitor.yml`,
> lalu salin-tempel isi file `monitor.yml` dari paket ini, klik **Commit**.

### 6.2 Masukkan rahasia ke Secrets
1. Di repo GitHub, buka **Settings ▸ Secrets and variables ▸ Actions**.
2. Klik **New repository secret**:
   - Name: `TELEGRAM_TOKEN` → Value: token bot Anda → **Add secret**.
3. Klik **New repository secret** lagi:
   - Name: `TELEGRAM_CHAT_IDS` → Value: chat id Anda (mis. `12345678,-1001234567890`) → **Add secret**.

### 6.3 Nyalakan & uji
1. Buka tab **Actions** di repo Anda. Jika diminta, klik **I understand my workflows, enable them**.
2. Pilih workflow **Family Office Monitor** → klik **Run workflow** (uji manual sekarang).
3. Tunggu ±1 menit. Klik baris run yang muncul untuk melihat **log**. Kalau hijau ✓ dan Telegram menerima pesan, berhasil.
4. Setelah ini, sistem akan **jalan sendiri tiap jam**. Tidak perlu laptop menyala.

> Catatan: jadwal GitHub (cron) kadang molor beberapa menit saat server sibuk — itu normal untuk kebutuhan per-jam.

---

## 7. DEPLOY 24/7 — CARA B: RAILWAY (alternatif)

Pakai ini jika Anda ingin program yang **menyala terus** (bukan per jam). Ingat: gratis hanya saat trial.

1. Pastikan project sudah di GitHub (langkah 6.1).
2. Daftar di https://railway.com → **Login with GitHub** (perlu kartu kredit untuk trial).
3. **New Project ▸ Deploy from GitHub repo** → pilih repo `family-office-monitor`.
4. Railway otomatis mendeteksi Python dan menjalankan `python main.py` (sesuai `Procfile`/`railway.json`).
5. Buka tab **Variables**, tambahkan:
   - `TELEGRAM_TOKEN` = token Anda
   - `TELEGRAM_CHAT_IDS` = chat id Anda
   - `RUN_MODE` = `loop`
   - `CHECK_INTERVAL_MINUTES` = `60`
   - `MIN_SCORE_TO_ALERT` = `4`
   - `DAILY_SUMMARY_HOUR` = `7`
6. **Logs:** tab **Deployments ▸ View Logs** untuk melihat aktivitas.
7. **Restart:** menu titik-tiga pada service ▸ **Restart**.

> Di Railway mode `loop`, program tidur 60 menit di antara cek — ini lebih hemat kredit daripada cek terus-menerus.

---

## 8. CHECKLIST VERIFIKASI

Centang satu per satu:

- [ ] `python --version` menunjukkan 3.11+
- [ ] Bot Telegram dibuat, token tersimpan
- [ ] Chat ID didapat (pribadi dan/atau grup)
- [ ] `pip install -r requirements.txt` sukses
- [ ] `python main.py` jalan tanpa error fatal
- [ ] **Telegram menerima alert** saat tes lokal
- [ ] Project ter-upload ke GitHub (tanpa file `.env`)
- [ ] Secrets `TELEGRAM_TOKEN` & `TELEGRAM_CHAT_IDS` terisi
- [ ] Tab Actions: run manual berstatus hijau ✓
- [ ] Alert **tidak duplikat** (jalankan 2x, berita sama tidak terkirim ulang)
- [ ] Data berita masuk, data pasar/crypto masuk saat ada pergerakan besar
- [ ] Setelah 1 jam, run terjadwal otomatis muncul di tab Actions

---

## 9. DAFTAR KEYWORD & RUMUS SKOR

### Keyword (per kategori, ada di `main.py` bagian 3 — boleh Anda tambah)
- **Family Office:** family office, multi-family office, private wealth, UHNWI, HNWI
- **Wealth Management:** wealth management, asset allocation, portfolio, rebalancing
- **Private Banking:** private banking, private bank
- **Tax Planning:** tax, pajak, dividen, PPh, PPN, beneficial ownership, transfer pricing, tax treaty
- **Estate & Trust:** estate planning, trust, inheritance, warisan
- **Succession:** succession planning, wealth transfer, generational wealth, next generation
- **Family Governance:** family governance, family constitution, family business
- **Alternative Investment:** private equity, venture capital, private credit, hedge fund
- **Real Estate:** real estate, property, REIT
- **Gold & Commodities:** gold, emas, commodities, oil, minyak, treasury
- **Bond & Yield:** bond, yield, SBN, obligasi, US Treasury
- **Crypto & Digital:** crypto, bitcoin, ethereum, stablecoin, digital asset, tokenized, RWA, DeFi
- **Indonesia Regulator:** OJK, Bank Indonesia, DJP, Kemenkeu, PPATK, IHSG, IDX, BEI
- **Global Regulator:** SEC, MAS, SFC, FCA, FINMA, OECD, FATCA, CRS, IRS
- **Macro:** Federal Reserve, the Fed, interest rate, suku bunga, inflation, recession, rate cut/hike
- **Big Institution:** BlackRock, Vanguard, JP Morgan, Goldman Sachs, Morgan Stanley, UBS, Julius Baer, Fidelity, Franklin Templeton, Citi Private Bank
- **Security Risk:** fraud, scam, ponzi, hack, bank failure, custodian, depeg, sanction, AML, cyberattack, phishing, deepfake, tax investigation

### Rumus skor (otomatis di `main.py`)
- Setiap kategori yang cocok menambah bobotnya:
  - Security Risk **+5**, Indonesia Regulator **+4**, Family Office/Estate/Succession **+3**,
    Global Regulator/Big Institution **+3**, Tax/Macro/Crypto/Wealth **+2**, lainnya **+1**
- Mengandung kata bahaya (hack, fraud, depeg, sanction, bank failure, dll) → **+4 dan prioritas tinggi**
- Sumber tepercaya (The Fed, SEC, OJK, BI, DJP) → **+ bobot sumber (sampai +4)**
- Berita < 6 jam → **+2**; < 24 jam → **+1**
- **Prioritas:** High jika skor ≥ 9 atau ada kata bahaya; Medium jika ≥ 6; selain itu Low
- Hanya dikirim jika skor ≥ `MIN_SCORE_TO_ALERT` (default 4)

**Ingin lebih sedikit / lebih banyak alert?** Ubah `MIN_SCORE_TO_ALERT` di Secrets/Variables/.env.
Naikkan (mis. 6) agar lebih selektif; turunkan (mis. 3) agar lebih banyak.

---

## 10. MVP vs ADVANCED

**MVP (yang Anda dapatkan sekarang):**
- Monitoring RSS + Google News + regulator
- Filter keyword + skoring prioritas
- Anti-duplikat (`seen.json`)
- Data pasar (Stooq) + crypto (CoinGecko)
- Alert Telegram terformat
- Ringkasan harian sederhana
- Deploy gratis 24/7 (GitHub Actions)

**Advanced (pengembangan berikutnya):**
- Ringkasan & terjemahan otomatis tiap berita memakai AI (Claude API)
- Sentiment scoring & pengelompokan berita mirip (clustering)
- Deteksi duplikat lebih pintar (kemiripan judul)
- Simpan ke database (PostgreSQL) + dashboard admin
- Pipeline ke Notion/Airtable
- Auto-generate memo investment committee, family briefing, client advisory
- Auto-generate draft LinkedIn / Instagram carousel / newsletter
- Klasifikasi audiens (investor, founder, CFO, trustee, dst.)

> Saran: kuasai MVP dulu 1–2 minggu, baru tambah fitur Advanced satu per satu.

---

## 11. RENCANA KERJA 7 HARI

| Hari | Target |
|---|---|
| **Day 1** | Install Python + VS Code, daftar GitHub. Cek `python --version`. |
| **Day 2** | Buat bot Telegram (BotFather), dapatkan token & chat ID. |
| **Day 3** | Buka project di VS Code, buat `.env`, `pip install`, lihat berita RSS masuk. |
| **Day 4** | Pahami & sesuaikan keyword + `MIN_SCORE_TO_ALERT`. Tes alert ke Telegram. |
| **Day 5** | Pastikan data pasar (Stooq) & crypto (CoinGecko) muncul saat pergerakan besar. |
| **Day 6** | Upload ke GitHub, isi Secrets, nyalakan GitHub Actions (atau deploy Railway). |
| **Day 7** | Jalankan checklist verifikasi, rapikan grup Telegram, atur jam ringkasan harian. |

---

## 12. MENGATASI ERROR UMUM

| Gejala | Penyebab & solusi |
|---|---|
| `python: command not found` | Python belum ter-install / belum di PATH. Mac: pakai `python3`. Windows: install ulang & centang "Add to PATH". |
| `pip: command not found` | Pakai `pip3`, atau `python -m pip install -r requirements.txt`. |
| Telegram tidak menerima apa pun | 1) Cek `TELEGRAM_TOKEN` benar. 2) Cek chat ID benar (untuk grup pakai minus). 3) Pastikan Anda sudah **Start** bot / bot ada di grup. 4) Coba turunkan `MIN_SCORE_TO_ALERT` ke 2 untuk tes. |
| Telegram error `403 Forbidden` | Anda belum menekan **Start** pada bot, atau bot di-kick dari grup. |
| Telegram error `400 chat not found` | Chat ID salah. Ambil ulang lewat link `getUpdates`. |
| Banyak `Gagal baca feed ...` | Sebagian sumber kadang down — normal, program tetap lanjut. Kalau semua gagal, cek koneksi internet. |
| `CoinGecko error 403/429` | Terlalu sering memanggil. Wajar pada free tier; alert crypto akan terlewat sesekali, tidak menggugurkan yang lain. |
| Di Railway program berhenti setelah beberapa hari | Kredit trial habis. Itu sebabnya **GitHub Actions** lebih cocok untuk gratis. |
| Alert muncul berulang | `seen.json` tidak tersimpan. Di GitHub Actions sudah otomatis di-commit; pastikan langkah "Simpan riwayat" pada workflow berstatus hijau. |

---

## 13. PERAWATAN & MULAI HARI INI

**Perawatan rutin (5 menit/minggu):**
- Sesekali buka tab **Actions** (GitHub) → pastikan run terbaru hijau.
- Tambah/kurangi keyword di `main.py` sesuai fokus keluarga.
- Sesuaikan `MIN_SCORE_TO_ALERT` jika alert terlalu ramai atau terlalu sepi.

**Mulai hari ini — 3 langkah saja:**
1. **Install Python & VS Code** (bagian 4.1–4.2) — 15 menit.
2. **Buat bot Telegram & dapatkan token + chat ID** (bagian 4.4–4.5) — 10 menit.
3. **Buat `.env`, lalu `pip install -r requirements.txt` dan `python main.py`** (bagian 4.7 & 5),
   pastikan **alert pertama masuk ke Telegram**.

Setelah alert pertama berhasil, lanjut ke **GitHub Actions** (bagian 6) agar berjalan 24/7 gratis.

Selamat membangun Family Office Intelligence Anda. 🚀

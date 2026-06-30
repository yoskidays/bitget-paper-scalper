# Bitget Paper Scalper

Aplikasi desktop Windows untuk **paper trading internal** menggunakan data publik Bitget USDT Futures. Tidak ada API key, tidak ada koneksi akun, dan tidak ada order real.

## Fitur

- Modal virtual default 50 USDT.
- Screening otomatis setiap 5 menit selama aplikasi berjalan.
- Bot mulai otomatis saat aplikasi dibuka; opsi ini dapat dimatikan di Pengaturan.
- Universe crypto USDT perpetual yang dapat diedit.
- Strategi Multi-Timeframe Liquidity Pullback Scalper:
  - 1H: arah tren EMA50/EMA200.
  - 15M: konteks pullback EMA20/EMA50.
  - 5M: candle, break struktur, EMA9/EMA20, RSI, volume.
  - Filter spread, volume 24 jam, funding rate, dan perubahan open interest antarscan.
- Satu posisi virtual pada satu waktu.
- Sizing berdasarkan risiko dan jarak stop, bukan nominal tetap.
- TP1 parsial, pindah stop ke breakeven, TP2, time stop, dan batas loss harian.
- Fallback paper trade opsional setelah beberapa scan kosong, dengan risiko lebih kecil dan label terpisah.
- Ledger CSV, state persisten, log, dan laporan HTML.
- Build portable EXE serta installer Windows melalui GitHub Actions.

## Penting

Ini bukan bot profit terjamin. Hasil paper trading sangat dipengaruhi spread, fee, slippage, asumsi urutan intrabar, kualitas koneksi, dan rezim pasar. Pengujian singkat tidak bermakna secara statistik. Uji minimal ratusan transaksi sebelum menyimpulkan apa pun.

## Menjalankan dari source

PC/VPS harus tetap hidup dan aplikasi harus tetap berjalan agar scan 5-menitan terus dilakukan.

Saat memperbarui dari v1.0.0, konfigurasi lama dengan interval default 10 menit otomatis dimigrasikan menjadi 5 menit. Interval tetap dapat diubah melalui menu Pengaturan.


1. Install Python 3.12.
2. Clone/download repository.
3. Jalankan `run.bat` atau:

```bash
python -m pip install -r requirements.txt
python app.py
```

Data aplikasi disimpan di:

```text
%LOCALAPPDATA%\BitgetPaperScalper
```

Folder tersebut berisi `config.json`, `state.json`, `trades.csv`, `bot.log`, dan laporan HTML.

## Build EXE di GitHub

1. Buat repository GitHub baru.
2. Upload seluruh isi folder proyek ini ke root repository.
3. Buka tab **Actions**.
4. Pilih **Build Windows EXE and Installer**.
5. Klik **Run workflow**.
6. Setelah selesai, download artifact:
   - `BitgetPaperScalper-Portable`
   - `BitgetPaperScalper-Installer`

Workflow menjalankan unit test, membangun EXE dengan PyInstaller, lalu membuat installer menggunakan Inno Setup. Karena EXE belum ditandatangani dengan sertifikat code-signing, Windows SmartScreen dapat menampilkan peringatan pada instalasi pertama.

## Build lokal Windows

Install Python 3.12 dan Inno Setup 6, kemudian klik:

```text
build_windows.bat
```

Hasil:

```text
dist\BitgetPaperScalper.exe
dist-installer\BitgetPaperScalper-Setup.exe
```

## Strategi dan skor

Sinyal dinilai 0–100 dari:

- tren 1H;
- alignment/pullback 15M;
- trigger 5M;
- volume relatif;
- spread;
- funding;
- perubahan open interest dari scan sebelumnya.

Default entry normal membutuhkan skor minimal 68. Jika fallback diaktifkan, setelah enam scan kosong bot dapat memakai kandidat terbaik dengan skor minimal 52, risiko 0,25%, dan leverage maksimal 2x. Trade fallback ditandai di ledger agar performanya dapat dipisahkan dari strategi normal.

## Asumsi simulasi

- Entry memakai bid/ask publik ditambah estimasi slippage.
- Fee menggunakan `takerFeeRate` dari konfigurasi kontrak Bitget bila tersedia.
- Jika SL dan TP tersentuh dalam candle yang sama, engine mengasumsikan SL tersentuh lebih dahulu. Ini sengaja konservatif.
- Candle terbaru yang masih berjalan dibuang dari analisis.
- PnL dihitung secara linear untuk kontrak USDT perpetual.

## API publik yang digunakan

- `/api/v2/mix/market/tickers`
- `/api/v2/mix/market/contracts`
- `/api/v2/mix/market/candles`

Tidak ada endpoint private dan tidak ada tempat memasukkan API key.

## Mengubah universe coin

Buka `%LOCALAPPDATA%\BitgetPaperScalper\config.json`, lalu edit array `crypto_symbols`. Restart aplikasi setelah perubahan.

## Pengamanan

- `dry_run_only` selalu dipaksa `true` oleh aplikasi.
- Tidak ada kode untuk place order.
- Tidak ada field API key, secret, atau passphrase.
- Maksimal satu posisi virtual.
- Tidak ada martingale dan tidak ada averaging down.

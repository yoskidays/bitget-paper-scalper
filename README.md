# Bitget Paper Scalper v1.1.0

Aplikasi desktop Windows untuk **paper trading internal** menggunakan data publik Bitget USDT Futures. Tidak ada API key, tidak ada koneksi akun, dan tidak ada order real.

## Arsitektur v1.1.0

Versi ini memakai model **hybrid** agar lebih cepat tanpa menjadikan strategi terlalu berisik:

- **Screening seluruh kandidat setiap 1 menit** menggunakan REST API publik Bitget.
- **1H** menentukan arah tren utama.
- **15M** menentukan konteks pullback.
- **5M** memastikan alignment momentum.
- **1M yang sudah close** menjadi trigger entry.
- Setelah posisi virtual dibuka, **public WebSocket Bitget** memantau ticker terus-menerus.
- SL, TP1, breakeven, dan TP2 dievaluasi dari bid/ask live, tidak menunggu scan berikutnya.
- Jika WebSocket terputus, engine memakai candle 1M REST sebagai fallback dan mencoba reconnect otomatis.

Pendekatan ini lebih tepat daripada hanya menurunkan seluruh logika ke timeframe 1M. Entry tetap cepat, tetapi sinyal 1M wajib searah struktur 5M, 15M, dan 1H.

## Fitur

- Modal virtual default 50 USDT.
- Screening otomatis setiap 1 menit selama aplikasi berjalan.
- Monitor posisi melalui public WebSocket real-time tanpa API key.
- Heartbeat ping/pong dan reconnect otomatis.
- Bot mulai otomatis saat aplikasi dibuka; opsi dapat dimatikan di Pengaturan.
- Universe crypto USDT perpetual yang dapat diedit.
- Filter spread, volume 24 jam, funding rate, open interest, dan volatilitas.
- Satu posisi virtual pada satu waktu.
- Sizing berdasarkan risiko dan jarak stop.
- TP1 parsial, pindah stop ke breakeven, TP2, time stop, dan batas loss harian.
- Fallback paper trade opsional setelah beberapa scan kosong, dengan risiko lebih kecil.
- Ledger CSV, state persisten, log, dan laporan HTML.
- Build portable EXE serta installer Windows melalui GitHub Actions.

## Penting

Ini bukan bot profit terjamin. Screening lebih sering dapat meningkatkan jumlah entry sekaligus meningkatkan noise, fee simulasi, dan false signal. Hasil harus dinilai dari ratusan transaksi, bukan beberapa jam.

## Menjalankan dari source

PC/VPS harus tetap hidup dan aplikasi harus tetap terbuka.

```bash
python -m pip install -r requirements.txt
python app.py
```

Data aplikasi disimpan di:

```text
%LOCALAPPDATA%\BitgetPaperScalper
```

Folder tersebut berisi `config.json`, `state.json`, `trades.csv`, `bot.log`, dan laporan HTML.

## Upgrade dari v1.0.x

Konfigurasi lama tetap digunakan. Saat pertama kali menjalankan v1.1.0:

- interval default lama 5 atau 10 menit otomatis dimigrasikan menjadi 1 menit;
- WebSocket publik otomatis diaktifkan;
- saldo, posisi virtual, dan ledger lama tetap dipertahankan.

Jika ingin mulai bersih, tekan **Stop**, lalu **Reset Akun**.

## Build EXE di GitHub

1. Upload seluruh isi folder proyek ke root repository GitHub.
2. Pastikan file `.github/workflows/build-windows.yml` ada.
3. Buka **Actions**.
4. Pilih **Build Windows EXE and Installer**.
5. Klik **Run workflow**.
6. Download artifact:
   - `BitgetPaperScalper-Portable`
   - `BitgetPaperScalper-Installer`

## Strategi dan skor

Sinyal dinilai dari:

- tren EMA50/EMA200 1H;
- pullback dan alignment EMA 15M;
- alignment EMA dan momentum 5M;
- candle, break struktur, EMA, RSI, dan volume 1M;
- spread;
- funding;
- perubahan open interest antarscan.

Default entry normal membutuhkan skor minimal 68. Candle 1M terbaru yang masih berjalan dibuang; keputusan hanya memakai candle yang sudah close.

## Asumsi simulasi

- Entry memakai bid/ask publik ditambah estimasi slippage.
- Fee menggunakan `takerFeeRate` kontrak Bitget bila tersedia.
- Exit long memakai bid live; exit short memakai ask live.
- WebSocket hanya memantau posisi aktif agar koneksi ringan dan stabil.
- Jika SL dan TP sama-sama terlewati sebelum tick berhasil diproses, engine memprioritaskan stop sebagai asumsi konservatif.
- PnL dihitung linear untuk kontrak USDT perpetual.

## API publik

REST:

- `/api/v2/mix/market/tickers`
- `/api/v2/mix/market/contracts`
- `/api/v2/mix/market/candles`

WebSocket:

- `wss://ws.bitget.com/v2/ws/public`
- channel `ticker` untuk pair posisi aktif

Tidak ada endpoint private dan tidak ada field API key, secret, atau passphrase.

## Pengamanan

- `dry_run_only` selalu dipaksa `true`.
- Tidak ada kode untuk place order.
- Maksimal satu posisi virtual.
- Tidak ada martingale dan tidak ada averaging down.
- Batas loss harian tetap aktif.

## Perubahan v1.1.0

- Screening default 1 menit.
- Trigger entry memakai candle 1M yang sudah close.
- Konfirmasi tetap memakai 5M, 15M, dan 1H.
- Public WebSocket memantau posisi secara real-time.
- Reconnect otomatis dan heartbeat.
- SL/TP virtual tidak lagi menunggu siklus scan satu atau lima menit.
- REST candle 1M menjadi fallback jika WebSocket terputus.

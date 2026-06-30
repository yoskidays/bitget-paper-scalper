from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bot.config import config_path, data_dir, load_config, save_config
from bot.engine import PaperTradingEngine


class PaperScalperApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bitget Paper Scalper")
        self.geometry("1080x720")
        self.minsize(960, 620)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.events: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.ws_connected = False
        self.ws_symbol: str | None = None
        self.live_price: float | None = None
        self.engine = PaperTradingEngine(self.on_engine_event)
        self._build_style()
        self._build_ui()
        self.after(150, self.process_events)
        self.refresh_snapshot()
        if load_config().get("auto_start_bot", True):
            self.after(900, self.start_bot)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.configure(bg="#111827")
        style.configure("TFrame", background="#111827")
        style.configure("Card.TFrame", background="#1f2937")
        style.configure("TLabel", background="#111827", foreground="#e5e7eb", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#1f2937", foreground="#e5e7eb")
        style.configure("Title.TLabel", background="#111827", foreground="#f9fafb", font=("Segoe UI Semibold", 18))
        style.configure("Metric.TLabel", background="#1f2937", foreground="#f9fafb", font=("Segoe UI Semibold", 16))
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=8)
        style.configure("Treeview", background="#111827", foreground="#e5e7eb", fieldbackground="#111827", rowheight=27)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="Bitget Paper Scalper", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="PAPER TRADING • SCAN 1 MENIT • MONITOR WS REAL-TIME • TANPA ORDER REAL", foreground="#fbbf24").pack(side="left", padx=18)

        button_bar = ttk.Frame(header)
        button_bar.pack(side="right")
        self.start_button = ttk.Button(button_bar, text="Mulai Bot", command=self.start_bot)
        self.start_button.pack(side="left", padx=4)
        self.stop_button = ttk.Button(button_bar, text="Stop", command=self.stop_bot)
        self.stop_button.pack(side="left", padx=4)
        ttk.Button(button_bar, text="Scan Sekarang", command=self.engine.scan_now_async).pack(side="left", padx=4)

        metrics = ttk.Frame(self, padding=(18, 0, 18, 12))
        metrics.pack(fill="x")
        self.metric_vars: dict[str, tk.StringVar] = {}
        for key, title in [
            ("status", "Status"), ("balance", "Saldo Virtual"), ("position", "Posisi"),
            ("return", "Return"), ("winrate", "Win Rate"), ("drawdown", "Max Drawdown")
        ]:
            card = ttk.Frame(metrics, style="Card.TFrame", padding=12)
            card.pack(side="left", fill="x", expand=True, padx=4)
            ttk.Label(card, text=title, style="Card.TLabel").pack(anchor="w")
            var = tk.StringVar(value="-")
            self.metric_vars[key] = var
            ttk.Label(card, textvariable=var, style="Metric.TLabel").pack(anchor="w", pady=(4, 0))

        controls = ttk.Frame(self, padding=(18, 0, 18, 10))
        controls.pack(fill="x")
        ttk.Button(controls, text="Tutup Posisi Virtual", command=self.close_virtual_position).pack(side="left", padx=4)
        ttk.Button(controls, text="Laporan HTML", command=self.make_report).pack(side="left", padx=4)
        ttk.Button(controls, text="Export Ledger CSV", command=self.export_ledger).pack(side="left", padx=4)
        ttk.Button(controls, text="Buka Folder Data", command=self.open_data_folder).pack(side="left", padx=4)
        ttk.Button(controls, text="Pengaturan", command=self.open_settings).pack(side="left", padx=4)
        ttk.Button(controls, text="Reset Akun", command=self.reset_account).pack(side="right", padx=4)

        main = ttk.Panedwindow(self, orient="vertical")
        main.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        candidates_frame = ttk.Labelframe(main, text="Kandidat Sinyal Terakhir", padding=8)
        columns = ("symbol", "direction", "score", "price", "spread", "volume", "funding", "reason")
        self.tree = ttk.Treeview(candidates_frame, columns=columns, show="headings", height=10)
        headings = {
            "symbol": "Pair", "direction": "Arah", "score": "Skor", "price": "Harga",
            "spread": "Spread bps", "volume": "Vol 24h", "funding": "Funding", "reason": "Ringkasan"
        }
        widths = {"symbol": 90, "direction": 70, "score": 65, "price": 100, "spread": 85, "volume": 105, "funding": 85, "reason": 360}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True)
        main.add(candidates_frame, weight=3)

        log_frame = ttk.Labelframe(main, text="Log", padding=8)
        self.log_text = tk.Text(log_frame, height=10, bg="#0b1220", fg="#d1d5db", insertbackground="white", relief="flat", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        main.add(log_frame, weight=2)

    def on_engine_event(self, event: str, payload: dict) -> None:
        self.events.put((event, payload))

    def process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self.log(payload.get("text", ""))
                elif event == "error":
                    self.log("ERROR: " + payload.get("text", ""))
                elif event == "status":
                    self.metric_vars["status"].set(payload.get("text", "-"))
                elif event == "progress":
                    self.metric_vars["status"].set(f"Scan {payload.get('current')}/{payload.get('total')}")
                elif event == "candidates":
                    self.update_candidates(payload.get("items", []))
                elif event == "ws_status":
                    self.ws_connected = bool(payload.get("connected"))
                    self.ws_symbol = payload.get("symbol")
                    self.log(payload.get("text", "Status WebSocket berubah."))
                    self.refresh_snapshot()
                elif event == "live_tick":
                    self.live_price = payload.get("price")
                    self.ws_symbol = payload.get("symbol")
                elif event == "trade_open":
                    p = payload["position"]
                    self.log(f"OPEN PAPER {p['symbol']} {p['direction']} @ {p['entry_price']:.8g} | SL {p['stop_price']:.8g} | TP2 {p['tp2_price']:.8g}")
                elif event == "trade_update":
                    self.log(payload.get("text", ""))
                elif event == "trade_close":
                    t = payload["trade"]
                    self.log(f"CLOSE PAPER {t['symbol']} | {t['exit_reason']} | Net {t['net_pnl']} USDT")
                elif event == "state":
                    self.apply_snapshot(payload["state"])
        except queue.Empty:
            pass
        self.after(150, self.process_events)

    def start_bot(self) -> None:
        self.engine.start()
        self.log("Bot dimulai. Screening 1 menit aktif; posisi dipantau WebSocket real-time.")

    def stop_bot(self) -> None:
        self.engine.stop()
        self.log("Bot dihentikan. Posisi virtual yang terbuka tetap tersimpan.")

    def close_virtual_position(self) -> None:
        if not self.engine.state.open_position:
            messagebox.showinfo("Paper Scalper", "Tidak ada posisi virtual yang terbuka.")
            return
        if messagebox.askyesno("Konfirmasi", "Tutup posisi virtual memakai harga pasar publik terbaru?"):
            self.engine.close_position_async()

    def refresh_snapshot(self) -> None:
        self.apply_snapshot(self.engine.snapshot())

    def apply_snapshot(self, snapshot: dict) -> None:
        metrics = snapshot["metrics"]
        self.ws_connected = bool(snapshot.get("websocket_connected", self.ws_connected))
        self.ws_symbol = snapshot.get("websocket_symbol", self.ws_symbol)
        self.live_price = snapshot.get("live_price", self.live_price)
        position = snapshot.get("open_position")
        if snapshot["running"]:
            if position and self.ws_connected and self.ws_symbol:
                status = "BERJALAN • WS LIVE"
            elif position:
                status = "BERJALAN • REST FALLBACK"
            elif snapshot.get("websocket_enabled", True):
                status = "BERJALAN • WS SIAGA"
            else:
                status = "BERJALAN • REST 1M"
        else:
            status = "BERHENTI"
        self.metric_vars["status"].set(status)
        self.metric_vars["balance"].set(f"{snapshot['balance']:.4f} USDT")
        if position:
            live_suffix = f" @ {self.live_price:.8g}" if self.live_price and self.ws_symbol == position["symbol"] else ""
            self.metric_vars["position"].set(f"{position['symbol']} {position['direction']}{live_suffix}")
        else:
            self.metric_vars["position"].set("Tidak ada")
        self.metric_vars["return"].set(f"{metrics['return_pct']:+.3f}%")
        self.metric_vars["winrate"].set(f"{metrics['win_rate']:.1f}% ({metrics['trades']})")
        self.metric_vars["drawdown"].set(f"{metrics['max_drawdown_pct']:.3f}%")

    def update_candidates(self, items: list[dict]) -> None:
        for child in self.tree.get_children():
            self.tree.delete(child)
        for item in items:
            self.tree.insert("", "end", values=(
                item["symbol"], item["direction"], f"{item['score']:.1f}", f"{item['price']:.8g}",
                f"{item['spread_bps']:.2f}", f"{item['volume']/1_000_000:.1f}M",
                f"{item['funding']*100:.4f}%", item["reasons"]
            ))

    def log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def make_report(self) -> None:
        try:
            path = self.engine.make_report()
            webbrowser.open(path.as_uri())
            self.log(f"Laporan dibuat: {path}")
        except Exception as exc:
            messagebox.showerror("Laporan gagal", str(exc))

    def export_ledger(self) -> None:
        target = filedialog.asksaveasfilename(
            title="Simpan ledger",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"bitget-paper-ledger-{datetime.now().strftime('%Y%m%d')}.csv",
        )
        if target:
            self.engine.storage.export_ledger(Path(target))
            self.log(f"Ledger diekspor: {target}")

    def open_data_folder(self) -> None:
        path = data_dir()
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def open_settings(self) -> None:
        cfg = load_config()
        window = tk.Toplevel(self)
        window.title("Pengaturan")
        window.geometry("460x540")
        window.configure(bg="#111827")
        fields = [
            ("scan_interval_minutes", "Interval screening (menit)"),
            ("starting_equity", "Modal awal virtual"),
            ("risk_per_trade_pct", "Risiko per trade (%)"),
            ("max_leverage", "Maks leverage virtual"),
            ("max_pairs_to_analyze", "Jumlah pair dianalisis"),
            ("min_usdt_volume_24h", "Minimum volume 24h USDT"),
            ("max_spread_bps", "Maks spread (bps)"),
            ("min_signal_score", "Skor minimum normal"),
            ("fallback_after_empty_scans", "Fallback setelah scan kosong"),
            ("fallback_min_score", "Skor minimum fallback"),
            ("daily_loss_limit_pct", "Batas loss harian (%)"),
        ]
        entries: dict[str, ttk.Entry] = {}
        form = ttk.Frame(window, padding=16)
        form.pack(fill="both", expand=True)
        for row, (key, label) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=6)
            entry = ttk.Entry(form, width=18)
            entry.insert(0, str(cfg[key]))
            entry.grid(row=row, column=1, sticky="e", pady=6)
            entries[key] = entry

        fallback_var = tk.BooleanVar(value=bool(cfg["fallback_enabled"]))
        auto_start_var = tk.BooleanVar(value=bool(cfg.get("auto_start_bot", True)))
        websocket_var = tk.BooleanVar(value=bool(cfg.get("websocket_enabled", True)))
        ttk.Checkbutton(form, text="Aktifkan fallback paper trade", variable=fallback_var).grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(form, text="Aktifkan monitor harga WebSocket real-time", variable=websocket_var).grid(row=len(fields)+1, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(form, text="Mulai bot otomatis saat aplikasi dibuka", variable=auto_start_var).grid(row=len(fields)+2, column=0, columnspan=2, sticky="w", pady=6)

        def save() -> None:
            try:
                updated = dict(cfg)
                for key, _label in fields:
                    old = cfg[key]
                    value = entries[key].get().strip()
                    updated[key] = int(value) if isinstance(old, int) and not isinstance(old, bool) else float(value)
                updated["fallback_enabled"] = fallback_var.get()
                updated["websocket_enabled"] = websocket_var.get()
                updated["auto_start_bot"] = auto_start_var.get()
                save_config(updated)
                messagebox.showinfo("Pengaturan", "Tersimpan. Restart aplikasi agar seluruh perubahan diterapkan.")
                window.destroy()
            except ValueError:
                messagebox.showerror("Input salah", "Gunakan angka yang valid.")

        ttk.Button(form, text="Simpan", command=save).grid(row=len(fields)+3, column=0, columnspan=2, pady=16)

    def reset_account(self) -> None:
        if self.engine.is_running:
            messagebox.showwarning("Reset", "Stop bot dahulu sebelum reset.")
            return
        if messagebox.askyesno("Reset akun", "Reset saldo dan ledger? Backup otomatis akan dibuat."):
            self.engine.state = self.engine.storage.reset(self.engine.config["starting_equity"])
            self.refresh_snapshot()
            self.update_candidates([])
            self.log("Akun virtual direset. Backup tersimpan di folder data.")

    def on_close(self) -> None:
        self.engine.stop()
        self.destroy()


if __name__ == "__main__":
    app = PaperScalperApp()
    app.mainloop()

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from statistics import mean

from .config import data_dir


def calculate_metrics(trades: list[dict[str, str]], starting_equity: float, current_balance: float, max_drawdown_pct: float) -> dict[str, float | int | str]:
    def f(row: dict[str, str], key: str) -> float:
        try:
            return float(row.get(key, 0) or 0)
        except ValueError:
            return 0.0

    wins = [row for row in trades if f(row, "net_pnl") > 0]
    losses = [row for row in trades if f(row, "net_pnl") < 0]
    gross = sum(f(row, "gross_pnl") for row in trades)
    fees = sum(f(row, "fees") for row in trades)
    slippage = sum(f(row, "slippage_estimate") for row in trades)
    net = current_balance - starting_equity
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    average_win = mean(f(row, "net_pnl") for row in wins) if wins else 0.0
    average_loss = abs(mean(f(row, "net_pnl") for row in losses)) if losses else 0.0
    payoff = average_win / average_loss if average_loss > 0 else 0.0
    return {
        "starting_equity": starting_equity,
        "ending_equity": current_balance,
        "gross_pnl": gross,
        "fees": fees,
        "slippage": slippage,
        "net_pnl": net,
        "return_pct": net / starting_equity * 100.0 if starting_equity else 0.0,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "average_win": average_win,
        "average_loss": average_loss,
        "payoff_ratio": payoff,
        "max_drawdown_pct": max_drawdown_pct,
    }


def build_html_report(trades: list[dict[str, str]], metrics: dict, open_position: str = "Tidak ada") -> Path:
    report_dir = data_dir() / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"

    rows = []
    for trade in reversed(trades):
        rows.append("<tr>" + "".join(
            f"<td>{html.escape(str(trade.get(key, '')))}</td>"
            for key in ("closed_at", "symbol", "direction", "setup_type", "net_pnl", "exit_reason", "balance_after")
        ) + "</tr>")

    content = f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><title>Laporan Bitget Paper Scalper</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:28px;background:#111827;color:#e5e7eb}}
.card{{background:#1f2937;padding:18px;border-radius:12px;margin-bottom:16px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #374151;text-align:left}}
small{{color:#9ca3af}} .metric{{display:inline-block;min-width:190px;margin:6px 12px 6px 0}}
</style></head><body>
<h1>Bitget Paper Scalper — Laporan Simulasi</h1>
<p><strong>Paper trading saja.</strong> Tidak ada order real dan tidak ada API key.</p>
<div class="card">
<div class="metric">Modal awal: <strong>{metrics['starting_equity']:.4f} USDT</strong></div>
<div class="metric">Saldo akhir: <strong>{metrics['ending_equity']:.4f} USDT</strong></div>
<div class="metric">Net PnL: <strong>{metrics['net_pnl']:.4f} USDT</strong></div>
<div class="metric">Return: <strong>{metrics['return_pct']:.3f}%</strong></div>
<div class="metric">Trade: <strong>{metrics['trades']}</strong></div>
<div class="metric">Win rate: <strong>{metrics['win_rate']:.2f}%</strong></div>
<div class="metric">Max DD: <strong>{metrics['max_drawdown_pct']:.3f}%</strong></div>
<div class="metric">Fee: <strong>{metrics['fees']:.4f} USDT</strong></div>
<div class="metric">Slippage est.: <strong>{metrics['slippage']:.4f} USDT</strong></div>
<p>Posisi terbuka: {html.escape(open_position)}</p>
</div>
<div class="card"><h2>Ledger</h2><table><thead><tr><th>Waktu close</th><th>Pair</th><th>Arah</th><th>Setup</th><th>Net PnL</th><th>Alasan keluar</th><th>Saldo</th></tr></thead>
<tbody>{''.join(rows) if rows else '<tr><td colspan="7">Belum ada trade selesai.</td></tr>'}</tbody></table></div>
<small>Hasil sangat pendek tidak cukup untuk membuktikan strategi. Uji ratusan trade dan beberapa rezim pasar.</small>
</body></html>"""
    path.write_text(content, encoding="utf-8")
    return path

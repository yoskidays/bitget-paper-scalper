from __future__ import annotations

import csv
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .config import data_dir
from .models import AccountState


class Storage:
    TRADE_FIELDS = [
        "trade_id", "symbol", "direction", "setup_type", "opened_at", "closed_at",
        "entry_price", "exit_price", "initial_qty", "leverage", "score", "gross_pnl",
        "fees", "slippage_estimate", "net_pnl", "return_on_starting_equity_pct",
        "exit_reason", "tp1_hit", "balance_after", "reasons"
    ]

    def __init__(self) -> None:
        self.root = data_dir()
        self.state_path = self.root / "state.json"
        self.ledger_path = self.root / "trades.csv"
        self.log_path = self.root / "bot.log"
        self._lock = RLock()
        self._ensure_ledger()
        self.logger = self._build_logger()

    def _build_logger(self) -> logging.Logger:
        logger = logging.getLogger("bitget-paper-scalper")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.FileHandler(self.log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            logger.addHandler(handler)
        return logger

    def _ensure_ledger(self) -> None:
        if not self.ledger_path.exists():
            with self.ledger_path.open("w", newline="", encoding="utf-8-sig") as handle:
                csv.DictWriter(handle, fieldnames=self.TRADE_FIELDS).writeheader()

    def load_state(self, starting_equity: float) -> AccountState:
        with self._lock:
            if self.state_path.exists():
                try:
                    payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                    return AccountState.from_dict(payload)
                except (OSError, ValueError, TypeError):
                    self.logger.exception("State file tidak dapat dibaca; akun dibuat ulang.")
            today = datetime.now(timezone.utc).date().isoformat()
            state = AccountState(
                starting_equity=starting_equity,
                balance=starting_equity,
                peak_equity=starting_equity,
                day_anchor=today,
                day_start_balance=starting_equity,
            )
            self.save_state(state)
            return state

    def save_state(self, state: AccountState) -> None:
        with self._lock:
            temp = self.state_path.with_suffix(".tmp")
            temp.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            temp.replace(self.state_path)

    def append_trade(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_ledger()
            with self.ledger_path.open("a", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=self.TRADE_FIELDS)
                writer.writerow({key: row.get(key, "") for key in self.TRADE_FIELDS})

    def read_trades(self) -> list[dict[str, str]]:
        with self._lock:
            self._ensure_ledger()
            with self.ledger_path.open("r", newline="", encoding="utf-8-sig") as handle:
                return list(csv.DictReader(handle))

    def export_ledger(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.ledger_path, destination)
        return destination

    def reset(self, starting_equity: float) -> AccountState:
        with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            if self.ledger_path.exists():
                shutil.copy2(self.ledger_path, self.root / f"trades-backup-{timestamp}.csv")
            if self.state_path.exists():
                shutil.copy2(self.state_path, self.root / f"state-backup-{timestamp}.json")
            self.ledger_path.unlink(missing_ok=True)
            self.state_path.unlink(missing_ok=True)
            self._ensure_ledger()
        return self.load_state(starting_equity)

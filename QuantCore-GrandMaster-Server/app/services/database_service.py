import os
import math
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import numpy as np

from app.core.config import settings
from app.core.memory_guard import memory_guard
from app.domain.interfaces import IService


class DatabaseService(IService):
    """
    Надлегкий SQLite WAL сервіс із фіксованим буфером кешу (4 МБ) та mmap_size=0.
    Забезпечує миттєві векторні вибірки для графіків без зайвих алокацій пам'яті.
    """

    __slots__ = ("_db_path",)

    def __init__(self, db_path: str = settings.DB_PATH) -> None:
        self._db_path = db_path

    @property
    def name(self) -> str:
        return "DatabaseService"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-4000;")  # Обмеження кешу SQLite до 4 МБ
        conn.execute("PRAGMA mmap_size=0;")
        return conn

    async def init(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol VARCHAR(24) DEFAULT 'BTCUSDT',
                    order_id VARCHAR(50),
                    side VARCHAR(10) NOT NULL,
                    amount_btc FLOAT NOT NULL,
                    price FLOAT NOT NULL,
                    realized_pnl FLOAT DEFAULT 0.0,
                    fee_usdt FLOAT DEFAULT 0.0,
                    note VARCHAR(120) DEFAULT ''
                );
            """)
            for sql in (
                "ALTER TABLE trades ADD COLUMN symbol VARCHAR(24) DEFAULT 'BTCUSDT';",
                "ALTER TABLE trades ADD COLUMN fee_usdt FLOAT DEFAULT 0.0;",
            ):
                try:
                    conn.execute(sql)
                except Exception:
                    pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    balance_usdt FLOAT NOT NULL,
                    position_btc FLOAT NOT NULL,
                    btc_price FLOAT NOT NULL,
                    total_equity FLOAT DEFAULT 0.0,
                    unrealized_pnl FLOAT DEFAULT 0.0,
                    model_action FLOAT DEFAULT 0.0,
                    gross_leverage FLOAT DEFAULT 0.0,
                    active_coins INTEGER DEFAULT 0
                );
            """)
            for sql in (
                "ALTER TABLE equity_snapshots ADD COLUMN total_equity FLOAT DEFAULT 0.0;",
                "ALTER TABLE equity_snapshots ADD COLUMN gross_leverage FLOAT DEFAULT 0.0;",
                "ALTER TABLE equity_snapshots ADD COLUMN active_coins INTEGER DEFAULT 0;",
            ):
                try:
                    conn.execute(sql)
                except Exception:
                    pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS coin_states (
                    symbol VARCHAR(24) PRIMARY KEY,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    mode INTEGER DEFAULT 1,
                    phase INTEGER DEFAULT 0,
                    position_qty FLOAT DEFAULT 0.0,
                    notional_usdt FLOAT DEFAULT 0.0,
                    entry_price FLOAT DEFAULT 0.0,
                    mark_price FLOAT DEFAULT 0.0,
                    sl_price FLOAT DEFAULT 0.0,
                    unrealized_pnl FLOAT DEFAULT 0.0,
                    alpha_score FLOAT DEFAULT 0.0,
                    mwu_weight FLOAT DEFAULT 1.0,
                    bars_held INTEGER DEFAULT 0
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts ON equity_snapshots(timestamp);")
            conn.commit()

    async def shutdown(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass

    def record_trade(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        order_id: Optional[str] = None,
        pnl: float = 0.0,
        fee: float = 0.0,
        note: str = "",
    ) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO trades (timestamp, symbol, order_id, side, amount_btc, price, realized_pnl, fee_usdt, note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (now_str, symbol.upper(), str(order_id or ""), side.upper(), float(amount), float(price), float(pnl), float(fee), note[:115]),
                )
                conn.commit()
        except Exception:
            pass

    def record_snapshot(
        self,
        balance_usdt: float,
        btc_pos_qty: float,
        btc_price: float,
        unrealized_pnl: float,
        master_action: float,
        gross_leverage: float = 0.0,
        active_coins: int = 0,
    ) -> None:
        if balance_usdt <= 0.0:
            return
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        total_eq = float(balance_usdt) + float(unrealized_pnl)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO equity_snapshots "
                    "(timestamp, balance_usdt, position_btc, btc_price, total_equity, unrealized_pnl, model_action, gross_leverage, active_coins) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (now_str, float(balance_usdt), float(btc_pos_qty), float(btc_price), total_eq, float(unrealized_pnl), float(master_action), float(gross_leverage), int(active_coins)),
                )
                conn.commit()
        except Exception:
            pass

    def upsert_coin_states(self, coins_radar: List[Dict[str, Any]]) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                for c in coins_radar:
                    conn.execute(
                        """
                        INSERT INTO coin_states
                        (symbol, updated_at, mode, phase, position_qty, notional_usdt, entry_price, mark_price, sl_price, unrealized_pnl, alpha_score, mwu_weight, bars_held)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol) DO UPDATE SET
                            updated_at=excluded.updated_at,
                            mode=excluded.mode,
                            phase=excluded.phase,
                            position_qty=excluded.position_qty,
                            notional_usdt=excluded.notional_usdt,
                            entry_price=excluded.entry_price,
                            mark_price=excluded.mark_price,
                            sl_price=excluded.sl_price,
                            unrealized_pnl=excluded.unrealized_pnl,
                            alpha_score=excluded.alpha_score,
                            mwu_weight=excluded.mwu_weight,
                            bars_held=excluded.bars_held
                        """,
                        (
                            c["symbol"], now_str, int(c["mode"]), int(c["phase"]),
                            float(c["current_pos_qty"]), float(c.get("notional_usdt", 0.0)),
                            float(c["entry_price"]), float(c.get("price", 0.0)),
                            float(c["active_sl_price"]), float(c.get("unrealized_pnl", 0.0)),
                            float(c["alpha_score"]), float(c.get("mwu_trust", 1.0)),
                            int(c["bars_held"]),
                        ),
                    )
                conn.commit()
        except Exception:
            pass

    def get_daily_realized_pnl(self) -> float:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(realized_pnl - COALESCE(fee_usdt, 0.0)), 0.0) AS dpnl FROM trades WHERE timestamp >= ?",
                    (cutoff,),
                ).fetchone()
                return float(row["dpnl"]) if row else 0.0
        except Exception:
            return 0.0

    def get_recent_trades(self, limit: int = 50, symbol: str = "") -> List[Dict[str, Any]]:
        try:
            with self._connect() as conn:
                if symbol:
                    rows = conn.execute(
                        "SELECT timestamp, COALESCE(symbol, 'BTCUSDT') AS symbol, UPPER(side) AS side, "
                        "amount_btc, price, COALESCE(realized_pnl, 0.0) AS pnl, COALESCE(fee_usdt, 0.0) AS fee, "
                        "COALESCE(note, 'QuantCore') AS note FROM trades WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                        (symbol.upper(), int(limit)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT timestamp, COALESCE(symbol, 'BTCUSDT') AS symbol, UPPER(side) AS side, "
                        "amount_btc, price, COALESCE(realized_pnl, 0.0) AS pnl, COALESCE(fee_usdt, 0.0) AS fee, "
                        "COALESCE(note, 'QuantCore') AS note FROM trades ORDER BY timestamp DESC LIMIT ?",
                        (int(limit),),
                    ).fetchall()

                return [
                    {
                        "time": str(r["timestamp"])[:19],
                        "symbol": r["symbol"],
                        "side": r["side"],
                        "amount": round(float(r["amount_btc"]), 4),
                        "price": round(float(r["price"]), 4),
                        "pnl": round(float(r["pnl"]), 2),
                        "fee": round(float(r["fee"]), 3),
                        "net_pnl": round(float(r["pnl"]) - float(r["fee"]), 2),
                        "note": r["note"],
                    }
                    for r in rows
                ]
        except Exception:
            return []

    def get_equity_series_and_kpis(self, days: int = 30) -> Dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT timestamp, balance_usdt, btc_price, total_equity, unrealized_pnl, "
                    "model_action, COALESCE(gross_leverage, 0.0) AS gross_lev "
                    "FROM equity_snapshots WHERE balance_usdt > 0 AND timestamp >= ? ORDER BY timestamp ASC",
                    (cutoff,),
                ).fetchall()

                if not rows:
                    rows = conn.execute(
                        "SELECT timestamp, balance_usdt, btc_price, total_equity, unrealized_pnl, "
                        "model_action, COALESCE(gross_leverage, 0.0) AS gross_lev "
                        "FROM equity_snapshots WHERE balance_usdt > 0 ORDER BY timestamp ASC LIMIT 500"
                    ).fetchall()

                tr_stats = conn.execute(
                    "SELECT COUNT(*) AS cnt, "
                    "SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins, "
                    "SUM(CASE WHEN realized_pnl != 0 THEN 1 ELSE 0 END) AS closed_cnt, "
                    "COALESCE(SUM(fee_usdt), 0.0) AS tot_fee, "
                    "COALESCE(SUM(realized_pnl - COALESCE(fee_usdt, 0.0)), 0.0) AS net_realized "
                    "FROM trades WHERE timestamp >= ?",
                    (cutoff,),
                ).fetchone()

            if not rows:
                return {"ok": True, "series": [], "kpis": {}}

            times = [str(r["timestamp"])[:16] for r in rows]
            eq_arr = np.array(
                [
                    float(r["total_equity"])
                    if (r["total_equity"] and float(r["total_equity"]) > 0)
                    else (float(r["balance_usdt"]) + float(r["unrealized_pnl"] or 0.0))
                    for r in rows
                ],
                dtype=np.float64,
            )
            btc_arr = np.array([max(1.0, float(r["btc_price"])) for r in rows], dtype=np.float64)
            act_arr = [round(float(r["model_action"] or 0.0), 3) for r in rows]
            lev_arr = [round(float(r["gross_lev"] or 0.0), 2) for r in rows]

            first_eq = max(1.0, float(eq_arr[0]))
            latest_eq = float(eq_arr[-1])
            first_btc = max(1.0, float(btc_arr[0]))
            latest_btc = float(btc_arr[-1])

            eq_ret_pct = ((eq_arr / first_eq) - 1.0) * 100.0
            btc_ret_pct = ((btc_arr / first_btc) - 1.0) * 100.0
            peaks = np.maximum.accumulate(eq_arr)
            dd_pct = ((eq_arr - peaks) / peaks) * 100.0

            total_pnl_pct = float(eq_ret_pct[-1])
            btc_bh_pct = float(btc_ret_pct[-1])
            alpha_pct = total_pnl_pct - btc_bh_pct
            max_dd = float(np.min(dd_pct))

            if len(eq_arr) > 5:
                log_rets = np.diff(np.log(np.maximum(eq_arr, 1.0)))
                std_r = float(np.std(log_rets))
                sharpe = float(math.sqrt(35040.0) * (float(np.mean(log_rets)) / std_r)) if std_r > 1e-9 else 0.0
            else:
                sharpe = 0.0

            calmar = total_pnl_pct / max(1.0, abs(max_dd))

            total_ops = int(tr_stats["cnt"] or 0) if tr_stats else 0
            closed_cnt = int(tr_stats["closed_cnt"] or 0) if tr_stats else 0
            wins_cnt = int(tr_stats["wins"] or 0) if tr_stats else 0
            win_rate = (wins_cnt / closed_cnt * 100.0) if closed_cnt > 0 else 0.0
            tot_fee = float(tr_stats["tot_fee"] or 0.0) if tr_stats else 0.0
            net_realized = float(tr_stats["net_realized"] or 0.0) if tr_stats else 0.0

            return {
                "ok": True,
                "kpis": {
                    "latest_equity": round(latest_eq, 2),
                    "initial_equity": round(first_eq, 2),
                    "total_pnl_pct": round(total_pnl_pct, 2),
                    "btc_bh_pct": round(btc_bh_pct, 2),
                    "alpha_vs_btc_pct": round(alpha_pct, 2),
                    "btc_price": round(latest_btc, 2),
                    "max_drawdown_pct": round(max_dd, 2),
                    "sharpe_ratio": round(sharpe, 2),
                    "calmar_ratio": round(calmar, 2),
                    "total_ops": total_ops,
                    "win_rate_pct": round(win_rate, 1),
                    "total_fees_usdt": round(tot_fee, 2),
                    "net_realized_pnl": round(net_realized, 2),
                },
                "chart": {
                    "times": times,
                    "equity_usd": [round(float(x), 2) for x in eq_arr],
                    "equity_ret_pct": [round(float(x), 2) for x in eq_ret_pct],
                    "btc_ret_pct": [round(float(x), 2) for x in btc_ret_pct],
                    "drawdown_pct": [round(float(x), 2) for x in dd_pct],
                    "action": act_arr,
                    "gross_lev": lev_arr,
                },
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "kpis": {}, "chart": {}}

    def cleanup_old_records_and_backup(self) -> Optional[str]:
        """Очищує старі записи старше 60 діб, стискає WAL та створює компактний бекап у storage/backups/."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.DB_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM equity_snapshots WHERE timestamp < ?", (cutoff,))
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            backup_file = os.path.join(settings.BACKUPS_DIR, f"trading_history_{stamp}.db")
            shutil.copy2(self._db_path, backup_file)
            memory_guard.enforce_disk_quota()
            return backup_file
        except Exception:
            return None
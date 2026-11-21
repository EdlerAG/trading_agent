import contextlib
import io
import json
import os
import math
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Iterator, List, Optional
import numpy as np

try:
    import orjson as _orjson
except ImportError:
    _orjson = None  # type: ignore[assignment]

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

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
            conn.execute("PRAGMA cache_size=-4000;")  # Обмеження кешу SQLite до 4 МБ
            conn.execute("PRAGMA mmap_size=0;")
            yield conn
        finally:
            conn.close()

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

            # --- ТРЕК A (V2 TESTNET TELEMETRY & RESEARCH AUDIT TABLES) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS v2_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    candle_ts VARCHAR(32) NOT NULL,
                    equity FLOAT NOT NULL,
                    wallet_balance FLOAT NOT NULL,
                    upnl FLOAT DEFAULT 0.0,
                    tier INTEGER DEFAULT 1,
                    gross_b_scale FLOAT DEFAULT 0.0,
                    overlay_scale FLOAT DEFAULT 0.0,
                    btc_trend_200 FLOAT DEFAULT 0.0,
                    market_breadth FLOAT DEFAULT 0.0,
                    rebalanced_flag INTEGER DEFAULT 0,
                    raw_factors_json TEXT DEFAULT '{}',
                    weights_a_json TEXT DEFAULT '{}',
                    weights_b_json TEXT DEFAULT '{}',
                    weights_net_json TEXT DEFAULT '{}',
                    skipped_reasons_json TEXT DEFAULT '{}'
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS v2_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                    candle_ts VARCHAR(32) DEFAULT '',
                    symbol VARCHAR(24) NOT NULL,
                    sleeve_book VARCHAR(32) DEFAULT '',
                    side VARCHAR(10) NOT NULL,
                    target_qty FLOAT DEFAULT 0.0,
                    executed_qty FLOAT DEFAULT 0.0,
                    signal_close_px FLOAT DEFAULT 0.0,
                    arrival_mid_px FLOAT DEFAULT 0.0,
                    fill_avg_px FLOAT DEFAULT 0.0,
                    slippage_bps FLOAT DEFAULT 0.0,
                    slippage_arrival_bps FLOAT DEFAULT 0.0,
                    slippage_signal_bps FLOAT DEFAULT 0.0,
                    spread_bps FLOAT DEFAULT 0.0,
                    is_maker INTEGER DEFAULT 0,
                    maker_fallback_used INTEGER DEFAULT 0,
                    maker_qty FLOAT DEFAULT 0.0,
                    taker_qty FLOAT DEFAULT 0.0,
                    fee_usdt FLOAT DEFAULT 0.0,
                    latency_ms FLOAT DEFAULT 0.0,
                    order_status VARCHAR(24) DEFAULT 'FILLED'
                );
            """)
            for sql in (
                "ALTER TABLE v2_executions ADD COLUMN slippage_bps FLOAT DEFAULT 0.0;",
                "ALTER TABLE v2_executions ADD COLUMN slippage_arrival_bps FLOAT DEFAULT 0.0;",
                "ALTER TABLE v2_executions ADD COLUMN slippage_signal_bps FLOAT DEFAULT 0.0;",
            ):
                try:
                    conn.execute(sql)
                except Exception:
                    pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS v2_funding_ledger (
                    tran_id VARCHAR(64) PRIMARY KEY,
                    funding_time DATETIME NOT NULL,
                    symbol VARCHAR(24) NOT NULL,
                    income_usdt FLOAT NOT NULL,
                    pos_qty_at_bar FLOAT DEFAULT 0.0,
                    funding_rate_est FLOAT DEFAULT 0.0
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS v2_market_micro (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candle_ts VARCHAR(32) NOT NULL,
                    symbol VARCHAR(24) NOT NULL,
                    best_bid FLOAT DEFAULT 0.0,
                    best_ask FLOAT DEFAULT 0.0,
                    spread_bps FLOAT DEFAULT 0.0,
                    top5_depth_usd FLOAT DEFAULT 0.0,
                    mark_price FLOAT DEFAULT 0.0,
                    index_price FLOAT DEFAULT 0.0,
                    basis_bps FLOAT DEFAULT 0.0,
                    open_interest_usd FLOAT DEFAULT 0.0,
                    funding_rate FLOAT DEFAULT 0.0
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_v2_dec_ts ON v2_decisions(candle_ts);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_v2_exec_ts ON v2_executions(ts);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_v2_fund_ts ON v2_funding_ledger(funding_time);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_v2_micro_ts ON v2_market_micro(candle_ts);")

            # --- SHADOW ARENA (ЖИВИЙ ЧЕМПІОНАТ 6 МОДЕЛЕЙ НА TESTNET / LIVE) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shadow_arena_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    candle_ts VARCHAR(32) NOT NULL,
                    bot_id VARCHAR(36) NOT NULL,
                    initial_equity FLOAT NOT NULL,
                    equity FLOAT NOT NULL,
                    return_pct FLOAT DEFAULT 0.0,
                    max_dd_pct FLOAT DEFAULT 0.0,
                    gross_lev FLOAT DEFAULT 0.0,
                    net_lev FLOAT DEFAULT 0.0,
                    active_positions INTEGER DEFAULT 0,
                    trades_count INTEGER DEFAULT 0,
                    fees_usd FLOAT DEFAULT 0.0,
                    funding_usd FLOAT DEFAULT 0.0
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_arena_ts ON shadow_arena_snapshots(candle_ts);")
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

            raw_rows = list(rows)
            raw_eq = [
                float(r["total_equity"])
                if (r["total_equity"] and float(r["total_equity"]) > 0)
                else (float(r["balance_usdt"]) + float(r["unrealized_pnl"] or 0.0))
                for r in raw_rows
            ]

            # 1. Автоматичне відсікання старих епох при зміні віртуального масштабу (напр. перехід з Demo $6,500 на Virtual Cap $500)
            epoch_start = 0
            for idx_r in range(1, len(raw_eq)):
                prev_e, cur_e = raw_eq[idx_r - 1], raw_eq[idx_r]
                if prev_e > 0 and abs(cur_e - prev_e) / prev_e > 0.55:
                    epoch_start = idx_r
            raw_rows = raw_rows[epoch_start:]
            raw_eq = raw_eq[epoch_start:]

            # 2. Стиснення "мертвих" днів на паузі (щоб неактивні дні ніколи не розтягували графік пласкою лінією!)
            comp_rows = []
            comp_eq = []
            for idx_r, r in enumerate(raw_rows):
                e_val = raw_eq[idx_r]
                g_val = float(r["gross_lev"] or 0.0)
                if (
                    0 < idx_r < len(raw_rows) - 1
                    and len(comp_eq) >= 1
                    and abs(e_val - comp_eq[-1]) < 0.02
                    and abs(e_val - raw_eq[idx_r + 1]) < 0.02
                    and g_val < 0.01
                ):
                    continue
                comp_rows.append(r)
                comp_eq.append(e_val)

            rows = comp_rows or raw_rows
            eq_arr = np.array(comp_eq if comp_eq else raw_eq, dtype=np.float64)
            times = [str(r["timestamp"])[:16] for r in rows]
            btc_arr = np.array([max(1.0, float(r["btc_price"])) for r in rows], dtype=np.float64)
            act_arr = [round(float(r["model_action"] or 0.0), 3) for r in rows]
            lev_arr = [round(float(r["gross_lev"] or 0.0), 2) for r in rows]

            # Серії живого чемпіонату Shadow Arena для графіка порівняння моделей
            arena_series: Dict[str, Dict[str, list]] = {}
            try:
                with self._connect() as conn:
                    a_rows = conn.execute(
                        "SELECT candle_ts, bot_id, return_pct, equity FROM shadow_arena_snapshots "
                        "WHERE recorded_at >= ? ORDER BY id ASC",
                        (cutoff,),
                    ).fetchall()
                for ar in a_rows:
                    bid = str(ar["bot_id"])
                    rec = arena_series.setdefault(bid, {"times": [], "ret_pct": [], "equity": []})
                    rec["times"].append(str(ar["candle_ts"])[:16].replace("T", " "))
                    rec["ret_pct"].append(round(float(ar["return_pct"] or 0.0), 3))
                    rec["equity"].append(round(float(ar["equity"] or 0.0), 2))
            except Exception:
                pass

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
                bars_per_year = (365.0 * 24.0 * 60.0) / max(1.0, float(settings.CANDLE_INTERVAL_MINUTES))
                sharpe = float(math.sqrt(bars_per_year) * (float(np.mean(log_rets)) / std_r)) if std_r > 1e-9 else 0.0
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
                    "arena_series": arena_series,
                },
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "kpis": {}, "chart": {}}

    def reset_and_optimize_history(self, seed_equity: float = 0.0, btc_price: float = 0.0) -> Dict[str, Any]:
        """Архівує стару БД/логи та створює ідеально чистий старт без старих неактивних днів."""
        os.makedirs(settings.BACKUPS_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_db = os.path.join(settings.BACKUPS_DIR, f"pre_reset_{stamp}.db")
        try:
            if os.path.exists(self._db_path):
                shutil.copy2(self._db_path, backup_db)
        except Exception:
            backup_db = ""

        with self._connect() as conn:
            for tbl in (
                "equity_snapshots",
                "trades",
                "v2_decisions",
                "v2_executions",
                "v2_funding_ledger",
                "v2_market_micro",
                "shadow_arena_snapshots",
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
            try:
                conn.execute("VACUUM;")
            except Exception:
                pass

        # Очищення текстових логів від старих записів
        for lp in (settings.LOG_PATH, os.path.join(settings.BASE_DIR, "trading_bot.log")):
            if lp and os.path.exists(lp):
                try:
                    with open(lp, "w", encoding="utf-8") as f:
                        f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} [INFO] ✨ Історію та графіки очищено — чистий старт QuantCore V5.0!\n")
                except Exception:
                    pass

        if seed_equity > 0.0:
            self.record_snapshot(
                balance_usdt=float(seed_equity),
                btc_pos_qty=0.0,
                btc_price=float(btc_price if btc_price > 0 else 90000.0),
                unrealized_pnl=0.0,
                master_action=0.0,
                gross_leverage=0.0,
                active_coins=0,
            )
        return {"ok": True, "backup_path": backup_db}

    def cleanup_old_records_and_backup(self) -> Optional[str]:
        """Очищує старі записи старше 60 діб, стискає WAL та створює компактний бекап у storage/backups/."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.DB_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM equity_snapshots WHERE timestamp < ?", (cutoff,))
                conn.execute("DELETE FROM v2_decisions WHERE recorded_at < ?", (cutoff,))
                conn.execute("DELETE FROM v2_executions WHERE ts < ?", (cutoff,))
                conn.execute("DELETE FROM v2_market_micro WHERE candle_ts < ?", (cutoff,))
                conn.execute("DELETE FROM shadow_arena_snapshots WHERE recorded_at < ?", (cutoff,))
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            backup_file = os.path.join(settings.BACKUPS_DIR, f"trading_history_{stamp}.db")
            shutil.copy2(self._db_path, backup_file)
            memory_guard.enforce_disk_quota()
            return backup_file
        except Exception:
            return None

    # =====================================================================
    # V2 TESTNET TELEMETRY, JSONL STREAMING & ANALYTICS BUNDLE
    # =====================================================================
    @staticmethod
    def _append_v2_jsonl(event_type: str, payload: Dict[str, Any]) -> None:
        try:
            os.makedirs(settings.V2_TELEMETRY_DIR, exist_ok=True)
            month_tag = datetime.now(timezone.utc).strftime("%Y-%m")
            path = os.path.join(settings.V2_TELEMETRY_DIR, f"{month_tag}.jsonl")
            record = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, **payload}
            if _orjson is not None:
                raw_line = _orjson.dumps(record) + b"\n"
                with open(path, "ab") as f:
                    f.write(raw_line)
            else:
                line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def record_v2_decision(
        self,
        candle_ts: str,
        equity: float,
        wallet_balance: float,
        upnl: float,
        extra_telemetry: Dict[str, Any],
        skipped_exec: Optional[Dict[str, str]] = None,
    ) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        tier = int(extra_telemetry.get("tier", 1))
        gb = float(extra_telemetry.get("gross_b_scale", extra_telemetry.get("risk_mult", 0.0)) or 0.0)
        ov = float(extra_telemetry.get("overlay_scale", extra_telemetry.get("a_gross", 0.0)) or 0.0)
        bt = float(extra_telemetry.get("btc_trend", 0.0) or 0.0)
        br = float(extra_telemetry.get("market_breadth", 0.0) or 0.0)
        reb = 1 if bool(extra_telemetry.get("any_rebalanced", extra_telemetry.get("b_rebalanced", False))) else 0
        factors = extra_telemetry.get("factor_scores") or extra_telemetry.get("factors") or {}
        w_a = extra_telemetry.get("weights_a") or {}
        w_b = extra_telemetry.get("weights_b") or {}
        w_c = extra_telemetry.get("weights_c") or {}
        w_d = extra_telemetry.get("weights_d") or {}
        w_e = extra_telemetry.get("weights_e") or {}
        w_net = extra_telemetry.get("weights_net") or {}
        skipped = dict(extra_telemetry.get("skipped_symbols") or extra_telemetry.get("skipped") or {})
        if skipped_exec:
            skipped.update(skipped_exec)

        w_a_store = w_a if not (w_c or w_d or w_e) else {**w_a, "__weights_c__": w_c, "__weights_d__": w_d, "__weights_e__": w_e}

        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO v2_decisions (
                        recorded_at, candle_ts, equity, wallet_balance, upnl, tier,
                        gross_b_scale, overlay_scale, btc_trend_200, market_breadth,
                        rebalanced_flag, raw_factors_json, weights_a_json,
                        weights_b_json, weights_net_json, skipped_reasons_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_str, str(candle_ts), float(equity), float(wallet_balance), float(upnl),
                        tier, gb, ov, bt, br, reb,
                        json.dumps(factors, separators=(",", ":")),
                        json.dumps(w_a_store, separators=(",", ":")),
                        json.dumps(w_b, separators=(",", ":")),
                        json.dumps(w_net, separators=(",", ":")),
                        json.dumps(skipped, separators=(",", ":")),
                    ),
                )
                conn.commit()
        except Exception:
            pass

        self._append_v2_jsonl("decision", {
            "candle_ts": str(candle_ts),
            "equity": round(float(equity), 2),
            "wallet_balance": round(float(wallet_balance), 2),
            "upnl": round(float(upnl), 2),
            "tier": tier,
            "gross_b_scale": round(gb, 4),
            "overlay_scale": round(ov, 4),
            "btc_trend_200": round(bt, 5),
            "market_breadth": round(br, 4),
            "rebalanced": bool(reb),
            "weights_a": w_a,
            "weights_b": w_b,
            "weights_c": w_c,
            "weights_d": w_d,
            "weights_e": w_e,
            "weights_net": w_net,
            "factors": factors,
            "skipped": skipped,
        })

    def record_v2_execution(
        self,
        candle_ts: str,
        symbol: str,
        sleeve_book: str,
        side: str,
        target_qty: float,
        executed_qty: float,
        signal_close_px: float,
        arrival_mid_px: float,
        fill_avg_px: float,
        spread_bps: float,
        maker_qty: float,
        taker_qty: float,
        fee_usdt: float,
        latency_ms: float,
        order_status: str = "FILLED",
    ) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        sgn = 1.0 if side.upper() == "BUY" else -1.0
        slip_arr = ((fill_avg_px - arrival_mid_px) / max(arrival_mid_px, 1e-8) * sgn * 10_000.0) if (fill_avg_px > 0 and arrival_mid_px > 0) else 0.0
        slip_sig = ((fill_avg_px - signal_close_px) / max(signal_close_px, 1e-8) * sgn * 10_000.0) if (fill_avg_px > 0 and signal_close_px > 0) else 0.0
        is_maker = 1 if (maker_qty > 0 and taker_qty <= 1e-12) else 0
        fb_used = 1 if taker_qty > 1e-12 else 0
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO v2_executions (
                        ts, candle_ts, symbol, sleeve_book, side, target_qty, executed_qty,
                        signal_close_px, arrival_mid_px, fill_avg_px, slippage_bps,
                        slippage_arrival_bps, slippage_signal_bps, spread_bps, is_maker,
                        maker_fallback_used, maker_qty, taker_qty, fee_usdt, latency_ms, order_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_str, str(candle_ts), symbol.upper(), str(sleeve_book), side.upper(),
                        float(target_qty), float(executed_qty), float(signal_close_px),
                        float(arrival_mid_px), float(fill_avg_px), round(float(slip_arr), 3),
                        round(float(slip_arr), 3), round(float(slip_sig), 3), round(float(spread_bps), 3),
                        is_maker, fb_used, float(maker_qty), float(taker_qty),
                        float(fee_usdt), float(latency_ms), str(order_status),
                    ),
                )
                conn.commit()
        except Exception:
            pass

        self._append_v2_jsonl("execution", {
            "candle_ts": str(candle_ts),
            "symbol": symbol.upper(),
            "book": sleeve_book,
            "side": side.upper(),
            "target_qty": round(float(target_qty), 6),
            "executed_qty": round(float(executed_qty), 6),
            "signal_px": float(signal_close_px),
            "arrival_px": float(arrival_mid_px),
            "fill_px": float(fill_avg_px),
            "slippage_bps": round(float(slip_arr), 3),
            "slip_arr_bps": round(float(slip_arr), 3),
            "slip_sig_bps": round(float(slip_sig), 3),
            "spread_bps": round(float(spread_bps), 3),
            "is_maker": bool(is_maker),
            "maker_fallback_used": bool(fb_used),
            "maker_qty": round(float(maker_qty), 6),
            "taker_qty": round(float(taker_qty), 6),
            "fee_usdt": round(float(fee_usdt), 5),
            "latency_ms": round(float(latency_ms), 1),
            "status": order_status,
        })

    def record_v2_funding_batch(
        self,
        events: List[Dict[str, Any]],
        pos_qty_map: Dict[str, float],
        rate_map: Dict[str, float],
    ) -> int:
        if not events:
            return 0
        inserted = 0
        try:
            with self._connect() as conn:
                for ev in events:
                    tid = str(ev.get("tran_id") or "")
                    sym = str(ev.get("symbol") or "").upper()
                    t_ms = int(ev.get("funding_time_ms") or 0)
                    inc = float(ev.get("income_usdt") or 0.0)
                    if not tid or not sym or t_ms <= 0:
                        continue
                    f_str = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO v2_funding_ledger
                        (tran_id, funding_time, symbol, income_usdt, pos_qty_at_bar, funding_rate_est)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (tid, f_str, sym, inc, float(pos_qty_map.get(sym, 0.0)), float(rate_map.get(sym, 0.0))),
                    )
                    if cur.rowcount and cur.rowcount > 0:
                        inserted += 1
                        self._append_v2_jsonl("funding", {
                            "tran_id": tid,
                            "funding_time": f_str,
                            "symbol": sym,
                            "income_usdt": inc,
                            "pos_qty_at_bar": float(pos_qty_map.get(sym, 0.0)),
                            "funding_rate_est": float(rate_map.get(sym, 0.0)),
                        })
                conn.commit()
        except Exception:
            pass
        return inserted

    def record_v2_market_micro(self, candle_ts: str, micro_map: Dict[str, Dict[str, float]]) -> None:
        if not micro_map:
            return
        try:
            with self._connect() as conn:
                rows = [
                    (
                        str(candle_ts), sym.upper(),
                        float(m.get("best_bid", 0.0)), float(m.get("best_ask", 0.0)),
                        float(m.get("spread_bps", 0.0)), float(m.get("top5_depth_usd", 0.0)),
                        float(m.get("mark_price", 0.0)), float(m.get("index_price", 0.0)),
                        float(m.get("basis_bps", 0.0)), float(m.get("open_interest_usd", 0.0)),
                        float(m.get("funding_rate", 0.0)),
                    )
                    for sym, m in micro_map.items()
                ]
                conn.executemany(
                    """
                    INSERT INTO v2_market_micro (
                        candle_ts, symbol, best_bid, best_ask, spread_bps, top5_depth_usd,
                        mark_price, index_price, basis_bps, open_interest_usd, funding_rate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
        except Exception:
            pass

        self._append_v2_jsonl("market_micro", {
            "candle_ts": str(candle_ts),
            "assets": {sym.upper(): m for sym, m in micro_map.items()},
        })

    def get_v2_recent_executions(self, limit: int = 30) -> List[Dict[str, Any]]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT ts, candle_ts, symbol, sleeve_book, side, target_qty, executed_qty,
                           signal_close_px, arrival_mid_px, fill_avg_px, slippage_arrival_bps,
                           slippage_signal_bps, spread_bps, is_maker, maker_fallback_used,
                           fee_usdt, latency_ms, order_status
                    FROM v2_executions ORDER BY id DESC LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_v2_analytics_summary(self, days: int = 30) -> Dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                ex = conn.execute(
                    """
                    SELECT COUNT(*) AS n,
                           SUM(CASE WHEN order_status='FILLED' THEN 1 ELSE 0 END) AS filled,
                           COALESCE(SUM(maker_qty * fill_avg_px), 0.0) AS maker_usd,
                           COALESCE(SUM(taker_qty * fill_avg_px), 0.0) AS taker_usd,
                           COALESCE(AVG(CASE WHEN order_status='FILLED' THEN slippage_arrival_bps END), 0.0) AS avg_slip_arr,
                           COALESCE(AVG(CASE WHEN order_status='FILLED' THEN slippage_signal_bps END), 0.0) AS avg_slip_sig,
                           COALESCE(AVG(CASE WHEN order_status='FILLED' THEN spread_bps END), 0.0) AS avg_spread,
                           COALESCE(AVG(CASE WHEN order_status='FILLED' THEN latency_ms END), 0.0) AS avg_lat,
                           COALESCE(SUM(fee_usdt), 0.0) AS fees
                    FROM v2_executions WHERE ts >= ?
                    """,
                    (cutoff,),
                ).fetchone()
                fn = conn.execute(
                    "SELECT COUNT(*) AS cnt, COALESCE(SUM(income_usdt), 0.0) AS net_inc FROM v2_funding_ledger WHERE funding_time >= ?",
                    (cutoff,),
                ).fetchone()
                dc = conn.execute(
                    "SELECT COUNT(*) AS cnt, SUM(rebalanced_flag) AS rebs FROM v2_decisions WHERE recorded_at >= ?",
                    (cutoff,),
                ).fetchone()
                last_dec = conn.execute(
                    "SELECT candle_ts, tier, gross_b_scale, overlay_scale, btc_trend_200, market_breadth, weights_a_json, weights_b_json "
                    "FROM v2_decisions ORDER BY id DESC LIMIT 1"
                ).fetchone()

            m_usd = float(ex["maker_usd"] or 0.0) if ex else 0.0
            t_usd = float(ex["taker_usd"] or 0.0) if ex else 0.0
            tot_usd = m_usd + t_usd
            maker_ratio = (m_usd / tot_usd * 100.0) if tot_usd > 0 else 0.0

            latest_sleeves: Dict[str, Any] = {}
            if last_dec:
                latest_sleeves = {
                    "candle_ts": last_dec["candle_ts"],
                    "tier": int(last_dec["tier"] or 1),
                    "gross_b_scale": round(float(last_dec["gross_b_scale"] or 0.0), 3),
                    "overlay_scale": round(float(last_dec["overlay_scale"] or 0.0), 3),
                    "btc_trend_pct": round(float(last_dec["btc_trend_200"] or 0.0) * 100.0, 2),
                    "breadth_pct": round(float(last_dec["market_breadth"] or 0.0) * 100.0, 1),
                    "weights_a": json.loads(last_dec["weights_a_json"] or "{}"),
                    "weights_b": json.loads(last_dec["weights_b_json"] or "{}"),
                }

            return {
                "ok": True,
                "decisions_logged": int(dc["cnt"] or 0) if dc else 0,
                "rebalances_logged": int(dc["rebs"] or 0) if dc else 0,
                "orders_total": int(ex["n"] or 0) if ex else 0,
                "orders_filled": int(ex["filled"] or 0) if ex else 0,
                "maker_fill_pct": round(maker_ratio, 1),
                "avg_slippage_arrival_bps": round(float(ex["avg_slip_arr"] or 0.0), 2) if ex else 0.0,
                "avg_slippage_signal_bps": round(float(ex["avg_slip_sig"] or 0.0), 2) if ex else 0.0,
                "avg_spread_bps": round(float(ex["avg_spread"] or 0.0), 2) if ex else 0.0,
                "avg_latency_ms": round(float(ex["avg_lat"] or 0.0), 1) if ex else 0.0,
                "v2_fees_usdt": round(float(ex["fees"] or 0.0), 3) if ex else 0.0,
                "funding_events": int(fn["cnt"] or 0) if fn else 0,
                "net_funding_income_usdt": round(float(fn["net_inc"] or 0.0), 3) if fn else 0.0,
                "latest_sleeves": latest_sleeves,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def export_v2_research_zip(self) -> Optional[str]:
        """Пакує SQLite БД + усі JSONL логи телеметрії Testnet у компактний ZIP для аналізу."""
        try:
            os.makedirs(settings.BACKUPS_DIR, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out_zip = os.path.join(settings.BACKUPS_DIR, f"v2_testnet_telemetry_{stamp}.zip")
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(self._db_path):
                    zf.write(self._db_path, arcname="trading_history.db")
                if os.path.exists(settings.STATE_FILE):
                    zf.write(settings.STATE_FILE, arcname="engine_state.json")
                v2_st = os.path.join(settings.STORAGE_DIR, "v2_live_state.json")
                if os.path.exists(v2_st):
                    zf.write(v2_st, arcname="v2_live_state.json")
                ar_st = os.path.join(settings.STORAGE_DIR, "shadow_arena_state.json")
                if os.path.exists(ar_st):
                    zf.write(ar_st, arcname="shadow_arena_state.json")
                if os.path.exists(settings.V2_TELEMETRY_DIR):
                    for fn in sorted(os.listdir(settings.V2_TELEMETRY_DIR)):
                        if fn.endswith(".jsonl"):
                            zf.write(
                                os.path.join(settings.V2_TELEMETRY_DIR, fn),
                                arcname=f"v2_telemetry/{fn}",
                            )
            return out_zip
        except Exception:
            return None

    def record_shadow_arena_batch(self, candle_ts: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO shadow_arena_snapshots (
                        recorded_at, candle_ts, bot_id, initial_equity, equity, return_pct,
                        max_dd_pct, gross_lev, net_lev, active_positions, trades_count, fees_usd, funding_usd
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            now_str, str(candle_ts), str(r["bot_id"]), float(r["initial_equity"]),
                            float(r["equity"]), float(r["return_pct"]), float(r["max_dd_pct"]),
                            float(r["gross_lev"]), float(r["net_lev"]), int(r["active_positions"]),
                            int(r["trades_count"]), float(r["fees_usd"]), float(r["funding_usd"]),
                        )
                        for r in rows
                    ],
                )
                conn.commit()
        except Exception:
            pass
        self._append_v2_jsonl("shadow_arena", {"candle_ts": str(candle_ts), "leaderboard": rows})
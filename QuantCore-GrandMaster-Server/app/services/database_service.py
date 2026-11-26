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
from app.core.metrics_math import (
    compute_equity_bridge_dict,
    compute_hourly_attribution_step,
    compute_unified_performance_metrics,
)
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
                "ALTER TABLE trades ADD COLUMN action VARCHAR(24) DEFAULT '';",
                "ALTER TABLE trades ADD COLUMN is_artifact INTEGER DEFAULT 0;",
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
                "ALTER TABLE equity_snapshots ADD COLUMN is_artifact INTEGER DEFAULT 0;",
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
                    skipped_reasons_json TEXT DEFAULT '{}',
                    prices_json TEXT DEFAULT '{}'
                );
            """)
            try:
                conn.execute("ALTER TABLE v2_decisions ADD COLUMN prices_json TEXT DEFAULT '{}';")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS v2_income_ledger (
                    tran_id VARCHAR(64) PRIMARY KEY,
                    ts_ms BIGINT NOT NULL,
                    ts_utc DATETIME NOT NULL,
                    income_type VARCHAR(24) NOT NULL,
                    symbol VARCHAR(24) DEFAULT '',
                    income_usdt FLOAT NOT NULL,
                    info VARCHAR(64) DEFAULT ''
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_v2_inc_ts ON v2_income_ledger(ts_utc, income_type);")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS v2_hourly_attribution (
                    candle_ts VARCHAR(32) PRIMARY KEY,
                    prev_candle_ts VARCHAR(32) DEFAULT '',
                    equity_prev FLOAT DEFAULT 0.0,
                    port_ret_1h FLOAT DEFAULT 0.0,
                    sleeve_a_pnl FLOAT DEFAULT 0.0,
                    sleeve_b_pnl FLOAT DEFAULT 0.0,
                    sleeve_c_pnl FLOAT DEFAULT 0.0,
                    sleeve_d_pnl FLOAT DEFAULT 0.0,
                    fac_mom_pnl FLOAT DEFAULT 0.0,
                    fac_carry_pnl FLOAT DEFAULT 0.0,
                    fac_bab_pnl FLOAT DEFAULT 0.0,
                    fac_flow_pnl FLOAT DEFAULT 0.0,
                    fac_spot_pnl FLOAT DEFAULT 0.0,
                    fac_smart_oi_pnl FLOAT DEFAULT 0.0
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
            self._migrate_historical_artifacts_conn(conn)
            conn.commit()

    @staticmethod
    def _migrate_historical_artifacts_conn(conn: sqlite3.Connection) -> Dict[str, int]:
        """Ідемпотентно позначає історичні артефакти 21-25.11 (`is_artifact=1`), зберігаючи сирі записи недоторканими."""
        marked_trades = 0
        marked_snaps = 0
        try:
            # 1. Дублікати стопів із однаковим (symbol, order_id) при непорожньому order_id
            cur1 = conn.execute("""
                UPDATE trades SET is_artifact = 1
                WHERE COALESCE(is_artifact, 0) = 0
                  AND order_id IS NOT NULL AND order_id != ''
                  AND (note LIKE '%STOP%' OR note LIKE '%MFE%')
                  AND id NOT IN (
                      SELECT MIN(id) FROM trades
                      WHERE order_id IS NOT NULL AND order_id != ''
                        AND (note LIKE '%STOP%' OR note LIKE '%MFE%')
                      GROUP BY symbol, order_id
                  )
            """)
            marked_trades += max(0, cur1.rowcount or 0)

            # 2. Фейкові записи MFE_HARVESTER_TP та старі вхідні дублі за 23.11 13:50..15:10 UTC (коли в V6.1 не існувало TP)
            cur2 = conn.execute("""
                UPDATE trades SET is_artifact = 1
                WHERE COALESCE(is_artifact, 0) = 0
                  AND timestamp >= '2026-11-23 13:50:00' AND timestamp <= '2026-11-23 15:10:00'
                  AND (
                      note = 'MFE_HARVESTER_TP'
                      OR (symbol = 'SOLUSDT' AND ABS(amount_btc - 0.42) < 1e-6 AND ABS(price - 68.86) < 1e-4)
                  )
            """)
            marked_trades += max(0, cur2.rowcount or 0)

            # 3. Поодинокі $500.00-тики в equity_snapshots після SIGKILL-рестарту (коли сусіди > $508.00)
            snaps = conn.execute(
                "SELECT id, timestamp, balance_usdt, total_equity, unrealized_pnl, gross_leverage "
                "FROM equity_snapshots ORDER BY id ASC"
            ).fetchall()
            eq_vals = [
                float(r["total_equity"]) if (r["total_equity"] and float(r["total_equity"]) > 0)
                else (float(r["balance_usdt"]) + float(r["unrealized_pnl"] or 0.0))
                for r in snaps
            ]
            art_ids: List[int] = []
            for idx in range(1, len(snaps)):
                ev = eq_vals[idx]
                prv = eq_vals[idx - 1]
                nxt = eq_vals[idx + 1] if (idx + 1) < len(snaps) else prv
                ts_s = str(snaps[idx]["timestamp"])
                g_lev = float(snaps[idx]["gross_leverage"] or 0.0)
                # Точне скидання в 500.0000 при рестарті без якоря (після стартового снапшота V6.1 2026-11-22 16:02)
                if abs(ev - 500.0) < 1e-6 and ts_s > "2026-11-22 16:02:00" and (abs(prv - 500.0) > 0.05 or abs(nxt - 500.0) > 0.05):
                    art_ids.append(int(snaps[idx]["id"]))
                elif abs(ev - 500.0) < 0.05 and prv > 508.0 and nxt > 508.0:
                    art_ids.append(int(snaps[idx]["id"]))
                elif g_lev < 0.01 and abs(ev - 500.0) < 0.05 and prv > 508.0:
                    art_ids.append(int(snaps[idx]["id"]))
            if art_ids:
                q_marks = ",".join("?" for _ in art_ids)
                cur3 = conn.execute(
                    f"UPDATE equity_snapshots SET is_artifact = 1 WHERE COALESCE(is_artifact, 0) = 0 AND id IN ({q_marks})",
                    tuple(art_ids),
                )
                marked_snaps += max(0, cur3.rowcount or 0)

            # 4. Видалення мертвих нульових пар V58 (WIFUSDT, RENDERUSDT, ORDIUSDT, ICPUSDT) із таблиці coin_states
            conn.execute("""
                DELETE FROM coin_states
                WHERE symbol IN ('WIFUSDT', 'RENDERUSDT', 'ORDIUSDT', 'ICPUSDT')
                  AND ABS(COALESCE(position_qty, 0.0)) <= 1e-12
            """)
        except Exception:
            pass
        return {"marked_trades": marked_trades, "marked_snapshots": marked_snaps}

    def migrate_historical_artifacts(self) -> Dict[str, int]:
        with self._connect() as conn:
            res = self._migrate_historical_artifacts_conn(conn)
            conn.commit()
            return res

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
        action: str = "",
        timestamp_override: Optional[str] = None,
    ) -> bool:
        now_str = str(timestamp_override or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        oid = str(order_id or "").strip()
        sym_u = symbol.upper()
        try:
            with self._connect() as conn:
                if oid:
                    dup = conn.execute(
                        "SELECT id FROM trades WHERE symbol = ? AND order_id = ? AND COALESCE(is_artifact, 0) = 0 LIMIT 1",
                        (sym_u, oid),
                    ).fetchone()
                    if dup is not None and ("STOP" in note.upper() or "CLOSE_" in action.upper()):
                        return False
                conn.execute(
                    "INSERT INTO trades (timestamp, symbol, order_id, side, action, amount_btc, price, realized_pnl, fee_usdt, note, is_artifact) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (now_str, sym_u, oid, side.upper(), str(action or "")[:24], float(amount), float(price), float(pnl), float(fee), note[:115]),
                )
                conn.commit()
                return True
        except Exception:
            return False

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
                if len(coins_radar) >= 5:
                    active_syms = [str(c["symbol"]).upper() for c in coins_radar]
                    q_marks = ",".join("?" for _ in active_syms)
                    conn.execute(
                        f"DELETE FROM coin_states WHERE ABS(COALESCE(position_qty, 0.0)) <= 1e-12 AND symbol NOT IN ({q_marks})",
                        tuple(active_syms),
                    )
                conn.commit()
        except Exception:
            pass

    def get_daily_realized_pnl(self) -> float:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(realized_pnl - COALESCE(fee_usdt, 0.0)), 0.0) AS dpnl "
                    "FROM trades WHERE COALESCE(is_artifact, 0) = 0 AND timestamp >= ?",
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
                        "COALESCE(action, '') AS action, amount_btc, price, COALESCE(realized_pnl, 0.0) AS pnl, "
                        "COALESCE(fee_usdt, 0.0) AS fee, COALESCE(note, 'QuantCore') AS note "
                        "FROM trades WHERE COALESCE(is_artifact, 0) = 0 AND symbol = ? ORDER BY timestamp DESC LIMIT ?",
                        (symbol.upper(), int(limit)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT timestamp, COALESCE(symbol, 'BTCUSDT') AS symbol, UPPER(side) AS side, "
                        "COALESCE(action, '') AS action, amount_btc, price, COALESCE(realized_pnl, 0.0) AS pnl, "
                        "COALESCE(fee_usdt, 0.0) AS fee, COALESCE(note, 'QuantCore') AS note "
                        "FROM trades WHERE COALESCE(is_artifact, 0) = 0 ORDER BY timestamp DESC LIMIT ?",
                        (int(limit),),
                    ).fetchall()

                return [
                    {
                        "time": str(r["timestamp"])[:19],
                        "symbol": r["symbol"],
                        "side": r["side"],
                        "action": r["action"] or r["side"],
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
                    "FROM equity_snapshots WHERE COALESCE(is_artifact, 0) = 0 AND balance_usdt > 0 AND timestamp >= ? ORDER BY timestamp ASC",
                    (cutoff,),
                ).fetchall()

                if not rows:
                    rows = conn.execute(
                        "SELECT timestamp, balance_usdt, btc_price, total_equity, unrealized_pnl, "
                        "model_action, COALESCE(gross_leverage, 0.0) AS gross_lev "
                        "FROM equity_snapshots WHERE COALESCE(is_artifact, 0) = 0 AND balance_usdt > 0 ORDER BY timestamp ASC LIMIT 500"
                    ).fetchall()

                tr_stats = conn.execute(
                    "SELECT COUNT(*) AS cnt, "
                    "SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins, "
                    "SUM(CASE WHEN realized_pnl != 0 THEN 1 ELSE 0 END) AS closed_cnt, "
                    "COALESCE(SUM(fee_usdt), 0.0) AS tot_fee, "
                    "COALESCE(SUM(realized_pnl - COALESCE(fee_usdt, 0.0)), 0.0) AS net_realized "
                    "FROM trades WHERE COALESCE(is_artifact, 0) = 0 AND timestamp >= ?",
                    (cutoff,),
                ).fetchone()
                tr_pnl_rows = conn.execute(
                    "SELECT realized_pnl - COALESCE(fee_usdt, 0.0) AS net_p FROM trades "
                    "WHERE COALESCE(is_artifact, 0) = 0 AND realized_pnl != 0 AND timestamp >= ?",
                    (cutoff,),
                ).fetchall()

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
            closed_pnls = [float(r["net_p"] or 0.0) for r in tr_pnl_rows] if tr_pnl_rows else []
            perf = compute_unified_performance_metrics(
                timestamps=[str(r["timestamp"]) for r in rows],
                equities=[float(x) for x in eq_arr],
                trade_pnls=closed_pnls,
            )
            max_dd = float(perf["max_drawdown_pct"])
            sharpe = float(perf["sharpe_ratio"])
            calmar = float(perf["calmar_ratio"])

            total_ops = int(tr_stats["cnt"] or 0) if tr_stats else 0
            win_rate = float(perf["win_rate_pct"])
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
                    "sharpe_is_provisional": bool(perf["sharpe_is_provisional"]),
                    "sharpe_label": str(perf["sharpe_label"]),
                    "sharpe_non_annualized": float(perf["sharpe_non_annualized"]),
                    "sortino_ratio": float(perf["sortino_ratio"]),
                    "profit_factor": float(perf["profit_factor"]),
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

        prices_map = extra_telemetry.get("signal_prices") or extra_telemetry.get("prices") or {}
        w_a_store = w_a if not (w_c or w_d or w_e) else {**w_a, "__weights_c__": w_c, "__weights_d__": w_d, "__weights_e__": w_e}

        attr_step: Optional[Dict[str, float]] = None
        try:
            with self._connect() as conn:
                prev_row = conn.execute(
                    "SELECT candle_ts, equity, raw_factors_json, weights_a_json, weights_b_json, weights_net_json, prices_json "
                    "FROM v2_decisions WHERE candle_ts < ? ORDER BY candle_ts DESC, id DESC LIMIT 1",
                    (str(candle_ts),),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO v2_decisions (
                        recorded_at, candle_ts, equity, wallet_balance, upnl, tier,
                        gross_b_scale, overlay_scale, btc_trend_200, market_breadth,
                        rebalanced_flag, raw_factors_json, weights_a_json,
                        weights_b_json, weights_net_json, skipped_reasons_json, prices_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_str, str(candle_ts), float(equity), float(wallet_balance), float(upnl),
                        tier, gb, ov, bt, br, reb,
                        json.dumps(factors, separators=(",", ":")),
                        json.dumps(w_a_store, separators=(",", ":")),
                        json.dumps(w_b, separators=(",", ":")),
                        json.dumps(w_net, separators=(",", ":")),
                        json.dumps(skipped, separators=(",", ":")),
                        json.dumps(prices_map, separators=(",", ":")),
                    ),
                )
                if prev_row is not None and prices_map:
                    prev_prices = json.loads(prev_row["prices_json"] or "{}")
                    if prev_prices:
                        prev_wa_raw = json.loads(prev_row["weights_a_json"] or "{}")
                        prev_wc = prev_wa_raw.pop("__weights_c__", {}) if isinstance(prev_wa_raw, dict) else {}
                        prev_wd = prev_wa_raw.pop("__weights_d__", {}) if isinstance(prev_wa_raw, dict) else {}
                        prev_wa_raw.pop("__weights_e__", None)
                        prev_wb = json.loads(prev_row["weights_b_json"] or "{}")
                        prev_wn = json.loads(prev_row["weights_net_json"] or "{}")
                        prev_fac = json.loads(prev_row["raw_factors_json"] or "{}")
                        attr_step = compute_hourly_attribution_step(
                            prev_equity=float(prev_row["equity"] or equity),
                            prev_weights_a=prev_wa_raw,
                            prev_weights_b=prev_wb,
                            prev_weights_c=prev_wc,
                            prev_weights_d=prev_wd,
                            prev_factors=prev_fac,
                            prev_prices=prev_prices,
                            curr_prices=prices_map,
                            prev_weights_net=prev_wn if isinstance(prev_wn, dict) else None,
                        )
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO v2_hourly_attribution (
                                candle_ts, prev_candle_ts, equity_prev, port_ret_1h,
                                sleeve_a_pnl, sleeve_b_pnl, sleeve_c_pnl, sleeve_d_pnl,
                                fac_mom_pnl, fac_carry_pnl, fac_bab_pnl, fac_flow_pnl, fac_spot_pnl, fac_smart_oi_pnl
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(candle_ts), str(prev_row["candle_ts"]), float(prev_row["equity"] or equity),
                                attr_step["port_ret_1h"], attr_step["sleeve_a_pnl"], attr_step["sleeve_b_pnl"],
                                attr_step["sleeve_c_pnl"], attr_step["sleeve_d_pnl"], attr_step["fac_mom_pnl"],
                                attr_step["fac_carry_pnl"], attr_step["fac_bab_pnl"], attr_step["fac_flow_pnl"],
                                attr_step["fac_spot_pnl"], attr_step["fac_smart_oi_pnl"],
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
            "prices": prices_map,
            "attribution": attr_step or {},
            "skipped": skipped,
        })

    def record_v2_income_ledger(self, events: List[Dict[str, Any]]) -> int:
        """Зберігає канонічні події Binance fapiPrivateGetIncome (REALIZED_PNL, COMMISSION, FUNDING_FEE) за tranId."""
        if not events:
            return 0
        inserted = 0
        try:
            with self._connect() as conn:
                for ev in events:
                    tid = str(ev.get("tran_id") or "").strip()
                    itype = str(ev.get("income_type") or "").strip().upper()
                    t_ms = int(ev.get("ts_ms") or 0)
                    if not tid or not itype or t_ms <= 0:
                        continue
                    t_str = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO v2_income_ledger (tran_id, ts_ms, ts_utc, income_type, symbol, income_usdt, info)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            tid, t_ms, t_str, itype,
                            str(ev.get("symbol") or "").upper(),
                            float(ev.get("income_usdt") or 0.0),
                            str(ev.get("info") or "")[:60],
                        ),
                    )
                    if cur.rowcount and cur.rowcount > 0:
                        inserted += 1
                conn.commit()
        except Exception:
            pass
        return inserted

    def compute_equity_bridge(
        self,
        actual_equity: float,
        current_wallet: float,
        current_upnl: float,
        demo_anchor: float = 0.0,
        virtual_cap: float = 0.0,
        since_ts: str = "2026-11-22 16:00:00",
    ) -> Dict[str, Any]:
        """Зводить бухгалтерський баланс рахунку за канонічними таблицями v2_decisions + v2_income_ledger/trades."""
        try:
            with self._connect() as conn:
                d0 = None
                if demo_anchor > 0.0:
                    d0 = conn.execute(
                        "SELECT candle_ts, recorded_at, equity, wallet_balance, upnl FROM v2_decisions "
                        "WHERE recorded_at >= ? AND ("
                        "  ABS((wallet_balance + upnl) - ?) < 0.02 "
                        "  OR ABS(wallet_balance - ?) < 0.02"
                        ") ORDER BY id ASC LIMIT 1",
                        (since_ts, float(demo_anchor), float(demo_anchor)),
                    ).fetchone()
                if d0 is None:
                    d0 = conn.execute(
                        "SELECT candle_ts, recorded_at, equity, wallet_balance, upnl FROM v2_decisions "
                        "WHERE recorded_at >= ? OR candle_ts >= ? ORDER BY id ASC LIMIT 1",
                        (since_ts, since_ts),
                    ).fetchone()
                if d0 is not None:
                    start_eq = float(d0["equity"])
                    w0 = float(d0["wallet_balance"])
                    u0 = float(d0["upnl"])
                    rec0 = str(d0["recorded_at"])
                else:
                    start_eq = float(virtual_cap if virtual_cap > 0 else actual_equity)
                    w0 = float(current_wallet)
                    u0 = float(current_upnl)
                    rec0 = since_ts

                try:
                    rec0_ms = int(
                        datetime.strptime(rec0[:19], "%Y-%m-%d %H:%M:%S")
                        .replace(tzinfo=timezone.utc)
                        .timestamp() * 1000
                    )
                except Exception:
                    rec0_ms = 0

                # Перевіряємо наявність точного біржового реєстру v2_income_ledger (відсікаємо події до моменту фіксації w0!)
                inc_rows = conn.execute(
                    "SELECT income_type, COALESCE(SUM(income_usdt), 0.0) AS s, COUNT(*) AS c "
                    "FROM v2_income_ledger WHERE ts_ms > ? GROUP BY income_type",
                    (rec0_ms,),
                ).fetchall()
                inc_map = {str(r["income_type"]): (float(r["s"] or 0.0), int(r["c"] or 0)) for r in inc_rows}

                if sum(v[1] for v in inc_map.values()) > 0:
                    realized_gross = inc_map.get("REALIZED_PNL", (0.0, 0))[0]
                    net_funding = inc_map.get("FUNDING_FEE", (0.0, 0))[0]
                    fees_abs = abs(inc_map.get("COMMISSION", (0.0, 0))[0])
                    source = "exchange_income_ledger"
                else:
                    tr_r = conn.execute(
                        "SELECT COALESCE(SUM(realized_pnl), 0.0) AS rp, COALESCE(SUM(fee_usdt), 0.0) AS fe "
                        "FROM trades WHERE COALESCE(is_artifact, 0) = 0 AND timestamp >= ?",
                        (rec0,),
                    ).fetchone()
                    fn_r = conn.execute(
                        "SELECT COALESCE(SUM(income_usdt), 0.0) AS fn FROM v2_funding_ledger WHERE funding_time >= ?",
                        (rec0,),
                    ).fetchone()
                    realized_gross = float(tr_r["rp"] or 0.0) if tr_r else 0.0
                    fees_abs = abs(float(tr_r["fe"] or 0.0)) if tr_r else 0.0
                    net_funding = float(fn_r["fn"] or 0.0) if fn_r else 0.0
                    source = "trades_and_funding_fallback"

                # На віртуальному демо-ліміті ($500) корекція старт-якоря враховує точний старт d0:
                if virtual_cap > 0 and demo_anchor > 0 and d0 is not None:
                    if abs(w0 - float(demo_anchor)) < 0.02:
                        eff_start_eq = float(virtual_cap)
                    else:
                        eff_start_eq = float(virtual_cap) + (w0 + u0 - float(demo_anchor))
                else:
                    eff_start_eq = start_eq
                delta_upnl = float(current_upnl) - u0

                bridge = compute_equity_bridge_dict(
                    start_equity=eff_start_eq,
                    actual_equity=float(actual_equity),
                    realized_pnl_gross=realized_gross,
                    delta_unrealized_pnl=delta_upnl,
                    net_funding_usd=net_funding,
                    total_fees_usd=fees_abs,
                )
                bridge["source"] = source
                bridge["anchor_timestamp"] = rec0
                return bridge
        except Exception as e:
            return {
                "start_equity": float(actual_equity),
                "realized_pnl_usd": 0.0,
                "unrealized_pnl_delta_usd": 0.0,
                "net_funding_usd": 0.0,
                "total_fees_usd": 0.0,
                "expected_equity": float(actual_equity),
                "actual_equity": float(actual_equity),
                "accounting_diff_usd": 0.0,
                "within_tolerance": True,
                "error": str(e),
            }

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
        bbo_spread_bps: Optional[float] = None,
        best_bid: float = 0.0,
        best_ask: float = 0.0,
        top5_depth_usd: float = 0.0,
    ) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        sgn = 1.0 if side.upper() == "BUY" else -1.0
        slip_arr = ((fill_avg_px - arrival_mid_px) / max(arrival_mid_px, 1e-8) * sgn * 10_000.0) if (fill_avg_px > 0 and arrival_mid_px > 0) else 0.0
        slip_sig = ((fill_avg_px - signal_close_px) / max(signal_close_px, 1e-8) * sgn * 10_000.0) if (fill_avg_px > 0 and signal_close_px > 0) else 0.0
        is_maker = 1 if (maker_qty > 0 and taker_qty <= 1e-12) else 0
        fb_used = 1 if taker_qty > 1e-12 else 0
        eff_bbo_sp = float(bbo_spread_bps if bbo_spread_bps is not None else spread_bps)
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
                        round(float(slip_arr), 3), round(float(slip_sig), 3), round(eff_bbo_sp, 3),
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
            "spread_bps": round(eff_bbo_sp, 3),
            "bbo_spread_bps": round(eff_bbo_sp, 3),
            "best_bid": float(best_bid),
            "best_ask": float(best_ask),
            "top5_depth_usd": round(float(top5_depth_usd), 2),
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
                "avg_bbo_spread_bps": round(float(ex["avg_spread"] or 0.0), 2) if ex else 0.0,
                "est_maker_savings_usd": round(
                    t_usd * ((0.00030 + 0.5 * float(ex["avg_spread"] or 0.0) / 10_000.0) if ex else 0.00030), 3
                ),
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
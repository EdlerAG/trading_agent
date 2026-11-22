import asyncio
import html
import io
import logging
import os
import signal
import zipfile
from typing import Any, Dict, List, Optional
import numpy as np

from app.core.config import settings
from app.core.http_client import http_pool
from app.core.memory_guard import memory_guard
from app.core.events import event_bus, EventType
from app.domain.interfaces import IService
from app.services.state_service import StateService
from app.services.database_service import DatabaseService
from app.cartridges.cartridge_loader import CartridgeLoaderService


class TelegramBotService(IService):
    """
    Інституційний пульт керування QuantCore (V2 Multi-Sleeve 32-Asset & V58) у Telegram:
      1. Компактний статус, радар факторів/рукавів (Sleeve A + Sleeve B) без спаму порожніми монетами.
      2. Пагінований пульт 32 валют (8 монет на сторінку) + перемикання режимів у 1 клік.
      3. Жива телеметрія Testnet V2 (/v2): Maker %, сліпедж (bps), фандінг, латентність та 1-клік вивантаження ZIP для testnet_reconcile.py (/export).
      4. Моніторинг парсера новин та захисту R5 Geo-Shock (/news).
      5. OTA прийом .joblib / .py / .zip та безпечний рестарт сервера.
    """

    __slots__ = (
        "_logger",
        "_state",
        "_db",
        "_cartridges",
        "_news",
        "_orchestrator",
        "_exchange",
        "_shadow_arena",
        "_last_update_id",
        "_synced",
    )

    PY_FILE_ROUTES = {
        "main.py": "",
        "config.py": "app/core",
        "memory_guard.py": "app/core",
        "events.py": "app/core",
        "security.py": "app/core",
        "http_client.py": "app/core",
        "enums.py": "app/domain",
        "schemas.py": "app/domain",
        "interfaces.py": "app/domain",
        "feature_pipe_v58.py": "app/cartridges",
        "v58_grand_master_cartridge.py": "app/cartridges",
        "v2_multi_sleeve_cartridge.py": "app/cartridges",
        "cartridge_loader.py": "app/cartridges",
        "state_service.py": "app/services",
        "online_adaptation_service.py": "app/services",
        "database_service.py": "app/services",
        "exchange_ccxt_service.py": "app/services",
        "market_data_service.py": "app/services",
        "currency_governor_service.py": "app/services",
        "risk_guard_service.py": "app/services",
        "ws_sentinel_service.py": "app/services",
        "news_ai_service.py": "app/services",
        "execution_service.py": "app/services",
        "shadow_arena_service.py": "app/services",
        "telegram_bot_service.py": "app/services",
        "service_registry.py": "app/services",
        "router.py": "app/api",
        "endpoints_telemetry.py": "app/api",
        "endpoints_control.py": "app/api",
        "endpoints_cartridge.py": "app/api",
        "portal_html.py": "app/web",
    }

    def __init__(
        self,
        logger: logging.Logger,
        state_service: StateService,
        db_service: DatabaseService,
        cartridge_service: CartridgeLoaderService,
        news_service: Any,
        orchestrator,
    ) -> None:
        self._logger = logger
        self._state = state_service
        self._db = db_service
        self._cartridges = cartridge_service
        self._news = news_service
        self._orchestrator = orchestrator
        self._exchange: Any = None
        self._shadow_arena: Any = None
        self._last_update_id: int = 0
        self._synced: bool = False

    def bind_extra_services(self, exchange_service: Any = None, shadow_arena: Any = None) -> None:
        self._exchange = exchange_service
        self._shadow_arena = shadow_arena

    @property
    def name(self) -> str:
        return "TelegramBotService"

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def _is_v2(self) -> bool:
        return (
            settings.CARTRIDGE_ENGINE in ("v2", "v3", "v4", "v5", "v6")
            or "v2" in str(self._cartridges.active_name).lower()
            or "v3" in str(self._cartridges.active_name).lower()
            or "v5" in str(self._cartridges.active_name).lower()
            or "v6" in str(self._cartridges.active_name).lower()
        )

    def _env_badge(self) -> str:
        return "🧪 TESTNET/DEMO" if settings.USE_DEMO_TRADING else "🔴 LIVE"

    # ==========================================
    # 1. КЛАВІАТУРИ TELEGRAM-ТЕРМІНАЛА
    # ==========================================
    def _main_keyboard(self) -> Dict[str, Any]:
        n_coins = len(self._state.coins)
        eng_lbl = "V2" if self._is_v2() else "V58"
        return {
            "inline_keyboard": [
                [
                    {"text": f"📊 Статус {eng_lbl}", "callback_data": "cmd_status"},
                    {"text": f"🧬 Радар ({n_coins})", "callback_data": "cmd_radar"},
                ],
                [
                    {"text": "🏆 Арена (6 Моделей)", "callback_data": "cmd_arena"},
                    {"text": "🔬 Телеметрія V3", "callback_data": "cmd_v2_stats"},
                ],
                [
                    {"text": "🛡️ Pre-Flight Чек", "callback_data": "cmd_preflight"},
                    {"text": "📰 Новини & Шок", "callback_data": "cmd_news"},
                ],
                [
                    {"text": f"🎛️ Валюти ({n_coins})", "callback_data": "coins_page:0"},
                    {"text": "⚙️ Профіль Плеча", "callback_data": "cmd_risk_menu"},
                ],
                [
                    {"text": "📈 Графік Альфи", "callback_data": "cmd_chart"},
                    {"text": "📜 Історія Угод", "callback_data": "cmd_trades"},
                ],
                [
                    {"text": "📥 ZIP Reconcile", "callback_data": "cmd_export_v2"},
                    {"text": "⚡ Перерахувати", "callback_data": "cmd_wakeup"},
                ],
                [
                    {"text": "⏸️ Пауза", "callback_data": "cmd_pause_menu"},
                    {"text": "▶️ Старт", "callback_data": "cmd_resume"},
                    {"text": "🔄 Рестарт", "callback_data": "cmd_restart_confirm"},
                ],
                [
                    {"text": "🧠 OTA & Моделі", "callback_data": "cmd_ota_info"},
                    {"text": "🚨 PANIC USDT", "callback_data": "cmd_panic_confirm"},
                    {"text": "🌐 Дашборд", "url": settings.DASHBOARD_URL},
                ],
            ]
        }

    def _coins_menu_keyboard(self, page: int = 0) -> Dict[str, Any]:
        mode_icons = {0: "🔴 OFF", 1: "🟢 AUTO", 2: "📈 LONG", 3: "📉 SHORT", 4: "🛡️ CORE"}
        items = list(self._state.coins.items())
        per_page = 8
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        chunk = items[page * per_page : (page + 1) * per_page]

        rows: List[List[Dict[str, str]]] = []
        for sym, c in chunk:
            m_lbl = mode_icons.get(c.mode, "🟢 AUTO")
            pos_tag = " •POS" if abs(c.current_pos_qty) > 0 else ""
            rows.append([
                {"text": f"{sym}: {m_lbl}{pos_tag}", "callback_data": f"coin_cycle:{sym}:{page}"},
            ])

        if total_pages > 1:
            nav: List[Dict[str, str]] = []
            if page > 0:
                nav.append({"text": "⬅️ Попер.", "callback_data": f"coins_page:{page - 1}"})
            nav.append({"text": f"Стор. {page + 1}/{total_pages}", "callback_data": f"coins_page:{page}"})
            if page < total_pages - 1:
                nav.append({"text": "Наст. ➡️", "callback_data": f"coins_page:{page + 1}"})
            rows.append(nav)

        rows.append([{"text": "🔙 Головне меню", "callback_data": "cmd_status"}])
        return {"inline_keyboard": rows}

    def _risk_menu_keyboard(self) -> Dict[str, Any]:
        cur_p = self._state.risk_profile
        cur_m = self._state.orchestrator_mode
        return {
            "inline_keyboard": [
                [{"text": f"{'✅ ' if cur_p=='CONSERVATIVE' else ''}🛡️ Conservative (1.6x Cap)", "callback_data": "risk:CONSERVATIVE"}],
                [{"text": f"{'✅ ' if cur_p=='OPTIMAL' else ''}⚖️ Optimal (2.4x Cap)", "callback_data": "risk:OPTIMAL"}],
                [{"text": f"{'✅ ' if cur_p=='AGGRESSIVE' else ''}🔥 Aggressive (3.2x Cap)", "callback_data": "risk:AGGRESSIVE"}],
                [{"text": f"{'✅ ' if cur_p=='OVERDRIVE' else ''}🚀 Overdrive (3.5x Cap)", "callback_data": "risk:OVERDRIVE"}],
                [{"text": f"🧬 Режим: {cur_m} (Змінити)", "callback_data": "mode_toggle"}],
                [{"text": "🔙 Головне меню", "callback_data": "cmd_status"}],
            ]
        }

    # ==========================================
    # 2. БАЗОВІ МЕТОДИ TELEGRAM API
    # ==========================================
    async def _api(self, method: str, payload: Dict[str, Any], timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        if not settings.TELEGRAM_TOKEN:
            return None
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/{method}"
        try:
            resp = await http_pool.get().post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    async def send_alert(self, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return
        safe_txt = text[:4050] if len(text) > 4050 else text
        await self._api("sendMessage", {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": safe_txt,
            "parse_mode": "HTML",
            "reply_markup": reply_markup or self._main_keyboard(),
            "disable_web_page_preview": True,
        })

    async def send_document(self, file_path: str, caption: str = "") -> None:
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID or not os.path.exists(file_path):
            return
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendDocument"
        try:
            with open(file_path, "rb") as f:
                files = {"document": (os.path.basename(file_path), f)}
                data = {"chat_id": settings.TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
                await http_pool.get().post(url, data=data, files=files, timeout=35.0)
        except Exception as e:
            self._logger.error(f"Помилка відправки документа в Telegram: {e}")

    async def _download_tg_file(self, file_id: str) -> Optional[bytes]:
        f_info = await self._api("getFile", {"file_id": file_id})
        f_path = (f_info.get("result") or {}).get("file_path") if isinstance(f_info, dict) else None
        if not f_path:
            return None
        dl_url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_TOKEN}/{f_path}"
        try:
            resp = await http_pool.get().get(dl_url, timeout=45.0)
            return resp.content if resp.status_code == 200 else None
        except Exception:
            return None

    # ==========================================
    # 3. ФОРМУВАННЯ ЗВІТІВ ТА ГРАФІКІВ
    # ==========================================
    def _build_status_text(self) -> str:
        t = self._state.latest_telemetry
        eq = float(t.get("total_equity", 0.0))
        bal = float(t.get("wallet_balance", 0.0))
        upnl = float(t.get("unrealized_pnl", 0.0))
        gross = float(t.get("gross_leverage", 0.0))
        net_lev = float(t.get("net_leverage", 0.0))
        leader = t.get("top_leader", "BTCUSDT")
        ram_mb = memory_guard.get_rss_mb()

        status_str = "⏸️ НА ПАУЗІ" if self._state.is_paused else "🟢 ОНЛАЙН (Zero-Idle)"
        radar = self._state.get_coins_radar_list()
        active_pos = [c for c in radar if abs(c["current_pos_qty"]) > 0]
        active_pos.sort(key=lambda x: -x["notional_usdt"])

        coin_lines: List[str] = []
        if active_pos:
            for c in active_pos[:16]:
                sym = c["symbol"]
                qty = c["current_pos_qty"]
                dir_ic = "🟢 L" if qty > 0 else "🔴 S"
                bk = c.get("sleeve_book") or ""
                bk_tag = f" [{bk.replace('SLEEVE_', '')}]" if bk and bk not in ("V2_MOMENTUM", "FLAT") else ""
                coin_lines.append(
                    f"• <b>{sym}</b>{bk_tag}: {dir_ic} <code>${c['notional_usdt']:,.0f}</code> "
                    f"(<code>{c['target_weight']:+.2f}x</code>) | PnL: <b>{c['unrealized_pnl']:+.2f}$</b>"
                )
            if len(active_pos) > 16:
                coin_lines.append(f"<i>... ще {len(active_pos) - 16} відкритих позицій</i>")
        else:
            top_cands = sorted(radar, key=lambda x: -abs(x["alpha_score"]))[:6]
            coin_lines.append("⚪ <b>100% КЕШ (USDT)</b> — відкритих позицій немає.")
            for c in top_cands:
                coin_lines.append(
                    f"  ▫️ <code>{c['symbol']:<10}</code> ${c['price']:,.2f} | Score: <code>{c['alpha_score']:+.2f}</code>"
                )

        title = "QUANTCORE V2 MULTI-SLEEVE (1H)" if self._is_v2() else "QUANTCORE V58.0 PURE SOTA"
        sleeve_line = ""
        if self._is_v2():
            tier_n = int(t.get("tier", 1) or 1)
            ag = float(t.get("a_gross", 0.0) or 0.0)
            bg = float(t.get("b_gross", 0.0) or 0.0)
            bt = float(t.get("btc_trend", 0.0) or 0.0) * 100.0
            sleeve_line = (
                f"• <b>Рукави (Tier {tier_n}):</b> A=<code>{ag:.2f}x</code> | B=<code>{bg:.2f}x</code> | BTC200=<code>{bt:+.1f}%</code>\n"
            )

        return (
            f"👑 <b>{title}</b> [{self._env_badge()}]\n"
            f"═══════════════════════\n"
            f"• <b>Статус:</b> {status_str} | TF: <code>{settings.CANDLE_TIMEFRAME}</code>\n"
            f"• <b>Картридж:</b> <code>{self._cartridges.active_name}</code> ({len(radar)} пар)\n"
            f"• <b>Сумарний Equity:</b> <b>${eq:,.2f} USDT</b> (uPnL: <b>{upnl:+.2f}$</b>)\n"
            f"• <b>Маржа:</b> <code>${bal:,.2f}</code> | Gross: <b>{gross:.2f}x</b> (Net: <code>{net_lev:+.2f}x</code>)\n"
            + sleeve_line
            + f"• <b>Лідер:</b> <code>{leader}</code> | RAM: <code>{ram_mb:.1f} MB</code>\n"
            f"───────────────────────\n"
            + "\n".join(coin_lines)
            + f"\n═══════════════════════\n"
            f"🕯 <i>Свічка: {t.get('timestamp', 'Очікування')} UTC</i>"
        )

    def _build_radar_text(self) -> str:
        radar = self._state.get_coins_radar_list()
        t = self._state.latest_telemetry
        geo_status = "🚨 АКТИВОВАНО" if t.get("geo_shock_active") else "🛡️ Норма"
        sorted_r = sorted(radar, key=lambda x: -float(x.get("alpha_score", 0.0)))
        top_longs = sorted_r[:6]
        top_shorts = list(reversed(sorted_r[-6:]))

        lines = [
            f"🧬 <b>РАДАР КРОС-СЕКЦІЇ ({len(radar)} ВАЛЮТ)</b>",
            f"═══════════════════════",
            f"• <b>Breadth:</b> <code>{float(t.get('market_breadth', 0.0))*100:.1f}%</code> | "
            f"<b>BTC vs EMA200:</b> <code>{float(t.get('btc_trend', 0.0))*100:+.2f}%</code>",
            f"• <b>Новини:</b> <code>{float(t.get('news_sentiment', 0.0)):+.2f}</code> | <b>R5 Захист:</b> {geo_status}",
            f"───────────────────────",
            f"🟢 <b>ТОП-6 ЛІДЕРІВ (LONG КАНДИДАТИ):</b>",
        ]
        for c in top_longs:
            f = c.get("factors") or {}
            fac_s = f"M:{f.get('z_mom',0):+.1f} C:{f.get('z_carry',0):+.1f} B:{f.get('z_bab',0):+.1f}" if f else f"MWU:{c['effective_weight']:.2f}x"
            lines.append(
                f"  • <b>{c['symbol']}</b>: Score <code>{c['alpha_score']:+.2f}</code> | W: <b>{c['target_weight']:+.2f}x</b> ({fac_s})"
            )

        lines.append(f"───────────────────────\n🔴 <b>ТОП-6 АУТСАЙДЕРІВ (SHORT КАНДИДАТИ):</b>")
        for c in top_shorts:
            f = c.get("factors") or {}
            fac_s = f"M:{f.get('z_mom',0):+.1f} C:{f.get('z_carry',0):+.1f} B:{f.get('z_bab',0):+.1f}" if f else f"MWU:{c['effective_weight']:.2f}x"
            lines.append(
                f"  • <b>{c['symbol']}</b>: Score <code>{c['alpha_score']:+.2f}</code> | W: <b>{c['target_weight']:+.2f}x</b> ({fac_s})"
            )
        return "\n".join(lines)

    def _build_v2_telemetry_text(self) -> str:
        s = self._db.get_v2_analytics_summary(days=30)
        if not s.get("ok"):
            return "⚠️ Телеметрія V2 ще порожня."
        ls = s.get("latest_sleeves") or {}
        wa = ls.get("weights_a") or {}
        wb = ls.get("weights_b") or {}
        n_long_b = sum(1 for v in wb.values() if float(v) > 0)
        n_short_b = sum(1 for v in wb.values() if float(v) < 0)

        return (
            f"🔬 <b>ТЕЛЕМЕТРІЯ TESTNET V2 (30 ДНІВ)</b>\n"
            f"═══════════════════════\n"
            f"• <b>Зрізів свічок (v2_decisions):</b> <code>{s.get('decisions_logged', 0)}</code> (ребалансів: <b>{s.get('rebalances_logged', 0)}</b>)\n"
            f"• <b>Ордерів виконано:</b> <b>{s.get('orders_filled', 0)}</b> / <code>{s.get('orders_total', 0)}</code>\n"
            f"• <b>Частка Maker-філів:</b> <b>{s.get('maker_fill_pct', 0.0):.1f}%</b> (ціль моделі: <code>70.0%</code>)\n"
            f"• <b>Сліпедж vs Arrival:</b> <code>{s.get('avg_slippage_arrival_bps', 0.0):+.2f} bps</code>\n"
            f"• <b>Сліпедж vs Signal Close:</b> <code>{s.get('avg_slippage_signal_bps', 0.0):+.2f} bps</code>\n"
            f"• <b>Середній спред BBO:</b> <code>{s.get('avg_spread_bps', 0.0):.2f} bps</code> | Латентність: <code>{s.get('avg_latency_ms', 0.0):.0f} мс</code>\n"
            f"• <b>Комісії біржі:</b> <code>${s.get('v2_fees_usdt', 0.0):.3f}</code>\n"
            f"• <b>Живий фандінг ({s.get('funding_events', 0)} виплат):</b> <b>{s.get('net_funding_income_usdt', 0.0):+.3f} USDT</b>\n"
            f"───────────────────────\n"
            f"• <b>Книга зараз:</b> Tier <code>{ls.get('tier', 1)}</code> | Sleeve A: <code>{len(wa)}</code> мейджорів | "
            f"Sleeve B: <code>{n_long_b}L / {n_short_b}S</code> (Gross scale: <code>{ls.get('gross_b_scale', 0.0):.2f}x</code>)\n"
            f"📥 <i>Натисніть «📥 ZIP Reconcile», щоб вивантажити повний пакет БД + JSONL для локальної звірки testnet_reconcile.py.</i>"
        )

    def _build_news_text(self) -> str:
        info = self._news.get_cached_info()
        headlines = info.get("headlines") or []
        sent = float(info.get("macro_sentiment", 0.0))
        prob = float(info.get("geo_shock_prob", 0.0))
        mode = info.get("engine_mode", "idle")
        srcs = info.get("sources_ok", 0)
        hl_lines = [f"• {html.escape(h)}" for h in headlines[:6]] or ["<i>Заголовки ще не завантажені (натисніть Оновити).</i>"]
        bias = info.get("coin_bias") or {}
        bias_str = ", ".join(f"{k}:{v:+.2f}" for k, v in list(bias.items())[:8]) if bias else "Нейтрально"

        return (
            f"📰 <b>НОВИННИЙ ІНТЕЛЕКТ ТА ЗАХИСТ R5</b>\n"
            f"═══════════════════════\n"
            f"• <b>Макро-сентимент:</b> <b>{sent:+.2f}</b> | Джерел RSS: <code>{srcs}/5</code>\n"
            f"• <b>Ймовірність Geo-Shock:</b> <b>{prob:.0%}</b> ({'🚨 ШОК!' if prob > 0.75 else '🛡️ Безпечно'})\n"
            f"• <b>Аналізатор:</b> <code>{html.escape(str(mode))}</code>\n"
            f"• <b>Імпульси монет:</b> <code>{html.escape(bias_str)}</code>\n"
            f"───────────────────────\n"
            + "\n".join(hl_lines)
        )

    async def _send_alpha_chart(self) -> None:
        res = await asyncio.to_thread(self._db.get_equity_series_and_kpis, 30)
        chart = res.get("chart", {})
        kpis = res.get("kpis", {})
        times = chart.get("times", [])
        if len(times) < 2:
            await self.send_alert("📉 Недостатньо історичних точок для графіка (потрібно мінімум 2 свічки).")
            return

        eng_lbl = (
            "QuantCore V5.0 All-Regime"
            if settings.CARTRIDGE_ENGINE == "v5"
            else ("QuantCore V4.0 Apex" if settings.CARTRIDGE_ENGINE == "v4" else ("QuantCore V2/V3" if self._is_v2() else "QuantCore V58.0"))
        )

        def _render_png() -> bytes:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.8, 5.9), sharex=True, gridspec_kw={"height_ratios": [2.6, 1.0]})
            fig.patch.set_facecolor("#050914")
            x_idx = np.arange(len(times))

            for ax in (ax1, ax2):
                ax.set_facecolor("#0b1326")
                ax.tick_params(colors="#94a3b8", labelsize=8)
                ax.grid(True, linestyle="--", alpha=0.14, color="#64748b")
                for sp in ax.spines.values():
                    sp.set_color("#1e293b")

            eq_r = chart["equity_ret_pct"]
            btc_r = chart["btc_ret_pct"]
            dd_r = chart["drawdown_pct"]

            ax1.axhline(0.0, color="#334155", linewidth=0.9, linestyle=":")
            ax1.plot(x_idx, eq_r, color="#10b981", linewidth=2.4, label=f"{eng_lbl} ({kpis.get('total_pnl_pct', 0):+.2f}%)")
            ax1.fill_between(x_idx, eq_r, 0, where=(np.asarray(eq_r) >= 0), color="#10b981", alpha=0.12)
            ax1.plot(x_idx, btc_r, color="#f59e0b", linewidth=1.35, linestyle="--", label=f"BTC B&H ({kpis.get('btc_bh_pct', 0):+.2f}%)")
            ax1.set_ylabel("Дохідність (%)", color="#cbd5e1", fontsize=9)
            ax1.legend(loc="upper left", facecolor="#070b14", edgecolor="#334155", labelcolor="white", fontsize=8.5)
            ax1.set_title(f"{eng_lbl.upper()}: EQUITY vs BTC", color="#f8fafc", fontsize=10.5, weight="bold")

            ax2.plot(x_idx, dd_r, color="#ef4444", linewidth=1.3, label="Drawdown %")
            ax2.fill_between(x_idx, dd_r, 0, color="#ef4444", alpha=0.18)
            ax2.set_ylabel("MaxDD (%)", color="#cbd5e1", fontsize=8.5)

            step = max(1, len(times) // 6)
            ax2.set_xticks(x_idx[::step])
            ax2.set_xticklabels([times[i][5:] for i in range(0, len(times), step)], rotation=15)
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor())
            plt.close(fig)
            raw = buf.getvalue()
            buf.close()
            return raw

        png_bytes = await asyncio.to_thread(_render_png)
        memory_guard.trim_ram()

        url = f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendPhoto"
        files = {"photo": ("quantcore_equity.png", png_bytes, "image/png")}
        caption = (
            f"📈 <b>Звіт {eng_lbl}:</b>\n"
            f"• Equity: <b>${kpis.get('latest_equity', 0):,.2f}</b> (<b>{kpis.get('total_pnl_pct', 0):+.2f}%</b>)\n"
            f"• Чиста Альфа vs BTC: <b>{kpis.get('alpha_vs_btc_pct', 0):+.2f}%</b>\n"
            f"• Sharpe: <b>{kpis.get('sharpe_ratio', 0):.2f}</b> | Calmar: <b>{kpis.get('calmar_ratio', 0):.2f}</b> | MaxDD: <b>{kpis.get('max_drawdown_pct', 0):.2f}%</b>"
        )
        data = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
        }
        try:
            await http_pool.get().post(url, data=data, files=files, timeout=25.0)
        except Exception:
            pass

    # ==========================================
    # 4. ПРИЙОМ ПРОШИВОК (.JOBLIB / .PY / .ZIP) ТА РЕСТАРТ СЕРВЕРА
    # ==========================================
    async def trigger_graceful_server_restart(self) -> None:
        self._state.save_snapshot()
        await self._db.shutdown()
        await asyncio.sleep(0.6)
        os.kill(os.getpid(), signal.SIGTERM)

    async def _handle_uploaded_document(self, doc: Dict[str, Any], caption: str) -> None:
        fname = str(doc.get("file_name") or "").strip()
        file_id = str(doc.get("file_id") or "")
        if not fname or not file_id:
            return

        if fname.endswith(".joblib"):
            await self.send_alert(f"⏳ <i>Завантаження ШІ-картриджа <code>{html.escape(fname)}</code>...</i>")
            raw_bytes = await self._download_tg_file(file_id)
            if not raw_bytes:
                await self.send_alert("❌ Не вдалося завантажити файл із серверів Telegram.")
                return
            try:
                info = await self._cartridges.hot_swap_from_bytes(fname, raw_bytes)
                self._state.sync_supported_symbols(info["supported_symbols"])
                await self.send_alert(
                    f"🚀 <b>ШІ-Картридж успішно оновлено (Hot-Swap)!</b>\n"
                    f"═══════════════════════\n"
                    f"• <b>Файл:</b> <code>{info['active_cartridge']}</code>\n"
                    f"• <b>Архітектура:</b> <code>{info['architecture']}</code>\n"
                    f"• <b>Валют у кошику:</b> <code>{len(info['supported_symbols'])}</code>\n"
                    f"• <b>RAM:</b> <code>{info.get('ram_after_mb', memory_guard.get_rss_mb()):.1f} MB</code>"
                )
            except Exception as e:
                await self.send_alert(f"❌ <b>Відхилено пошкоджений картридж:</b>\n<code>{html.escape(str(e))}</code>")
            return

        if fname.endswith(".py") or fname.endswith(".zip"):
            raw_bytes = await self._download_tg_file(file_id)
            if not raw_bytes:
                await self.send_alert("❌ Помилка завантаження файлу з Telegram.")
                return

            restart_kb = {
                "inline_keyboard": [
                    [{"text": "🔄 Перезавантажити сервер зараз (3 сек)", "callback_data": "cmd_restart_exec"}],
                    [{"text": "🔙 Застосувати пізніше", "callback_data": "cmd_status"}],
                ]
            }

            base_real = os.path.realpath(settings.BASE_DIR)
            if fname.endswith(".py"):
                safe_fname = os.path.basename(fname.replace("\\", "/"))
                sub_dir = self.PY_FILE_ROUTES.get(safe_fname, caption.strip() if caption else "")
                target_dir = os.path.realpath(os.path.join(base_real, sub_dir) if sub_dir else base_real)
                target_path = os.path.realpath(os.path.join(target_dir, safe_fname))
                if os.path.commonpath([base_real, target_path]) != base_real:
                    await self.send_alert("❌ Відхилено: неприпустимий шлях файлу.")
                    return
                os.makedirs(target_dir, exist_ok=True)
                tmp_path = target_path + ".tmp"
                with open(tmp_path, "wb") as f:
                    f.write(raw_bytes)
                os.replace(tmp_path, target_path)
                rel_p = os.path.relpath(target_path, settings.BASE_DIR)
                await self.send_alert(
                    f"✅ <b>Модуль <code>{html.escape(rel_p)}</code> ({len(raw_bytes)} байт) оновлено!</b>",
                    reply_markup=restart_kb,
                )
            elif fname.endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                        extracted = []
                        for member in zf.namelist():
                            norm_m = member.replace("\\", "/")
                            dest_real = os.path.realpath(os.path.join(base_real, norm_m))
                            if os.path.commonpath([base_real, dest_real]) != base_real or ".env" in norm_m.lower():
                                continue
                            zf.extract(member, base_real)
                            extracted.append(member)
                    await self.send_alert(
                        f"📦 <b>ZIP-патч розпаковано ({len(extracted)} файлів)!</b>",
                        reply_markup=restart_kb,
                    )
                except Exception as ze:
                    await self.send_alert(f"❌ Помилка розпакування ZIP: <code>{html.escape(str(ze))}</code>")

    # ==========================================
    # 5. ОБРОБКА КОМАНД ТА INLINE-КНОПОК
    # ==========================================
    async def _handle_command_or_callback(self, cmd: str) -> None:
        cmd = cmd.strip()

        if cmd in ("/start", "/status", "cmd_status"):
            await self.send_alert(self._build_status_text())

        elif cmd in ("/radar", "cmd_radar"):
            await self.send_alert(self._build_radar_text())

        elif cmd in ("/arena", "cmd_arena"):
            if self._shadow_arena is None:
                await self.send_alert("⚠️ Shadow Arena вимкнена.")
            else:
                board = self._shadow_arena.get_leaderboard()
                medals = {1: "🥇", 2: "🥈", 3: "🥉"}
                lines = [
                    "🏆 <b>SHADOW ARENA — ЖИВИЙ ЧЕМПІОНАТ 6 МОДЕЛЕЙ</b>",
                    "═══════════════════════",
                ]
                for r in board:
                    m_ic = medals.get(r["rank"], f"#{r['rank']}")
                    lines.append(
                        f"{m_ic} <b>{r['bot_id']}</b> (Старт: <code>${r['initial_equity']:.0f}</code>)\n"
                        f"   Eq: <b>${r['equity']:,.2f}</b> (<b>{r['return_pct']:+.2f}%</b>) | DD: <code>{r['max_dd_pct']:.2f}%</code>\n"
                        f"   Gross: <code>{r['gross_lev']:.2f}x</code> | Поз: <code>{r['active_positions']}</code> | Угод: <code>{r['trades_count']}</code>"
                    )
                await self.send_alert("\n".join(lines))

        elif cmd in ("/preflight", "cmd_preflight"):
            if self._exchange is not None and hasattr(self._exchange, "run_preflight_diagnostics"):
                pf = await self._exchange.run_preflight_diagnostics()
                cap_s = f"${pf['virtual_equity_cap']:.0f} (Симуляція стартового депозиту!)" if (pf["demo_trading_mode"] and pf["virtual_equity_cap"] > 0) else "Вимкнено (100% гаманця)"
                await self.send_alert(
                    "🛡️ <b>PRE-FLIGHT САМОДІАГНОСТИКА ПЕРЕД СТАРТОМ</b>\n"
                    "═══════════════════════\n"
                    f"• <b>Режим біржі:</b> {'🧪 DEMO / TESTNET' if pf['demo_trading_mode'] else '🔴 LIVE REAL MONEY'}\n"
                    f"• <b>Віртуальна стеля (VIRTUAL_EQUITY_CAP):</b> <code>{cap_s}</code>\n"
                    f"• <b>Зв'язок з Binance API:</b> {'✅ OK' if pf['exchange_reachable'] else '⚠️ Немає ключів'}\n"
                    f"• <b>One-Way Mode (hedged=False):</b> {'✅ OK' if pf['one_way_mode_ok'] else '⚠️ Перевірте режим хеджування'}\n"
                    f"• <b>Ядро та таймфрейм:</b> <code>{pf['cartridge_engine'].upper()} ({pf['candle_timeframe']}, {pf['symbols_count']} пар)</code>\n"
                    f"• <b>ML Ансамбль V3 (.joblib):</b> {'✅ Завантажено' if pf['ml_ranker_v3_present'] else 'ℹ️ Лінійний фолбек'}\n"
                    f"• <b>Баланс гаманця USDT:</b> <b>${pf['usdt_wallet_balance']:,.2f}</b>\n"
                    f"• <b>BNB (знижка -10% комісій):</b> <code>{pf['bnb_fee_burn_balance']:.4f} BNB</code>\n"
                    f"• <b>BFUSD (дохідна застава 5-8% APR):</b> <code>${pf['bfusd_collateral_balance']:,.2f}</code> (Multi-Asset: {'✅' if pf['multi_assets_margin'] else 'OFF'})\n"
                    f"• <b>Споживання RAM:</b> <code>{pf['ram_rss_mb']:.1f} MB / 420 MB</code>"
                )
            else:
                await self.send_alert("⚠️ Сервіс шлюзу ще ініціалізується.")

        elif cmd in ("/v2", "cmd_v2_stats"):
            kb = {
                "inline_keyboard": [
                    [{"text": "📥 Завантажити ZIP для Reconcile", "callback_data": "cmd_export_v2"}],
                    [{"text": "🔙 Головне меню", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert(self._build_v2_telemetry_text(), reply_markup=kb)

        elif cmd in ("/export", "cmd_export_v2"):
            zip_p = await asyncio.to_thread(self._db.export_v2_research_zip)
            if zip_p and os.path.exists(zip_p):
                await self.send_document(
                    zip_p,
                    caption="📦 <b>Пакет телеметрії Testnet V2</b> (SQLite + JSONL + LiveState) для <code>python -m quant_v2.testnet_reconcile</code>",
                )
            else:
                await self.send_alert("⚠️ Не вдалося створити ZIP-архів телеметрії.")

        elif cmd in ("/news", "cmd_news"):
            kb = {
                "inline_keyboard": [
                    [{"text": "🔄 Оновити RSS + ШІ зараз", "callback_data": "cmd_news_refresh"}],
                    [{"text": "🔙 Головне меню", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert(self._build_news_text(), reply_markup=kb)

        elif cmd == "cmd_news_refresh":
            await self._news.fetch_market_intelligence(force_refresh=True)
            await self.send_alert(self._build_news_text())

        elif cmd in ("/coins", "cmd_coins_menu") or cmd.startswith("coins_page:"):
            pg = int(cmd.split(":", 1)[1]) if ":" in cmd else 0
            await self.send_alert(
                "🎛️ <b>ПУЛЬТ КЕРУВАННЯ ВАЛЮТАМИ:</b>\n"
                "Натисніть на валюту, щоб перемкнути режим:\n"
                "<code>🟢 AUTO ➔ 📈 LONG ➔ 📉 SHORT ➔ 🔴 OFF</code>",
                reply_markup=self._coins_menu_keyboard(page=pg),
            )

        elif cmd.startswith("coin_cycle:"):
            parts = cmd.split(":")
            sym = parts[1]
            pg = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            c = self._state.coins.get(sym)
            if c:
                next_map = {1: 2, 2: 3, 3: 0, 0: 1, 4: 1}
                new_m = next_map.get(c.mode, 1)
                self._state.update_coin_settings(symbol=sym, enabled=(new_m != 0), mode=new_m)
                await event_bus.publish(EventType.COIN_CONFIG_CHANGED, {"symbol": sym}, wake_engine=True)
            await self.send_alert(f"🎛️ <b>{sym}: режим оновлено!</b>", reply_markup=self._coins_menu_keyboard(page=pg))

        elif cmd in ("/risk", "cmd_risk_menu"):
            await self.send_alert("⚙️ <b>ОБЕРІТЬ ПРОФІЛЬ РИЗИКУ ТА РЕЖИМ ЯДРА:</b>", reply_markup=self._risk_menu_keyboard())

        elif cmd.startswith("risk:"):
            prof = cmd.split(":", 1)[1]
            self._state.set_risk_profile(prof)
            await event_bus.publish(EventType.RISK_PROFILE_CHANGED, {"risk_profile": prof}, wake_engine=True)
            await self.send_alert(
                f"✅ <b>Профіль змінено на {prof} (Max {self._state.max_portfolio_lev:.1f}x)!</b>",
                reply_markup=self._risk_menu_keyboard(),
            )

        elif cmd == "mode_toggle":
            new_om = "SOLO_MAX" if self._state.orchestrator_mode == "PORTFOLIO_SYNERGY" else "PORTFOLIO_SYNERGY"
            self._state.set_risk_profile(self._state.risk_profile, orchestrator_mode=new_om)
            await event_bus.publish(EventType.RISK_PROFILE_CHANGED, {"orchestrator_mode": new_om}, wake_engine=True)
            await self.send_alert(f"🧬 <b>Режим оркестратора: {new_om}!</b>", reply_markup=self._risk_menu_keyboard())

        elif cmd in ("/chart", "cmd_chart"):
            await self._send_alpha_chart()

        elif cmd in ("/trades", "cmd_trades"):
            trades = self._db.get_recent_trades(limit=10)
            if not trades:
                await self.send_alert("📜 Журнал угод поки порожній.")
            else:
                lines = ["📜 <b>ОСТАННІ ВИКОНАНІ ОПЕРАЦІЇ:</b>\n═══════════════════════"]
                for t in trades:
                    ic = "🟢 BUY" if t["side"] == "BUY" else "🔴 SELL"
                    pnl_s = f" | PnL: <b>{t['net_pnl']:+.2f}$</b>" if t["pnl"] != 0 else ""
                    lines.append(
                        f"• <code>{t['time'][5:16]}</code> | <b>{t['symbol']}</b> {ic} <code>{t['amount']}</code> @ <code>${t['price']:,.2f}</code>{pnl_s}\n"
                        f"  <i>{html.escape(t['note'])}</i>"
                    )
                await self.send_alert("\n".join(lines))

        elif cmd in ("/ota", "cmd_ota_info"):
            meta = self._cartridges.get_metadata()
            res = memory_guard.get_resource_telemetry(meta["active_cartridge"])
            kb = {
                "inline_keyboard": [
                    [{"text": "📥 Пакет телеметрії V2 (.zip)", "callback_data": "cmd_export_v2"}],
                    [{"text": "📦 Завантажити бекап БД (.db)", "callback_data": "cmd_dl_db"}],
                    [{"text": "⏪ Відкотити на попередню модель", "callback_data": "cmd_rollback_model"}],
                    [{"text": "🔄 Перезавантажити сервер", "callback_data": "cmd_restart_confirm"}],
                    [{"text": "🔙 Головне меню", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert(
                f"🧠 <b>КАРТРИДЖІ МОДЕЛЕЙ ТА OTA-ПУЛЬТ</b>\n"
                f"═══════════════════════\n"
                f"• <b>Активне ядро:</b> <code>{meta['active_cartridge']}</code> ({meta['architecture']})\n"
                f"• <b>Резервна модель:</b> <code>{meta['previous_cartridge'] or '—'}</code>\n"
                f"• <b>RAM (VmRSS):</b> <code>{res['ram_rss_mb']:.1f} MB / 420 MB</code>\n"
                f"• <b>Диск (storage/):</b> <code>{res['storage_used_mb']:.1f} MB / {res['storage_limit_mb']} MB</code>\n"
                f"───────────────────────\n"
                f"Надішліть у чат <code>*.joblib</code> (Hot-Swap) або <code>*.py</code> / <code>*.zip</code> для OTA-оновлення без SSH.",
                reply_markup=kb,
            )

        elif cmd == "cmd_rollback_model":
            try:
                info = await self._cartridges.rollback_to_previous()
                self._state.sync_supported_symbols(info["supported_symbols"])
                await self.send_alert(f"⏪ <b>Відкат виконано!</b> Активна модель: <code>{info['active_cartridge']}</code>")
            except Exception as e:
                await self.send_alert(f"⚠️ Неможливо виконати відкат: {html.escape(str(e))}")

        elif cmd == "cmd_dl_db":
            b_path = self._db.cleanup_old_records_and_backup()
            if b_path:
                await self.send_document(b_path, caption="📦 Актуальний зріз бази даних QuantCore")

        elif cmd == "cmd_wakeup":
            await event_bus.publish(EventType.FORCE_RECALC, {}, wake_engine=True)
            await self.send_alert("⚡ <b>Сигнал миттєвого перерахунку відправлено!</b>")

        elif cmd == "cmd_pause_menu":
            kb = {
                "inline_keyboard": [
                    [{"text": "⏸️ 1 год", "callback_data": "pause:1"}, {"text": "⏸️ 8 год", "callback_data": "pause:8"}],
                    [{"text": "⏸️ 24 год", "callback_data": "pause:24"}, {"text": "🛑 Безстроково", "callback_data": "pause:0"}],
                    [{"text": "🔙 Назад", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert("⏸️ <b>Оберіть тривалість паузи:</b>", reply_markup=kb)

        elif cmd.startswith("pause:"):
            hrs = float(cmd.split(":")[1])
            self._state.set_pause_state(paused=True, hours=hrs if hrs > 0 else None)
            await self.send_alert(f"⏸️ <b>Торгівлю поставлено на паузу</b> ({f'{hrs:.0f} год' if hrs > 0 else 'безстроково'}).")

        elif cmd in ("/resume", "cmd_resume"):
            self._state.set_pause_state(paused=False)
            event_bus.trigger_wakeup()
            await self.send_alert("▶️ <b>Торгівлю відновлено!</b> Оркестратор активний.")

        elif cmd in ("/restart", "cmd_restart_confirm"):
            kb = {
                "inline_keyboard": [
                    [{"text": "✅ ТАК, ПЕРЕЗАВАНТАЖИТИ СЕРВЕР", "callback_data": "cmd_restart_exec"}],
                    [{"text": "❌ Скасувати", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert(
                "🔄 <b>ПІДТВЕРДЖЕННЯ ПЕРЕЗАПУСКУ СЕРВЕРА</b>\n\n"
                "Усі стани та SQLite WAL будуть збережені, а служба <code>systemd</code> підніме оновлений процес за 3 секунди.",
                reply_markup=kb,
            )

        elif cmd == "cmd_restart_exec":
            await self.send_alert("🔄 <b>Перезавантаження сервера...</b> Через 3–5 секунд бот знову онлайн!")
            asyncio.create_task(self.trigger_graceful_server_restart())

        elif cmd == "cmd_panic_confirm":
            kb = {
                "inline_keyboard": [
                    [{"text": "🚨 ТАК, ЛІКВІДУВАТИ ВСЕ В USDT", "callback_data": "cmd_panic_exec"}],
                    [{"text": "❌ Скасувати", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert(
                f"⚠️ <b>ЕКСТРЕНИЙ ВИХІД У КЕШ (PANIC CLOSE)!</b>\n\n"
                f"Усі відкриті позиції ({len(self._state.coins)} монет під наглядом) будуть закриті за ринком, а торгівля стане на паузу.",
                reply_markup=kb,
            )

        elif cmd == "cmd_panic_exec":
            self._state.set_pause_state(paused=True)
            await self._orchestrator.emergency_close_all_positions()

        else:
            if settings.GEMINI_API_KEY and len(cmd) > 1:
                await self._handle_gemini_ai_query(cmd)
            else:
                await self.send_alert(
                    f"❓ Команда: <code>{html.escape(cmd)}</code>\n"
                    f"Доступні: /start, /status, /radar, /v2, /export, /news, /coins, /chart, /trades"
                )

    async def _handle_gemini_ai_query(self, user_question: str) -> None:
        st = self._state.get_full_state_dict()
        t = st.get("telemetry", {})
        eq = t.get("total_equity") or st.get("daily_starting_equity") or 0.0
        upnl = t.get("unrealized_pnl", 0.0)
        breadth = t.get("market_breadth", 0.0)
        news_s = t.get("news_sentiment", 0.0)
        risk = st.get("risk_profile", "OPTIMAL")
        lev = st.get("max_portfolio_lev", 2.4)
        active_c = self._cartridges.active_name

        coins_info = []
        for c in st.get("coins", []):
            if abs(c.get("current_pos_qty", 0.0)) > 0:
                side = "LONG" if c["current_pos_qty"] > 0 else "SHORT"
                coins_info.append(f"• {c['symbol']}: {side} ${c.get('notional_usdt', 0.0):,.0f} (uPnL: {c.get('unrealized_pnl', 0.0):+.2f}$)")

        pos_str = "\n".join(coins_info[:20]) if coins_info else "100% КЕШ (USDT), позицій немає"

        prompt = (
            "Ти — QuantCore Sovereign AI, квантовий портфельний стратег і ризик-офіцер.\n"
            "Відповідай об'єктивно, чесно та лаконічно українською мовою без вигаданих обіцянок.\n\n"
            f"ПОТОЧНИЙ СТАН СИСТЕМИ:\n"
            f"- Середовище: {self._env_badge()}\n"
            f"- Equity: ${eq:,.2f} USDT (uPnL: {upnl:+.2f}$)\n"
            f"- Профіль: {risk} (стеля {lev:.1f}x)\n"
            f"- Ширина ринку (Breadth): {breadth:.2f} | Сентимент новин: {news_s:+.2f}\n"
            f"- Активне ядро: {active_c}\n"
            f"- Відкриті позиції:\n{pos_str}\n\n"
            f"Запитання користувача: \"{user_question}\""
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 380},
        }

        client = http_pool.get()
        reply_text = None
        for model_name in (settings.GEMINI_MODEL, "gemini-2.5-flash", "gemini-2.0-flash"):
            if not model_name:
                continue
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
            try:
                resp = await client.post(url, json=payload, timeout=12.0)
                if resp.status_code == 200:
                    d = resp.json()
                    reply_text = d["candidates"][0]["content"]["parts"][0]["text"].strip()
                    break
            except Exception:
                continue

        if reply_text:
            await self.send_alert(f"🤖 <b>QuantCore AI:</b>\n\n{html.escape(reply_text)}")
        else:
            await self.send_alert("⚠️ Gemini AI тимчасово недоступний. Скористайтесь кнопками меню /start.")

    # ==========================================
    # 6. ФОНОВИЙ ЦИКЛ LONG-POLLING (ZERO-IDLE CPU)
    # ==========================================
    async def polling_loop(self) -> None:
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            self._logger.warning("⚠️ TELEGRAM_TOKEN не налаштовано. Telegram-бот вимкнено.")
            return

        self._logger.info("📱 Telegram Long-Polling слухач QuantCore активовано.")
        eng_title = "QuantCore V2 Multi-Sleeve" if self._is_v2() else "QuantCore V58.0"
        await self.send_alert(
            f"👑 <b>{eng_title} запущено!</b> [{self._env_badge()}]\n"
            f"• Картридж: <code>{self._cartridges.active_name}</code> ({len(self._state.coins)} пар)\n"
            f"• Таймфрейм: <code>{settings.CANDLE_TIMEFRAME}</code> | Профіль: <code>{self._state.risk_profile}</code>\n"
            f"• RAM: <code>{memory_guard.get_rss_mb():.1f} MB</code>"
        )

        while True:
            try:
                offset = -1 if not self._synced else (self._last_update_id + 1)
                timeout_val = 0 if not self._synced else 50
                data = await self._api(
                    "getUpdates",
                    {"offset": offset, "limit": 10, "timeout": timeout_val},
                    timeout=58.0,
                )

                if data and data.get("ok"):
                    results = data.get("result", [])
                    if not self._synced:
                        if results:
                            self._last_update_id = int(results[-1]["update_id"])
                        self._synced = True
                        continue

                    for item in results:
                        self._last_update_id = int(item["update_id"])

                        if "callback_query" in item:
                            cq = item["callback_query"]
                            chat_id = str(((cq.get("message") or {}).get("chat") or {}).get("id", ""))
                            if chat_id == str(settings.TELEGRAM_CHAT_ID):
                                await self._api("answerCallbackQuery", {"callback_query_id": cq["id"]})
                                await self._handle_command_or_callback(str(cq.get("data", "")))

                        elif "message" in item:
                            msg = item["message"]
                            chat_id = str((msg.get("chat") or {}).get("id", ""))
                            if chat_id != str(settings.TELEGRAM_CHAT_ID):
                                continue

                            if "document" in msg:
                                await self._handle_uploaded_document(
                                    msg["document"],
                                    caption=str(msg.get("caption") or ""),
                                )
                            else:
                                text = str(msg.get("text") or "").strip()
                                if text:
                                    await self._handle_command_or_callback(text)
                else:
                    await asyncio.sleep(4.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.debug(f"Тимчасова помилка telegram polling: {e}")
                await asyncio.sleep(4.0)

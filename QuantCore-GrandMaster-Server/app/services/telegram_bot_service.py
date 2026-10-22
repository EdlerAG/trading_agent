import io
import os
import gc
import sys
import html
import time
import signal
import zipfile
import asyncio
import logging
from typing import Dict, Any, Optional
import numpy as np

from app.core.config import settings
from app.core.http_client import http_pool
from app.core.memory_guard import memory_guard
from app.core.events import event_bus, EventType
from app.domain.interfaces import IService
from app.services.state_service import StateService
from app.services.database_service import DatabaseService
from app.services.news_ai_service import NewsAiService
from app.cartridges.cartridge_loader import CartridgeLoaderService


class TelegramBotService(IService):
    """
    Повнофункціональний пульт керування QuantCore V58.0 Pure SOTA у Telegram:
    1. Керування 5 валютами в 1 клік (AUTO / LONG_ONLY / CORE_ONLY / OFF).
    2. Прийом файлів прямо в чаті (як OTA у SmartLamp):
       - *.joblib -> миттєва гаряча заміна моделі ШІ (Hot-Swap) без зупинки!
       - *.py або *.zip -> оновлення коду сервера з кнопкою миттєвого перезапуску!
    3. Кнопка '🔄 Рестарт Сервера' -> перезавантажує процес через systemd без входу в SSH-консоль.
    """

    __slots__ = (
        "_logger",
        "_state",
        "_db",
        "_cartridges",
        "_news",
        "_orchestrator",
        "_last_update_id",
        "_synced",
    )

    # Мапа автоматичного розміщення .py файлів при відправці їх у чат Telegram
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
        "feature_pipe_v58.py": "app/cartridges",
        "v58_grand_master_cartridge.py": "app/cartridges",
        "cartridge_loader.py": "app/cartridges",
        "state_service.py": "app/services",
        "online_adaptation_service.py": "app/services",
        "database_service.py": "app/services",
        "exchange_ccxt_service.py": "app/services",
        "news_ai_service.py": "app/services",
        "execution_service.py": "app/services",
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
        news_service: NewsAiService,
        orchestrator,
    ) -> None:
        self._logger = logger
        self._state = state_service
        self._db = db_service
        self._cartridges = cartridge_service
        self._news = news_service
        self._orchestrator = orchestrator
        self._last_update_id: int = 0
        self._synced: bool = False

    @property
    def name(self) -> str:
        return "TelegramBotService"

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    # ==========================================
    # 1. КЛАВІАТУРИ TELEGRAM-ТЕРМІНАЛА
    # ==========================================
    def _main_keyboard(self) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 Статус V58", "callback_data": "cmd_status"},
                    {"text": "🧬 Радар 5 Валют", "callback_data": "cmd_radar"},
                ],
                [
                    {"text": "🎛️ Пульт Валют (5)", "callback_data": "cmd_coins_menu"},
                    {"text": "⚙️ Профіль Плеча", "callback_data": "cmd_risk_menu"},
                ],
                [
                    {"text": "📈 Графік Альфи", "callback_data": "cmd_chart"},
                    {"text": "📜 Історія Угод", "callback_data": "cmd_trades"},
                ],
                [
                    {"text": "🧠 Самонавчання & OTA", "callback_data": "cmd_ota_info"},
                    {"text": "⚡ Перерахувати свічку", "callback_data": "cmd_wakeup"},
                ],
                [
                    {"text": "⏸️ Пауза", "callback_data": "cmd_pause_menu"},
                    {"text": "▶️ Старт", "callback_data": "cmd_resume"},
                    {"text": "🔄 Рестарт Сервера", "callback_data": "cmd_restart_confirm"},
                ],
                [
                    {"text": "🚨 PANIC CLOSE USDT", "callback_data": "cmd_panic_confirm"},
                    {"text": "🌐 Web-Термінал", "url": settings.DASHBOARD_URL},
                ],
            ]
        }

    def _coins_menu_keyboard(self) -> Dict[str, Any]:
        mode_icons = {0: "🔴 OFF", 1: "🟢 AUTO", 2: "📈 LONG", 3: "📉 SHORT", 4: "🛡️ CORE"}
        rows = []
        for sym, c in self._state.coins.items():
            m_lbl = mode_icons.get(c.mode, "🟢 AUTO")
            rows.append([
                {"text": f"{sym}: {m_lbl} ({c.base_weight:.2f}x)", "callback_data": f"coin_cycle:{sym}"},
                {"text": "🔀 Режим", "callback_data": f"coin_cycle:{sym}"},
            ])
        rows.append([{"text": "🔙 Головне меню", "callback_data": "cmd_status"}])
        return {"inline_keyboard": rows}

    def _risk_menu_keyboard(self) -> Dict[str, Any]:
        cur_p = self._state.risk_profile
        cur_m = self._state.orchestrator_mode
        return {
            "inline_keyboard": [
                [{"text": f"{'✅ ' if cur_p=='CONSERVATIVE' else ''}🛡️ Conservative (1.6x Cap)", "callback_data": "risk:CONSERVATIVE"}],
                [{"text": f"{'✅ ' if cur_p=='OPTIMAL' else ''}⚖️ Optimal (2.4x | Calmar 10.35)", "callback_data": "risk:OPTIMAL"}],
                [{"text": f"{'✅ ' if cur_p=='AGGRESSIVE' else ''}🔥 Aggressive (3.2x High-Octane)", "callback_data": "risk:AGGRESSIVE"}],
                [{"text": f"{'✅ ' if cur_p=='OVERDRIVE' else ''}🚀 Overdrive (3.5x | +264.8% OOS)", "callback_data": "risk:OVERDRIVE"}],
                [{"text": f"🧬 Режим: {cur_m} (Натисни для зміни)", "callback_data": "mode_toggle"}],
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
        await self._api("sendMessage", {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": text,
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
        leader = t.get("top_leader", "BTCUSDT")
        ram_mb = memory_guard.get_rss_mb()

        status_str = "⏸️ НА ПАУЗІ" if self._state.is_paused else "🟢 ОНЛАЙН (Zero-Idle Sync)"
        radar = self._state.get_coins_radar_list()

        coin_lines = []
        for c in radar:
            sym = c["symbol"]
            qty = c["current_pos_qty"]
            p = c["price"]
            ph = c["phase_label"].split()[0]
            if abs(qty) > 0:
                dir_ic = "🟢 L" if qty > 0 else "🔴 S"
                coin_lines.append(
                    f"• <b>{sym}</b>: {dir_ic} <code>{abs(qty):.4f}</code> (${c['notional_usdt']:,.0f}) | "
                    f"PnL: <b>{c['unrealized_pnl']:+.2f}$</b> | {ph}"
                )
            else:
                m_str = "OFF" if not c["enabled"] else f"Score:{c['alpha_score']:+.2f}"
                coin_lines.append(f"• <b>{sym}</b>: ⚪ Кеш (<code>${p:,.2f}</code>) | {m_str}")

        return (
            f"👑 <b>QUANTCORE V58.0 PURE SOTA</b>\n"
            f"═══════════════════════\n"
            f"• <b>Статус:</b> {status_str}\n"
            f"• <b>Картридж:</b> <code>{self._cartridges.active_name}</code>\n"
            f"• <b>Профіль:</b> <code>{self._state.risk_profile} (Max {self._state.max_portfolio_lev:.1f}x)</code>\n"
            f"• <b>Сумарний Equity:</b> <b>${eq:,.2f} USDT</b> (PnL: <b>{upnl:+.2f}$</b>)\n"
            f"• <b>Вільна маржа:</b> <code>${bal:,.2f} USDT</code> | Плече: <b>{gross:.2f}x</b>\n"
            f"• <b>Топ-Лідер:</b> <code>{leader}</code> | RAM: <code>{ram_mb:.1f} MB</code>\n"
            f"───────────────────────\n"
            + "\n".join(coin_lines)
            + f"\n═══════════════════════\n"
            f"🕯 <i>Свічка: {t.get('timestamp', 'Очікування')} UTC</i>"
        )

    def _build_radar_text(self) -> str:
        radar = self._state.get_coins_radar_list()
        t = self._state.latest_telemetry
        lines = [
            f"🧬 <b>РАДАР 5 МЕЙДЖОРІВ V58.0 PURE SOTA</b>",
            f"═══════════════════════",
            f"• <b>Ширина ринку (Breadth):</b> <code>{t.get('market_breadth', 0.0):+.2f}</code>",
            f"• <b>Новинний сентимент Gemini:</b> <code>{t.get('news_sentiment', 0.0):+.2f}</code>",
            f"───────────────────────",
        ]
        for c in radar:
            sl_txt = f"${c['active_sl_price']:,.2f}{' 🛡️BE' if c['is_breakeven'] else ''}" if c["active_sl_price"] > 0 else "—"
            lines.append(
                f"🔹 <b>{c['symbol']}</b> [{c['mode_label']}]\n"
                f"   Фаза: <b>{c['phase_label']}</b> | Ціль: <b>{c['target_weight']:+.2f}x</b>\n"
                f"   Alpha: <code>{c['alpha_score']:+.3f}</code> | MWU Довіра: <code>{c['effective_weight']:.2f}x</code> | SL: <code>{sl_txt}</code>"
            )
        return "\n".join(lines)

    async def _send_alpha_chart(self) -> None:
        res = await asyncio.to_thread(self._db.get_equity_series_and_kpis, 30)
        chart = res.get("chart", {})
        kpis = res.get("kpis", {})
        times = chart.get("times", [])
        if len(times) < 2:
            await self.send_alert("📉 Недостатньо історичних точок для графіка (потрібно мінімум 2 свічки).")
            return

        def _render_png() -> bytes:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.5, 5.8), sharex=True, gridspec_kw={"height_ratios": [2.5, 1.1]})
            fig.patch.set_facecolor("#070b14")
            x_idx = np.arange(len(times))

            for ax in (ax1, ax2):
                ax.set_facecolor("#0f172a")
                ax.tick_params(colors="#94a3b8", labelsize=8)
                ax.grid(True, linestyle="--", alpha=0.15, color="#cbd5e1")
                for sp in ax.spines.values():
                    sp.set_color("#1e293b")

            eq_r = chart["equity_ret_pct"]
            btc_r = chart["btc_ret_pct"]
            dd_r = chart["drawdown_pct"]

            ax1.plot(x_idx, eq_r, color="#10b981", linewidth=2.2, label=f"QuantCore V58.0 Pure SOTA ({kpis.get('total_pnl_pct', 0):+.2f}%)")
            ax1.plot(x_idx, btc_r, color="#f59e0b", linewidth=1.3, linestyle="--", label=f"BTC B&H ({kpis.get('btc_bh_pct', 0):+.2f}%)")
            ax1.set_ylabel("Дохідність (%)", color="#cbd5e1", fontsize=9)
            ax1.legend(loc="upper left", facecolor="#070b14", edgecolor="#334155", labelcolor="white", fontsize=8.5)
            ax1.set_title("QUANTCORE V58.0 PURE SOTA: MULTI-ASSET EQUITY vs BTC", color="#f8fafc", fontsize=10.5, weight="bold")

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
        files = {"photo": ("quantcore_v58.png", png_bytes, "image/png")}
        caption = (
            f"📈 <b>Звіт QuantCore V58.0 Pure SOTA:</b>\n"
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
        """
        Зберігає всі стани на диск і посилає сигнал SIGTERM власному процесу.
        Служба systemd (Restart=always) автоматично піднімає оновлений сервер за 3 секунди!
        """
        self._state.save_snapshot()
        await self._db.shutdown()
        await asyncio.sleep(0.6)
        os.kill(os.getpid(), signal.SIGTERM)

    async def _handle_uploaded_document(self, doc: Dict[str, Any], caption: str) -> None:
        fname = str(doc.get("file_name") or "").strip()
        file_id = str(doc.get("file_id") or "")
        if not fname or not file_id:
            return

        # 1. Гаряча заміна ШІ-картриджа (.joblib)
        if fname.endswith(".joblib"):
            await self.send_alert(f"⏳ <i>Завантаження ШІ-картриджа <code>{html.escape(fname)}</code> та перевірка контракту...</i>")
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
                    f"• <b>Активні валюти:</b> <code>{', '.join(info['supported_symbols'])}</code>\n"
                    f"• <b>Споживання RAM:</b> <code>{info['ram_rss_mb']:.1f} MB</code>\n"
                    f"⚡ <i>Торговий цикл вже перераховує свічку за новою моделлю!</i>"
                )
            except Exception as e:
                await self.send_alert(f"❌ <b>Відхилено пошкоджений картридж:</b>\n<code>{html.escape(str(e))}</code>")
            return

        # 2. Оновлення коду прошивки сервера (.py або .zip архів) прямо через Telegram
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

            if fname.endswith(".py"):
                sub_dir = self.PY_FILE_ROUTES.get(fname, caption.strip() if caption else "")
                target_dir = os.path.join(settings.BASE_DIR, sub_dir) if sub_dir else settings.BASE_DIR
                os.makedirs(target_dir, exist_ok=True)
                target_path = os.path.join(target_dir, fname)
                tmp_path = target_path + ".tmp"
                with open(tmp_path, "wb") as f:
                    f.write(raw_bytes)
                os.replace(tmp_path, target_path)
                rel_p = os.path.relpath(target_path, settings.BASE_DIR)
                await self.send_alert(
                    f"✅ <b>Модуль коду <code>{html.escape(rel_p)}</code> ({len(raw_bytes)} байт) оновлено!</b>\n\n"
                    f"Натисніть кнопку нижче, щоб перезавантажити сервер і активувати зміни:",
                    reply_markup=restart_kb,
                )
            elif fname.endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                        extracted = []
                        for member in zf.namelist():
                            if ".." in member or member.startswith("/") or ".env" in member:
                                continue
                            zf.extract(member, settings.BASE_DIR)
                            extracted.append(member)
                    await self.send_alert(
                        f"📦 <b>ZIP-патч розпаковано ({len(extracted)} файлів)!</b>\n\n"
                        f"Натисніть кнопку нижче для миттєвого перезапуску сервера:",
                        reply_markup=restart_kb,
                    )
                except Exception as ze:
                    await self.send_alert(f"❌ Помилка розпакування ZIP: <code>{html.escape(str(ze))}</code>")
            return

    # ==========================================
    # 5. ОБРОБКА КОМАНД ТА INLINE-КНОПОК
    # ==========================================
    async def _handle_command_or_callback(self, cmd: str) -> None:
        cmd = cmd.strip()

        if cmd in ("/start", "/status", "cmd_status"):
            await self.send_alert(self._build_status_text())

        elif cmd in ("/radar", "cmd_radar"):
            await self.send_alert(self._build_radar_text())

        elif cmd in ("/coins", "cmd_coins_menu"):
            await self.send_alert(
                "🎛️ <b>ПУЛЬТ КЕРУВАННЯ ВАЛЮТАМИ V58:</b>\n"
                "Натисніть на валюту, щоб перемкнути її режим по колу:\n"
                "<code>🟢 AUTO ➔ 📈 LONG ONLY ➔ 🛡️ CORE ONLY ➔ 🔴 OFF</code>",
                reply_markup=self._coins_menu_keyboard(),
            )

        elif cmd.startswith("coin_cycle:"):
            sym = cmd.split(":", 1)[1]
            c = self._state.coins.get(sym)
            if c:
                # Цикл: 1 (AUTO) -> 2 (LONG_ONLY) -> 4 (CORE_ONLY) -> 0 (OFF) -> 1 (AUTO)
                next_map = {1: 2, 2: 4, 4: 0, 0: 1, 3: 1}
                new_m = next_map.get(c.mode, 1)
                self._state.update_coin_settings(symbol=sym, enabled=(new_m != 0), mode=new_m)
                await event_bus.publish(EventType.COIN_CONFIG_CHANGED, {"symbol": sym}, wake_engine=True)
            await self.send_alert("🎛️ <b>Режим валюти оновлено!</b>", reply_markup=self._coins_menu_keyboard())

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
            await self.send_alert(f"🧬 <b>Режим оркестратора змінено на: {new_om}!</b>", reply_markup=self._risk_menu_keyboard())

        elif cmd in ("/chart", "cmd_chart"):
            await self._send_alpha_chart()

        elif cmd in ("/trades", "cmd_trades"):
            trades = self._db.get_recent_trades(limit=8)
            if not trades:
                await self.send_alert("📜 Журнал угод поки порожній.")
            else:
                lines = ["📜 <b>ОСТАННІ ОПЕРАЦІЇ V58.0 PURE SOTA:</b>\n═══════════════════════"]
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
                    [{"text": "⏪ Відкотити на попередню модель", "callback_data": "cmd_rollback_model"}],
                    [{"text": "📦 Завантажити бекап БД (.db)", "callback_data": "cmd_dl_db"}],
                    [{"text": "🔄 Перезавантажити сервер", "callback_data": "cmd_restart_confirm"}],
                    [{"text": "🔙 Головне меню", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert(
                f"🧠 <b>КАРТРИДЖІ МОДЕЛЕЙ ТА OTA-ОНОВЛЕННЯ</b>\n"
                f"═══════════════════════\n"
                f"• <b>Активна модель:</b> <code>{meta['active_cartridge']}</code>\n"
                f"• <b>Резервна (Rollback):</b> <code>{meta['previous_cartridge'] or '—'}</code>\n"
                f"• <b>RAM (VmRSS):</b> <code>{res['ram_rss_mb']:.1f} MB / 420 MB</code>\n"
                f"• <b>Диск (storage/):</b> <code>{res['storage_used_mb']:.1f} MB / {res['storage_limit_mb']} MB</code>\n"
                f"───────────────────────\n"
                f"📥 <b>Як оновити без консолі:</b>\n"
                f"1) Надішліть сюди файл <code>*.joblib</code> — виконається миттєвий <b>Hot-Swap</b> моделі.\n"
                f"2) Змініть файли на сервері через GUI або надішліть сюди <code>*.py</code> / <code>*.zip</code> і натисніть <b>«🔄 Перезавантажити сервер»</b>!",
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
                await self.send_document(b_path, caption="📦 Актуальний зріз бази даних QuantCore V58.0 Pure SOTA")

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
                "Усі поточні стани та БД будуть збережені, а служба <code>systemd</code> автоматично перезапустить бота з оновленими файлами за 3 секунди (відкриті позиції та стопи на біржі залишаються недоторканими).",
                reply_markup=kb,
            )

        elif cmd == "cmd_restart_exec":
            await self.send_alert("🔄 <b>Перезавантаження сервера...</b> Через 3–5 секунд бот знову буде онлайн!")
            asyncio.create_task(self.trigger_graceful_server_restart())

        elif cmd == "cmd_panic_confirm":
            kb = {
                "inline_keyboard": [
                    [{"text": "🚨 ТАК, ЛІКВІДУВАТИ ВСЕ В USDT", "callback_data": "cmd_panic_exec"}],
                    [{"text": "❌ Скасувати", "callback_data": "cmd_status"}],
                ]
            }
            await self.send_alert(
                "⚠️ <b>ЕКСТРЕНИЙ ВИХІД У КЕШ (PANIC CLOSE)!</b>\n\n"
                "Усі відкриті позиції по всіх 5 валютах будуть миттєво закриті за ринком, а торгівля стане на паузу.",
                reply_markup=kb,
            )

        elif cmd == "cmd_panic_exec":
            self._state.set_pause_state(paused=True)
            await self._orchestrator.emergency_close_all_positions()

        else:
            # Free-form intelligent conversation with Gemini AI about system state & crypto market
            if settings.GEMINI_API_KEY and len(cmd) > 1:
                await self._handle_gemini_ai_query(cmd)
            else:
                await self.send_alert(
                    f"❓ Невідома команда: <code>{html.escape(cmd)}</code>\n\n"
                    f"Надішліть /start для виклику головного меню або запитайте мене будь-що звичайною мовою!"
                )

    async def _handle_gemini_ai_query(self, user_question: str) -> None:
        """Інтерактивний діалог користувача з Gemini AI про стан ринку, позиції та стратегію."""
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
                coins_info.append(f"• {c['symbol']}: {side} {abs(c['current_pos_qty']):.4f} (uPnL: {c.get('unrealized_pnl', 0.0):+.2f}$)")

        pos_str = "\n".join(coins_info) if coins_info else "100% КЕШ (USDT), позицій немає"

        prompt = (
            "Ти — QuantCore Sovereign AI, інтелектуальний квантовий помічник і стратег крипто-фонду користувача.\n"
            "Користувач надіслав тобі запитання в Telegram. Відповідай дружньо, професійно, впевнено та лаконічно українською мовою.\n\n"
            f"ПОТОЧНИЙ СТАН СИСТЕМИ QUANTCORE:\n"
            f"- Депозит / Equity: ${eq:,.2f} USDT (Плаваючий uPnL: {upnl:+.2f}$)\n"
            f"- Режим ризику: {risk} ({lev:.1f}x)\n"
            f"- Ринкова ширина (Breadth): {breadth:+.2f} (від -1.0 до +1.0)\n"
            f"- Сентимент новин: {news_s:+.2f}\n"
            f"- Активні позиції на біржі:\n{pos_str}\n"
            f"- Активне квантове ядро: {active_c}\n\n"
            f"Запитання користувача: \"{user_question}\"\n\n"
            "Дай чітку, практичну відповідь без зайвої води, спираючись на поточний стан ринку та портфеля."
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 350},
        }

        client = http_pool.get()
        reply_text = None
        for model_name in (settings.GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-flash-latest"):
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
            await self.send_alert("⚠️ Не вдалося отримати відповідь від Gemini AI. Спробуйте ще раз або скористайтесь кнопками меню /start.")



    # ==========================================
    # 6. ФОНОВИЙ ЦИКЛ LONG-POLLING (ZERO-IDLE CPU)
    # ==========================================
    async def polling_loop(self) -> None:
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            self._logger.warning("⚠️ TELEGRAM_TOKEN не налаштовано. Telegram-бот вимкнено.")
            return

        self._logger.info("📱 Telegram Long-Polling слухач V58 (OTA + Multi-Coin Control) активовано.")
        await self.send_alert(
            f"👑 <b>QuantCore V58.0 Pure SOTA запущено!</b>\n"
            f"• Картридж: <code>{self._cartridges.active_name}</code>\n"
            f"• Профіль: <code>{self._state.risk_profile} ({self._state.max_portfolio_lev:.1f}x)</code>\n"
            f"• RAM: <code>{memory_guard.get_rss_mb():.1f} MB</code>"
        )

        while True:
            try:
                offset = -1 if not self._synced else (self._last_update_id + 1)
                timeout_val = 0 if not self._synced else 35
                data = await self._api(
                    "getUpdates",
                    {"offset": offset, "limit": 10, "timeout": timeout_val},
                    timeout=42.0,
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
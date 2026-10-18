from enum import IntEnum, StrEnum


class CoinMode(IntEnum):
    """Індивідуальний режим торгівлі для кожної монети."""
    OFF = 0               # Повністю вимкнено (ігнорується, позиція = 0)
    AUTO = 1              # Повний автомат (Long + Short + StatArb + Waterfall)
    LONG_ONLY = 2         # Тільки Long-тренди та відкупи проливів (шорти заборонено)
    SHORT_ONLY = 3        # Тільки хедж-шорти
    CORE_TREND_ONLY = 4   # Тільки макро-тренд без імпульсних пробоїв Pod2

    @property
    def label_ua(self) -> str:
        labels = {
            0: "🔴 ВИМКНЕНО (OFF)",
            1: "🟢 АВТО (Long+Short)",
            2: "📈 ТІЛЬКИ LONG",
            3: "📉 ТІЛЬКИ SHORT",
            4: "🛡️ ЛИШЕ МАКРО-ТРЕНД",
        }
        return labels.get(int(self), "🟢 АВТО")


class TierRole(IntEnum):
    """Ієрархічний ешелон монети у Верховному Оркестраторі."""
    CORE_SOVEREIGN = 1    # Фундаментальне ядро (BTC, ETH, SOL — найвищий пріоритет маржі)
    STRUCTURAL_MAJOR = 2  # Середній ешелон (BNB, XRP — збалансована квота)
    TACTICAL_SATELLITE = 3 # Сателіт під суворим карантином просадки

    @property
    def label_ua(self) -> str:
        labels = {
            1: "👑 T1: CORE SOVEREIGN",
            2: "⚔️ T2: STRUCTURAL MAJOR",
            3: "🛰️ T3: SATELLITE",
        }
        return labels.get(int(self), "⚔️ T2: MAJOR")


class CascadePhase(IntEnum):
    """Фаза каскадного скінченного автомата (State Machine V13..V23)."""
    SHORT_CASCADE = -1    # 🔴 F4: Каскадний шорт
    SCANNING_CASH = 0     # ⚪ F0: 100% Кеш (Сканування)
    SCOUT_IGNITION = 1    # 🟡 F1: Розвідник (0.7x..0.85x)
    CORE_EXPANSION = 2    # 🟢 F2: Основний тренд (1.0x..1.6x)
    APEX_OVERDRIVE = 3    # 🔥 F3: Повний форсаж (1.65x..2.5x)

    @property
    def label_ua(self) -> str:
        labels = {
            -1: "🔴 F4: SHORT CASCADE",
            0:  "⚪ F0: КЕШ (SCANNING)",
            1:  "🟡 F1: РОЗВІДНИК (SCOUT)",
            2:  "🟢 F2: ОСНОВНИЙ ТРЕНД",
            3:  "🔥 F3: ФОРСАЖ (APEX)",
        }
        return labels.get(int(self), "⚪ F0: КЕШ")


class RiskProfile(StrEnum):
    CONSERVATIVE = "CONSERVATIVE"  # 1.6x Cap
    OPTIMAL = "OPTIMAL"            # 2.4x Cap (Calmar 10.35)
    AGGRESSIVE = "AGGRESSIVE"      # 3.2x Cap
    OVERDRIVE = "OVERDRIVE"        # 3.5x Cap (+264.8% OOS)


class OrchestratorMode(StrEnum):
    PORTFOLIO_SYNERGY = "PORTFOLIO_SYNERGY"  # Командне синхронне ядро V23 (+ Sticky Waterfall)
    SOLO_MAX = "SOLO_MAX"                    # Незалежні соло-рекордсмени для кожної монети
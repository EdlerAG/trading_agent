# QuantCore Execution Server

Асинхронний сервер виконання ордерів та моніторингу портфеля для **Binance USD-M Perpetuals** (`FastAPI` + `CCXT` + `WebSocket Sentinel` + `Telegram` + `Web Terminal`).

> **Примітка з безпеки:** Пропрієтарні математичні моделі, торгові стратегії, ваги (`*.joblib`) та дослідницькі модулі зберігаються виключно локально й виключені з публічного Git-репозиторію.

---

## Про проєкт

**QuantCore** побудований як модульне ядро виконання (Execution Engine), відділене від дослідницьких стратегій через єдиний інтерфейс картриджів (`IAlphaCartridge`):

- **Асинхронний цикл виконання (`ExecutionService`)**: синхронізує ринкові дані, формує цільові позиції через активний картридж, проводить внутрішній нетинг та виставляє лімітні/ринкові ордери з мінімальним проковзуванням (`Maker-First`).
- **Реалтайм-захист (`WebSocketSentinelService` + `RiskGuardService`)**: відстежує ринкові потоки по WebSocket, контролює ліміти ризику, плече, денні просадки та аварійне закриття позицій.
- **Стан і телеметрія (`StateService` + `DatabaseService` + `ShadowArenaService`)**: зберігає стан портфеля, історію угод, метрики та логи в SQLite/JSONL із автоматичним резервним копіюванням.
- **Веб-термінал і Telegram (`portal_html.py` + `TelegramBotService`)**: захищений паролем/токеном вебінтерфейс моніторингу та керування сервером (старт/пауза, статус позицій, експорт телеметрії, алерти збою systemd).
- **Низьке споживання ресурсів (`MemoryGuard`)**: спроєктований для стабільної роботи 24/7 на бюджетному Linux VPS (Docker або native `systemd`).

---

## Структура репозиторію

```text
trading_agent/
├── .github/workflows/ci.yml              # CI: компіляція, аудит коду та unit-тести
├── requirements.lock                     # Зафіксовані залежності середовища
└── QuantCore-GrandMaster-Server/
    ├── app/
    │   ├── api/                          # Захищені REST-ендпоінти керування й телеметрії
    │   ├── cartridges/                   # Інтерфейс та завантажувач картриджів (IAlphaCartridge)
    │   ├── core/                         # Конфігурація (.env), безпека, події, memory guard
    │   ├── domain/                       # DTO-схеми, enum-и та доменні інтерфейси
    │   ├── services/                     # Execution, CCXT Exchange, Market Data, WS Sentinel, Risk, State, Telegram
    │   └── web/                          # Вбудований веб-термінал моніторингу
    ├── deploy/                           # Скрипти systemd-сповіщень про збої
    ├── tests/                            # Інтеграційні тести серверної інфраструктури
    ├── Dockerfile
    ├── docker-compose.yml
    ├── deploy_native.sh                  # Скрипт нативного розгортання під systemd
    └── main.py                           # Точка входу FastAPI-сервера
```

---

## Швидкий старт

### 1. Локальні серверні тести
```powershell
cd QuantCore-GrandMaster-Server
..\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

### 2. Налаштування оточення
Скопіюйте [`QuantCore-GrandMaster-Server/.env.example`](QuantCore-GrandMaster-Server/.env.example) у `.env` та заповніть власні ключі (`BINANCE_API_KEY`, `BINANCE_SECRET`, `DASHBOARD_PASSWORD`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`).

### 3. Деплой на VPS
```bash
ssh -i <PATH_TO_SSH_KEY> <VPS_USER>@<VPS_HOST>
cd ~/trading_agent/QuantCore-GrandMaster-Server
sudo systemctl status trading_bot.service
sudo journalctl -u trading_bot.service -f
```

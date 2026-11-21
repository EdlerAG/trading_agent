# QuantCore Execution Server

Асинхронний торговий сервер та інфраструктура виконання ордерів для **Binance USD-M Perpetuals** (`FastAPI` + `CCXT` + `WebSocket Sentinel` + `Telegram` + `Web Terminal`).

> **Примітка з безпеки:** Пропрієтарні математичні моделі, ваги (`*.joblib`) та дослідницькі модулі зберігаються виключно локально і виключені з публічного Git-репозиторію.

---

## Структура репозиторію

```text
trading_agent/
└── QuantCore-GrandMaster-Server/  # Асинхронний сервер (FastAPI + Web Terminal + Telegram + WS Sentinel)
    ├── app/api/                   # Захищені REST/WebSocket ендпоінти
    ├── app/cartridges/            # Інтерфейс та завантажувач картриджів (моделі завантажуються локально)
    ├── app/core/                  # Конфігурація, безпека, memory guard
    ├── app/domain/                # Схеми DTO та інтерфейси
    ├── app/services/              # Execution, Exchange CCXT, Market Data, WS Sentinel, State, Telegram
    └── tests/                     # Інтеграційні тести серверної інфраструктури
```

---

## Швидкі команди

### 1. Локальні серверні тести
```powershell
cd QuantCore-GrandMaster-Server
..\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

### 2. Деплой на VPS
```bash
ssh -i <PATH_TO_SSH_KEY> <VPS_USER>@<VPS_HOST>
cd ~/trading_agent
sudo systemctl status trading_bot.service
sudo journalctl -u trading_bot.service -f
```

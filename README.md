# ⚡ QuantCore GrandMaster Server

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Binance Futures](https://img.shields.io/badge/Binance-Futures_USDT--M-F0B90B?style=for-the-badge&logo=binance&logoColor=black)](https://www.binance.com/)
[![Architecture](https://img.shields.io/badge/Architecture-Clean_%26_SOLID-10B981?style=for-the-badge)](#-архітектура)

**QuantCore GrandMaster Server** — високопродуктивний, низьколатентний автономний сервер кількісного алготрейдингу для біржі Binance Futures. Побудований на принципах Clean Architecture & SOLID, оптимізований для роботи на серверах з обмеженою пам'яттю (до 320–512 МБ RAM) завдяки Zero-Idle Hibernation та контролю аллокатора C (`malloc_trim`).

---

## 🏛 Архітектура системи

```text
📦 QuantCore-GrandMaster-Server
 ┣ 📜 .env.example                      # Шаблон ключів (Binance, TG, Gemini, Admin Pass, RAM Caps)
 ┣ 📜 .gitignore                        # Ігнорування .env, storage/, *.joblib, *.db, __pycache__
 ┣ 📜 deploy_native.sh                  # 1-клік інсталятор systemd (MemoryMax=320M, MALLOC_ARENA_MAX=2)
 ┣ 📜 Dockerfile                        # Легкий образ python:3.12-slim з оптимізацією аллокатора C
 ┣ 📜 docker-compose.yml                # Контейнер із жорстким лімітом пам'яті та авторестартом
 ┣ 📜 requirements.txt                  # Залежності (fastapi, uvicorn, orjson, ccxt, lightgbm, catboost...)
 ┣ 📜 main.py                           # Точка входу FastAPI + Lifespan-оркестратор фонових воркерів
 ┃
 ┣ 📂 storage                           # Ізольоване дискове сховище (внесено в .gitignore)
 ┃ ┣ 📂 cartridges                      # Папка для гарячої заміни моделей (quant_core_v23.joblib тощо)
 ┃ ┣ 📂 backups                         # Авто-бекапи БД та снапшотів для відправки в Telegram
 ┃ ┣ 📜 trading_history.db              # SQLite (WAL Mode, mmap_size=0 для економії RAM)
 ┃ ┣ 📜 engine_state.json               # Атомарний стан позицій, стопів та налаштувань валют (orjson)
 ┃ ┗ 📜 adaptive_weights.json           # Живі онлайн-ваги самонавчання (MWU + Bandit Meta-Weights)
 ┃
 ┗ 📂 app                               # Головний пакет застосунку (Clean Architecture & SOLID)
   ┣ 📜 __init__.py
   ┃
   ┣ 📂 core                            # Фундамент системи, конфігурація та контроль ресурсів
   ┃ ┣ 📜 config.py                     # @dataclass(frozen=True, slots=True) Settings + змінні .env
   ┃ ┣ 📜 memory_guard.py               # Zero-Idle Hibernation: gc.collect() + libc.malloc_trim(0)
   ┃ ┣ 📜 events.py                     # Асинхронна шина подій (EventBus) та сигнали пробудження
   ┃ ┣ 📜 security.py                   # Авторизація API/Web (Bearer / X-Api-Key / Session Cookie)
   ┃ ┗ 📜 http_client.py                # Спільний пул з'єднань httpx.AsyncClient (ліміт конектів)
   ┃
   ┣ 📂 domain                          # Контракти (Interfaces) та строгі структури даних (DTO)
   ┃ ┣ 📜 enums.py                      # Валютні режими (AUTO, LONG_ONLY, OFF), фази (F0..F4), ролі
   ┃ ┣ 📜 schemas.py                    # Pydantic v2 / __slots__ DTO: CandleBatch, PortfolioTargetDTO
   ┃ ┗ 📜 interfaces.py                 # Абстрактні контракти SOLID (IService, IAlphaCartridge, IExchangeGateway)
   ┃
   ┣ 📂 cartridges                      # Шари ШІ-моделей (Змінюються БЕЗ переписування сервера — OCP)
   ┃ ┣ 📜 cartridge_loader.py           # Гаряче завантаження (Hot-Swap) .joblib з Telegram або диска
   ┃ ┣ 📜 feature_pipe_v23.py           # Векторизований float32 генератор 43 факторів без фрагментації
   ┃ ┣ 📜 v23_grand_master_cartridge.py # Реалізація IAlphaCartridge для V23 (Соло + Sticky Waterfall)
   ┃ ┗ 📜 legacy_v7_adapter.py          # Адаптер зворотної сумісності зі старими 1-монетними бандлами
   ┃
   ┣ 📂 services                        # Незалежні доменні мікросервіси
   ┃ ┣ 📜 service_registry.py           # Оркестратор життєвого циклу сервісів
   ┃ ┣ 📜 state_service.py              # Потокобезпечна шина стану в пам'яті + атомарний orjson
   ┃ ┣ 📜 market_data_service.py        # Ring-Buffer кеш свічок для 5+ валют (довантажує дельту)
   ┃ ┣ 📜 online_adaptation_service.py  # Реал-тайм самонавчання (MWU, Bandit Meta-Weights, partial_fit)
   ┃ ┣ 📜 currency_governor_service.py  # Пульт валют: індивідуальні ліміти, вимкнення монет, режими
   ┃ ┣ 📜 risk_guard_service.py         # Незалежний CRO: Circuit Breaker, ATR Breakeven, Funding Guard
   ┃ ┣ 📜 execution_service.py          # Мультивалютний роутер ордерів (Maker Post-Only -> Market)
   ┃ ┣ 📜 exchange_ccxt_service.py      # Імплементація IExchangeGateway для Binance Futures
   ┃ ┣ 📜 news_ai_service.py            # RSS + Gemini AI Sentiment з кешем на 60 хв
   ┃ ┣ 📜 database_service.py           # Асинхронний запис угод та Equity у SQLite WAL
   ┃ ┗ 📜 telegram_bot_service.py       # Керування 5 валютами, графіки, прийом нових .joblib у чаті
   ┃
   ┣ 📂 api                             # Швидкі контролери FastAPI (ORJSONResponse)
   ┃ ┣ 📜 router.py                     # Головний роутер API
   ┃ ┣ 📜 endpoints_telemetry.py        # GET /api/v1/state, /api/v1/radar, /api/v1/equity, /api/v1/trades
   ┃ ┣ 📜 endpoints_control.py          # POST /api/v1/currency/{sym}/mode, /api/v1/risk-profile, /panic
   ┃ ┗ 📜 endpoints_cartridge.py        # POST /api/v1/cartridge/hot-swap (заміна моделі без рестарту)
   ┃
   ┗ 📂 web                             # Надлегкий Веб-Термінал (0 МБ додаткового RAM)
     ┗ 📜 portal_html.py                # Односторінковий Glassmorphism Bento-UI (HTML5 + Plotly.js CDN)
```

---

## ⚡ Ключові технологічні особливості

1. **Extreme Memory Optimization (< 320 MB RAM)**:
   * Заміна важкого Streamlit на вбудований у FastAPI легковесний HTML5 Glassmorphism термінал (0 MB оверхеду RAM).
   * Використання `__slots__ = (...)` та `@dataclass(slots=True)` у всіх критичних структурах.
   * Періодичний скид пам'яті: `gc.collect()` + низькорівневий `ctypes.CDLL('libc.so.6').malloc_trim(0)`.
   * Жорсткі обмеження через systemd (`MemoryMax=320M`) та Docker Compose (`mem_limit: 350m`).

2. **Cartridge Hot-Swap Engine**:
   * Зміна та оновлення моделей прогнозування (V23, V24 тощо) без перезапуску процесу.
   * Можливість надіслати новий файл `.joblib` прямо у Telegram-бот або через API ендпоінт `/api/v1/cartridge/hot-swap`.
   * Адаптер зворотної сумісності `legacy_v7_adapter.py` для підтримки старих одинарних моделей.

3. **Мультивалютний та адаптивний трейдинг**:
   * Одночасне ведення до 5+ торгових пар через єдиний баланс.
   * Онлайн-самонавчання ваг моделей (Multiplicative Weights Update / Contextual Bandit).
   * Ізольоване дискове сховище `storage/` для баз даних, снапшотів та бекапів (виключене з Git).

---

## 🚀 Запуск та розгортання

### Локальний запуск (Development)

```bash
cd QuantCore-GrandMaster-Server

# Створення оточення
python -m venv .venv
source .venv/bin/activate  # на Windows: .\.venv\Scripts\Activate.ps1

# Встановлення залежностей
pip install -r requirements.txt

# Налаштування змінних оточення
cp .env.example .env

# Запуск сервера
python main.py
```

### Розгортання через Docker Compose

```bash
cd QuantCore-GrandMaster-Server
docker-compose up -d --build
```

### Розгортання як native systemd сервіс на Linux/VPS

```bash
cd QuantCore-GrandMaster-Server
chmod +x deploy_native.sh
sudo ./deploy_native.sh
```

---

## 🔒 Безпека та Git

Файли бази даних, реальні змінні оточення та бінарні моделі надійно виключені з репозиторію через `.gitignore`:
* ❌ `.env` — не потрапляє у репозиторій.
* ❌ `storage/` — усі бази, стейти та бекапи зберігаються виключно локально на диску.
* ❌ `*.joblib` — моделі машинного навчання захищені від публікації.

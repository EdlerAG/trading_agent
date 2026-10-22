# ⚡ QuantCore Sovereign Server (V58.0 Pure SOTA)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2.10%2B-E92063?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Binance Futures](https://img.shields.io/badge/Binance-Futures_USDT--M-F0B90B?style=for-the-badge&logo=binance&logoColor=black)](https://www.binance.com/)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Architecture](https://img.shields.io/badge/Architecture-Clean_%26_SOLID-10B981?style=for-the-badge)](#-архітектура-системи)

**QuantCore Sovereign Server (V58.0 Pure SOTA)** — автономний сервер кількісного алготрейдингу інституційного рівня для біржі **Binance Futures (USDT-M)**.

Побудований на принципах **Clean Architecture** та **SOLID**, сервер автономно управляє диверсифікованим портфелем із **10 криптоактивів** (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LINKUSDT`, `NEARUSDT`, `SUIUSDT`, `BNBUSDT`, `AVAXUSDT`, `XRPUSDT`, `FETUSDT`), використовуючи **55 ортогональних факторів альфи**, субсекундний ML-інференс, паралельний збір маркет-даних, пасивні Stink-Bids та апаратну оптимізацію ресурсів (**< 290 МБ RAM на 1 GB VPS**).

---

## 📑 Зміст

1. [Ключові технологічні переваги V58.0](#-ключові-технологічні-переваги-v580)
2. [55 Ортогональних факторів альфи](#-55-ортогональних-факторів-альфи)
3. [Архітектура системи](#-архітектура-системи)
4. [Апаратний захист пам'яті та гібернація](#-апаратний-захист-памяті-та-гібернація)
5. [REST API та Bento-UI Веб-Термінал](#-rest-api-та-bento-ui-веб-термінал)
6. [Пульт керування в Telegram (OTA V58)](#-пульт-керування-в-telegram-ota-v58)
7. [Швидкий старт та розгортання](#-швидкий-старт-та-розгортання)
8. [Конфігурація (.env)](#-конфігурація-env)
9. [Безпека та ізоляція секретів](#-безпека-та-ізоляція-секретів)

---

## ⚡ Ключові технологічні переваги V58.0

* **Мультивалютний портфель із 10 активів**:
  Керування активами з динамічним розподілом ризику через індекс ринкової широти (Core Breadth & Continuous Thrust Z-Score: від `-2.50` до `+2.50`), крос-активну дисперсію та відносну силу до Bitcoin (`RS vs BTC`).
* **Конкурентний збір даних (`asyncio.gather` < 2.5с)**:
  Паралельне завантаження свічок для всіх 10 інструментів одночасно з ізольованими таймаутами. Час реакції на закриття 15m бару скорочено з 60 до **< 2.5 секунд**.
* **Пасивні Margin Stink-Bids & Sub-Candle MFE Harvester**:
  * *Stink-Bids*: Виставлення пасивних лімітних заявок у глибині тіней свічок (`-1.65 ATR` нижче ринку) на залишкове плече для збору панічної ліквідності з 0% комісією тейкера.
  * *MFE Harvester*: Внутрішньосвічковий збір прибутку при імпульсному розширенні (`+1.35 ATR`) без очікування закриття свічки.
* **Стійкість до біржових помилок (Self-Healing Execution)**:
  Інтелектуальне опрацювання кодів Binance (`-2022 ReduceOnly Order is rejected`): якщо позиція вже закрита біржовим стопом, бот автоматично синхронізує нульову експозицію і знімає ордери без збоїв.
* **Zero-Idle CPU Hibernation**:
  Процесор перебуває у **0.00% CPU стані** між 15-хвилинними свічками, прокидаючись виключно на закритті бару або через асинхронні події `EventBus`.
* **Гаряча заміна моделей (AI Cartridge Hot-Swap)**:
  Миттєве оновлення навчених ШІ-картриджів `.joblib` через Telegram або Web API за **1.5 секунди** без зупинки торгового циклу.
* **Інституційний ризик-менеджмент (CRO Watchdog)**:
  * *Daily Circuit Breaker*: Аварійне закриття позицій при досягненні 6% денної просадки.
  * *Dynamic ATR Breakeven*: Переведення Stop-Loss у беззбиток (+0.07% буфер) при русі ціни на `+1.8x ATR`.
  * *Spread & Volatility Filter*: Блокування входу при спреді > 0.08% або аномальному знеціненні ліквідності.

---

## 🔬 55 Ортогональних факторів альфи

Конвеєр ознак [feature_pipe_v58.py](QuantCore-GrandMaster-Server/app/cartridges/feature_pipe_v58.py) обчислює **55 взаємно ортогональних факторів** у форматі Float32 за < 150 мс:

| Категорія | Ознаки | Фізичний зміст |
| :--- | :--- | :--- |
| **Базовий імпульс (TSMOM)** | `tsmom_24`, `tsmom_96`, `tsmom_384`, `tsmom_1536` | Лог-прибутковість за 6г, 24г, 4д, 16д, нормована на Yang-Zhang волатильність |
| **Ковзні спреди та нахили** | `spread_96_384`, `spread_384_1536`, `slope_768` | Нормовані розходження трендів та нахил 768 EMA |
| **Ефективність руху (KER)** | `signed_ker_96`, `signed_ker_288` | Коефіцієнт Кауфмана (спрямованість без паразитного шуму) |
| **Канали та рівні** | `donchian_96`, `donchian_384`, `zscore_96`, `rsi_14`, `dist_vwap_96` | Відносна позиція у Дончіан-каналі, Z-Score, RSI та відхилення від VWAP |
| **Потік ордерів та об'єм** | `vol_surge`, `taker_imb_32`, `taker_imb_96` | Сплески об'єму та дельта тейкерських покупок/продажів |
| **Відносна сила проти BTC** | `btc_lead_24`, `rs_vs_btc_96`, `rs_vs_btc_384` | Альфа-випередження та кумулятивна відносна сила до Bitcoin |
| **Глибокі SOTA-тензори (35)** | `yz_vol_96`, `yz_vol_ratio`, `elastic_clock_mom`, `ehlers_roof_osc`, `ehlers_roof_vel`, `dist_anchored_vwap`, `frac_diff_z`, `kalman_vel_z`, `kalman_acc_z`, `kalman_gap_z`, `whale_ticket_z`, `quote_flow_imb_16`, `quote_flow_imb_64`, `vpin_toxicity_z`, `hawkes_cascade_z`, `dist_vp_poc_96`, `vp_poc_density`, `levy_path_area`, `wick_demand_pressure`, `institutional_absorption`, `sortino_asymmetry`, `shannon_entropy_96`, `hurst_vr_ratio`, `lead_lag_transfer_z`, `dyn_mom_rank`, `dyn_vol_rank`, `trend_quality_score`, `funding_rate_z`, `squeeze_thrust_idx`, `cross_dispersion_idx`, `cont_breadth_z`, `geo_shock_idx`, `macro_fng_idx`, `cs_momentum_z`, `cs_orderflow_z` | Адаптивний Калман (Qt/Rt), Zero-Lag Ehlers Roofing, Event-Anchored VWAP, дробове диференціювання d=0.35, VPIN & Hawkes, Volume Profile POC, сигнатури контуру Леві, дисбаланс тиску тіней свічок, ентропія Шеннона та крос-секційні ранги уваги |

---

## 🏛 Архітектура системи

Сервіси побудовані за суворим стандартом інверсії залежностей:

```text
📦 QuantCore-GrandMaster-Server
 ┣ 📂 app
 ┃ ┣ 📂 api                             # FastAPI контролери (Telemtry, Control, Cartridges)
 ┃ ┣ 📂 cartridges                      # Pure SOTA ШІ-картриджі (v58, 55 ознак, Hot-Swap)
 ┃ ┃ ┣ 📜 cartridge_loader.py           # Сервіс гарячої заміни моделей у пам'яті
 ┃ ┃ ┣ 📜 feature_pipe_v58.py           # Векторизований розрахунок 55 ознак у Float32
 ┃ ┃ ┗ 📜 v58_grand_master_cartridge.py # Мультивалютний оркестратор позицій
 ┃ ┣ 📂 core                            # Ядро (Config, EventBus, MemoryGuard, Security)
 ┃ ┣ 📂 domain                          # DTO-моделі (Pydantic v2), Enums та інтерфейси
 ┃ ┣ 📂 services                        # Ізольовані мікросервіси бізнес-логіки
 ┃ ┃ ┣ 📜 exchange_ccxt_service.py      # Шлюз Binance Futures (Smart Orders, Stink-Bids)
 ┃ ┃ ┣ 📜 execution_service.py          # Верховний оркестратор виконання портфеля
 ┃ ┃ ┣ 📜 market_data_service.py        # Конкурентний збір даних (asyncio.gather)
 ┃ ┃ ┣ 📜 database_service.py           # SQLite WAL сервіс (кеш 4 МБ, нульовий I/O)
 ┃ ┃ ┗ 📜 telegram_bot_service.py       # Long-polling бот керування та OTA-оновлень
 ┃ ┗ 📂 web                             # Bento-UI веб-термінал прямо у пам'яті FastAPI
 ┣ 📂 tests                             # Автоматичні юніт-тести та верифікація пайплайну
 ┣ 📜 deploy_native.sh                  # 1-клік native systemd інсталятор для Linux VPS
 ┣ 📜 Dockerfile                        # Оптимізований slim-контейнер з лімітом пам'яті
 ┗ 📜 main.py                           # Точка входу FastAPI + Lifespan оркестратор
```

---

## 🛡️ Апаратний захист пам'яті та гібернація

* **Фіксований буфер пам'яті (< 290 МБ RAM)**:
  Всі структури даних використовують `__slots__` та `@dataclass(slots=True)`.
* **C-Memory Trim**:
  Після кожного розрахунку викликається `libc.malloc_trim(0)`, повертаючи невикористані сторінки ядру ОС.
* **Zero Disk Bloat**:
  SQLite працює в режимі `PRAGMA journal_mode=WAL; PRAGMA cache_size=-4000; PRAGMA mmap_size=0;`.
* **Zero-Idle CPU**:
  Під час 15-хвилинної гібернації навантаження на vCPU дорівнює **0.00%**.

---

## 🌐 REST API та Bento-UI Веб-Термінал

Вбудований високошвидкісний веб-термінал доступний на порті `8501`:
* **URL:** `http://<IP_СЕРВЕРА>:8501`
* **Авторизація:** Захист за сесійними токенами SHA-256 (`DASHBOARD_PASSWORD`).
* **Можливості:**
  * Живий радар 10 активів (експозиція, Stop-Loss, Take-Profit, Alpha Score).
  * Графіки прибутковості та просадки (Plotly).
  * Гаряча зміна ризик-профілю (`CONSERVATIVE`, `MODERATE`, `AGGRESSIVE`).
  * Екстрене закриття позицій (Panic Button).

---

## 📱 Пульт керування в Telegram (OTA V58)

Телеграм-бот підтримує повне двостороннє керування сервером:
* `/status` — детальна телеметрія (експозиція, RAM, активний картридж, PnL).
* `/radar` — поточний радар 10 активів з цільовими вагами.
* `/coins` — інтерактивний пульт перемикання режимів для кожної монети (`AUTO`, `LONG_ONLY`, `OFF`).
* **OTA (Over-The-Air) Оновлення:** Надішліть новий файл `.joblib` або `.py` прямо в чат — бот перевірить його, оновить код і виконає гарячу заміну за 1.5 секунди.

---

## 🚀 Швидкий старт та розгортання

### Варіант 1: Native 1-Клік інсталяція на Linux VPS (Рекомендовано)

```bash
git clone https://github.com/EdlerAG/trading_agent.git
cd trading_agent/QuantCore-GrandMaster-Server

# Створіть конфігураційний файл .env з вашими ключами
cp .env.example .env
nano .env

# Запустіть автоматичний інсталятор native systemd сервісу
chmod +x deploy_native.sh
./deploy_native.sh
```

Інсталятор автоматично створить віртуальне оточення, встановить залежності, налаштує systemd-службу з обмеженням пам'яті (`MemoryMax=450M`) та запустить бота.

### Варіант 2: Запуск через Docker Compose

```bash
cd QuantCore-GrandMaster-Server
docker-compose up -d --build
```

---

## ⚙️ Конфігурація (.env)

Зразок конфігураційного файлу знаходиться в [.env.example](QuantCore-GrandMaster-Server/.env.example):

```ini
# --- Binance Futures API ---
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
BINANCE_TESTNET=false
IS_PAPER_TRADING=true
MAX_ACCOUNT_LEVERAGE=3.0

# --- Telegram Bot ---
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_user_id

# --- Web Terminal Access ---
DASHBOARD_PASSWORD=your_secure_password
PORT=8501
HOST=0.0.0.0
```

---

## 🔒 Безпека та ізоляція секретів

* Жодні API-ключі, приватні ключі, токени ботів або навчені файли моделей `.joblib` **ніколи не потрапляють у Git**.
* Репозиторій містить виключно код рушія, конфігураційні шаблони `.env.example` та тести.
* Пайплайн **GitHub Actions** автоматично перевіряє код на відсутність застарілих компонентів і секретів при кожному пуші.

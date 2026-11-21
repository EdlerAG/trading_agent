# ⚡ QuantCore Sovereign Server (V58.0 Pure SOTA)

[English](#-english) | [Українська](#-українська)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2.10%2B-E92063?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Binance Futures](https://img.shields.io/badge/Binance-Futures_USDT--M-F0B90B?style=for-the-badge&logo=binance&logoColor=black)](https://www.binance.com/)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Architecture](https://img.shields.io/badge/Architecture-Clean_%26_SOLID-10B981?style=for-the-badge)](#-system-architecture)

---

<a name="-english"></a>
## 🌐 English

**QuantCore Sovereign Server (V58.0 Pure SOTA)** is an institutional-grade autonomous quantitative trading engine engineered for **Binance Futures (USDT-M)**.

Architected under strict **Clean Architecture** and **SOLID** principles, the server autonomously manages a diversified portfolio of **10 crypto assets** (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LINKUSDT`, `NEARUSDT`, `SUIUSDT`, `BNBUSDT`, `AVAXUSDT`, `XRPUSDT`, `FETUSDT`). It leverages **55 orthogonal alpha factors**, sub-second ML inference, parallel concurrent market data ingestion, passive margin stink-bids, and rigorous hardware resource constraints (**< 290 MB RAM on budget 1 GB VPS**).

---

### 📑 Table of Contents
1. [Key Technological Advantages](#-key-technological-advantages)
2. [55 Orthogonal Alpha Factors](#-55-orthogonal-alpha-factors)
3. [System Architecture](#-system-architecture)
4. [Hardware Memory Shield & Hibernation](#-hardware-memory-shield--hibernation)
5. [REST API & Bento-UI Web Terminal](#-rest-api--bento-ui-web-terminal)
6. [Telegram Control Center (OTA V58)](#-telegram-control-center-ota-v58)
7. [Quick Start & Deployment](#-quick-start--deployment)
8. [Configuration (.env)](#-configuration-env)
9. [Security & Zero-Secrets Isolation](#-security--zero-secrets-isolation)

---

### ⚡ Key Technological Advantages

* **10-Asset Cross-Sectional Portfolio**:
  Autonomous capital allocation governed by market breadth indicators (Core Breadth & Continuous Thrust Z-Score: `-2.50` to `+2.50`), cross-asset dispersion, and relative strength against Bitcoin (`RS vs BTC`).
* **Concurrent Data Ingestion (`asyncio.gather` < 2.5s)**:
  Parallel non-blocking candle fetching across all 10 instruments with isolated per-symbol timeouts. Reduces round-trip latency at candle closes from 60s down to **< 2.5 seconds**.
* **Passive Margin Stink-Bids & Sub-Candle MFE Harvester**:
  * *Stink-Bids*: Automatically places deep passive limit bids (`-1.65 ATR` below mark) utilizing residual unallocated leverage to capture panic flash-wick liquidity with zero taker fees.
  * *MFE Harvester*: Harvests intra-candle profits during explosive momentum spikes (`+1.35 ATR`) without awaiting the 15m candle close.
* **Self-Healing Exchange Resilience**:
  Gracefully handles exchange response edge cases (`-2022 ReduceOnly Order is rejected`): when a position is already closed via stop-loss or exchange triggers, local state instantly harmonizes to flat without error storms.
* **Zero-Idle CPU Hibernation**:
  CPU consumes **0.00% utilization** between 15-minute candles, waking instantaneously via asynchronous events (`EventBus`).
* **AI Cartridge Hot-Swap**:
  Hot-reloads trained `.joblib` model cartridges via Telegram or REST API in **1.5 seconds** with zero trading loop downtime.
* **Institutional Risk Sentinel (CRO Watchdog)**:
  * *Daily Circuit Breaker*: Emergency liquidation freeze upon reaching 6% daily drawdown.
  * *Dynamic ATR Breakeven*: Transitions Stop-Loss to breakeven (+0.07% buffer) upon price advancing by `+1.8x ATR`.
  * *Spread & Volatility Filter*: Gates order submission when spread exceeds 0.08% or orderbook liquidity degrades.

---

### 🔬 55 Orthogonal Alpha Factors

The feature engine [feature_pipe_v58.py](QuantCore-GrandMaster-Server/app/cartridges/feature_pipe_v58.py) computes **55 mutually orthogonal factors** in pure Float32 in < 150 ms:

| Category | Features | Financial / Mathematical Meaning |
| :--- | :--- | :--- |
| **Momentum (TSMOM)** | `tsmom_24`, `tsmom_96`, `tsmom_384`, `tsmom_1536` | Log returns across 6h, 24h, 4d, 16d scaled by Yang-Zhang volatility |
| **Moving Spreads & Slopes** | `spread_96_384`, `spread_384_1536`, `slope_768` | Normalized trend divergence and slope of 768-period EMA |
| **Kaufman Efficiency (KER)**| `signed_ker_96`, `signed_ker_288` | Price path efficiency ratio isolating directional drift from noise |
| **Channels & Relative State**| `donchian_96`, `donchian_384`, `zscore_96`, `rsi_14`, `dist_vwap_96` | Relative position in Donchian channels, Z-Score, RSI, and distance to VWAP |
| **Orderflow & Volume** | `vol_surge`, `taker_imb_32`, `taker_imb_96` | Relative volume surge and rolling taker buy/sell imbalance |
| **Relative Strength vs BTC** | `btc_lead_24`, `rs_vs_btc_96`, `rs_vs_btc_384` | Lead-lag impulse alpha and cumulative relative strength over Bitcoin |
| **Deep SOTA Tensors (35)** | `yz_vol_96`, `yz_vol_ratio`, `elastic_clock_mom`, `ehlers_roof_osc`, `ehlers_roof_vel`, `dist_anchored_vwap`, `frac_diff_z`, `kalman_vel_z`, `kalman_acc_z`, `kalman_gap_z`, `whale_ticket_z`, `quote_flow_imb_16`, `quote_flow_imb_64`, `vpin_toxicity_z`, `hawkes_cascade_z`, `dist_vp_poc_96`, `vp_poc_density`, `levy_path_area`, `wick_demand_pressure`, `institutional_absorption`, `sortino_asymmetry`, `shannon_entropy_96`, `hurst_vr_ratio`, `lead_lag_transfer_z`, `dyn_mom_rank`, `dyn_vol_rank`, `trend_quality_score`, `funding_rate_z`, `squeeze_thrust_idx`, `cross_dispersion_idx`, `cont_breadth_z`, `geo_shock_idx`, `macro_fng_idx`, `cs_momentum_z`, `cs_orderflow_z` | Adaptive Kalman Filter ($Q_t/R_t$), Zero-Lag Ehlers Roofing, Event-Anchored VWAP, Fractional Differentiation $d=0.35$, VPIN & Hawkes intensity, Volume Profile POC distance/density, Lévy Area path signature, candle wick demand pressure, Shannon entropy, and Cross-Sectional Attention ranks |

---

### 🏛 System Architecture

Engineered under strict dependency inversion and microservice boundaries:

```text
📦 QuantCore-GrandMaster-Server
 ┣ 📂 app
 ┃ ┣ 📂 api                             # FastAPI controllers (Telemetry, Control, Cartridges)
 ┃ ┣ 📂 cartridges                      # Pure SOTA AI Cartridges (V58, 55 features, Hot-Swap)
 ┃ ┃ ┣ 📜 cartridge_loader.py           # In-memory hot-swap service
 ┃ ┃ ┣ 📜 feature_pipe_v58.py           # Vectorized 55-feature pipeline in Float32
 ┃ ┃ ┗ 📜 v58_grand_master_cartridge.py # Multi-asset portfolio orchestrator
 ┃ ┣ 📂 core                            # Core primitives (Config, EventBus, MemoryGuard, Security)
 ┃ ┣ 📂 domain                          # DTOs (Pydantic v2), Enums, and interface contracts
 ┃ ┣ 📂 services                        # Decoupled business logic microservices
 ┃ ┃ ┣ 📜 exchange_ccxt_service.py      # Binance Futures gateway (Smart Orders, Stink-Bids)
 ┃ ┃ ┣ 📜 execution_service.py          # Supreme portfolio execution orchestrator
 ┃ ┃ ┣ 📜 market_data_service.py        # Concurrent data fetching (asyncio.gather)
 ┃ ┃ ┣ 📜 database_service.py           # Ultra-lightweight SQLite WAL service
 ┃ ┃ ┗ 📜 telegram_bot_service.py       # Long-polling bot with OTA model uploader
 ┃ ┗ 📂 web                             # Zero-dependency Bento-UI terminal in FastAPI
 ┣ 📂 tests                             # Automated pipeline and unit tests
 ┣ 📜 deploy_native.sh                  # 1-Click native systemd installer for Linux VPS
 ┣ 📜 Dockerfile                        # Production container with memory alloc guards
 ┗ 📜 main.py                           # FastAPI entrypoint + Lifespan background task runner
```

---

### 🛡️ Hardware Memory Shield & Hibernation

* **RAM Footprint (< 290 MB)**:
  All state models utilize `__slots__` and `@dataclass(slots=True)`.
* **C-Memory Trim**:
  Invokes `libc.malloc_trim(0)` at the conclusion of each calculation loop, releasing heap allocations directly to the Linux kernel.
* **Zero Disk I/O Contention**:
  SQLite operates with `PRAGMA journal_mode=WAL; PRAGMA cache_size=-4000; PRAGMA mmap_size=0;`.
* **Zero-Idle CPU**:
  CPU usage drops to **0.00%** during the 15-minute inter-candle hibernation window.

---

### 🌐 REST API & Bento-UI Web Terminal

Built-in high-performance web dashboard hosted on port `8501`:
* **URL:** `http://<SERVER_IP>:8501`
* **Authentication:** Deterministic SHA-256 session token (`DASHBOARD_PASSWORD`).
* **Capabilities:**
  * Real-time 10-asset radar (current exposure, Stop-Loss, Take-Profit, Alpha Score).
  * Interactive PnL & drawdown curves powered by Plotly.js.
  * Instant risk profile toggling (`CONSERVATIVE`, `MODERATE`, `AGGRESSIVE`).
  * One-click emergency position liquidation (Panic Button).

---

### 📱 Telegram Control Center (OTA V58)

Interactive two-way bot management:
* `/status` — Telemetry snapshot (gross leverage, RAM, active cartridge, realized PnL).
* `/radar` — Real-time 10-asset target allocation matrix.
* `/coins` — Interactive keyboard to cycle coin modes (`AUTO` ➔ `LONG_ONLY` ➔ `CORE_ONLY` ➔ `OFF`).
* **OTA (Over-The-Air) Model Uploads:** Send new `.joblib` or `.py` files directly to the bot. The engine validates weights, hot-replaces the active cartridge, and resumes trading in 1.5 seconds.

---

### 🚀 Quick Start & Deployment

#### Option 1: Native 1-Click Linux VPS Installer (Recommended)

```bash
git clone https://github.com/EdlerAG/trading_agent.git
cd trading_agent/QuantCore-GrandMaster-Server

# Configure environment variables
cp .env.example .env
nano .env

# Run automated systemd installer
chmod +x deploy_native.sh
./deploy_native.sh
```

#### Option 2: Docker Compose

```bash
cd QuantCore-GrandMaster-Server
docker-compose up -d --build
```

---

### ⚙️ Configuration (.env)

Template provided in [.env.example](QuantCore-GrandMaster-Server/.env.example):

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

### 🔒 Security & Zero-Secrets Isolation

* **Zero Credentials in Git**: All API keys, secrets, tokens, and private SSH keys are strictly excluded via `.gitignore`.
* **Zero Model Weights in Git**: Machine learning model weights (`*.joblib`, `*.pkl`) remain isolated from version control.
* **Automated CI Security Gate**: GitHub Actions pipeline rejects any commit containing accidental secrets or legacy remnants.

---
---

<a name="-українська"></a>
## 🇺🇦 Українська

**QuantCore Sovereign Server (V58.0 Pure SOTA)** — автономний сервер кількісного алготрейдингу інституційного рівня для біржі **Binance Futures (USDT-M)**.

Побудований на принципах **Clean Architecture** та **SOLID**, сервер автономно управляє диверсифікованим портфелем із **10 криптоактивів** (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LINKUSDT`, `NEARUSDT`, `SUIUSDT`, `BNBUSDT`, `AVAXUSDT`, `XRPUSDT`, `FETUSDT`), використовуючи **55 ортогональних факторів альфи**, субсекундний ML-інференс, паралельний збір маркет-даних, пасивні Stink-Bids та апаратну оптимізацію ресурсів (**< 290 МБ RAM на 1 GB VPS**).

---

### 📑 Зміст
1. [Ключові технологічні переваги V58.0](#-ключові-технологічні-переваги-v580)
2. [55 Ортогональних факторів альфи](#-55-ортогональних-факторів-альфи-1)
3. [Архітектура системи](#-архітектура-системи-1)
4. [Апаратний захист пам'яті та гібернація](#-апаратний-захист-памяті-та-гібернація-1)
5. [REST API та Bento-UI Веб-Термінал](#-rest-api-та-bento-ui-веб-термінал-1)
6. [Пульт керування в Telegram (OTA V58)](#-пульт-керування-в-telegram-ota-v58-1)
7. [Швидкий старт та розгортання](#-швидкий-старт-та-розгортання-1)
8. [Конфігурація (.env)](#-конфігурація-env-1)
9. [Безпека та ізоляція секретів](#-безпека-та-ізоляція-секретів-1)

---

### ⚡ Ключові технологічні переваги V58.0

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

### 🔬 55 Ортогональних факторів альфи

Конвеєр ознак [feature_pipe_v58.py](QuantCore-GrandMaster-Server/app/cartridges/feature_pipe_v58.py) обчислює **55 взаємно ортогональних факторів** у форматі Float32 за < 150 мс:

| Категорія | Ознаки | Фізичний зміст |
| :--- | :--- | :--- |
| **Базовий імпульс (TSMOM)** | `tsmom_24`, `tsmom_96`, `tsmom_384`, `tsmom_1536` | Лог-прибутковість за 6г, 24г, 4д, 16д, нормована на Yang-Zhang волатильність |
| **Ковзні спреди та нахили** | `spread_96_384`, `spread_384_1536`, `slope_768` | Нормовані розходження трендів та нахил 768 EMA |
| **Ефективність руху (KER)** | `signed_ker_96`, `signed_ker_288` | Коефіцієнт Кауфмана (спрямованість без паразитного шуму) |
| **Канали та рівні** | `donchian_96`, `donchian_384`, `zscore_96`, `rsi_14`, `dist_vwap_96` | Відносна позиція у Дончіан-каналі, Z-Score, RSI та відхилення від VWAP |
| **Потік ордерів та об'єм** | `vol_surge`, `taker_imb_32`, `taker_imb_96` | Сплески об'єму та дельта тейкерських покупок/продажів |
| **Відносна сила проти BTC** | `btc_lead_24`, `rs_vs_btc_96`, `rs_vs_btc_384` | Альфа-випередження та кумулятивна відносна сила до Bitcoin |
| **Глибокі SOTA-тензори (35)** | `yz_vol_96`, `yz_vol_ratio`, `elastic_clock_mom`, `ehlers_roof_osc`, `ehlers_roof_vel`, `dist_anchored_vwap`, `frac_diff_z`, `kalman_vel_z`, `kalman_acc_z`, `kalman_gap_z`, `whale_ticket_z`, `quote_flow_imb_16`, `quote_flow_imb_64`, `vpin_toxicity_z`, `hawkes_cascade_z`, `dist_vp_poc_96`, `vp_poc_density`, `levy_path_area`, `wick_demand_pressure`, `institutional_absorption`, `sortino_asymmetry`, `shannon_entropy_96`, `hurst_vr_ratio`, `lead_lag_transfer_z`, `dyn_mom_rank`, `dyn_vol_rank`, `trend_quality_score`, `funding_rate_z`, `squeeze_thrust_idx`, `cross_dispersion_idx`, `cont_breadth_z`, `geo_shock_idx`, `macro_fng_idx`, `cs_momentum_z`, `cs_orderflow_z` | Адаптивний Калман ($Q_t/R_t$), Zero-Lag Ehlers Roofing, Event-Anchored VWAP, дробове диференціювання $d=0.35$, VPIN & Hawkes, Volume Profile POC, сигнатури контуру Леві, дисбаланс тиску тіней свічок, ентропія Шеннона та крос-секційні ранги уваги |

---

### 🏛 Архітектура системи

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

### 🛡️ Апаратний захист пам'яті та гібернація

* **Фіксований буфер пам'яті (< 290 МБ RAM)**:
  Всі структури даних використовують `__slots__` та `@dataclass(slots=True)`.
* **C-Memory Trim**:
  Після кожного розрахунку викликається `libc.malloc_trim(0)`, повертаючи невикористані сторінки ядру ОС.
* **Zero Disk Bloat**:
  SQLite працює в режимі `PRAGMA journal_mode=WAL; PRAGMA cache_size=-4000; PRAGMA mmap_size=0;`.
* **Zero-Idle CPU**:
  Під час 15-хвилинної гібернації навантаження на vCPU дорівнює **0.00%**.

---

### 🌐 REST API та Bento-UI Веб-Термінал

Вбудований високошвидкісний веб-термінал доступний на порті `8501`:
* **URL:** `http://<IP_СЕРВЕРА>:8501`
* **Авторизація:** Захист за сесійними токенами SHA-256 (`DASHBOARD_PASSWORD`).
* **Можливості:**
  * Живий радар 10 активів (експозиція, Stop-Loss, Take-Profit, Alpha Score).
  * Графіки прибутковості та просадки (Plotly).
  * Гаряча зміна ризик-профілю (`CONSERVATIVE`, `MODERATE`, `AGGRESSIVE`).
  * Екстрене закриття позицій (Panic Button).

---

### 📱 Пульт керування в Telegram (OTA V58)

Телеграм-бот підтримує повне двостороннє керування сервером:
* `/status` — детальна телеметрія (експозиція, RAM, активний картридж, PnL).
* `/radar` — поточний радар 10 активів з цільовими вагами.
* `/coins` — інтерактивний пульт перемикання режимів для кожної монети (`AUTO`, `LONG_ONLY`, `OFF`).
* **OTA (Over-The-Air) Оновлення:** Надішліть новий файл `.joblib` або `.py` прямо в чат — бот перевірить його, оновить код і виконає гарячу заміну за 1.5 секунди.

---

### 🚀 Швидкий старт та розгортання

#### Варіант 1: Native 1-Клік інсталяція на Linux VPS (Рекомендовано)

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

#### Варіант 2: Запуск через Docker Compose

```bash
cd QuantCore-GrandMaster-Server
docker-compose up -d --build
```

---

### ⚙️ Конфігурація (.env)

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

### 🔒 Безпека та ізоляція секретів

* Жодні API-ключі, приватні ключі, токени ботів або навчені файли моделей `.joblib` **ніколи не потрапляють у Git**.
* Репозиторій містить виключно код рушія, конфігураційні шаблони `.env.example` та тести.
* Пайплайн **GitHub Actions** автоматично перевіряє код на відсутність застарілих компонентів і секретів при кожному пуші.

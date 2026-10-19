# ⚡ QuantCore GrandMaster Server (V23.0)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2.8%2B-E92063?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Binance Futures](https://img.shields.io/badge/Binance-Futures_USDT--M-F0B90B?style=for-the-badge&logo=binance&logoColor=black)](https://www.binance.com/)
[![Google Gemini](https://img.shields.io/badge/Google_Gemini-2.5_Flash-8E75C2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Architecture](https://img.shields.io/badge/Architecture-Clean_%26_SOLID-10B981?style=for-the-badge)](#-архітектура-системи)

**QuantCore GrandMaster Server** — високопродуктивний, суверенний автономний сервер кількісного алготрейдингу (Quantitative Trading Server) для біржі **Binance Futures (USDT-M)**. 

Побудований на принципах **Clean Architecture** та **SOLID**, сервер одночасно керує диверсифікованим портфелем із 5+ криптоактивів (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT`), використовуючи ансамблевий ML-стекінг, субсекундний інференс, адаптивне самонавчання в реальному часі та апаратний захист від вичерпання пам'яті на бюджетних VPS (**< 390 МБ RAM на 1 GB VPS**).

---

## 📑 Зміст

1. [Ключові технологічні переваги](#-ключові-технологічні-переваги)
2. [Архітектура системи](#-архітектура-системи)
3. [ШІ-Ядро V23 Grand-Master](#-ші-ядро-v23-grand-master)
4. [Апаратний захист пам'яті та гібернація](#-апаратний-захист-памяті-та-гібернація)
5. [REST API та Веб-Термінал](#-rest-api-та-веб-термінал)
6. [Пульт керування в Telegram](#-пульт-керування-в-telegram)
7. [Швидкий старт та розгортання](#-швидкий-старт-та-розгортання)
8. [Конфігурація (.env)](#-конфігурація-env)
9. [Безпека та ізоляція даних](#-безпека-та-ізоляція-даних)

---

## ⚡ Ключові технологічні переваги

* **Мультивалютна синергія 5 активів**: Єдиний портфельний оптимізатор розраховує цільові експозиції монет із врахуванням індексу ринкової широти (Market Breadth: від `-1.00` до `+1.00`) та відносної сили активів проти Bitcoin (RS vs BTC).
* **6-модельний ансамблевий ML-стекер**: Одночасне прогнозування альфи через **LightGBM**, **CatBoost**, **HistGradientBoosting**, **Ridge Regression**, **Multi-Layer Perceptron (MLP)** та **Huber Regressor**.
* **Реал-тайм самонавчання без витоків пам'яті (Online Adaptation)**:
  * *Multiplicative Weights Update (MWU)* адаптує довіру до кожної монети на кожному барі.
  * *Contextual Bandit* безперервно коригує мета-ваги під-моделей ансамблю під зміну ринкового режиму.
  * Атомарне скидання ваг у `storage/adaptive_weights.json` захищає від збоїв живлення.
* **Extreme Memory Shield (< 390 МБ RAM)**:
  * Вбудований низьколатентний Glassmorphism Bento-UI веб-термінал прямо у FastAPI (0 МБ додаткового RAM порівняно зі Streamlit).
  * Повна оптимізація через `__slots__ = (...)` та `@dataclass(slots=True)`.
  * Примусове повернення сторінок пам'яті ядру Linux через `libc.malloc_trim(0)`.
  * Потоковий моніторинг логів через `collections.deque` ($O(1)$ RAM).
* **Zero-Idle CPU Hibernation**: Процесор спить із **0.00% навантаженням на CPU** між 15-хвилинними свічками та миттєво прокидається через асинхронні події (`EventBus`).
* **Гаряча заміна моделей (AI Cartridge Hot-Swap)**: Оновлення ШІ-моделей `.joblib` на льоту прямо через чат Telegram або Web UI без перезапуску сервера за 1.5 секунди.
* **Інституційний ризик-менеджмент (CRO Watchdog)**:
  * *Daily Circuit Breaker*: Аварійний стоп-кран при досягненні 6% денної просадки.
  * *Dynamic ATR Breakeven*: Автоматичне переведення Stop-Loss у беззбиток (+0.07% буфер) при русі ціни на `+1.8x ATR`.
  * *Funding Rate & Spread Filter*: Блокування входу в позицію при несприятливій ставці фінансування або розширенні спреду.

---

## 🏛 Архітектура системи

Проєкт реалізовано за стандартом **Clean Architecture & SOLID**: сервіси мають слабку зв'язаність (Decoupled), суворі інтерфейсні контракти (`interfaces.py`), інверсію залежностей (Dependency Injection Container) та ізольоване сховище.

```text
📦 QuantCore-GrandMaster-Server
 ┣ 📜 .env.example                      # Еталонний шаблон ключів (Binance, TG, Gemini, паролі)
 ┣ 📜 .gitignore                        # Повна ізоляція (.env, storage/, *.joblib, *.db)
 ┣ 📜 deploy_native.sh                  # 1-клік інсталятор native systemd сервісу для Linux VPS
 ┣ 📜 Dockerfile                        # Легкий контейнер python:3.12-slim з оптимізацією C-аллокатора
 ┣ 📜 docker-compose.yml                # Запуск у Docker з жорстким лімітом пам'яті (mem_limit: 360m)
 ┣ 📜 requirements.txt                  # Сучасні асинхронні залежності (FastAPI 0.115+, orjson, ccxt...)
 ┣ 📜 main.py                           # Точка входу FastAPI + Lifespan-оркестратор фонових задач
 ┃
 ┣ 📂 storage                           # Ізольоване дискове сховище (автономна квота LRU, поза Git)
 ┃ ┣ 📂 cartridges                      # Каталог для гарячої заміни моделей (v23_grand_master.joblib)
 ┃ ┣ 📂 backups                         # Автоматичні щоденні бекапи SQLite для надсилання в Telegram
 ┃ ┣ 📜 trading_history.db              # SQLite база даних (WAL Mode, mmap_size=0, кеш 4 МБ)
 ┃ ┣ 📜 engine_state.json               # Атомарний зріз стану позицій, плечей та налаштувань валют
 ┃ ┗ 📜 adaptive_weights.json           # Живі ваги самонавчання (MWU + Bandit Meta-Weights)
 ┃
 ┗ 📂 app                               # Ядро системи (Clean Architecture & SOLID)
   ┣ 📂 core                            # Системні утиліти, конфігурація та апаратний контроль
   ┃ ┣ 📜 config.py                     # @dataclass(slots=True) Settings + валідований парсер .env
   ┃ ┣ 📜 memory_guard.py               # Memory & Disk Guard: gc.collect() + glibc malloc_trim(0)
   ┃ ┣ 📜 events.py                     # Асинхронна шина подій (AsyncEventBus) та wakeup-сигнали
   ┃ ┣ 📜 security.py                   # Авторизація API/Web (X-Api-Key / Bearer / Session Cookie)
   ┃ ┗ 📜 http_client.py                # Singleton-пул HTTP-з'єднань httpx.AsyncClient
   ┃
   ┣ 📂 domain                          # Доменні сутності, контракти та структури даних
   ┃ ┣ 📜 enums.py                      # CoinMode (AUTO/LONG_ONLY/OFF), CascadePhase, RiskProfile
   ┃ ┣ 📜 schemas.py                    # Внутрішні швидкі DTO з __slots__ та Pydantic v2 схеми API
   ┃ ┗ 📜 interfaces.py                 # Чисті контракти SOLID (IService, IAlphaCartridge, IExchangeGateway)
   ┃
   ┣ 📂 cartridges                      # Шар ШІ-моделей (Open/Closed Principle — змінний без правок коду)
   ┃ ┣ 📜 cartridge_loader.py           # Менеджер гарячого завантаження .joblib та відкату (Rollback)
   ┃ ┣ 📜 feature_pipe_v23.py           # Векторизований float32 пайплайн 43 факторів без фрагментації RAM
   ┃ ┗ 📜 v23_grand_master_cartridge.py # Реалізація IAlphaCartridge V23 (Team Alpha, Waterfall, 5 монет)
   ┃
   ┣ 📂 services                        # Незалежні бізнес-мікросервіси
   ┃ ┣ 📜 service_registry.py           # DI-Контейнер мікросервісів з єдиним життєвим циклом (Lifespan)
   ┃ ┣ 📜 state_service.py              # In-Memory шина стану валют з атомарним скиданням через orjson
   ┃ ┣ 📜 execution_service.py          # Мультивалютний оркестратор ребалансу та виконання ордерів
   ┃ ┣ 📜 exchange_ccxt_service.py      # Шлюз Binance Futures (One-Way Mode, Ring-Buffer свічок)
   ┃ ┣ 📜 online_adaptation_service.py  # Дворівневе реал-тайм самонавчання (MWU + Contextual Bandit)
   ┃ ┣ 📜 currency_governor_service.py  # Пульт валют: індивідуальні режими, пріоритети, ліміти плеча
   ┃ ┣ 📜 risk_guard_service.py         # Незалежний CRO Watchdog: Circuit Breaker та Dynamic ATR Breakeven
   ┃ ┣ 📜 market_data_service.py        # Дельта-завантажувач 15m свічок з кешуванням
   ┃ ┣ 📜 news_ai_service.py            # RSS парсер + Google Gemini AI макро-сентимент аналізатор
   ┃ ┣ 📜 database_service.py           # Асинхронний SQLite WAL журнал операцій та кривої Equity
   ┃ ┗ 📜 telegram_bot_service.py       # Повнофункціональний пульт керування, графіки та OTA оновлення
   ┃
   ┣ 📂 api                             # Швидкі контролери FastAPI (ORJSONResponse, Swagger /docs)
   ┃ ┣ 📜 router.py                     # Головний агрегатор маршрутів API
   ┃ ┣ 📜 endpoints_telemetry.py        # GET /state, /radar, /equity, /trades, /logs
   ┃ ┣ 📜 endpoints_control.py          # POST /coin, /risk, /pause, /wakeup, /panic, /restart
   ┃ ┗ 📜 endpoints_cartridge.py        # GET /list, POST /upload, /activate, /rollback
   ┃
   ┗ 📂 web                             # Надлегкий Веб-Термінал (0 МБ додаткового RAM)
     ┗ 📜 portal_html.py                # Glassmorphism Bento-UI термінал (HTML5 + Plotly.js CDN)
```

---

## 🧠 ШІ-Ядро V23 Grand-Master

ШІ-картридж реалізує контракт [`IAlphaCartridge`](file:///d:/Vlasne/code/trading_agent/QuantCore-GrandMaster-Server/app/domain/interfaces.py#L33-L67). Сервер взаємодіє з моделлю виключно через стандартизований виклик `compute_portfolio_targets()`, що дозволяє оновлювати математику моделі без переписування коду сервера.

### 1. Векторизований пайплайн факторів (43 ознаки)
* **Технічні індикатори**: RSI-14, MACD Hist, Bollinger Bandwidth, ATR-14, Kaufman Efficiency Ratio (KER), NATR.
* **Режими та волатильність**: Multi-timeframe Z-Scores (96 барів = 24h, 288 барів = 72h), Parkinson Volatility, Rolling Kurtosis, Skewness.
* **Міжринкова взаємодія**: Relative Strength проти BTC (`RS_BTC`), коваріація з ринковою широтою (`Core Breadth`), новинний макро-сентимент від Google Gemini.

### 2. Каскадний скінченний автомат фаз (Cascade State Machine)
Для кожної монети визначається фаза експозиції:
* **`F0 (Scanning / Cash)`**: Поза ринком (100% кеш USDT). Позиція закривається.
* **`F1 (Scout Ignition)`**: Розвідник мінімальним обсягом ($0.70x \dots 0.85x$).
* **`F2 (Core Expansion)`**: Підтверджений тренд ($1.00x \dots 1.60x$).
* **`F3 (Apex Overdrive)`**: Максимальний форсаж та імпульс ($1.65x \dots 2.50x$).
* **`F4 (Short Cascade)`**: Хеджуючий або каскадний шорт.

### 3. Профілі ризику портфеля (Portfolio Synergy)
| Профіль | Базове плече | Макс. Gross плече | Стеля на одну монету |
| :--- | :---: | :---: | :---: |
| **`CONSERVATIVE`** | `0.75x` | `1.60x` | `1.20x` |
| **`OPTIMAL`** *(рекомендовано)* | `1.00x` | `2.40x` | `1.65x` |
| **`AGGRESSIVE`** | `1.15x` | `3.20x` | `2.10x` |
| **`OVERDRIVE`** | `1.25x` | `3.50x` | `2.50x` |

---

## 🛡️ Апаратний захист пам'яті та гібернація

Сервер спеціально спроєктований для стабільної цілодобової роботи на хмарних VPS з обмеженою пам'яттю (**1 GB RAM**):

1. **Zero-Idle CPU Hibernation**:  
   Оскільки аналіз проводиться на 15-хвилинних свічках, після виконання ребалансу оркестратор переходить у глибокий сон через `asyncio.wait_for(WAKEUP_EVENT, timeout)`. Навантаження на процесор падає до **0.00% CPU**, вивільняючи ресурси сервера.
2. **Низькорівневе скидання C-пам'яті**:  
   Після кожного торгового циклу викликається `gc.collect()`, а потім через `ctypes` викликається функція стандартної бібліотеки Linux C:
   ```python
   libc = ctypes.CDLL("libc.so.6")
   libc.malloc_trim(0)
   ```
   Це повертає фрагментовані арени аллокатора назад операційній системі, утримуючи споживання **RAM у діапазоні 360–390 МБ**.
3. **Потокове читання логів**:  
   Ендпоінт читання журналу `/api/v1/logs` використовує `collections.deque(f, maxlen=lines)`, що забезпечує швидкість та фіксований $O(1)$ розмір буфера без зчитування всього файлу в пам'ять.

---

## 🌐 REST API та Веб-Термінал

Вбудований Веб-Термінал доступний за адресою `http://<IP_СЕРВЕРА>:8501`. Він виконаний в концепції **Glassmorphism Bento-UI**, транслюється напряму з пам'яті (0 МБ дискового/RAM оверхеду) і використовує бібліотеку Plotly.js через CDN.

Авторизація відбувається автоматично за паролем `DASHBOARD_PASSWORD` зі збереженням захищеного `HttpOnly` Cookie `qc_session`.

### Основні ендпоінти REST API

| Метод | URL | Опис | Авторизація |
| :--- | :--- | :--- | :---: |
| `GET` | `/` | Головний Bento-UI Веб-термінал | Публічний / Cookie |
| `POST` | `/api/v1/auth/login` | Вхід у веб-термінал (видача кукі) | Відкритий |
| `GET` | `/health` | Моніторинг RAM, здоров'я та стану паузи | Відкритий |
| `GET` | `/api/v1/state` | Повний зріз стану: баланс, 5 монет, пам'ять | `Bearer` / `Cookie` |
| `GET` | `/api/v1/radar` | Live-радар фаз (F0..F4), ваг MWU та сигналів | `Bearer` / `Cookie` |
| `GET` | `/api/v1/equity` | Векторні часові ряди кривої капіталу та просадки | `Bearer` / `Cookie` |
| `GET` | `/api/v1/trades` | Журнал виконаних угод із фільтром за монетою | `Bearer` / `Cookie` |
| `GET` | `/api/v1/logs` | Останні $N$ рядків системного логу (стримінг $O(1)$) | `Bearer` / `Cookie` |
| `POST` | `/api/v1/control/coin` | Зміна налаштувань валюти (`AUTO`, `LONG_ONLY`, плече) | `Bearer` / `Cookie` |
| `POST` | `/api/v1/control/risk` | Зміна профілю ризику (`OPTIMAL`, `AGGRESSIVE` тощо) | `Bearer` / `Cookie` |
| `POST` | `/api/v1/control/pause` | Встановлення паузи (на $N$ годин або безстроково) | `Bearer` / `Cookie` |
| `POST` | `/api/v1/control/wakeup` | Миттєве пробудження для позачергового перерахунку | `Bearer` / `Cookie` |
| `POST` | `/api/v1/control/panic` | **Екстрена ліквідація всіх позицій у кеш USDT** | `Bearer` / `Cookie` |
| `POST` | `/api/v1/control/restart`| Безпечний перезапуск сервера (systemd) | `Bearer` / `Cookie` |
| `GET` | `/api/v1/cartridge/list` | Список доступних моделей .joblib на диску | `Bearer` / `Cookie` |
| `POST` | `/api/v1/cartridge/upload`| Завантаження та **гаряча заміна (Hot-Swap)** моделі | `Bearer` / `Cookie` |
| `POST` | `/api/v1/cartridge/rollback`| Миттєвий відкат на попередню модель | `Bearer` / `Cookie` |

Інтерактивна OpenAPI документація доступна за адресою: `http://<IP_СЕРВЕРА>:8501/docs`.

---

## 📱 Пульт керування в Telegram

Telegram-бот надає повний контроль над сервером без необхідності входу в SSH-консоль:

### Команди бота
* `/status` — Загальний статус сервера, баланс, Equity, поточний лідер серед монет.
* `/radar` — Детальна матриця стану всіх 5 активів (позиція, PnL, вага, Stop-Loss).
* `/coins` — Інтерактивний пульт перемикання режимів монет (`AUTO`, `LONG_ONLY`, `OFF`).
* `/risk` — Зміна глобального профілю плеча (`CONSERVATIVE`, `OPTIMAL`, `AGGRESSIVE`, `OVERDRIVE`).
* `/chart` — Генерація та відправка PNG-графіка кривої капіталу з коефіцієнтами Шарпа та просадкою.
* `/trades` — Журнал останніх виконаних операцій.
* `/ota` — Інформація про активний картридж, пам'ять та меню оновлення.
* `/pause` / `/resume` — Керування паузою торгівлі.
* `/restart` — Безпечний перезапуск серверного процесу через `systemd`.
* `/panic` — Аварійний вихід у 100% кеш USDT.

### Оновлення «по повітрю» (OTA Updates прямо в чаті)
1. **Гаряча заміна моделі**: Надішліть файл `*.joblib` у чат — бот валідує його, завантажить у пам'ять і миттєво активує нову модель без перезапуску сервера.
2. **Оновлення коду**: Надішліть файл `*.py` або ZIP-архів з оновленими модулями — бот автоматично розкладе їх по відповідних папках `app/` та запропонує кнопку миттєвого перезапуску.

---

## 🚀 Швидкий старт та розгортання

### Варіант 1: Native systemd сервіс на Linux VPS (Рекомендовано для 1GB VPS)

Найбільш енергоефективний та стабільний варіант запуску без оверхеду віртуалізації Docker.

```bash
# 1. Клонування репозиторію
cd ~
git clone https://github.com/EdlerAG/trading_agent.git
cd trading_agent/QuantCore-GrandMaster-Server

# 2. Налаштування ключів API
cp .env.example .env
nano .env  # Заповніть ваші ключі Binance, Telegram, Gemini та пароль

# 3. 1-клік інсталяція та автозапуск systemd
chmod +x deploy_native.sh
./deploy_native.sh
```

**Керування сервісом:**
```bash
sudo systemctl status trading_bot.service   # Перевірити статус
sudo journalctl -u trading_bot.service -f   # Перегляд логів у реальному часі
sudo systemctl restart trading_bot.service  # Перезапуск
```

---

### Варіант 2: Розгортання через Docker Compose

```bash
cd QuantCore-GrandMaster-Server
cp .env.example .env
# Відредагуйте .env
docker compose up -d --build
```

---

### Варіант 3: Локальний запуск (Development / Windows / macOS)

```bash
cd QuantCore-GrandMaster-Server

# Створення віртуального оточення
python -m venv .venv

# Активація
# На Windows:
.\.venv\Scripts\Activate.ps1
# На Linux / macOS:
source .venv/bin/activate

# Встановлення залежностей
pip install -r requirements.txt

# Запуск
python main.py
```

Після запуску відкрийте браузер: `http://localhost:8501`.

---

## ⚙️ Конфігурація (.env)

Усі параметри конфігуруються через єдиний файл `.env` у корені сервера:

```env
# --- 1. Binance Futures API (Demo / Testnet та Live) ---
TESTNET_API_KEY="your_binance_api_key_here"
TESTNET_SECRET_KEY="your_binance_secret_key_here"
USE_DEMO_TRADING="true"                  # "true" для тестнету/демо, "false" для реального рахунку
EXCHANGE_LEVERAGE="3"                    # Встановлене кредитне плече на біржі

# --- 2. Telegram Bot Alert & Remote Terminal ---
TELEGRAM_TOKEN="your_telegram_bot_token"
TELEGRAM_CHAT_ID="your_telegram_chat_id"

# --- 3. Google Gemini AI (Macro News Sentiment) ---
GEMINI_API_KEY="your_gemini_api_key"
GEMINI_MODEL="gemini-2.5-flash"          # gemini-2.5-flash або gemini-3.5-flash-lite
ENABLE_NEWS_SENTIMENT="true"

# --- 4. Web Terminal & FastAPI Gateway ---
DASHBOARD_URL="http://your-server-ip:8501"
DASHBOARD_PASSWORD="change_this_secure_password"
SERVER_HOST="0.0.0.0"
SERVER_PORT="8501"

# --- 5. Мультивалютний портфель та профіль ризику ---
RISK_PROFILE="OPTIMAL"                   # CONSERVATIVE | OPTIMAL | AGGRESSIVE | OVERDRIVE
ORCHESTRATOR_MODE="PORTFOLIO_SYNERGY"    # PORTFOLIO_SYNERGY або SOLO_MAX
ACTIVE_SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT"
ENABLE_ONLINE_LEARNING="true"

# --- 6. Захист капіталу та диска (1GB RAM VPS) ---
MAX_DAILY_LOSS_PCT="0.06"                # 6% денний стоп-кран (Circuit Breaker)
MAX_STORAGE_MB="250"                     # Авто-квота сховища storage/
```

---

## 🔒 Безпека та ізоляція даних

* **Zero-Leak репозиторій**: Конфіденційні файли (`.env`, `storage/`, `*.joblib`, `*.db`, `*.log`) повністю виключені з контролю версій через `.gitignore`.
* **Захист від несанкціонованого доступу**: Будь-які зміни конфігурації через REST API або Web UI захищені паролем з криптографічним порівнянням `secrets.compare_digest()` (захист від Timing Attacks) та сесійними `HttpOnly` cookie.
* **Автономні щоденні бекапи**: SQLite база даних щоночі автоматично архівується та надсилається власнику в захищений чат Telegram.

---

## 📄 Ліцензія та відмова від відповідальності

Цей проєкт створено для дослідницьких та алгоритмічних цілей. Торгівля криптовалютними деривативами на Binance Futures пов'язана з високим рівнем фінансового ризику. Завжди ретельно тестуйте стратегії в режимі Demo (`USE_DEMO_TRADING="true"`) перед переходом на реальний капітал.

import time
from datetime import datetime, timedelta
import pandas as pd
import requests


def parse_interval_to_milliseconds(interval: str) -> int:
    """Конвертує таймфрейм Binance у мілісекунди"""
    unit = interval[-1]
    val = int(interval[:-1])
    if unit == 'm':
        return val * 60 * 1000
    elif unit == 'h':
        return val * 60 * 60 * 1000
    elif unit == 'd':
        return val * 24 * 60 * 60 * 1000
    else:
        raise ValueError(f"Невідомий формат інтервалу: {interval}")


def download_binance_history(symbol="BTCUSDT", interval="15m", target_candles=100000):
    candle_ms = parse_interval_to_milliseconds(interval)
    total_time_ms = target_candles * candle_ms

    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - total_time_ms

    start_date_str = datetime.fromtimestamp(start_time / 1000.0).strftime('%Y-%m-%d %H:%M')
    print(f"🚀 Починаємо завантаження {target_candles:,} свічок для {symbol} ({interval})...")
    print(f"📅 Розрахунковий період: з {start_date_str} до сьогодні (~{total_time_ms / (1000 * 60 * 60 * 24):.1f} днів)")

    url = "https://api.binance.com/api/v3/klines"
    all_klines = []

    # Використовуємо Session для повторного використання TCP-з'єднань (значно швидше)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (TradingBot Data Downloader)"})

    current_start = start_time
    max_retries = 5

    while current_start < end_time and len(all_klines) < target_candles:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": 1000,
            "startTime": current_start,
            "endTime": end_time
        }

        success = False
        for attempt in range(1, max_retries + 1):
            try:
                response = session.get(url, params=params, timeout=10)

                # Захист від лімітів біржі
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 10))
                    print(f"⚠️ Перевищено ліміт запитів (429). Очікування {retry_after} сек...")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                data = response.json()

                if not data:
                    print("⚠️ Отримано порожню відповідь від біржі. Завантаження завершено.")
                    current_start = end_time
                    success = True
                    break

                all_klines.extend(data)

                # Наступний чанк починається з кінця поточної свічки + 1 мс
                current_start = data[-1][6] + 1

                # Прогрес завантаження
                progress_pct = min(100.0, (len(all_klines) / target_candles) * 100)
                current_date = datetime.fromtimestamp(data[-1][0] / 1000.0).strftime('%Y-%m-%d %H:%M')
                print(
                    f"[{len(all_klines):>6,} / {target_candles:,} ({progress_pct:>5.1f}%)] | Останній бар: {current_date}")

                success = True
                time.sleep(0.15)  # Оптимальна пауза, щоб не перевантажувати API біржі
                break

            except Exception as e:
                print(f"Помилка запиту (спроба {attempt}/{max_retries}): {e}")
                time.sleep(2 * attempt)

        if not success:
            print("❌ Не вдалося отримати дані після кількох спроб. Зупинка.")
            break

    print("\n📦 Обробка та валідація отриманих даних...")
    cols = [
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
    ]
    df = pd.DataFrame(all_klines, columns=cols)

    if df.empty:
        print("❌ Немає даних для збереження.")
        return

    # Приведення типів до чисел
    numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'taker_base', 'taker_quote']
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    # Конвертація часу
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')

    # Очищення від дублікатів та сортування
    df = df.drop_duplicates(subset=['open_time']).sort_values('open_time').reset_index(drop=True)

    # Якщо завантажили трохи більше, беремо рівно останні свіжі 100 000
    if len(df) > target_candles:
        df = df.iloc[-target_candles:].reset_index(drop=True)

    filename = f"{symbol}_{interval}_history.csv"
    df.to_csv(filename, index=False)

    print(f"✅ Успішно збережено {len(df):,} свічок у файл '{filename}'!")
    print(f"📅 Охоплений період: з {df['open_time'].min()} по {df['open_time'].max()}")


if __name__ == "__main__":
    # Завантажуємо рівно 100 000 свічок по 15 хвилин
    download_binance_history(symbol="BTCUSDT", interval="15m", target_candles=100000)
import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd
from features import load_and_prepare_features


class TradingEnv(gym.Env):
    def __init__(self, df, initial_balance=1000.0, fee=0.0005):
        super().__init__()
        self.df = df
        # Агент бачитиме лише ці 3 колонки (без дат і сирих цін)
        self.features = df[['log_return', 'hl_spread', 'sma_dist']].values
        self.prices = df['close_price'].values

        self.initial_balance = initial_balance
        self.fee = fee  # Комісія біржі 0.05%

        # Дія агента: одне число від -1.0 (на всі гроші в Short) до +1.0 (на всі гроші в Long)
        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)

        # Стан ринку: 3 фінансові ознаки + 1 (поточна позиція агента) = 4 значення
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(4,), dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0.0  # Починаємо без позиції (в USDT)
        return self._get_obs(), {}

    def _get_obs(self):
        # Агент "дивиться" на поточні метрики ринку і на те, чи є в нього відкрита угода
        obs = np.append(self.features[self.current_step], self.position)
        return obs.astype(np.float32)

    def step(self, action):
        target_position = float(action[0])

        # Фіксуємо поточну ціну та ціну наступної свічки
        current_price = self.prices[self.current_step]
        self.current_step += 1
        next_price = self.prices[self.current_step]

        # 1. Рахуємо зміну ціни у відсотках
        price_change_pct = (next_price - current_price) / current_price

        # 2. Розраховуємо PnL (прибуток/збиток) від утримання позиції
        pnl = self.balance * self.position * price_change_pct

        # 3. Рахуємо комісію за зміну розміру позиції (терб тертя об ринок)
        trade_size = abs(target_position - self.position)
        fee_cost = trade_size * self.balance * self.fee

        # Оновлюємо баланс та позицію
        self.balance += (pnl - fee_cost)
        self.position = target_position

        # Винагорода для нейромережі — це чистий фінансовий результат за крок
        reward = pnl - fee_cost

        # Зупиняємо симуляцію, якщо дані закінчилися або баланс впав нижче 50%
        terminated = self.current_step >= len(self.df) - 1 or self.balance < (self.initial_balance * 0.5)

        return self._get_obs(), reward, terminated, False, {"balance": self.balance}


if __name__ == "__main__":
    # Завантажуємо наші дані з бази
    dataset = load_and_prepare_features()

    if dataset is not None:
        # Створюємо середовище
        env = TradingEnv(dataset)
        obs, _ = env.reset()
        print(f"\nПочатковий стан: {obs}")

        print("\nЗапуск симуляції: Агент робить 5 ВИПАДКОВИХ кроків...")
        for i in range(5):
            # Генеруємо випадкову дію (від -1 до 1)
            random_action = env.action_space.sample()

            # Робимо крок у середовищі
            obs, reward, terminated, truncated, info = env.step(random_action)

            print(
                f"Крок {i + 1:02d} | Дія: {random_action[0]:+5.2f} | Винагорода (PnL): {reward:+6.2f} | Баланс: {info['balance']:.2f}")
from stable_baselines3 import PPO
from Prepearing.env import TradingEnv
from features import load_and_prepare_features


def train_and_test_agent():
    # 1. Завантажуємо дані
    dataset = load_and_prepare_features()
    if dataset is None:
        return

    # 2. Ініціалізуємо середовище
    env = TradingEnv(dataset)

    print("\nІніціалізація ШІ-агента (алгоритм PPO)...")
    # MlpPolicy означає багатошаровий перцептрон (стандартна нейромережа)
    model = PPO("MlpPolicy", env, verbose=1, learning_rate=0.0003)

    print("\nПочаток навчання (10 000 кроків)...")
    # Агент пройде наше середовище (~980 рядків) близько 10 разів, щоб знайти закономірності
    model.learn(total_timesteps=10000)

    # 3. Збереження "мозку"
    model.save("ppo_trading_agent")
    print("\nНавчання завершено! Ваги збережено у файл 'ppo_trading_agent.zip'.")

    # 4. Бектест (перевірка)
    print("\nТестування НАТРЕНОВАНОГО агента (перші 10 кроків):")
    obs, _ = env.reset()

    for i in range(10):
        # Тепер дію видає не env.action_space.sample(), а натренована модель
        # deterministic=True змушує агента приймати найбільш впевнене рішення без випадковостей
        action, _states = model.predict(obs, deterministic=True)

        obs, reward, terminated, truncated, info = env.step(action)
        print(f"Крок {i + 1:02d} | Дія: {action[0]:+5.2f} | Баланс: {info['balance']:.2f} USDT")

        if terminated:
            print("Симуляцію зупинено (кінець даних або ліквідація).")
            break


if __name__ == "__main__":
    train_and_test_agent()
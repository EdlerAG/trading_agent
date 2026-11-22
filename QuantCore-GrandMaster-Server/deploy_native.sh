#!/usr/bin/env bash
# ==============================================================================
# QuantCore Sovereign Server — Native systemd 1-Click Installer
# Оптимізовано для 1GB RAM Ubuntu/Debian VPS (MemoryMax=450M, MALLOC_ARENA_MAX=2)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="trading_bot.service"
CURRENT_USER="$(id -un)"

echo "🚀 [QuantCore] Початок налаштування native systemd сервісу для: $CURRENT_USER"
echo "📂 Робоча директорія: $SCRIPT_DIR"

# 1. Перевірка або створення віртуального оточення (підтримує venv та .venv)
if [ -d "$SCRIPT_DIR/venv" ]; then
    VENV_DIR="$SCRIPT_DIR/venv"
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    VENV_DIR="$SCRIPT_DIR/.venv"
elif [ -d "$PARENT_DIR/.venv" ]; then
    VENV_DIR="$PARENT_DIR/.venv"
else
    VENV_DIR="$SCRIPT_DIR/venv"
fi

if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "⚙️ Створення віртуального оточення Python 3.12..."
    python3 -m venv "$VENV_DIR"
fi

echo "📦 Оновлення залежностей..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# 2. Перевірка наявності .env
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        echo "⚠️ Файл .env не знайдено. Створюємо з .env.example..."
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        echo "❗ Будь ласка, відредагуйте $SCRIPT_DIR/.env перед запуском!"
    fi
fi

# 3. Створення необхідних локальних папок сховища
mkdir -p "$SCRIPT_DIR/storage/cartridges"
mkdir -p "$SCRIPT_DIR/storage/backups"
mkdir -p "$SCRIPT_DIR/storage/v2_telemetry"
mkdir -p "$SCRIPT_DIR/storage/market_cache"
chmod -R 750 "$SCRIPT_DIR/storage"
if [ -f "$SCRIPT_DIR/deploy/notify_systemd_failure.sh" ]; then
    chmod +x "$SCRIPT_DIR/deploy/notify_systemd_failure.sh"
fi

# 4. Генерація systemd unit-файлу (попередня компіляція кешу Numba для швидкого старту)
echo "⚡ Попередня компіляція 50-фічевого Numba-ядра..."
PYTHONPATH="$SCRIPT_DIR:$PARENT_DIR" NUMBA_NUM_THREADS=2 "$VENV_DIR/bin/python" -c "import numpy as np, quant_v2.features as qf; p={'ts':np.arange(16,dtype=np.int64)*3600000,'symbols':np.array(['BTCUSDT','ETHUSDT','SOLUSDT']),'open':np.ones((16,3)),'high':np.ones((16,3))*1.01,'low':np.ones((16,3))*0.99,'close':np.ones((16,3)),'quote_volume':np.ones((16,3))*1e6,'taker_quote':np.ones((16,3))*5e5,'num_trades':np.ones((16,3))*100,'funding_last':np.zeros((16,3)),'valid':np.ones((16,3),bool)}; qf.compute_features(p); print('Numba cache ready!')"

ALERT_SERVICE_FILE="/etc/systemd/system/trading_bot_failure_alert.service"
sudo bash -c "cat > $ALERT_SERVICE_FILE" <<EOF
[Unit]
Description=QuantCore Dead-Man Switch Telegram Alert on Failure

[Service]
Type=oneshot
User=$CURRENT_USER
ExecStart=/bin/bash $SCRIPT_DIR/deploy/notify_systemd_failure.sh
EOF

SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
echo "🔧 Генерація $SERVICE_FILE..."

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=QuantCore V6.1 Institutional Production Core Server
After=network.target network-online.target
Wants=network-online.target
OnFailure=trading_bot_failure_alert.service

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=$SCRIPT_DIR/.env
ExecStart=$VENV_DIR/bin/python $SCRIPT_DIR/main.py

# Апаратний захист пам'яті для 1GB RAM VPS
MemoryMax=550M
MemoryHigh=450M
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$SCRIPT_DIR:$PARENT_DIR
Environment=OMP_NUM_THREADS=1
Environment=MKL_NUM_THREADS=1
Environment=OPENBLAS_NUM_THREADS=1
Environment=NUMEXPR_NUM_THREADS=1
Environment=NUMBA_NUM_THREADS=2
Environment=MALLOC_TRIM_THRESHOLD_=65536
Environment=MALLOC_ARENA_MAX=2

# Автоматичний перезапуск та коректна зупинка
Restart=always
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=15
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 5. Активація та запуск сервісу
echo "🔄 Перезавантаження демона systemd..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "✅ QuantCore Sovereign Server успішно запущено!"
echo "═════════════════════════════════════════════════════════════════════"
echo "• Статус сервісу:    sudo systemctl status $SERVICE_NAME"
echo "• Онлайн-логи:       sudo journalctl -u $SERVICE_NAME -f"
echo "• Веб-термінал:      http://\$(curl -s ifconfig.me):8501"
echo "═════════════════════════════════════════════════════════════════════"

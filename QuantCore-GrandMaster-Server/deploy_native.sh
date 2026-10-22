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

# 1. Перевірка або створення віртуального оточення
VENV_DIR="$PARENT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    VENV_DIR="$SCRIPT_DIR/.venv"
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
chmod -R 750 "$SCRIPT_DIR/storage"

# 4. Генерація systemd unit-файлу
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
echo "🔧 Генерація $SERVICE_FILE..."

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=QuantCore V58.0 Pure SOTA Server
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=$SCRIPT_DIR/.env
ExecStart=$VENV_DIR/bin/python $SCRIPT_DIR/main.py

# Апаратний захист пам'яті для 1GB RAM VPS
MemoryMax=450M
MemoryHigh=400M
Environment=OMP_NUM_THREADS=1
Environment=MKL_NUM_THREADS=1
Environment=OPENBLAS_NUM_THREADS=1
Environment=NUMEXPR_NUM_THREADS=1
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

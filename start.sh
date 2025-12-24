#!/bin/bash

# Переходим в директорию скрипта (чтобы запускалось из любого места)
cd "$(dirname "$0")"

# Проверка наличия Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 не найден. Пожалуйста, установите его (sudo apt install python3 python3-venv python3-pip)."
    exit 1
fi

# Проверка и создание venv
if [ ! -d "venv" ]; then
    echo "[INFO] Создание виртуального окружения..."
    python3 -m venv venv
fi

# Активация окружения
source venv/bin/activate

# Установка зависимостей
echo "[INFO] Установка зависимостей..."
pip install -r requirements.txt

echo ""
echo "[INFO] Запуск бота..."
echo "---------------------------------------------------"
python3 main.py
echo "---------------------------------------------------"

echo ""
read -p "Нажмите Enter, чтобы выйти..."
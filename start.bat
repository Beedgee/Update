@echo off
title FunPay Cortex Launcher
:: Включаем поддержку кириллицы в консоли
chcp 65001 > nul

echo [INFO] Проверка наличия Python...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python не найден! Установите Python (желательно 3.10 или 3.11) и обязательно поставьте галочку "Add to PATH" при установке.
    pause
    exit
)

:: Проверка наличия виртуального окружения
if not exist "venv" (
    echo [INFO] Виртуальное окружение не найдено. Создаем...
    python -m venv venv
)

:: Активация виртуального окружения
call venv\Scripts\activate

:: Обновление pip (опционально, можно убрать)
python -m pip install --upgrade pip > nul

echo [INFO] Установка/Проверка зависимостей...
pip install -r requirements.txt

echo.
echo [INFO] Запуск бота...
echo ---------------------------------------------------
python main.py
echo ---------------------------------------------------

echo.
echo [INFO] Бот завершил работу.
pause
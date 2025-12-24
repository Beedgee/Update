# FunPayCortex/first_setup.py (ОБНОВЛЕННАЯ ВЕРСИЯ)

"""
В данном модуле написана подпрограмма первичной настройки FunPayCortex.
"""

import os
from configparser import ConfigParser
import time
import telebot
from colorama import Fore, Style
from Utils.cortex_tools import hash_password

default_config = {
    "FunPay": {
        "golden_key": "",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "autoRaise": "0", "autoResponse": "0", "autoDelivery": "0", "multiDelivery": "0",
        "autoRestore": "0", "autoDisable": "0", "oldMsgGetMode": "0",
        "keepSentMessagesUnread": "0", "locale": "ru"
    },
    "Telegram": {
        "enabled": "0", "token": "", "secretKeyHash": "УстановитеСвойПароль", "blockLogin": "0"
    },
    "CortexHosting": { "url": "", "token": "" },
    "Manager": { "registration_key": "" },
    "ManagerPermissions": {
        "autoResponse": "0", "autoDelivery": "0", "templates": "0", "greetings": "0",
        "orderConfirm": "0", "reviewReply": "0", "plugins": "0", "proxy": "0", "statistics": "0"
    },
    "BlockList": {
        "blockDelivery": "0", "blockResponse": "0", "blockNewMessageNotification": "0",
        "blockNewOrderNotification": "0", "blockCommandNotification": "0"
    },
    "NewMessageView": {
        "includeMyMessages": "1", "includeFPMessages": "1", "includeBotMessages": "0",
        "notifyOnlyMyMessages": "0", "notifyOnlyFPMessages": "0", "notifyOnlyBotMessages": "0",
        "showImageName": "1"
    },
    "Greetings": {
        "ignoreSystemMessages": "0", "sendGreetings": "0", "greetingsText": "Привет, $chat_name!", "greetingsCooldown": "2"
    },
    "OrderConfirm": {
        "watermark": "1", "sendReply": "0",
        "replyText": "$username, спасибо за подтверждение заказа $order_id!\nЕсли не сложно, оставь, пожалуйста, отзыв!"
    },
    "ReviewReply": {
        "star1Reply": "0", "star2Reply": "0", "star3Reply": "0", "star4Reply": "0", "star5Reply": "0",
        "star1ReplyText": "", "star2ReplyText": "", "star3ReplyText": "", "star4ReplyText": "", "star5ReplyText": ""
    },
    "Proxy": {
        "enable": "0", "ip": "", "port": "", "login": "", "password": "", "check": "0", "checkInterval": "3600"
    },
    "Statistics": { "enabled": "1", "analysis_period": "30", "report_interval": "0" },
    # ИЗМЕНЕНИЕ ЗДЕСЬ: watermark теперь по умолчанию пустая строка
    "Other": { "watermark": "", "requestsDelay": "4", "language": "ru" }
}

def create_configs():
    if not os.path.exists("configs/auto_response.cfg"):
        with open("configs/auto_response.cfg", "w", encoding="utf-8"): pass
    if not os.path.exists("configs/auto_delivery.cfg"):
        with open("configs/auto_delivery.cfg", "w", encoding="utf-8"): pass

def create_config_obj(settings) -> ConfigParser:
    config = ConfigParser(delimiters=(":",), interpolation=None)
    config.optionxform = str
    config.read_dict(settings)
    return config

def first_setup():
    config = create_config_obj(default_config)
    sleep_time = 0.5

    print(f"{Fore.CYAN}{Style.BRIGHT}Привет! Это FunPay Cortex! {Fore.RED}(`-`)/{Style.RESET_ALL}")
    time.sleep(sleep_time)
    print(f"\n{Fore.CYAN}{Style.BRIGHT}Похоже, это первый запуск... {Fore.RED}(-_-;). . .{Style.RESET_ALL}")
    time.sleep(sleep_time)
    print(f"\n{Fore.CYAN}{Style.BRIGHT}Давай проведем быструю настройку! Остальное ты сможешь ввести уже внутри Telegram-бота. {Fore.RED}°++°{Style.RESET_ALL}")
    time.sleep(sleep_time)

    # 1. Ввод токена бота
    while True:
        print(
            f"\n{Fore.MAGENTA}{Style.BRIGHT}┌── {Fore.CYAN}Введи API-токен Telegram-бота (получить его можно у @BotFather). "
            f"Юзернейм бота должен начинаться с \"funpay\". {Fore.RED}(._.){Style.RESET_ALL}")
        token = input(f"{Fore.MAGENTA}{Style.BRIGHT}└───> {Style.RESET_ALL}").strip()
        try:
            if not token or not token.split(":")[0].isdigit(): raise ValueError("Неправильный формат токена")
            test_bot = telebot.TeleBot(token, threaded=False)
            test_bot.get_me()
            break
        except Exception as ex:
            print(f"\n{Fore.CYAN}{Style.BRIGHT}Ошибка проверки токена. Попробуй еще раз! ({ex}) {Fore.RED}\\(!!˚0˚)/{Style.RESET_ALL}")

    # 2. Ввод пароля
    while True:
        print(
            f"\n{Fore.MAGENTA}{Style.BRIGHT}┌── {Fore.CYAN}Придумай пароль для доступа к боту. Он должен содержать >8 символов, заглавные, строчные буквы и цифру. "
            f" {Fore.RED}ᴖ̮ ̮ᴖ{Style.RESET_ALL}")
        password = input(f"{Fore.MAGENTA}{Style.BRIGHT}└───> {Style.RESET_ALL}").strip()
        if (len(password) >= 8 and any(c.islower() for c in password) and
                any(c.isupper() for c in password) and any(c.isdigit() for c in password)):
            break
        print(f"\n{Fore.CYAN}{Style.BRIGHT}Пароль слишком простой. Попробуй еще раз! {Fore.RED}\\(!!˚0˚)/{Style.RESET_ALL}")

    config.set("Telegram", "enabled", "1")
    config.set("Telegram", "token", token)
    config.set("Telegram", "secretKeyHash", hash_password(password))
    
    # Остальные поля (golden_key, proxy и т.д.) остаются пустыми по умолчанию из default_config

    print(f"\n{Fore.CYAN}{Style.BRIGHT}Готово! Основные данные сохранены. "
          f"{Fore.RED}ʘ>ʘ{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}Сейчас программа перезапустится. Напиши своему боту в Telegram команду /start и введи пароль. "
          f"Бот сам попросит у тебя Golden Key. {Fore.RED}ʕ•ᴥ•ʔ{Style.RESET_ALL}")
    
    with open("configs/_main.cfg", "w", encoding="utf-8") as f:
        config.write(f)
    create_configs()
    time.sleep(3)
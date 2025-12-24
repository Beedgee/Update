from __future__ import annotations
from typing import TYPE_CHECKING

import bcrypt
import requests

from locales.localizer import Localizer

if TYPE_CHECKING:
    from cortex import Cortex

import FunPayAPI.types

from datetime import datetime
import Utils.exceptions
import itertools
import psutil
import json
import sys
import os
import re
import time
import logging
import zipfile
# --- ИСПРАВЛЕНИЕ: Правильный импорт Currency ---
from FunPayAPI.common.enums import Currency

PHOTO_RE = re.compile(r'\$photo=[\d]+')
ENTITY_RE = re.compile(r"\$photo=\d+|\$new|(\$sleep=(\d+\.\d+|\d+))")
logger = logging.getLogger("FPC.cortex_tools")
localizer = Localizer()
_ = localizer.translate

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12
}


def random_tag() -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))


def parse_wait_time(response: str) -> int:
    x = "".join([i for i in response if i.isdigit()])
    if "секунд" in response or "second" in response:
        return int(x) if x else 2
    elif "минут" in response or "хвилин" in response or "minute" in response:
        return (int(x) - 1 if x else 1) * 60
    elif "час" in response or "годин" in response or "hour" in response:
        return int((int(x) - 0.5 if x else 1) * 3600)
    else:
        return 10


def parse_currency(s: str) -> Currency:
    return {"₽": Currency.RUB,
            "€": Currency.EUR,
            "$": Currency.USD,
            "¤": Currency.RUB}.get(s, Currency.UNKNOWN)


class RegularExpressions(object):
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "instance"):
            setattr(cls, "instance", super(RegularExpressions, cls).__new__(cls))
        return getattr(cls, "instance")

    def __init__(self):
        self.ORDER_PURCHASED = re.compile(r"(Покупатель|The buyer) [a-zA-Z0-9]+ (оплатил заказ|has paid for order) #[A-Z0-9]{8}\.")
        self.ORDER_PURCHASED2 = re.compile(r"[a-zA-Z0-9]+, (не забудьте потом нажать кнопку («Подтвердить выполнение заказа»|«Подтвердить получение валюты»)\.|do not forget to press the («Confirm order fulfilment»|«Confirm currency receipt») button once you finish\.)")
        self.ORDER_CONFIRMED = re.compile(r"(Покупатель|The buyer) [a-zA-Z0-9]+ (подтвердил успешное выполнение заказа|has confirmed that order) #[A-Z0-9]{8} (и отправил деньги продавцу|has been fulfilled successfully and that the seller) [a-zA-Z0-9]+( has been paid)?\.")
        self.NEW_FEEDBACK = re.compile(r"(Покупатель|The buyer) [a-zA-Z0-9]+ (написал отзыв к заказу|has given feedback to the order) #[A-Z0-9]{8}\.")
        self.FEEDBACK_CHANGED = re.compile(r"(Покупатель|The buyer) [a-zA-Z0-9]+ (изменил отзыв к заказу|has edited their feedback to the order) #[A-Z0-9]{8}\.")
        self.FEEDBACK_DELETED = re.compile(r"(Покупатель|The buyer) [a-zA-Z0-9]+ (удалил отзыв к заказу|has deleted their feedback to the order) #[A-Z0-9]{8}\.")
        self.NEW_FEEDBACK_ANSWER = re.compile(r"(Продавец|The seller) [a-zA-Z0-9]+ (ответил на отзыв к заказу|has replied to their feedback to the order) #[A-Z0-9]{8}\.")
        self.FEEDBACK_ANSWER_CHANGED = re.compile(r"(Продавец|The seller) [a-zA-Z0-9]+ (изменил ответ на отзыв к заказу|has edited a reply to their feedback to the order) #[A-Z0-9]{8}\.")
        self.FEEDBACK_ANSWER_DELETED = re.compile(r"(Продавец|The seller) [a-zA-Z0-9]+ (удалил ответ на отзыв к заказу|has deleted a reply to their feedback to the order) #[A-Z0-9]{8}\.")
        self.ORDER_REOPENED = re.compile(r"(Заказ|Order) #[A-Z0-9]{8} (открыт повторно|has been reopened)\.")
        self.REFUND = re.compile(r"(Продавец|The seller) [a-zA-Z0-9]+ (вернул деньги покупателю|has refunded the buyer) [a-zA-Z0-9]+ (по заказу|on order) #[A-Z0-9]{8}\.")
        self.REFUND_BY_ADMIN = re.compile(r"(Администратор|The administrator) [a-zA-Z0-9]+ (вернул деньги покупателю|has refunded the buyer) [a-zA-Z0-9]+ (по заказу|on order) #[A-Z0-9]{8}\.")
        self.PARTIAL_REFUND = re.compile(r"(Часть средств по заказу|A part of the funds pertaining to the order) #[A-Z0-9]{8} (возвращена покупателю|has been refunded)\.")
        self.ORDER_CONFIRMED_BY_ADMIN = re.compile(r"(Администратор|The administrator) [a-zA-Z0-9]+ (подтвердил успешное выполнение заказа|has confirmed that order) #[A-Z0-9]{8} (и отправил деньги продавцу|has been fulfilled successfully and that the seller) [a-zA-Z0-9]+( has been paid)?\.")
        self.ORDER_ID = re.compile(r"#[A-Z0-9]{8}")
        self.DISCORD = re.compile(r"(You can switch to|Вы можете перейти в) Discord\. (However, note that friending someone is considered a violation rules|Внимание: общение за пределами сервера FunPay считается нарушением правил)\.")
        self.DEAR_VENDORS = re.compile(r"(Уважаемые продавцы|Dear vendors), (не доверяйте сообщениям в чате|do not rely on chat messages)! (Перед выполнением заказа всегда проверяйте наличие оплаты в разделе «Мои продажи»|Before you process an order, you should always check whether you've been paid in «My sales» section)\.")
        self.PRODUCTS_AMOUNT = re.compile(r",\s(\d{1,3}(?:\s?\d{3})*)\s(шт|pcs)\.")
        self.PRODUCTS_AMOUNT_ORDER = re.compile(r"(\d{1,3}(?:\s?\d{3})*)\s(шт|pcs)\.")
        self.EXCHANGE_RATE = re.compile(r"(You will receive payment in|Вы начнёте получать оплату в|Ви почнете одержувати оплату в)\s*(USD|RUB|EUR)\.\s*(Your offers prices will be calculated based on the exchange rate:|Цены ваших предложений будут пересчитаны по курсу|Ціни ваших пропозицій будуть перераховані за курсом)\s*([\d.,]+)\s*(₽|€|\$)\s*(за|for)\s*([\d.,]+)\s*(₽|€|\$)\.")


import string
import random


def count_products(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        products = f.read()
    products = products.split("\n")
    products = list(itertools.filterfalse(lambda el: not el, products))
    return len(products)


def cache_blacklist(blacklist: list[str], base_path: str) -> None:
    cache_dir = os.path.join(base_path, "storage/cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "blacklist.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(blacklist, indent=4))


def load_blacklist(base_path: str) -> list[str]:
    filepath = os.path.join(base_path, "storage/cache/blacklist.json")
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        blacklist = f.read()
        try:
            blacklist = json.loads(blacklist)
        except json.decoder.JSONDecodeError:
            return []
        return blacklist


def validate_proxy(proxy: str):
    try:
        if "@" in proxy:
            login_password, ip_port = proxy.split("@")
            login, password = login_password.split(":")
            ip, port = ip_port.split(":")
        else:
            login, password = "", ""
            ip, port = proxy.split(":")
        if not all([0 <= int(i) < 256 for i in ip.split(".")]) or ip.count(".") != 3 \
                or not ip.replace(".", "").isdigit() or not 0 <= int(port) <= 65535:
            raise Exception()
    except:
        raise ValueError("Прокси должны иметь формат login:password@ip:port или ip:port")
    return login, password, ip, port


def cache_proxy_dict(proxy_dict: dict[int, str], base_path: str) -> None:
    cache_dir = os.path.join(base_path, "storage/cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "proxy_dict.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(proxy_dict, indent=4))


def load_proxy_dict(base_path: str) -> dict[int, str]:
    filepath = os.path.join(base_path, "storage/cache/proxy_dict.json")
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        proxy = f.read()
        try:
            proxy = json.loads(proxy)
            proxy = {int(k): v for k, v in proxy.items()}
        except json.decoder.JSONDecodeError:
            return {}
        return proxy


def cache_disabled_plugins(disabled_plugins: list[str], base_path: str) -> None:
    cache_dir = os.path.join(base_path, "storage/cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "disabled_plugins.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(disabled_plugins))


def load_disabled_plugins(base_path: str) -> list[str]:
    server_config_path = os.path.join(base_path, "configs", "disabled_plugins.json")
    if os.path.exists(server_config_path):
        try:
            with open(server_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения {server_config_path}: {e}")

    filepath = os.path.join(base_path, "storage/cache/disabled_plugins.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except json.decoder.JSONDecodeError:
            return []
            
    return []


def cache_old_users(old_users: dict[int, float], base_path: str):
    cache_dir = os.path.join(base_path, "storage/cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "old_users.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(old_users, ensure_ascii=False))


def load_old_users(greetings_cooldown: float, base_path: str) -> dict[int, float]:
    filepath = os.path.join(base_path, "storage/cache/old_users.json")
    if not os.path.exists(filepath):
        return dict()
    with open(filepath, "r", encoding="utf-8") as f:
        users = f.read()
    try:
        users = json.loads(users)
    except json.decoder.JSONDecodeError:
        return dict()
    
    if type(users) == list:
        users = {user: time.time() for user in users}
    else:
        users = {int(user): time_ for user, time_ in users.items() if
                 time.time() - time_ < greetings_cooldown * 24 * 60 * 60}
    cache_old_users(users, base_path)
    return users


def mask_ip(ip_address: str) -> str:
    octets = ip_address.split('.')
    if len(octets) == 4:
        return f"{octets[0]}.{octets[1]}.***.***"
    return "**.**.**.**"


def check_proxy(proxy: dict) -> bool:
    logger.debug(_("crd_checking_proxy"))
    try:
        response = requests.get("https://api.ipify.org/", proxies=proxy, timeout=10)
        response.raise_for_status()
        masked_ip = mask_ip(response.content.decode())
        
        logger.debug(_("crd_proxy_success", masked_ip))
        return True
    except requests.exceptions.RequestException as e:
        logger.error(_("crd_proxy_err"))
        logger.debug(f"TRACEBACK (check_proxy): {e}", exc_info=False)
        return False
    except Exception:
        logger.error(_("crd_proxy_err"))
        logger.debug("TRACEBACK", exc_info=True)
        return False

def create_greeting_text(cortex_instance: Cortex):
    account = cortex_instance.account
    balance = cortex_instance.balance
    current_time = datetime.now()
    if current_time.hour < 4:
        greetings = "Какая прекрасная ночь"
    elif current_time.hour < 12:
        greetings = "Доброе утро"
    elif current_time.hour < 17:
        greetings = "Добрый день"
    else:
        greetings = "Добрый вечер"

    lines = [
        f"* {greetings}, $CYAN{account.username}.",
        f"* Ваш ID: $YELLOW{account.id}.",
        f"* Ваш текущий баланс: $CYAN{balance.total_rub} RUB $RESET| $MAGENTA{balance.total_usd} USD $RESET| $YELLOW{balance.total_eur} EUR",
        f"* Текущие незавершенные сделки: $YELLOW{account.active_sales}.",
        f"* Удачной торговли!"
    ]

    length = 60
    greetings_text = f"\n{'-' * length}\n"
    for line in lines:
        greetings_text += line + " " * (length - len(
            line.replace("$CYAN", "").replace("$YELLOW", "").replace("$MAGENTA", "").replace("$RESET",
                                                                                             "")) - 1) + "$RESET*\n"
    greetings_text += f"{'-' * length}\n"
    return greetings_text


def time_to_str(time_: int):
    days = time_ // 86400
    hours = (time_ - days * 86400) // 3600
    minutes = (time_ - days * 86400 - hours * 3600) // 60
    seconds = time_ - days * 86400 - hours * 3600 - minutes * 60

    if not any([days, hours, minutes, seconds]):
        return "0 сек"
    time_str = ""
    if days:
        time_str += f"{days}д"
    if hours:
        time_str += f" {hours}ч"
    if minutes:
        time_str += f" {minutes}мин"
    if seconds:
        time_str += f" {seconds}сек"
    return time_str.strip()


def get_month_name(month_number: int) -> str:
    months = [
        "Января", "Февраля", "Марта",
        "Апреля", "Мая", "Июня",
        "Июля", "Августа", "Сентября",
        "Октября", "Ноября", "Декабря"
    ]
    if month_number > len(months):
        return months[0]
    return months[month_number - 1]


def get_products(path: str, amount: int = 1) -> list[list[str] | int] | None:
    with open(path, "r", encoding="utf-8") as f:
        products = f.read()

    products = products.split("\n")
    products = list(itertools.filterfalse(lambda el: not el, products))

    if not products:
        raise Utils.exceptions.NoProductsError(path)
    elif len(products) < amount:
        raise Utils.exceptions.NotEnoughProductsError(path, len(products), amount)

    got_products = products[:amount]
    save_products = products[amount:]
    amount = len(save_products)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(save_products))

    return [got_products, amount]


def add_products(path: str, products: list[str], at_zero_position=False):
    if not at_zero_position:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(products))
    else:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(products) + "\n" + text)


def safe_text(text: str):
    return "⁣".join(text)


def format_msg_text(text: str, obj: FunPayAPI.types.Message | FunPayAPI.types.ChatShortcut) -> str:
    date_obj = datetime.now()
    month_name = get_month_name(date_obj.month)
    date = date_obj.strftime("%d.%m.%Y")
    str_date = f"{date_obj.day} {month_name}"
    str_full_date = str_date + f" {date_obj.year} года"

    time_ = date_obj.strftime("%H:%M")
    time_full = date_obj.strftime("%H:%M:%S")

    username = obj.author if isinstance(obj, FunPayAPI.types.Message) else obj.name
    chat_name = obj.chat_name if isinstance(obj, FunPayAPI.types.Message) else obj.name
    chat_id = str(obj.chat_id) if isinstance(obj, FunPayAPI.types.Message) else str(obj.id)

    variables = {
        "$full_date_text": str_full_date,
        "$date_text": str_date,
        "$date": date,
        "$time": time_,
        "$full_time": time_full,
        "$username": safe_text(username),
        "$message_text": str(obj),
        "$chat_id": chat_id,
        "$chat_name": safe_text(chat_name)
    }

    for var in variables:
        text = text.replace(var, variables[var])
    return text


def format_order_text(text: str, order: FunPayAPI.types.OrderShortcut | FunPayAPI.types.Order) -> str:
    date_obj = datetime.now()
    month_name = get_month_name(date_obj.month)
    date = date_obj.strftime("%d.%m.%Y")
    str_date = f"{date_obj.day} {month_name}"
    str_full_date = str_date + f" {date_obj.year} года"
    time_ = date_obj.strftime("%H:%M")
    time_full = date_obj.strftime("%H:%M:%S")
    game = subcategory_fullname = subcategory = ""
    try:
        if isinstance(order, FunPayAPI.types.OrderShortcut) and not order.subcategory:
            game, subcategory = order.subcategory_name.rsplit(", ", 1)
            subcategory_fullname = f"{subcategory} {game}"
        else:
            subcategory_fullname = order.subcategory.fullname
            game = order.subcategory.category.name
            subcategory = order.subcategory.name
    except:
        logger.warning("Произошла ошибка при парсинге игры из заказа")
        logger.debug("TRACEBACK", exc_info=True)
    description = order.description if isinstance(order,
                                                  FunPayAPI.types.OrderShortcut) else order.short_description if order.short_description else ""
    params = order.lot_params_text if isinstance(order, FunPayAPI.types.Order) and order.lot_params else ""
    variables = {
        "$full_date_text": str_full_date,
        "$date_text": str_date,
        "$date": date,
        "$time": time_,
        "$full_time": time_full,
        "$username": safe_text(order.buyer_username),
        "$order_desc_and_params": f"{description}, {params}" if description and params else f"{description}{params}",
        "$order_desc_or_params": description if description else params,
        "$order_desc": description,
        "$order_title": description,
        "$order_params": params,
        "$order_id": order.id,
        "$order_link": f"https://funpay.com/orders/{order.id}/",
        "$category_fullname": subcategory_fullname,
        "$category": subcategory,
        "$game": game
    }

    for var in variables:
        text = text.replace(var, variables[var])
    return text


def restart_program():
    python = sys.executable
    os.execl(python, python, *sys.argv)
    try:
        process = psutil.Process()
        for handler in process.open_files():
            os.close(handler.fd)
        for handler in process.connections():
            os.close(handler.fd)
    except:
        pass


def shut_down():
    try:
        process = psutil.Process()
        process.terminate()
    except:
        pass


def set_console_title(title: str) -> None:
    try:
        if os.name == 'nt':
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(title)
    except:
        logger.warning("Произошла ошибка при изменении названия консоли")
        logger.debug("TRACEBACK", exc_info=True)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')


def check_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))


def zipdir(path, zip_obj):
    for root, dirs, files in os.walk(path):
        if os.path.basename(root) == "__pycache__":
            continue
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, os.path.join(path, '..'))
            
            try:
                mtime = os.path.getmtime(full_path)
                
                if mtime < 315532800:
                    zinfo = zipfile.ZipInfo(rel_path, (1980, 1, 1, 0, 0, 0))
                    with open(full_path, 'rb') as f:
                        zip_obj.writestr(zinfo, f.read())
                else:
                    zip_obj.write(full_path, rel_path)
                    
            except OSError:
                pass
            except Exception as e:
                logger.warning(f"Не удалось добавить файл {file} в бэкап: {e}")


def create_backup() -> int:
    logger.info("Создание резервной копии...")
    try:
        with zipfile.ZipFile("backup.zip", "w", zipfile.ZIP_DEFLATED) as zip_f:
            for folder in ["storage", "configs"]:
                if os.path.exists(folder):
                    zipdir(folder, zip_f)
                else:
                    logger.warning(f"Папка '{folder}' для бэкапа не найдена, пропуск.")
        logger.info("Резервная копия успешно создана: backup.zip")
        return 0
    except Exception as e:
        logger.error(f"Ошибка при создании резервной копии: {e}")
        logger.debug("TRACEBACK", exc_info=True)
        return 1
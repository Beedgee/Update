# FunPayCortex/tg_bot/utils.py (ПОЛНАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ)

# -*- coding: utf-8 -*-

"""
FunPayBot by @beedge
--------------------------
Модуль с утилитами и вспомогательными функциями для Telegram-бота.
Включает загрузку/сохранение данных, форматирование текста, управление
состояниями пользователей и другие полезные инструменты.
"""

from __future__ import annotations
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex import Cortex

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
import os.path
import json
import time
from tg_bot import CBT
from locales.localizer import Localizer
import Utils.cortex_tools # Добавлен импорт для доступа к утилите

localizer = Localizer()
_ = localizer.translate

class NotificationTypes:
    """
    Константы для типов Telegram-уведомлений.
    """
    bot_start = "1"
    new_message = "2"
    command = "3"
    new_order = "4"
    order_confirmed = "5"
    review = "5r"
    lots_restore = "6"
    lots_deactivate = "7"
    delivery = "8"
    lots_raise = "9"
    other = "10"
    announcement = "11"
    ad = "12"
    critical = "13"
    important_announcement = "14"

# --- Функции для работы с данными (кэш и хостинг) ---
def load_authorized_users(base_path: str) -> dict[int, dict[str, str | None]]:
    """
    Загружает авторизованных пользователей из кэша.
    """
    filepath = os.path.join(base_path, "storage/cache/tg_authorized_users.json")
    if not os.path.exists(filepath): return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f: data = json.load(f)

        migrated, result = False, {}
        
        if isinstance(data, list): # Миграция со старого формата [int]
            result = {int(uid): {"username": None, "role": "admin"} for uid in data if isinstance(uid, int)}
            migrated = True
        elif isinstance(data, dict):
            for k, v in data.items():
                try:
                    user_id = int(k)
                    if isinstance(v, dict) and "role" in v: result[user_id] = v
                    else: # Миграция со старого формата {id: username}
                        result[user_id] = {"username": str(v) if v else None, "role": "admin"}
                        migrated = True
                except (ValueError, TypeError): continue
        
        if migrated:
            dir_path = os.path.join(base_path, "storage/cache/")
            with open(os.path.join(dir_path, "tg_authorized_users.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=4)
        return result
    except (json.JSONDecodeError, FileNotFoundError): return {}

def load_notification_settings(base_path: str) -> dict:
    """Загружает настройки Telegram-уведомлений из кэша."""
    filepath = os.path.join(base_path, "storage/cache/notifications.json")
    if not os.path.exists(filepath): return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return {}

def load_answer_templates(base_path: str) -> list[str]:
    """Загружает шаблоны ответов из кэша."""
    filepath = os.path.join(base_path, "storage/cache/answer_templates.json")
    if not os.path.exists(filepath): return []
    try:
        with open(filepath, "r", encoding="utf-8") as f: templates = json.load(f)
        return [str(item) for item in templates if isinstance(item, (str, int, float))] if isinstance(templates, list) else []
    except (json.JSONDecodeError, FileNotFoundError): return []


def save_authorized_users(cortex_instance: "Cortex", users: dict[int, dict]) -> None:
    """
    Сохраняет ID и роли авторизованных пользователей в отдельном потоке.
    """
    def threaded_save():
        dir_path = os.path.join(cortex_instance.base_path, "storage/cache/")
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, "tg_authorized_users.json"), "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        cortex_instance.save_json_setting("authorized_users", users)
    
    cortex_instance.executor.submit(threaded_save)


def save_notification_settings(cortex_instance: "Cortex", settings: dict) -> None:
    """Сохраняет настройки Telegram-уведомлений в отдельном потоке."""
    def threaded_save():
        dir_path = os.path.join(cortex_instance.base_path, "storage/cache/")
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, "notifications.json"), "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        cortex_instance.save_json_setting("notifications", settings)

    cortex_instance.executor.submit(threaded_save)

def save_answer_templates(cortex_instance: "Cortex", templates: list[str]) -> None:
    """Сохраняет шаблоны ответов в отдельном потоке."""
    def threaded_save():
        dir_path = os.path.join(cortex_instance.base_path, "storage/cache/")
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, "answer_templates.json"), "w", encoding="utf-8") as f:
            json.dump(templates, f, ensure_ascii=False, indent=4)
        cortex_instance.save_json_setting("templates", templates)

    cortex_instance.executor.submit(threaded_save)

# --- Вспомогательные функции ---
def get_user_role(users_dict: dict, user_id: int) -> str | None:
    """Возвращает роль пользователя ('admin' | 'manager') или None."""
    user_data = users_dict.get(user_id)
    return user_data.get("role") if isinstance(user_data, dict) else None

def escape(text: str) -> str:
    """Экранирует HTML-теги в тексте."""
    if not isinstance(text, str): text = str(text)
    return text.replace("&", "&").replace("<", "<").replace(">", ">")

def bool_to_text(value, on: str = "🟢", off: str = "🔴"):
    """Преобразует булево значение в текстовый статус с эмодзи."""
    return on if value and str(value) != "0" else off

def get_offset(element_index: int, max_elements_on_page: int) -> int:
    """Вычисляет смещение для пагинации."""
    page_num = element_index // max_elements_on_page
    return page_num * max_elements_on_page

def add_navigation_buttons(keyboard: K, offset: int, limit: int, on_page_count: int, total_count: int, cb_text: str, extra: list | None = None) -> K:
    """Добавляет кнопки навигации ('<<', '<', 'стр/всего', '>', '>>') к клавиатуре."""
    if total_count <= limit: return keyboard
    
    extra_cb = ":" + ":".join(map(str, extra)) if extra else ""
    current_page = (offset // limit) + 1
    total_pages = math.ceil(total_count / limit)
    
    nav_row = []
    if current_page > 1:
        nav_row.append(B("⏪ 1", callback_data=f"{cb_text}:0{extra_cb}"))
        nav_row.append(B("⬅️", callback_data=f"{cb_text}:{offset - limit}{extra_cb}"))
        
    nav_row.append(B(f"{current_page}/{total_pages}", callback_data=CBT.EMPTY))
    
    if current_page < total_pages:
        nav_row.append(B("➡️", callback_data=f"{cb_text}:{offset + limit}{extra_cb}"))
        last_page_offset = (total_pages - 1) * limit
        nav_row.append(B(f"{total_pages} ⏩", callback_data=f"{cb_text}:{last_page_offset}{extra_cb}"))
        
    keyboard.row(*nav_row)
    return keyboard


def get_current_proxy_str(proxy_section) -> str:
    """Возвращает текущий прокси в виде строки."""
    ip, port = proxy_section.get("ip"), proxy_section.get("port")
    login, password = proxy_section.get("login"), proxy_section.get("password")
    if not ip or not port: return ""
    return f"{f'{login}:{password}@' if login and password else ''}{ip}:{port}"


# --- ИЗМЕНЕНИЕ: Новая функция для маскировки прокси ---
def mask_proxy_string(proxy_str: str) -> str:
    """
    Маскирует чувствительные части строки прокси для безопасного отображения.
    Форматы: login:password@ip:port и ip:port
    """
    if not proxy_str:
        return "<i>(не задан)</i>"
    try:
        if "@" in proxy_str:
            credentials, address = proxy_str.split("@", 1)
            login, password = credentials.split(":", 1)
            masked_creds = f"{login}:****"
        else:
            address = proxy_str
            masked_creds = ""

        ip_parts = address.split(":")
        ip = ip_parts[0]
        port = ip_parts[1] if len(ip_parts) > 1 else ""
        
        octets = ip.split('.')
        if len(octets) == 4:
            masked_ip = f"{octets[0]}.{octets[1]}.***.***"
        else:
            masked_ip = "**.**.**.**" 
            
        masked_address = f"{masked_ip}:{port}"
        return f"{masked_creds}@{masked_address}" if masked_creds else masked_address
    except Exception:
        return "<i>(ошибка формата)</i>"

# --- Генераторы текста для сообщений ---
def generate_profile_text(cortex_instance: Cortex) -> str:
    """Генерирует текст с информацией об аккаунте для команды /profile."""
    acc = cortex_instance.account
    return f"""
👤 <b>Профиль FunPay:</b> <a href="https://funpay.com/users/{acc.id}/">{escape(acc.username)}</a>
<b>ID:</b> <code>{acc.id}</code>
🛒 <b>Активных заказов:</b> <code>{acc.active_sales}</code>

⏱ <i>Обновлено: {time.strftime('%H:%M:%S, %d.%m.%Y', time.localtime(acc.last_update))}</i>
"""

def generate_balance_text(cortex_instance: Cortex) -> str:
    """Генерирует текст с информацией о балансе аккаунта."""
    acc = cortex_instance.account
    bal = cortex_instance.balance
    
    return f"""
💰 <b>Баланс аккаунта «{escape(acc.username)}»</b>

🇷🇺 <b>RUB:</b>
 • <i>Всего:</i> <code>{bal.total_rub:,.2f} ₽</code>
 • <i>Доступно к выводу:</i> <code>{bal.available_rub:,.2f} ₽</code>

🇺🇸 <b>USD:</b>
 • <i>Всего:</i> <code>{bal.total_usd:,.2f} $</code>
 • <i>Доступно к выводу:</i> <code>{bal.available_usd:,.2f} $</code>

🇪🇺 <b>EUR:</b>
 • <i>Всего:</i> <code>{bal.total_eur:,.2f} €</code>
 • <i>Доступно к выводу:</i> <code>{bal.available_eur:,.2f} €</code>

⏱ <i>Обновлено: {time.strftime('%H:%M:%S, %d.%m.%Y', time.localtime(acc.last_update))}</i>
""".replace(",", " ")

def generate_lot_info_text(cortex_instance: "Cortex", lot_obj) -> str:
    """Генерирует текст с информацией о лоте автовыдачи."""
    file_name = lot_obj.get("productsFileName")
    products_amount_text = f"<code>∞</code> ({_('gf_infinity')})"

    if file_name:
        full_path = os.path.join(cortex_instance.base_path, "storage/products", file_name)
        file_display_path = os.path.join('storage/products', file_name)
        if os.path.exists(full_path):
            try: products_amount_text = f"<code>{Utils.cortex_tools.count_products(full_path)}</code>"
            except: products_amount_text = f"<code>⚠️</code> ({_('gf_count_error')})"
            file_info = f"<code>{escape(file_display_path)}</code>"
        else:
            products_amount_text = "<code>-</code>"
            file_info = f"<code>{escape(file_display_path)}</code> (⚠️ {_('gf_file_not_found_short')})"
    else:
        file_info = f"<i>({_('gf_not_linked')})</i>"
    
    return f"""
📦 <b>Лот «{escape(lot_obj.name)}»</b>

📜 <b>Текст выдачи:</b>
<i>{escape(lot_obj.get("response", _("text_not_set")))}</i>

🔢 <b>Товаров в наличии:</b> {products_amount_text}
🗂️ <b>Привязанный файл:</b> {file_info}
"""

def send_or_edit_message(bot, msg, text, reply, kb):
    """Отправляет или редактирует сообщение в зависимости от типа `msg`."""
    chat_id = msg.chat.id if isinstance(msg, Message) else msg.message.chat.id
    if isinstance(msg, Message) and reply:
        bot.reply_to(msg, text, reply_markup=kb)
    elif isinstance(msg, CallbackQuery):
        bot.edit_message_text(text, chat_id, msg.message.id, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)
# tg_bot/statistics_cp.py

from __future__ import annotations
import json
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
import os
import requests

from FunPayAPI.common.enums import OrderStatuses
from FunPayAPI.common.utils import RegularExpressions
from FunPayAPI.updater.events import NewMessageEvent, OrderStatusChangedEvent, NewOrderEvent
from FunPayAPI.types import MessageTypes

from locales.localizer import Localizer
from tg_bot import CBT, keyboards as kb, utils
from tg_bot.static_keyboards import CLEAR_STATE_BTN
from telebot.types import CallbackQuery, Message

if TYPE_CHECKING:
    from cortex import Cortex

localizer = Localizer()
_ = localizer.translate

WITHDRAWAL_FORECAST_FILE = "storage/cache/withdrawal_forecast.json"
LOCAL_STATS_FILE = "storage/cache/local_stats.json"

# Убираем проверки уровня доступа, так как это self-hosted версия
def ensure_files_exist(cortex: Cortex):
    path = os.path.join(cortex.base_path, LOCAL_STATS_FILE)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)

def upload_sales_to_backend(cortex: Cortex, sales: list):
    """
    Вместо отправки на бэкенд, сохраняем продажи в локальный JSON.
    """
    path = os.path.join(cortex.base_path, LOCAL_STATS_FILE)
    ensure_files_exist(cortex)
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            local_data = json.load(f)
    except:
        local_data = []

    # Преобразуем входящие продажи в словарь для простоты
    existing_ids = {item["order_id"] for item in local_data}
    
    updated = False
    for sale in sales:
        status_str = sale.status.name if hasattr(sale.status, 'name') else str(sale.status)
        currency_str = str(sale.currency)
        date_iso = sale.date.isoformat() if sale.date else datetime.now().isoformat()
        
        sale_obj = {
            "order_id": sale.id,
            "description": sale.description,
            "price": sale.price,
            "currency": currency_str,
            "status": status_str,
            "buyer_username": sale.buyer_username,
            "date": date_iso,
            "timestamp": sale.date.timestamp() if sale.date else time.time()
        }

        # Если заказ уже есть, обновляем его статус
        found = False
        for i, item in enumerate(local_data):
            if item["order_id"] == sale.id:
                local_data[i] = sale_obj
                found = True
                updated = True
                break
        
        if not found:
            local_data.append(sale_obj)
            updated = True

    if updated:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(local_data, f, ensure_ascii=False, indent=2)


def get_stats_from_backend(cortex: Cortex, period_days: int | None):
    """
    Генерирует статистику на основе локального JSON файла.
    """
    path = os.path.join(cortex.base_path, LOCAL_STATS_FILE)
    ensure_files_exist(cortex)
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return None

    # Фильтрация по времени
    if period_days is not None:
        cutoff_time = time.time() - (period_days * 86400)
        filtered_data = [x for x in data if x.get("timestamp", 0) >= cutoff_time]
    else:
        filtered_data = data

    sales_count = 0
    sales_sum = {}
    refund_count = 0
    refund_sum = {}

    for item in filtered_data:
        curr = item["currency"]
        price = item["price"]
        status = item["status"]

        # Логика подсчета (адаптируйте статусы под ваши Enum)
        # Обычно 'closed', 'paid' - это успех. 'refunded' - возврат.
        if status in ["refunded", "OrderStatuses.REFUNDED"]:
            refund_count += 1
            refund_sum[curr] = refund_sum.get(curr, 0) + price
        elif status in ["closed", "paid", "OrderStatuses.CLOSED", "OrderStatuses.PAID"]:
            sales_count += 1
            sales_sum[curr] = sales_sum.get(curr, 0) + price

    return {
        "sales_count": sales_count,
        "sales_sum": sales_sum,
        "refund_count": refund_count,
        "refund_sum": refund_sum
    }

# ... (load_forecast и save_forecast оставляем без изменений) ...
def load_forecast(cortex: Cortex):
    path = os.path.join(cortex.base_path, WITHDRAWAL_FORECAST_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cortex.withdrawal_forecast = json.load(f)
        except:
            cortex.withdrawal_forecast = {}
    else:
        cortex.withdrawal_forecast = {}

def save_forecast(cortex: Cortex):
    def threaded_save():
        path = os.path.join(cortex.base_path, WITHDRAWAL_FORECAST_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cortex.withdrawal_forecast, f, ensure_ascii=False, indent=2)
    cortex.executor.submit(threaded_save)

def periodic_sales_update(cortex: Cortex):
    load_forecast(cortex)
    scan_and_sync(cortex) # Первый скан
    
    report_interval_hours = cortex.MAIN_CFG["Statistics"].getint("report_interval", 0)
    last_report_time = time.time()

    while True:
        # Убраны проверки уровня доступа
        if report_interval_hours > 0 and time.time() - last_report_time >= report_interval_hours * 3600:
            scan_and_sync(cortex) 
            period_days = cortex.MAIN_CFG["Statistics"].getint("analysis_period", 30)
            stats_data = get_stats_from_backend(cortex, period_days)
            
            if stats_data:
                msg = format_stats_message(cortex, f"{period_days} дн.", stats_data)
                cortex.telegram.send_notification(f"📊 <b>Ежедневный отчет по статистике:</b>\n\n{msg}")
            last_report_time = time.time()
        
        time.sleep(1800) 
        scan_and_sync(cortex)

def scan_and_sync(cortex: Cortex):
    # Убрана проверка уровня доступа
    try:
        next_pos = None
        for _ in range(3): 
            time.sleep(1)
            # Получаем продажи с FP
            result = cortex.account.get_sales(start_from=next_pos, include_paid=True, include_closed=True, include_refunded=True)
            next_pos, orders_list, _, _ = result
            
            if orders_list:
                upload_sales_to_backend(cortex, orders_list) # Теперь это локальная функция
            
            if not next_pos:
                break
    except Exception as e:
        print(f"[Stats] Error during background scan: {e}")

# ... (format_price_summary и format_stats_message оставляем без изменений) ...
def format_price_summary(price_dict: dict) -> str:
    if not price_dict: return "0 ¤"
    return " | ".join([f"<b>{value:,.2f}</b> {currency}".replace(",", " ") for currency, value in sorted(price_dict.items())])

def format_stats_message(cortex: Cortex, period_name: str, stats: dict) -> str:
    # (Код этой функции из оригинала оставляем без изменений)
    if not cortex.balance:
        return f"📊 <b>Статистика за {period_name}</b>\n\n⚠️ Не удалось загрузить данные о балансе."

    now = time.time()
    forecast = {"hour": {}, "day": {}, "2day": {}}
    
    for order_id, data in list(cortex.withdrawal_forecast.items()):
        if now - data["time"] > 172800:
            del cortex.withdrawal_forecast[order_id]
            continue
        currency, price = data["currency"], data["price"]
        if now - data["time"] < 3600:
            forecast["hour"][currency] = forecast["hour"].get(currency, 0) + price
        if now - data["time"] < 86400:
            forecast["day"][currency] = forecast["day"].get(currency, 0) + price
        if now - data["time"] < 172800:
            forecast["2day"][currency] = forecast["2day"].get(currency, 0) + price

    sales_sum_formatted = format_price_summary(stats.get('sales_sum', {}))
    refund_sum_formatted = format_price_summary(stats.get('refund_sum', {}))

    return f"""
📊 <b>Статистика за {period_name}</b>

💰 <b><u>Финансы</u></b>
 • <b>Баланс:</b> <code>{cortex.balance.total_rub:,.2f} ₽, {cortex.balance.total_usd:,.2f} $, {cortex.balance.total_eur:,.2f} €</code>
 • <b>К выводу:</b> <code>{cortex.balance.available_rub:,.2f} ₽, {cortex.balance.available_usd:,.2f} $, {cortex.balance.available_eur:,.2f} €</code>

⏳ <b><u>Прогноз поступлений</u></b>
 • <b>~1 час:</b>  +{format_price_summary(forecast['hour'])}
 • <b>~1 день:</b> +{format_price_summary(forecast['day'])}
 • <b>~2 дня:</b>  +{format_price_summary(forecast['2day'])}

📈 <b><u>Продажи</u></b>
 • <b>Количество:</b> <code>{stats.get('sales_count', 0)} шт.</code>
 • <b>Сумма:</b> {sales_sum_formatted}

📉 <b><u>Возвраты</u></b>
 • <b>Количество:</b> <code>{stats.get('refund_count', 0)} шт.</code>
 • <b>Сумма:</b> {refund_sum_formatted}
    """.replace(",", " ")

def init_statistics_cp(cortex: Cortex, *args):
    tg = cortex.telegram
    bot = tg.bot

    def open_statistics_menu(c: CallbackQuery):
        # УБРАНА ПРОВЕРКА УРОВНЯ ДОСТУПА
        bot.answer_callback_query(c.id)

        period_key = c.data.split(":")[1]
        
        if period_key == "main":
            bot.edit_message_text("📊 <b>Статистика</b>\n\nВыберите период для анализа (Данные хранятся локально):", c.message.chat.id, c.message.id,
                                  reply_markup=kb.statistics_menu(cortex))
            return

        def threaded_job():
            period_names = {"day": "последний день", "week": "последнюю неделю", "month": "последний месяц", "all": "всё время"}
            period_days = {"day": 1, "week": 7, "month": 30, "all": None}.get(period_key)

            stats_data = get_stats_from_backend(cortex, period_days)
            
            if stats_data:
                msg_text = format_stats_message(cortex, period_names.get(period_key, "выбранный период"), stats_data)
            else:
                msg_text = "❌ Данных о статистике пока нет."

            try:
                bot.edit_message_text(msg_text, c.message.chat.id, c.message.id, reply_markup=kb.statistics_menu(cortex))
            except: pass

        cortex.executor.submit(threaded_job)


    def open_statistics_config(c: CallbackQuery):
        # УБРАНА ПРОВЕРКА УРОВНЯ ДОСТУПА
        action = c.data.split(":")[1]
        if action == "main":
            bot.edit_message_text("⚙️ <b>Настройки статистики</b>", c.message.chat.id, c.message.id,
                                  reply_markup=kb.statistics_config_menu(cortex))
        elif action == "set_period":
            result = bot.send_message(c.message.chat.id, "🔢 Введите новый период анализа в днях:", reply_markup=CLEAR_STATE_BTN())
            tg.set_state(c.message.chat.id, result.id, c.from_user.id, f"{CBT.STATS_CONFIG_MENU}:set_period")
        elif action == "set_interval":
            result = bot.send_message(c.message.chat.id, "⏰ Введите интервал для авто-отчета в часах (0 для отключения):", reply_markup=CLEAR_STATE_BTN())
            tg.set_state(c.message.chat.id, result.id, c.from_user.id, f"{CBT.STATS_CONFIG_MENU}:set_interval")
        bot.answer_callback_query(c.id)
    
    def set_analysis_period(m: Message):
        # УБРАНА ПРОВЕРКА УРОВНЯ ДОСТУПА
        tg.clear_state(m.chat.id, m.from_user.id, True)
        def threaded_save():
            try:
                days = int(m.text.strip())
                if days <= 0: raise ValueError
                cortex.MAIN_CFG.set("Statistics", "analysis_period", str(days))
                cortex.save_config(cortex.MAIN_CFG, os.path.join(cortex.base_path, "configs/_main.cfg"))
                bot.send_message(m.chat.id, f"✅ Период анализа изменен на <b>{days}</b> дн.", reply_markup=kb.statistics_config_menu(cortex))
            except ValueError:
                bot.send_message(m.chat.id, "❌ Неверное значение.")
        cortex.executor.submit(threaded_save)
            
    def set_report_interval(m: Message):
        # УБРАНА ПРОВЕРКА УРОВНЯ ДОСТУПА
        tg.clear_state(m.chat.id, m.from_user.id, True)
        def threaded_save():
            try:
                hours = int(m.text.strip())
                if hours < 0: raise ValueError
                cortex.MAIN_CFG.set("Statistics", "report_interval", str(hours))
                cortex.save_config(cortex.MAIN_CFG, os.path.join(cortex.base_path, "configs/_main.cfg"))
                bot.send_message(m.chat.id, "✅ Интервал авто-отчетов успешно изменен.", reply_markup=kb.statistics_config_menu(cortex))
            except ValueError:
                bot.send_message(m.chat.id, "❌ Неверное значение.")
        cortex.executor.submit(threaded_save)
            
    tg.cbq_handler(open_statistics_menu, lambda c: c.data.startswith(f"{CBT.STATS_MENU}:"))
    tg.cbq_handler(open_statistics_config, lambda c: c.data.startswith(f"{CBT.STATS_CONFIG_MENU}:"))
    tg.msg_handler(set_analysis_period, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, f"{CBT.STATS_CONFIG_MENU}:set_period"))
    tg.msg_handler(set_report_interval, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, f"{CBT.STATS_CONFIG_MENU}:set_interval"))

def sales_update_hook(cortex: Cortex, event: NewOrderEvent):
    # Локальное сохранение
    upload_sales_to_backend(cortex, [event.order])

def order_status_hook(cortex: Cortex, event: OrderStatusChangedEvent):
    # Локальное сохранение
    upload_sales_to_backend(cortex, [event.order])

def withdrawal_forecast_hook(cortex: Cortex, event: NewMessageEvent):
    # Оставляем как есть, работает локально
    if event.message.type not in [MessageTypes.ORDER_CONFIRMED, MessageTypes.ORDER_CONFIRMED_BY_ADMIN,
                                  MessageTypes.ORDER_REOPENED, MessageTypes.REFUND, MessageTypes.REFUND_BY_ADMIN]:
        return

    order_id_match = RegularExpressions().ORDER_ID.findall(str(event.message))
    if not order_id_match: return
    order_id = order_id_match[0][1:]

    if event.message.type in [MessageTypes.ORDER_REOPENED, MessageTypes.REFUND, MessageTypes.REFUND_BY_ADMIN]:
        if order_id in cortex.withdrawal_forecast:
            del cortex.withdrawal_forecast[order_id]
            save_forecast(cortex)
    else: 
        order = cortex.get_order_from_object(event.message)
        if not order or order.buyer_id == cortex.account.id: return
        cortex.withdrawal_forecast[order_id] = {"time": int(time.time()), "price": order.sum, "currency": str(order.currency)}
        save_forecast(cortex)

BIND_TO_PRE_INIT = [init_statistics_cp]
BIND_TO_NEW_ORDER = [sales_update_hook] 
BIND_TO_ORDER_STATUS_CHANGED = [order_status_hook]
BIND_TO_NEW_MESSAGE = [withdrawal_forecast_hook]
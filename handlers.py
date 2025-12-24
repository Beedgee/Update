# --- START OF FILE FunPayCortex/handlers.py ---

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex import Cortex

# ИЗМЕНЕНИЕ: Добавлен прямой импорт FunPayAPI для доступа к FunPayAPI.types.MessageTypes
import FunPayAPI
from FunPayAPI.types import OrderShortcut, Order, Currency
from FunPayAPI import exceptions, utils as fp_utils
from FunPayAPI.updater.events import *

from tg_bot import utils, keyboards
from Utils import cortex_tools, exceptions as UtilsExceptions
from locales.localizer import Localizer
from threading import Lock
import configparser
from datetime import datetime
import logging
import time
import re
import io

logger = logging.getLogger("FPC.handlers")
localizer = Localizer()
_ = localizer.translate

ORDER_HTML_TEMPLATE = """<a href="https://funpay.com/orders/DELITEST/" class="tc-item">
   <div class="tc-date" bis_skin_checked="1">
      <div class="tc-date-time" bis_skin_checked="1">сегодня, $date</div>
      <div class="tc-date-left" bis_skin_checked="1">только что</div>
   </div>
   <div class="tc-order" bis_skin_checked="1">#DELITEST</div>
   <div class="order-desc" bis_skin_checked="1">
      <div bis_skin_checked="1">$lot_name</div>
      <div class="text-muted" bis_skin_checked="1">Автовыдача, Тест</div>
   </div>
   <div class="tc-user" bis_skin_checked="1">
      <div class="media media-user offline" bis_skin_checked="1">
         <div class="media-left" bis_skin_checked="1">
            <div class="avatar-photo pseudo-a" tabindex="0" data-href="https://funpay.com/users/000000/" style="background-image: url(/img/layout/avatar.png);" bis_skin_checked="1"></div>
         </div>
         <div class="media-body" bis_skin_checked="1">
            <div class="media-user-name" bis_skin_checked="1">
               <span class="pseudo-a" tabindex="0" data-href="https://funpay.com/users/000000/">$username</span>
            </div>
            <div class="media-user-status" bis_skin_checked="1">был 1.000.000 лет назад</div>
         </div>
      </div>
   </div>
   <div class="tc-status text-primary" bis_skin_checked="1">Оплачен</div>
   <div class="tc-price text-nowrap tc-seller-sum" bis_skin_checked="1">999999.0 <span class="unit">₽</span></div>
</a>"""

def send_startup_error_notifications(c: Cortex, *args):
    if c.telegram is None:
        return

    if c.AR_CFG_LOAD_ERROR:
        text = "⚠️ <b>Ошибка загрузки конфигурации!</b>\n\nФайл <code>configs/auto_response.cfg</code> содержит ошибку.\n\nМодуль <b>Автоответчик</b> будет работать с пустой конфигурацией. Пожалуйста, исправьте файл или настройте команды заново через Telegram-бота."
        c.telegram.send_notification(text, notification_type=utils.NotificationTypes.critical)

    if c.AD_CFG_LOAD_ERROR:
        text = "⚠️ <b>Ошибка загрузки конфигурации!</b>\n\nФайл <code>configs/auto_delivery.cfg</code> содержит ошибку.\n\nМодуль <b>Автовыдача</b> будет работать с пустой конфигурацией. Пожалуйста, исправьте файл или настройте автовыдачу заново через Telegram-бота."
        c.telegram.send_notification(text, notification_type=utils.NotificationTypes.critical)

def save_init_chats_handler(c: Cortex, e: InitialChatEvent):
    if c.MAIN_CFG["Greetings"].getboolean("sendGreetings") and e.chat.id not in c.old_users:
        c.old_users[e.chat.id] = int(time.time())
        cortex_tools.cache_old_users(c.old_users, c.base_path)

def old_log_msg_handler(c: Cortex, e: LastChatMessageChangedEvent):
    if not c.old_mode_enabled:
        return
    text, chat_name, chat_id = str(e.chat), e.chat.name, e.chat.id
    username = c.account.username if not e.chat.unread else e.chat.name

    logger.info(_("log_new_msg", chat_name, chat_id))
    for index, line in enumerate(text.split("\n")):
        if not index:
            logger.info(f"$MAGENTA└───> $YELLOW{username}: $CYAN{line}")
        else:
            logger.info(f"      $CYAN{line}")


def log_msg_handler(c: Cortex, e: NewMessageEvent):
    # --- ИСПРАВЛЕНИЕ ДУБЛЕЙ В ЛОГАХ ---
    # Если пришла пачка сообщений, логируем её только один раз (на последнем событии)
    if e.stack and e.stack.get_stack():
        last_msg = e.stack.get_stack()[-1].message
        if e.message.id != last_msg.id:
            return
    # ----------------------------------

    chat_name, chat_id = e.message.chat_name, e.message.chat_id

    logger.info(_("log_new_msg", chat_name, chat_id))
    for index, event in enumerate(e.stack.get_stack()):
        username, text = event.message.author, event.message.text or event.message.image_link
        for line_index, line in enumerate(text.split("\n")):
            if not index and not line_index:
                logger.info(f"$MAGENTA└───> $YELLOW{username}: $CYAN{line}")
            elif not line_index:
                logger.info(f"      $YELLOW{username}: $CYAN{line}")
            else:
                logger.info(f"      $CYAN{line}")

def greetings_handler(c: Cortex, e: NewMessageEvent | LastChatMessageChangedEvent):
    """
    Улучшенный обработчик приветствий.
    1. Не отвечает, если диалог начал владелец бота.
    2. Не отвечает на системное сообщение о покупке.
    """
    if not c.MAIN_CFG["Greetings"].getboolean("sendGreetings"):
        return

    # 1. Извлекаем данные из события в зависимости от режима работы
    if not c.old_mode_enabled:
        if isinstance(e, LastChatMessageChangedEvent):
            return
        obj = e.message
        chat_id, chat_name, mtype, its_me, badge = obj.chat_id, obj.chat_name, obj.type, obj.author_id == c.account.id, obj.badge
    else:
        obj = e.chat
        chat_id, chat_name, mtype, its_me, badge = obj.id, obj.name, obj.last_message_type, not obj.unread, None

    # 2. Новая логика: если сообщение от владельца бота, помечаем чат как "старый" и выходим.
    if its_me:
        if chat_id not in c.old_users:
            c.old_users[chat_id] = int(time.time())
            cortex_tools.cache_old_users(c.old_users, c.base_path)
        return

    # 3. Проверяем кулдаун.
    with c.greeting_lock:
        greetings_cooldown_seconds = float(c.MAIN_CFG["Greetings"]["greetingsCooldown"]) * 24 * 60 * 60
        if chat_id in c.old_users and (time.time() - c.old_users.get(chat_id, 0) < greetings_cooldown_seconds):
            return

        # 4. Улучшенная фильтрация: добавляем проверку на сообщение о покупке.
        ignore_conditions = [
            mtype == FunPayAPI.types.MessageTypes.ORDER_PURCHASED,
            mtype in (FunPayAPI.types.MessageTypes.DEAR_VENDORS, FunPayAPI.types.MessageTypes.ORDER_CONFIRMED_BY_ADMIN),
            badge is not None,
            (mtype is not FunPayAPI.types.MessageTypes.NON_SYSTEM and c.MAIN_CFG["Greetings"].getboolean("ignoreSystemMessages"))
        ]
        
        if any(ignore_conditions):
            return
        
        # Если все проверки пройдены, помечаем пользователя как "старого"
        c.old_users[chat_id] = int(time.time())
        cortex_tools.cache_old_users(c.old_users, c.base_path)

    # 5. Отправляем приветствие в отдельном потоке
    def threaded_send():
        logger.info(_("log_sending_greetings", chat_name, chat_id))
        text = cortex_tools.format_msg_text(c.MAIN_CFG["Greetings"]["greetingsText"], obj)
        c.send_message(chat_id, text, chat_name)

    c.executor.submit(threaded_send)


def send_response_handler(c: Cortex, e: NewMessageEvent | LastChatMessageChangedEvent):
    if not c.autoresponse_enabled:
        return
    if not c.old_mode_enabled:
        if isinstance(e, LastChatMessageChangedEvent):
            return
        obj, mtext = e.message, str(e.message)
        chat_id, chat_name, username = e.message.chat_id, e.message.chat_name, e.message.author
    else:
        obj, mtext = e.chat, str(e.chat)
        chat_id, chat_name, username = obj.id, obj.name, obj.name

    mtext = mtext.replace("\n", "")
    if any([c.bl_response_enabled and username in c.blacklist, (command := mtext.strip().lower()) not in c.AR_CFG]):
        return
    
    def threaded_send():
        logger.info(_("log_new_cmd", command, chat_name, chat_id))
        response_text = cortex_tools.format_msg_text(c.AR_CFG[command]["response"], obj)
        c.send_message(chat_id, response_text, chat_name)

    c.executor.submit(threaded_send)


def old_send_new_msg_notification_handler(c: Cortex, e: LastChatMessageChangedEvent):
    if any([not c.old_mode_enabled, not c.telegram, not e.chat.unread,
            c.bl_msg_notification_enabled and e.chat.name in c.blacklist,
            e.chat.last_message_type is not FunPayAPI.types.MessageTypes.NON_SYSTEM, str(e.chat).strip().lower() in c.AR_CFG.sections(),
            str(e.chat).startswith("!автовыдача")]):
        return
    user = e.chat.name
    if user in c.blacklist:
        user = f"🚷 {user}"
    elif e.chat.last_by_bot:
        user = f"🧠 {user}"
    else:
        user = f"👤 {user}"
    text = f"<i><b>{user}: </b></i><code>{utils.escape(str(e.chat))}</code>"
    kb = keyboards.reply(e.chat.id, e.chat.name, extend=True)
    c.executor.submit(c.telegram.send_notification, text, kb, utils.NotificationTypes.new_message)


def send_new_msg_notification_handler(c: Cortex, e: NewMessageEvent) -> None:
    if not c.telegram:
        return

    chat_id, chat_name = e.message.chat_id, e.message.chat_name
    if c.bl_msg_notification_enabled and chat_name in c.blacklist:
        return

    # --- НОВАЯ ЛОГИКА ДЕДУПЛИКАЦИИ ---
    unique_events = []
    # Получаем список событий (если это стек) или одно событие
    raw_events = e.stack.get_stack() if e.stack else [e]
    
    for i in raw_events:
        # Уникальный ключ: ChatID_MessageID
        msg_unique_key = f"{chat_id}_{i.message.id}"
        
        # Проверяем, есть ли атрибут (на случай если cortex.py еще не обновлен, чтобы не крашнулось)
        if hasattr(c, 'processed_message_ids'):
            if msg_unique_key in c.processed_message_ids:
                continue # Дубликат, пропускаем
            c.processed_message_ids.append(msg_unique_key)
        
        unique_events.append(i)
    
    if not unique_events:
        return
    # -----------------------------------

    events = []
    nm, m, f, b = False, False, False, False
    
    # Используем отфильтрованный список unique_events вместо e.stack.get_stack()
    for i in unique_events:
        if i.message.author_id == 0:
            if c.include_fp_msg_enabled:
                events.append(i)
                f = True
        elif i.message.by_bot:
            if c.include_bot_msg_enabled:
                events.append(i)
                b = True
        elif i.message.author_id == c.account.id:
            if c.include_my_msg_enabled:
                events.append(i)
                m = True
        else:
            events.append(i)
            nm = True

    if not events:
        return

    if [m, f, b, nm].count(True) == 1 and \
            any([m and not c.only_my_msg_enabled, f and not c.only_fp_msg_enabled, b and not c.only_bot_msg_enabled]):
        return

    text = ""
    last_message_author_id = -1
    last_by_bot = False
    last_badge = None
    last_by_vertex = False
    
    # Итерируемся по отфильтрованным событиям для формирования текста
    for i in events:
        message_text = str(i.message)
        if message_text.strip().lower() in c.AR_CFG.sections() and len(events) < 2:
            return
        elif message_text.startswith("!автовыдача") and len(events) < 2:
            return
        if i.message.author_id == last_message_author_id and i.message.by_bot == last_by_bot and \
                i.message.badge == last_badge and i.message.by_vertex == last_by_vertex:
            author = ""
        elif i.message.author_id == c.account.id:
            author = f"<i><b>🤖 {_('you')} (<i>FPCortex</i>):</b></i> " if i.message.by_bot else f"<i><b>🫵 {_('you')}:</b></i> "
            if i.message.is_autoreply:
                author = f"<i><b>📦 {_('you')} ({i.message.badge}):</b></i> "
        elif i.message.author_id == 0:
            author = f"<i><b>🔵 {i.message.author}: </b></i>"
        elif i.message.is_employee:
            author = f"<i><b>🆘 {i.message.author} ({i.message.badge}): </b></i>"
        elif i.message.author == i.message.chat_name:
            author = f"<i><b>👤 {i.message.author}: </b></i>"
            if i.message.is_autoreply:
                author = f"<i><b>🛍️ {i.message.author} ({i.message.badge}):</b></i> "
            elif i.message.author in c.blacklist:
                author = f"<i><b>🚷 {i.message.author}: </b></i>"
            elif i.message.by_bot:
                author = f"<i><b>🧠 {i.message.author}: </b></i>"
            elif i.message.by_vertex:
                author = f"<i><b>🐺 {i.message.author}: </b></i>"
        else:
            author = f"<i><b>🆘 {i.message.author} ({_('support')}): </b></i>"
        msg_text = f"<code>{utils.escape(i.message.text)}</code>" if i.message.text else \
            f"<a href=\"{i.message.image_link}\">" \
            f"{c.show_image_name and not (i.message.author_id == c.account.id and i.message.by_bot) and i.message.image_name or _('photo')}</a>"
        text += f"{author}{msg_text}\n\n"
        last_message_author_id = i.message.author_id
        last_by_bot = i.message.by_bot
        last_by_vertex = i.message.by_vertex
        last_badge = i.message.badge
    kb = keyboards.reply(chat_id, chat_name, extend=True)
    c.executor.submit(c.telegram.send_notification, text, kb, utils.NotificationTypes.new_message)


def send_review_notification(c: Cortex, order: Order, chat_id: int, reply_text: str | None):
    if not c.telegram:
        return
    reply_text = _("ntfc_review_reply_text").format(utils.escape(reply_text)) if reply_text else ""
    c.executor.submit(c.telegram.send_notification,
                      _("ntfc_new_review").format('⭐' * order.review.stars, order.id, utils.escape(order.review.text),
                                                 reply_text),
                      keyboards.new_order(order.id, order.buyer_username, chat_id),
                      utils.NotificationTypes.review)


def process_review_handler(c: Cortex, e: NewMessageEvent | LastChatMessageChangedEvent):
    """
    Обрабатывает новые отзывы, пытается ответить на них с использованием системы
    повторных попыток и отправляет детальные уведомления об ошибках в Telegram.
    """
    if not c.old_mode_enabled:
        if isinstance(e, LastChatMessageChangedEvent):
            return
        obj = e.message
        message_type, its_me = obj.type, obj.i_am_buyer
        message_text, chat_id = str(obj), obj.chat_id

    else:
        obj = e.chat
        message_type, its_me = obj.last_message_type, f" {c.account.username} " in str(obj)
        message_text, chat_id = str(obj), obj.id

    if message_type not in [FunPayAPI.types.MessageTypes.NEW_FEEDBACK, FunPayAPI.types.MessageTypes.FEEDBACK_CHANGED] or its_me:
        return

    def threaded_task():
        try:
            order = c.get_order_from_object(obj)
            if order is None:
                raise Exception("Не удалось получить объект заказа.")
        except Exception:
            logger.error(f"Не удалось получить информацию о заказе для сообщения: \"{message_text}\".")
            logger.debug("TRACEBACK", exc_info=True)
            return

        if not order.review or not order.review.stars:
            return

        logger.info(f"Обнаружен новый/измененный отзыв на заказ #{order.id}.")

        toggle = f"star{order.review.stars}Reply"
        text_key = f"star{order.review.stars}ReplyText"
        reply_text = None

        # Проверяем, нужно ли вообще отвечать
        if c.MAIN_CFG["ReviewReply"].getboolean(toggle) and c.MAIN_CFG["ReviewReply"].get(text_key):
            try:
                # Вложенная функция для форматирования текста ответа
                def format_text4review(text_: str):
                    max_l = 999
                    if len(text_) > max_l:
                        text_ = text_[:max_l] + "..."
                    text_ = text_.strip()
                    # Уменьшаем количество переносов строк, если их слишком много
                    while text_.count("\n") > 9:
                        text_ = text_[::-1].replace("\n", " ", 1)[::-1]
                    return text_

                reply_text = cortex_tools.format_order_text(c.MAIN_CFG["ReviewReply"].get(text_key), order)
                reply_text = format_text4review(reply_text)

                # Система повторных попыток отправки ответа
                for attempt in range(3, 0, -1):
                    try:
                        c.account.send_review(order.id, reply_text)
                        logger.info(f"Успешно оставлен ответ на отзыв к заказу #{order.id}.")
                        break  # Выходим из цикла, если успешно
                    except (exceptions.FeedbackEditingError, exceptions.RequestFailedError) as ex:
                        logger.warning(f"Ошибка при ответе на отзыв #{order.id} (попытка {4-attempt}/3): {ex.short_str()}")
                        logger.debug("TRACEBACK", exc_info=True)
                        
                        if attempt == 1: # Если это была последняя попытка
                            error_details = f"Класс ошибки: {ex.__class__.__name__}\n" \
                                            f"Код ответа: {getattr(ex, 'status_code', 'N/A')}\n\n" \
                                            f"Текст ответа от FunPay:\n{getattr(ex.response, 'text', 'Нет данных')}"

                            error_caption = f"❌ <b>Не удалось ответить на отзыв к заказу</b> <code>{order.id}</code>\n\n" \
                                            f"<b>Причина:</b> <code>{utils.escape(ex.short_str())}</code>\n\n" \
                                            f"Бот попытался 3 раза, но не смог оставить ответ. Подробности ошибки — в файле."
                            
                            # Если лог слишком большой, отправляем его файлом
                            if len(error_details) > 3800:
                                with io.BytesIO(error_details.encode('utf-8')) as file:
                                    file.name = f'error_log_review_{order.id}.txt'
                                    c.telegram.send_notification(None,
                                                                 notification_type=utils.NotificationTypes.critical,
                                                                 photo=file, # Используем параметр photo для отправки файла
                                                                 caption=error_caption)
                            else:
                                c.telegram.send_notification(f"{error_caption}\n\n<pre>{utils.escape(error_details)}</pre>",
                                                             notification_type=utils.NotificationTypes.critical)
                        
                        time.sleep(3)  # Ждем перед следующей попыткой
                else: # Этот блок выполнится, если цикл завершился без break (все попытки неудачны)
                    logger.error(f"Не удалось отправить ответ на отзыв {order.id} после 3 попыток.")

            except Exception as e:
                logger.error(f"Произошла непредвиденная ошибка при обработке ответа на отзыв {order.id}.")
                logger.debug("TRACEBACK", exc_info=True)
        
        # Уведомляем о самом факте нового отзыва
        send_review_notification(c, order, chat_id, reply_text)

    c.executor.submit(threaded_task)


def send_command_notification_handler(c: Cortex, e: NewMessageEvent | LastChatMessageChangedEvent):
    if not c.telegram:
        return
    if not c.old_mode_enabled:
        if isinstance(e, LastChatMessageChangedEvent):
            return
        obj, message_text = e.message, str(e.message)
        chat_id, chat_name, username = e.message.chat_id, e.message.chat_name, e.message.author
    else:
        obj, message_text = e.chat, str(e.chat)
        chat_id, chat_name, username = obj.id, obj.name, obj.name if obj.unread else c.account.username

    if c.bl_cmd_notification_enabled and username in c.blacklist:
        return
    command = message_text.strip().lower()
    if command not in c.AR_CFG or not c.AR_CFG[command].getboolean("telegramNotification"):
        return

    if not c.AR_CFG[command].get("notificationText"):
        text = f"🧑‍💻 Пользователь <b><i>{username}</i></b> ввел команду <code>{utils.escape(command)}</code>."
    else:
        text = cortex_tools.format_msg_text(c.AR_CFG[command]["notificationText"], obj)

    c.executor.submit(c.telegram.send_notification, text, keyboards.reply(chat_id, chat_name),
                      utils.NotificationTypes.command)


def test_auto_delivery_handler(c: Cortex, e: NewMessageEvent | LastChatMessageChangedEvent):
    if not c.old_mode_enabled:
        if isinstance(e, LastChatMessageChangedEvent):
            return
        obj, message_text, chat_name, chat_id = e.message, str(e.message), e.message.chat_name, e.message.chat_id
    else:
        obj, message_text, chat_name, chat_id = e.chat, str(e.chat), e.chat.name, e.chat.id

    if not message_text.startswith("!автовыдача"):
        return
    
    def threaded_task():
        split = message_text.split()
        if len(split) < 2:
            logger.warning("Одноразовый ключ автовыдачи не обнаружен.")
            return

        key = split.strip()
        if key not in c.delivery_tests:
            logger.warning("Невалидный одноразовый ключ автовыдачи.")
            return

        lot_name = c.delivery_tests[key]
        del c.delivery_tests[key]
        date = datetime.now()
        date_text = date.strftime("%H:%M")
        html = ORDER_HTML_TEMPLATE.replace("$username", chat_name).replace("$lot_name", lot_name).replace("$date",
                                                                                                        date_text)

        fake_order = OrderShortcut("ADTEST", lot_name, 0.0, Currency.UNKNOWN, chat_name, 000000, chat_id,
                                FunPayAPI.types.OrderStatuses.PAID,
                                date, "Авто-выдача, Тест", None, html)

        fake_event = NewOrderEvent(e.runner_tag, fake_order)
        c.run_handlers(c.new_order_handlers, (c, fake_event,))

    c.executor.submit(threaded_task)


def send_categories_raised_notification_handler(c: Cortex, cat: FunPayAPI.types.Category, error_text: str = "") -> None:
    if not c.telegram or not c.running:
        return

    text = f"""⤴️<b><i>Поднял все лоты категории</i></b> <code>{cat.name}</code>\n<tg-spoiler>{error_text}</tg-spoiler>"""
    try:
        c.executor.submit(c.telegram.send_notification, text,
                          notification_type=utils.NotificationTypes.lots_raise)
    except RuntimeError:
        pass

def get_lot_config_by_name(c: Cortex, name: str) -> configparser.SectionProxy | None:
    for i in c.AD_CFG.sections():
        if i in name:
            return c.AD_CFG[i]
    return None


def check_products_amount(config_obj: configparser.SectionProxy) -> int:
    file_name = config_obj.get("productsFileName")
    if not file_name:
        return 1
    return cortex_tools.count_products(f"storage/products/{file_name}")


def update_current_lots_handler(c: Cortex, e: OrdersListChangedEvent):
    # Оборачиваем логику в функцию для выполнения в отдельном потоке
    def worker():
        logger.info("Получаю информацию о лотах (фоновый процесс)...")
        attempts = 3
        while attempts:
            try:
                # Получаем профиль
                c.curr_profile = c.account.get_user(c.account.id)
                # Обновляем тег только после успешного получения
                c.curr_profile_last_tag = e.runner_tag
                
                # Явно вызываем обновление лотов профиля здесь, так как мы в потоке
                # и основной цикл уже прошел этот шаг
                update_profile_lots_handler(c, e)
                break
            except Exception as ex:
                logger.error(f"Ошибка при фоновом обновлении лотов: {ex}")
                # Если ошибка 403/401 - нет смысла долбиться, выходим
                if "403" in str(ex) or "401" in str(ex):
                    break
                attempts -= 1
                time.sleep(2)
        else:
            logger.error("Не удалось получить информацию о лотах в фоне: превышено кол-во попыток.")

    # Отправляем задачу в пул потоков Cortex, чтобы не блокировать Runner
    c.executor.submit(worker)


def update_profile_lots_handler(c: Cortex, e: OrdersListChangedEvent):
    # Если теги не совпадают, значит фоновый поток update_current_lots_handler
    # еще не завершил работу и не обновил данные. Просто выходим.
    # Данные обновятся, когда worker вызовет эту функцию в конце своей работы.
    if c.curr_profile_last_tag != e.runner_tag or c.profile_last_tag == e.runner_tag:
        return
        
    c.profile_last_tag = e.runner_tag
    
    if c.curr_profile:
        lots = c.curr_profile.get_sorted_lots(1)
        for lot_id, lot in lots.items():
            c.profile.update_lot(lot)

def log_new_order_handler(c: Cortex, e: NewOrderEvent, *args):
    logger.info(f"Новый заказ! ID: $YELLOW#{e.order.id}$RESET")


def setup_event_attributes_handler(c: Cortex, e: NewOrderEvent, *args):
    config_section_name = None
    config_section_obj = None
    lot_description = e.order.description
    for lot in sorted(list(c.profile.get_sorted_lots(2).get(e.order.subcategory, {}).values()),
                      key=lambda l: len(f"{l.server}, {l.description}"), reverse=True):
        if lot.server and lot.description:
            temp_desc = f"{lot.server}, {lot.description}"
        elif lot.server:
            temp_desc = lot.server
        else:
            temp_desc = lot.description

        if temp_desc in e.order.description:
            lot_description = temp_desc
            break

    for i in range(3):
        for lot_name in c.AD_CFG:
            if i == 0:
                rule = lot_description == lot_name
            elif i == 1:
                rule = lot_description.startswith(lot_name)
            else:
                rule = lot_name in lot_description

            if rule:
                config_section_obj = c.AD_CFG[lot_name]
                config_section_name = lot_name
                break
        if config_section_obj:
            break

    attributes = {"config_section_name": config_section_name, "config_section_obj": config_section_obj,
                  "delivered": False, "delivery_text": None, "goods_delivered": 0, "goods_left": None,
                  "error": 0, "error_text": None}
    for i in attributes:
        setattr(e, i, attributes[i])

    if config_section_obj is None:
        logger.info("Лот не найден в конфиге авто-выдачи!")
    else:
        logger.info("Лот найден в конфиге авто-выдачи!")


def send_new_order_notification_handler(c: Cortex, e: NewOrderEvent, *args):
    if not c.telegram:
        return
    if e.order.buyer_username in c.blacklist and c.MAIN_CFG["BlockList"].getboolean("blockNewOrderNotification"):
        return

    def threaded_task():
        full_order = c.get_order_from_object(e.order)

        if not (config_obj := getattr(e, "config_section_obj")):
            delivery_info = _("ntfc_new_order_not_in_cfg")
        else:
            if not c.autodelivery_enabled:
                delivery_info = _("ntfc_new_order_ad_disabled")
            elif config_obj.getboolean("disable"):
                delivery_info = _("ntfc_new_order_ad_disabled_for_lot")
            elif c.bl_delivery_enabled and e.order.buyer_username in c.blacklist:
                delivery_info = _("ntfc_new_order_user_blocked")
            else:
                delivery_info = _("ntfc_new_order_will_be_delivered")

        if full_order:
            text = _("ntfc_new_order",
                     f"{utils.escape(e.order.description)}, {utils.escape(e.order.subcategory_name)}",
                     e.order.buyer_username,
                     e.order.price,
                     e.order.currency,
                     full_order.sum,
                     full_order.currency,
                     e.order.id,
                     delivery_info)
        else:
            text = _("ntfc_new_order_fallback", f"{utils.escape(e.order.description)}, {utils.escape(e.order.subcategory_name)}",
                     e.order.buyer_username, f"{e.order.price} {e.order.currency}", e.order.id, delivery_info)

        chat = c.account.get_chat_by_name(e.order.buyer_username, True)
        if chat:
            keyboard = keyboards.new_order(e.order.id, e.order.buyer_username, chat.id)
            c.telegram.send_notification(text, keyboard, utils.NotificationTypes.new_order)
        else:
            logger.warning(f"Не удалось найти чат для пользователя {e.order.buyer_username} при отправке уведомления о заказе.")
            c.telegram.send_notification(text, notification_type=utils.NotificationTypes.new_order)

    c.executor.submit(threaded_task)

def deliver_goods(c: Cortex, e: NewOrderEvent, *args):
    chat = c.account.get_chat_by_name(e.order.buyer_username, True)
    if not chat:
        logger.error(f"Не удалось найти чат для пользователя {e.order.buyer_username}, автовыдача невозможна.")
        setattr(e, "error", 1)
        setattr(e, "error_text", f"Не удалось найти чат для заказа {e.order.id}.")
        return

    chat_id = chat.id
    cfg_obj = getattr(e, "config_section_obj")
    delivery_text = cortex_tools.format_order_text(cfg_obj["response"], e.order)

    amount, goods_left, products = 1, -1, []
    file_name = cfg_obj.get("productsFileName")

    try:
        if file_name:
            if c.multidelivery_enabled and not cfg_obj.getboolean("disableMultiDelivery"):
                amount = e.order.amount if e.order.amount else 1
            products, goods_left = cortex_tools.get_products(f"storage/products/{file_name}", amount)
            delivery_text = delivery_text.replace("$product", "\n".join(products).replace("\\n", "\n"))
    except UtilsExceptions.ProductsFileNotFoundError as exc:
        error_text = f"Ошибка автовыдачи для заказа #{e.order.id}: файл товаров '{file_name}' не найден."
        logger.error(f"$RED{error_text}$RESET")
        if c.telegram:
            c.telegram.send_notification(f"❌ <b>Ошибка автовыдачи</b>\n\nНе удалось выдать товар по заказу <code>{e.order.id}</code> (лот «<i>{utils.escape(e.order.description)}</i>»).\n\n<b>Причина:</b> Не найден файл с товарами:\n<code>storage/products/{utils.escape(file_name)}</code>",
                                        notification_type=utils.NotificationTypes.critical)
        setattr(e, "error", 1)
        setattr(e, "error_text", error_text)
        return
    except Exception as exc:
        logger.error(f"Произошла ошибка при получении товаров для заказа $YELLOW{e.order.id}: {str(exc)}$RESET")
        logger.debug("TRACEBACK", exc_info=True)
        setattr(e, "error", 1)
        setattr(e, "error_text", f"Произошла ошибка при получении товаров для заказа {e.order.id}: {str(exc)}")
        return

    result = c.send_message(chat_id, delivery_text, e.order.buyer_username)
    if not result:
        logger.error(f"Не удалось отправить товар для ордера $YELLOW{e.order.id}$RESET.")
        setattr(e, "error", 1)
        setattr(e, "error_text", f"Не удалось отправить сообщение с товаром для заказа {e.order.id}.")
        if file_name and products:
            cortex_tools.add_products(f"storage/products/{file_name}", products, at_zero_position=True)
    else:
        logger.info(f"Товар для заказа {e.order.id} выдан.")
        setattr(e, "delivered", True)
        setattr(e, "delivery_text", delivery_text)
        setattr(e, "goods_delivered", amount)
        setattr(e, "goods_left", goods_left)

def deliver_product_handler(c: Cortex, e: NewOrderEvent, *args) -> None:
    if not c.MAIN_CFG["FunPay"].getboolean("autoDelivery"):
        return
    if e.order.buyer_username in c.blacklist and c.bl_delivery_enabled:
        logger.info(f"Пользователь {e.order.buyer_username} находится в ЧС и включена блокировка автовыдачи. $YELLOW(ID: {e.order.id})$RESET")
        return

    config_section_obj = getattr(e, "config_section_obj")
    if config_section_obj is None:
        return
    if config_section_obj.getboolean("disable"):
        logger.info(f"Для лота \"{e.order.description}\" отключена автовыдача.")
        return
    
    def threaded_delivery():
        c.run_handlers(c.pre_delivery_handlers, (c, e))
        deliver_goods(c, e, *args)
        c.run_handlers(c.post_delivery_handlers, (c, e))
    
    c.executor.submit(threaded_delivery)

def send_delivery_notification_handler(c: Cortex, e: NewOrderEvent):
    if c.telegram is None:
        return

    if getattr(e, "error"):
        text = f"""❌ <code>{getattr(e, "error_text")}</code>"""
    else:
        amount = "<b>∞</b>" if getattr(e, "goods_left") == -1 else f"<code>{getattr(e, 'goods_left')}</code>"
        text = f"""✅ Успешно выдал товар для ордера <code>{e.order.id}</code>.\n
🛒 <b><i>Товар:</i></b>
<code>{utils.escape(getattr(e, "delivery_text"))}</code>\n
📋 <b><i>Осталось товаров: </i></b>{amount}"""
    
    c.executor.submit(c.telegram.send_notification, text,
                      notification_type=utils.NotificationTypes.delivery)


def update_lot_state(cortex_instance: Cortex, lot: FunPayAPI.types.LotShortcut, task: int) -> bool:
    action_text = "восстановить" if task == 1 else "деактивировать"
    attempts = 3
    for attempt in range(attempts):
        try:
            lot_fields = cortex_instance.account.get_lot_fields(lot.id)
            if task == 1:
                lot_fields.active = True
            elif task == -1:
                lot_fields.active = False
            
            # --- ИЗМЕНЕНИЕ НАЧАЛО: Обработка ошибки пустых секретов ---
            try:
                cortex_instance.account.save_lot(lot_fields)
            except exceptions.LotSavingError as e:
                # Если FunPay вернул ошибку "Нет товаров" в поле secrets
                if "secrets" in e.errors:
                    logger.warning(f"Конфликт автовыдачи при восстановлении лота '{lot.description}'. Отключаю встроенную автовыдачу FunPay и пробую снова...")
                    # Отключаем галочку автовыдачи на сайте (так как бот выдает сам через чат)
                    lot_fields.auto_delivery = False
                    cortex_instance.account.save_lot(lot_fields)
                else:
                    # Если ошибка другая, пробрасываем её дальше, чтобы сработал внешний except
                    raise e
            # --- ИЗМЕНЕНИЕ КОНЕЦ ---

            if task == 1:
                logger.info(f"Восстановил лот $YELLOW{lot.description}$RESET.")
            elif task == -1:
                logger.info(f"Деактивировал лот $YELLOW{lot.description}$RESET.")
            return True
        
        except exceptions.RequestFailedError as e:
            logger.error(f"Ошибка API FunPay при попытке {action_text} лот $YELLOW{lot.description}$RESET (попытка {attempt + 1}/{attempts}). Статус: {e.status_code}. Ответ: {e.response.text[:100]}")
            logger.debug("TRACEBACK", exc_info=True)
            if e.status_code == 404:
                logger.error(f"Лот $YELLOW{lot.description}$RESET не найден на FunPay. Прекращаю попытки.")
                return False
            time.sleep(3 * (attempt + 1))
            
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при попытке {action_text} лот $YELLOW{lot.description}$RESET (попытка {attempt + 1}/{attempts}): {e}")
            logger.debug("TRACEBACK", exc_info=True)
            time.sleep(3 * (attempt + 1))

    logger.error(
        f"Не удалось {action_text} лот $YELLOW{lot.description}$RESET: превышено кол-во попыток.")
    return False


def update_lots_states(cortex_instance: Cortex, event: NewOrderEvent):
    if not any([cortex_instance.autorestore_enabled, cortex_instance.autodisable_enabled]):
        return
    if cortex_instance.curr_profile_last_tag != event.runner_tag or cortex_instance.last_state_change_tag == event.runner_tag:
        return

    lots = cortex_instance.curr_profile.get_sorted_lots(1)
    deactivated, restored = [], []
    for lot in cortex_instance.profile.get_sorted_lots(3)[FunPayAPI.types.SubCategoryTypes.COMMON].values():
        if not lot.description: continue
        current_task = 0
        config_obj = get_lot_config_by_name(cortex_instance, lot.description)

        if lot.id not in lots:
            if config_obj is None:
                if cortex_instance.autorestore_enabled: current_task = 1
            else:
                if cortex_instance.autorestore_enabled and config_obj.get("disableAutoRestore") in ["0", None]:
                    if not cortex_instance.autodisable_enabled:
                        current_task = 1
                    elif check_products_amount(config_obj):
                        current_task = 1
        else:
            if config_obj and not check_products_amount(config_obj) and \
               cortex_instance.MAIN_CFG["FunPay"].getboolean("autoDisable") and \
               config_obj.get("disableAutoDisable") in ["0", None]:
                current_task = -1

        if current_task:
            if update_lot_state(cortex_instance, lot, current_task):
                if current_task == -1: deactivated.append(lot.description)
                elif current_task == 1: restored.append(lot.description)
            time.sleep(0.5)

    if deactivated:
        text = f"🔴 <b>Деактивировал лоты:</b>\n\n<code>{os.linesep.join(deactivated)}</code>"
        cortex_instance.executor.submit(cortex_instance.telegram.send_notification, text,
                                        notification_type=utils.NotificationTypes.lots_deactivate)
    if restored:
        text = f"🟢 <b>Активировал лоты:</b>\n\n<code>{os.linesep.join(restored)}</code>"
        cortex_instance.executor.submit(cortex_instance.telegram.send_notification, text,
                                        notification_type=utils.NotificationTypes.lots_restore)
    cortex_instance.last_state_change_tag = event.runner_tag


def update_lots_state_handler(cortex_instance: Cortex, event: NewOrderEvent, *args):
    cortex_instance.executor.submit(update_lots_states, cortex_instance, event)

def send_thank_u_message_handler(c: Cortex, e: OrderStatusChangedEvent):
    if not c.MAIN_CFG["OrderConfirm"].getboolean("sendReply") or e.order.status is not FunPayAPI.types.OrderStatuses.CLOSED:
        return
    
    def threaded_task():
        chat = c.account.get_chat_by_name(e.order.buyer_username, True)
        if not chat:
            logger.warning(f"Не удалось найти чат для {e.order.buyer_username}, чтобы отправить благодарность.")
            return
        
        text = cortex_tools.format_order_text(c.MAIN_CFG["OrderConfirm"]["replyText"], e.order)
        logger.info(f"Пользователь $YELLOW{e.order.buyer_username}$RESET подтвердил выполнение заказа $YELLOW{e.order.id}.$RESET")
        logger.info(f"Отправляю ответное сообщение ...")
        c.send_message(chat.id, text, e.order.buyer_username,
                       watermark=c.MAIN_CFG["OrderConfirm"].getboolean("watermark"))

    c.executor.submit(threaded_task)


def send_order_confirmed_notification_handler(cortex_instance: Cortex, event: OrderStatusChangedEvent):
    if not event.order.status == FunPayAPI.types.OrderStatuses.CLOSED:
        return
    
    def threaded_task():
        chat = cortex_instance.account.get_chat_by_name(event.order.buyer_username, True)
        if chat:
            text = f"🪙 Пользователь <a href=\"https://funpay.com/chat/?node={chat.id}\">{event.order.buyer_username}</a> подтвердил выполнение заказа <code>{event.order.id}</code>. (<code>{event.order.price} {event.order.currency}</code>)"
            keyboard = keyboards.new_order(event.order.id, event.order.buyer_username, chat.id)
            cortex_instance.telegram.send_notification(text, keyboard, utils.NotificationTypes.order_confirmed)
        else:
            logger.warning(f"Не удалось найти чат для {event.order.buyer_username} при отправке уведомления о подтверждении заказа.")

    cortex_instance.executor.submit(threaded_task)


def send_bot_started_notification_handler(c: Cortex, *args):
    if c.telegram is None:
        return
    text = _("fpc_init", c.VERSION, c.account.username, c.account.id,
             c.balance.total_rub, c.balance.total_usd, c.balance.total_eur, c.account.active_sales)
    
    c.telegram.send_notification(text, notification_type=utils.NotificationTypes.bot_start)
    
    c.telegram.init_messages.clear()


BIND_TO_INIT_MESSAGE = [save_init_chats_handler]

BIND_TO_LAST_CHAT_MESSAGE_CHANGED = [old_log_msg_handler,
                                     greetings_handler,
                                     send_response_handler,
                                     process_review_handler,
                                     old_send_new_msg_notification_handler,
                                     send_command_notification_handler,
                                     test_auto_delivery_handler]

BIND_TO_NEW_MESSAGE = [log_msg_handler,
                       greetings_handler,
                       send_response_handler,
                       process_review_handler,
                       send_new_msg_notification_handler,
                       send_command_notification_handler,
                       test_auto_delivery_handler]

BIND_TO_POST_LOTS_RAISE = [send_categories_raised_notification_handler]

BIND_TO_ORDERS_LIST_CHANGED = [update_current_lots_handler, update_profile_lots_handler]

BIND_TO_NEW_ORDER = [log_new_order_handler, setup_event_attributes_handler,
                     send_new_order_notification_handler, deliver_product_handler,
                     update_lots_state_handler]

BIND_TO_ORDER_STATUS_CHANGED = [send_thank_u_message_handler, send_order_confirmed_notification_handler]

BIND_TO_POST_DELIVERY = [send_delivery_notification_handler]

BIND_TO_POST_START = [send_bot_started_notification_handler, send_startup_error_notifications]
# --- END OF FILE FunPayCortex/handlers.py ---
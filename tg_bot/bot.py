# --- START OF FILE FunPayCortex/tg_bot/bot.py ---

from __future__ import annotations
import re
from typing import TYPE_CHECKING, Literal
from FunPayAPI import Account
from tg_bot.utils import NotificationTypes
if TYPE_CHECKING:
    from cortex import Cortex
import os
import sys
import time
import random
import string
import psutil
import telebot
from telebot.apihelper import ApiTelegramException
import logging
import requests
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery, BotCommand, InputFile
from tg_bot import utils, static_keyboards as skb, keyboards as kb, CBT
from Utils import cortex_tools
from Utils.cortex_tools import validate_proxy, cache_proxy_dict
from locales.localizer import Localizer

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate
telebot.apihelper.ENABLE_MIDDLEWARE = True

def strip_html_comments(html_string: str) -> str:
    if not isinstance(html_string, str):
        return str(html_string)
    return re.sub(r"<!--(.*?)-->", "", html_string, flags=re.DOTALL)

def remove_html_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text)

class TGBot:
    def __init__(self, cortex_instance: Cortex):
        self.cortex: Cortex = cortex_instance
        self.bot = telebot.TeleBot(self.cortex.MAIN_CFG["Telegram"]["token"], parse_mode="HTML",
                                   allow_sending_without_reply=True, num_threads=5)
        self.file_handlers = {}
        self.attempts = {}
        self.init_messages = []
        self.user_states = {}
        self.authorized_users = utils.load_authorized_users(self.cortex.base_path)
        utils.save_authorized_users(self.cortex, self.authorized_users)
        self.notification_settings = utils.load_notification_settings(self.cortex.base_path)
        self.answer_templates = utils.load_answer_templates(self.cortex.base_path)
        
        self.commands = {
            "menu": "cmd_menu",
            "profile": "cmd_profile",
            "balance": "cmd_balance",
            "restart": "cmd_restart",
            "golden_key": "cmd_golden_key",
            "ban": "cmd_ban",
            "unban": "cmd_unban",
            "black_list": "cmd_black_list",
            "upload_chat_img": "cmd_upload_chat_img",
            "upload_offer_img": "cmd_upload_offer_img",
            "test_lot": "cmd_test_lot",
            "logs": "cmd_logs",
            "about": "cmd_about",
            "sys": "cmd_sys",
            "get_backup": "cmd_get_backup",
            "create_backup": "cmd_create_backup",
            "del_logs": "cmd_del_logs",
            "power_off": "cmd_power_off",
            "watermark": "cmd_watermark",
        }
        self.__default_notification_settings = {
            utils.NotificationTypes.ad: 1,
            utils.NotificationTypes.announcement: 1,
            utils.NotificationTypes.critical: 1
        }

    def setup_commands(self):
        bot_commands = []
        for cmd, key in self.commands.items():
            bot_commands.append(BotCommand(cmd, _(key)))
        try:
            self.bot.set_my_commands(bot_commands)
        except Exception as e:
            logger.warning(f"Не удалось обновить список команд в Telegram: {e}")

    def edit_bot(self):
        try:
            raw_desc = _("adv_description", self.cortex.VERSION)
            clean_desc = remove_html_tags(raw_desc).strip()
            self.bot.set_my_description(clean_desc)
        except Exception as e:
            logger.warning(f"Не удалось обновить описание бота в Telegram: {e}")

    def get_state(self, chat_id: int, user_id: int) -> dict | None:
        try:
            return self.user_states[chat_id][user_id]
        except KeyError:
            return None

    def set_state(self, chat_id: int, message_id: int, user_id: int, state: str, data: dict | None = None):
        if chat_id not in self.user_states:
            self.user_states[chat_id] = {}
        self.user_states[chat_id][user_id] = {"state": state, "mid": message_id, "data": data or {}}

    def clear_state(self, chat_id: int, user_id: int, del_msg: bool = False) -> int | None:
        try:
            state = self.user_states[chat_id][user_id]
        except KeyError:
            return None
        msg_id = state.get("mid")
        if user_id in self.user_states.get(chat_id, {}):
            del self.user_states[chat_id][user_id]
        if del_msg:
            try:
                self.bot.delete_message(chat_id, msg_id)
            except ApiTelegramException:
                pass
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение {msg_id} при очистке состояния: {e}")
        return msg_id

    def check_state(self, chat_id: int, user_id: int, state: str) -> bool:
        try:
            return self.user_states[chat_id][user_id]["state"] == state
        except KeyError:
            return False

    def is_notification_enabled(self, chat_id: int | str, notification_type: str) -> bool:
        try:
            return bool(self.notification_settings[str(chat_id)][notification_type])
        except KeyError:
            return notification_type == NotificationTypes.critical

    def toggle_notification(self, chat_id: int, notification_type: str) -> bool:
        chat_id_str = str(chat_id)
        if chat_id_str not in self.notification_settings:
            self.notification_settings[chat_id_str] = self.__default_notification_settings.copy()
            self.notification_settings[chat_id_str][NotificationTypes.critical] = 1 if int(chat_id) in self.authorized_users else 0
        current_status = self.notification_settings[chat_id_str].get(notification_type, False)
        self.notification_settings[chat_id_str][notification_type] = not current_status
        utils.save_notification_settings(self.cortex, self.notification_settings)
        return self.notification_settings[chat_id_str][notification_type]

    def file_handler(self, state, handler):
        self.file_handlers[state] = handler

    def run_file_handlers(self, m: Message):
        if (state := self.get_state(m.chat.id, m.from_user.id)) is None \
                or state["state"] not in self.file_handlers:
            return
        try:
            self.file_handlers[state["state"]](self, m)
        except Exception as e:
            logger.error(_("log_tg_handler_error") + f" (File Handler: {state['state']})")
            logger.debug(f"Error details: {e}", exc_info=True)

    def msg_handler(self, handler, **kwargs):
        bot_instance = self.bot
        @bot_instance.message_handler(**kwargs)
        def run_handler(message: Message):
            try:
                handler(message)
            except Exception as e:
                logger.error(_("log_tg_handler_error") + f" (Message Handler: {handler.__name__})")
                logger.debug(f"Error details: {e}", exc_info=True)

    def cbq_handler(self, handler, func, **kwargs):
        bot_instance = self.bot
        @bot_instance.callback_query_handler(func, **kwargs)
        def run_handler(call: CallbackQuery):
            try:
                handler(call)
            except Exception as e:
                logger.error(_("log_tg_handler_error") + f" (Callback Handler: {handler.__name__}, data: {call.data[:50]})")
                logger.debug(f"Error details: {e}", exc_info=True)

    def move_fallback_handler_to_end(self):
        pass

    def mdw_handler(self, handler, **kwargs):
        bot_instance = self.bot
        @bot_instance.middleware_handler(**kwargs)
        def run_handler(bot_mdw, update):
            try:
                handler(bot_mdw, update)
            except Exception as e:
                logger.error(_("log_tg_handler_error") + f" (Middleware Handler: {handler.__name__})")
                logger.debug(f"Error details: {e}", exc_info=True)

    def setup_chat_notifications(self, bot_instance_mdw: telebot.TeleBot, m: Message):
        chat_id_str = str(m.chat.id)
        user_id = m.from_user.id
        if chat_id_str not in self.notification_settings:
            self.notification_settings[chat_id_str] = self.__default_notification_settings.copy()
            is_authorized = user_id in self.authorized_users
            self.notification_settings[chat_id_str][NotificationTypes.critical] = 1 if is_authorized else 0
            utils.save_notification_settings(self.cortex, self.notification_settings)
        elif user_id in self.authorized_users and \
             not self.notification_settings[chat_id_str].get(NotificationTypes.critical, False):
            self.notification_settings[chat_id_str][NotificationTypes.critical] = 1
            utils.save_notification_settings(self.cortex, self.notification_settings)

    def reg_admin(self, m: Message):
        lang = m.from_user.language_code
        user_id = m.from_user.id
        
        # Проверяем, не заблокирован ли пользователь уже (6 и более попыток)
        # Если попыток >= 6, мы уже отправили сообщение об ошибке, просто молчим.
        if self.attempts.get(user_id, 0) >= 6:
            return

        if m.chat.type != "private" or m.text is None:
            return
            
        user_input = m.text.strip()
        username = m.from_user.username or str(user_id)
        current_role = utils.get_user_role(self.authorized_users, user_id)
        
        if not self.cortex.block_tg_login and cortex_tools.check_password(user_input, self.cortex.MAIN_CFG["Telegram"]["secretKeyHash"]):
            if current_role == "admin":
                self.bot.send_message(m.chat.id, _("role_change_err_already_admin", language=lang))
                return
            self.authorized_users[user_id] = {"username": username, "role": "admin"}
            utils.save_authorized_users(self.cortex, self.authorized_users)
            self.setup_chat_notifications(self.bot, m)
            if current_role == "manager":
                self.bot.send_message(m.chat.id, _("role_change_promoted", language=lang))
                logger.warning(_("log_user_role_changed", username, user_id, username, user_id, "admin"))
            else:
                logger.warning(_("log_access_granted", username, user_id))
                self.send_notification(text=_("access_granted_notification", username, user_id),
                                       notification_type=NotificationTypes.critical, pin=True, exclude_chat_id=m.chat.id)
                self.bot.send_message(m.chat.id, _("access_granted", language=lang))
            
            # Сбрасываем попытки при успешном входе
            if user_id in self.attempts:
                del self.attempts[user_id]

            if not self.cortex.is_proxy_configured():
                text = (
                    "🛑 <b>ТРЕБУЕТСЯ НАСТРОЙКА ПРОКСИ</b>\n\n"
                    "Работа бота без прокси запрещена техническими ограничениями.\n"
                    "Без рабочего IPv4 прокси бот не будет отправлять запросы к FunPay.\n\n"
                    "👉 <b>Отправьте прокси в формате:</b>\n"
                    "<code>login:password@ip:port</code>\n"
                    "или\n"
                    "<code>ip:port</code>\n\n"
                    "📚 <b>Где купить прокси?</b> <a href='https://funpaybot.ru/kb'>Инструкция здесь</a>"
                )
                result = self.bot.send_message(m.chat.id, text, reply_markup=skb.CLEAR_STATE_BTN())
                self.set_state(m.chat.id, result.id, m.from_user.id, "SETUP_PROXY_MANDATORY")
                return
            if not self.cortex.account.golden_key:
                welcome_text = (
                    "👋 <b>Почти готово!</b>\n\n"
                    "Прокси настроен. Теперь нужно ввести <code>golden_key</code>.\n"
                    "Пожалуйста, <b>отправьте токен прямо сейчас</b> ответным сообщением.\n\n"
                    "📚 <b>Как получить токен?</b> <a href='https://funpaybot.ru/kb'>Инструкция тут</a>"
                )
                result = self.bot.send_message(m.chat.id, welcome_text, reply_markup=skb.CLEAR_STATE_BTN())
                self.set_state(m.chat.id, result.id, m.from_user.id, CBT.CHANGE_GOLDEN_KEY)
                return
            return
            
        manager_key = self.cortex.MAIN_CFG["Manager"].get("registration_key", "").strip()
        if manager_key and user_input == manager_key:
            if current_role == "manager":
                self.bot.send_message(m.chat.id, _("role_change_err_already_manager", language=lang))
                return
            admins = [uid for uid, uinfo in self.authorized_users.items() if uinfo.get("role") == "admin"]
            if current_role == "admin" and len(admins) <= 1:
                self.bot.send_message(m.chat.id, _("demote_last_admin_error"), show_alert=True)
                return
            self.authorized_users[user_id] = {"username": username, "role": "manager"}
            utils.save_authorized_users(self.cortex, self.authorized_users)
            self.setup_chat_notifications(self.bot, m)
            
            # Сбрасываем попытки при успешном входе
            if user_id in self.attempts:
                del self.attempts[user_id]

            if current_role == "admin":
                self.bot.send_message(m.chat.id, _("role_change_demoted", language=lang))
                logger.warning(_("log_user_role_changed", username, user_id, username, user_id, "manager"))
            else:
                logger.warning(_("log_manager_access_granted", username, user_id))
                self.bot.send_message(m.chat.id, _("manager_access_granted", language=lang))
            return
            
        if current_role:
            self.bot.send_message(m.chat.id, _("role_change_prompt", role=_(f"role_{current_role}"), language=lang))
            return
            
        # Неверный ввод
        self.attempts[user_id] = self.attempts.get(user_id, 0) + 1
        
        # Если превысили лимит (6-я попытка) - отправляем предупреждение и блокируем
        if self.attempts[user_id] == 6:
            self.bot.send_message(m.chat.id, "⛔ <b>Доступ заблокирован</b>\n\nВы ввели пароль неверно слишком много раз. Бот больше не будет реагировать на ваши сообщения.\n\nПерезагрузите бота через панель управления (Dashboard), чтобы сбросить блокировку.")
            logger.warning(f"User {username} (ID: {user_id}) locked out due to too many failed attempts.")
            return

        links_kb = K(row_width=1)
        channel_btn = B(_("btn_channel_link", language=lang), url="https://t.me/RobotFunPay")
        website_btn = B(_("btn_website_link", language=lang), url="https://funpaybot.ru")
        links_kb.add(channel_btn, website_btn)
        
        self.bot.send_message(m.chat.id, _("access_denied", m.from_user.username, language=lang),
                              reply_markup=links_kb, disable_web_page_preview=True)
        logger.warning(_("log_access_attempt", username, user_id))

    def setup_proxy_mandatory(self, m: Message):
        proxy_text = m.text.strip()
        try:
            login, password, ip, port = validate_proxy(proxy_text)
            proxy_str_auth = f"{f'{login}:{password}@' if login and password else ''}{ip}:{port}"
            temp_proxy_dict = {
                "http": f"http://{proxy_str_auth}",
                "https": f"http://{proxy_str_auth}"
            }
            progress_msg = self.bot.send_message(m.chat.id, "⏳ <b>Проверяю прокси...</b>\nПробую соединиться с FunPay.com...", parse_mode="HTML")
            
            def worker():
                try:
                    from curl_cffi import requests as cffi_requests
                    test_resp = cffi_requests.get(
                        "https://funpay.com/",
                        proxies=temp_proxy_dict,
                        timeout=15,
                        impersonate="chrome120"
                    )
                    if test_resp.status_code not in [200, 301, 302, 403]:
                        raise Exception(f"Status code: {test_resp.status_code}")
                    
                    # Сохраняем настройки
                    self.cortex.MAIN_CFG["Proxy"]["enable"] = "1"
                    self.cortex.MAIN_CFG["Proxy"]["check"] = "1"
                    self.cortex.MAIN_CFG["Proxy"].update({
                        "ip": ip, "port": str(port), 
                        "login": login, "password": password
                    })
                    self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
                    self.cortex.account.proxy = temp_proxy_dict
                    
                    max_id = max(self.cortex.proxy_dict.keys()) if self.cortex.proxy_dict else -1
                    self.cortex.proxy_dict[max_id + 1] = proxy_str_auth
                    cache_proxy_dict(self.cortex.proxy_dict, self.cortex.base_path)
                    
                    self.bot.edit_message_text(f"✅ <b>Прокси рабочий!</b>\nСоединение с FunPay установлено.\nСохранено: <code>{ip}:{port}</code>.", progress_msg.chat.id, progress_msg.id, parse_mode="HTML")
                    self.clear_state(m.chat.id, m.from_user.id, True)
                    
                    # --- ЛОГИКА "ПРОГРЕВА" ПРИ ПЕРВОМ ЗАПУСКЕ ---
                    if not self.cortex.account.golden_key:
                        warmup_text = (
                            "🛡 <b>ОБЯЗАТЕЛЬНАЯ ПРОВЕРКА БЕЗОПАСНОСТИ</b>\n\n"
                            "Чтобы FunPay не заблокировал аккаунт за резкую смену IP, необходимо «прогреть» этот прокси.\n"
                            "Бот <b>заблокирует ввод токена на 10 минут</b>. За это время вы должны выполнить следующие действия:\n\n"
                            "1️⃣ <b>Скачайте приложение для прокси:</b>\n"
                            "• 🤖 <b>Android:</b> <a href='https://play.google.com/store/apps/details?id=com.scheler.superproxy'>SuperProxy</a>\n"
                            "• 🍏 <b>iOS:</b> <a href='https://apps.apple.com/us/app/potatso-lite/id1239860606'>Potatso Lite</a>\n"
                            "• 💻 <b>PC:</b> <a href='https://www.proxifier.com/'>Proxifier</a> или стандартные настройки Windows\n\n"
                            "2️⃣ <b>Подключитесь:</b>\n"
                            "Вставьте данные вашего прокси (<code>login:pass@ip:port</code>) в приложение и включите его (как VPN).\n\n"
                            "3️⃣ <b>Зайдите на FunPay:</b>\n"
                            "Откройте браузер на этом устройстве, зайдите на funpay.com, авторизуйтесь и погуляйте по сайту пару минут. Заодно скопируйте <code>golden_key</code> инструкция: https://funpaybot.ru/kb.\n\n"
                            "⏳ <b>Ожидание разблокировки: 10 мин...</b>"
                        )
                        
                        wait_msg = self.bot.send_message(m.chat.id, warmup_text, parse_mode="HTML", disable_web_page_preview=True)
                        
                        # Таймер на 10 минут
                        for i in range(9, -1, -1):
                            time.sleep(60)
                            try:
                                new_text = warmup_text.replace(f"Ожидание разблокировки: {i+1} мин...", f"Ожидание разблокировки: {i} мин...")
                                self.bot.edit_message_text(new_text, wait_msg.chat.id, wait_msg.id, parse_mode="HTML", disable_web_page_preview=True)
                            except: pass

                        # После таймера
                        text = (
                            "✅ <b>Время вышло! Прокси прогрет.</b>\n\n"
                            "Теперь можно безопасно вводить токен.\n"
                            "Пожалуйста, отправьте ваш <code>golden_key</code> ответным сообщением.\n\n"
                            "📚 <b>Инструкция:</b> <a href='https://funpaybot.ru/kb'>Как получить токен?</a>"
                        )
                        result = self.bot.send_message(m.chat.id, text, reply_markup=skb.CLEAR_STATE_BTN(), parse_mode="HTML")
                        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.CHANGE_GOLDEN_KEY)
                        
                    else:
                        # Если это просто смена прокси на уже работающем боте, перезагружаем сразу
                        self.bot.send_message(m.chat.id, "🚀 Настройки обновлены. Бот перезапускается...")
                        cortex_tools.restart_program()
                        
                except Exception as e:
                    logger.error(f"Error checking proxy: {e}")
                    self.bot.edit_message_text(f"❌ <b>Прокси не работает!</b>\n\n{str(e)[:200]}\n\n👉 <b>Отправьте другой прокси:</b>", progress_msg.chat.id, progress_msg.id, parse_mode="HTML")
            
            self.cortex.executor.submit(worker)
            
        except ValueError:
            self.bot.send_message(m.chat.id, "❌ <b>Неверный формат!</b>\nНужно: <code>login:pass@ip:port</code> или <code>ip:port</code>.\nПопробуйте снова:", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Critical error setting proxy: {e}", exc_info=True)
            self.bot.send_message(m.chat.id, "⚠️ Внутренняя ошибка бота. Попробуйте еще раз.")

    def ignore_unauthorized_users(self, c: CallbackQuery):
        # Также проверяем блокировку в колбэках, чтобы кнопки не работали
        if self.attempts.get(c.from_user.id, 0) >= 6:
            self.bot.answer_callback_query(c.id) # Silent ignore
            return

        logger.warning(_("log_click_attempt", c.from_user.username, c.from_user.id, c.message.chat.username,
                         c.message.chat.id))
        self.attempts[c.from_user.id] = self.attempts.get(c.from_user.id, 0) + 1
        
        if self.attempts[c.from_user.id] == 6:
             self.bot.answer_callback_query(c.id, "⛔ Доступ заблокирован. Перезагрузите бота.", show_alert=True)
             return

        if self.attempts[c.from_user.id] <= 5:
            self.bot.answer_callback_query(c.id, _("adv_fpc", language=c.from_user.language_code), show_alert=True)
        else:
            self.bot.answer_callback_query(c.id)

    def send_settings_menu(self, m: Message):
        start_message = f"""
👋 <b>Главное меню FunPayBot v{self.cortex.VERSION}</b>

Выберите раздел для настройки:
"""
        self.bot.send_message(m.chat.id, start_message, reply_markup=skb.SETTINGS_SECTIONS(self.cortex, m.from_user.id), disable_web_page_preview=True)

    def send_profile(self, m: Message):
        self.bot.send_message(m.chat.id, utils.generate_profile_text(self.cortex),
                              reply_markup=kb.profile_menu())

    def open_profile_menu(self, c: CallbackQuery):
        self.bot.edit_message_text(utils.generate_profile_text(self.cortex),
                                   c.message.chat.id,
                                   c.message.id,
                                   reply_markup=kb.profile_menu())
        self.bot.answer_callback_query(c.id)

    def send_balance(self, m: Message):
        user_role = utils.get_user_role(self.authorized_users, m.from_user.id)
        if user_role != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        balance_text = utils.generate_balance_text(self.cortex)
        self.bot.send_message(m.chat.id, balance_text, reply_markup=skb.BALANCE_REFRESH_BTN())

    def update_balance(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        progress_msg = self.bot.send_message(c.message.chat.id, f"⏳ {_('updating_profile')}")
        def worker():
            try:
                self.cortex.balance = self.cortex.get_balance()
                self.bot.delete_message(progress_msg.chat.id, progress_msg.id)
                try:
                    self.bot.edit_message_text(utils.generate_balance_text(self.cortex), c.message.chat.id,
                                               c.message.id, reply_markup=skb.BALANCE_REFRESH_BTN())
                except ApiTelegramException as e:
                    if "message is not modified" not in e.description:
                        raise
            except Exception as e:
                self.bot.edit_message_text(_("profile_updating_error") + f"\n\n<i>{str(e)[:100]}</i>", progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при обновлении баланса через TG: {e}")
                logger.debug("TRACEBACK", exc_info=True)
        self.cortex.executor.submit(worker)

    def act_change_cookie(self, m: Message):
        user_role = utils.get_user_role(self.authorized_users, m.from_user.id)
        if user_role != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        result = self.bot.send_message(m.chat.id, _("act_change_golden_key"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.CHANGE_GOLDEN_KEY)

    def change_cookie(self, m: Message):
        golden_key = m.text.strip()
        if len(golden_key) != 32:
            self.bot.send_message(m.chat.id, "❌ <b>Некорректный формат токена.</b>\nОн должен состоять из 32 символов.\nПопробуйте снова:", parse_mode="HTML")
            return
        try:
            self.bot.delete_message(m.chat.id, m.id)
        except: pass
        progress_msg = self.bot.send_message(m.chat.id, "🔑 <b>Проверяю токен...</b>", parse_mode="HTML")
        def worker():
            new_account = Account(golden_key, self.cortex.account.user_agent, proxy=self.cortex.account.proxy, locale=self.cortex.account.locale)
            try:
                new_account.get()
                self.cortex.account.golden_key = golden_key
                self.cortex.MAIN_CFG.set("FunPay", "golden_key", golden_key)
                self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
                self.clear_state(m.chat.id, m.from_user.id, True)
                self.bot.edit_message_text(f"✅ <b>Токен принят!</b>\nАккаунт: <b>{utils.escape(new_account.username)}</b>\n\n🚀 Перезапускаю бота для начала работы...", progress_msg.chat.id, progress_msg.id, parse_mode="HTML")
                time.sleep(1)
                cortex_tools.restart_program()
            except Exception as e:
                logger.warning(f"Error checking token: {e}")
                self.bot.edit_message_text(f"⚠️ <b>Не удалось авторизоваться!</b>\n\nПричина: {str(e)[:200]}\n\n👇 <b>Отправьте Golden Key еще раз:</b>", progress_msg.chat.id, progress_msg.id, parse_mode="HTML")
                self.set_state(m.chat.id, progress_msg.id, m.from_user.id, CBT.CHANGE_GOLDEN_KEY)
        self.cortex.executor.submit(worker)

    def update_profile(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        progress_msg = self.bot.send_message(c.message.chat.id, f"⏳ {_('updating_profile')}")
        def worker():
            try:
                result = self.cortex.update_lots_and_categories()
                if not result:
                    raise Exception("Failed to get user profile from FunPay.")
                self.cortex.balance = self.cortex.get_balance()
                self.bot.delete_message(progress_msg.chat.id, progress_msg.id)
                try:
                    self.bot.edit_message_text(utils.generate_profile_text(self.cortex), c.message.chat.id,
                                               c.message.id, reply_markup=kb.profile_menu())
                except ApiTelegramException as e:
                    if "message is not modified" not in e.description:
                        raise
            except Exception as e:
                self.bot.edit_message_text(_("profile_updating_error") + f"\n\n<i>{str(e)[:100]}</i>", progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при обновлении профиля через TG: {e}")
                logger.debug("TRACEBACK", exc_info=True)
        self.cortex.executor.submit(worker)

    def act_manual_delivery_test(self, m: Message):
        result = self.bot.send_message(m.chat.id, _("create_test_ad_key"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.MANUAL_AD_TEST)

    def manual_delivery_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        lot_name = m.text.strip()
        key = "".join(random.sample(string.ascii_letters + string.digits, 50))
        self.cortex.delivery_tests[key] = lot_name
        logger.info(_("log_new_ad_key", m.from_user.username, m.from_user.id, lot_name, key))
        self.bot.send_message(m.chat.id, _("test_ad_key_created", utils.escape(lot_name), key))

    def act_ban(self, m: Message):
        result = self.bot.send_message(m.chat.id, _("act_blacklist"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.BAN)

    def ban(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        nickname = m.text.strip()
        if nickname in self.cortex.blacklist:
            self.bot.send_message(m.chat.id, _("already_blacklisted", utils.escape(nickname)))
            return
        self.cortex.blacklist.append(nickname)
        self.cortex.save_json_setting("blacklist", self.cortex.blacklist)
        cortex_tools.cache_blacklist(self.cortex.blacklist, self.cortex.base_path)
        logger.info(_("log_user_blacklisted", m.from_user.username, m.from_user.id, nickname))
        self.bot.send_message(m.chat.id, _("user_blacklisted", utils.escape(nickname)))

    def act_unban(self, m: Message):
        result = self.bot.send_message(m.chat.id, _("act_unban"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.UNBAN)

    def unban(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        nickname = m.text.strip()
        if nickname not in self.cortex.blacklist:
            self.bot.send_message(m.chat.id, _("not_blacklisted", utils.escape(nickname)))
            return
        self.cortex.blacklist.remove(nickname)
        self.cortex.save_json_setting("blacklist", self.cortex.blacklist)
        cortex_tools.cache_blacklist(self.cortex.blacklist, self.cortex.base_path)
        logger.info(_("log_user_unbanned", m.from_user.username, m.from_user.id, nickname))
        self.bot.send_message(m.chat.id, _("user_unbanned", utils.escape(nickname)))

    def send_ban_list(self, m: Message):
        if not self.cortex.blacklist:
            self.bot.send_message(m.chat.id, _("blacklist_empty"))
            return
        blacklist_str = "\n".join(f"🚫 <code>{utils.escape(i)}</code>" for i in sorted(self.cortex.blacklist, key=lambda x: x.lower()))
        self.bot.send_message(m.chat.id, f"<b>{_('mm_blacklist')}:</b>\n{blacklist_str}" if blacklist_str else _("blacklist_empty"))

    def act_edit_watermark(self, m: Message):
        watermark = self.cortex.MAIN_CFG["Other"]["watermark"]
        watermark_display = f"\n\n{_('crd_msg_sent', '').split(' в чат')[0]} {_('v_edit_watermark_current')}: <code>{utils.escape(watermark)}</code>" if watermark else ""
        result = self.bot.send_message(m.chat.id, _("act_edit_watermark").format(watermark_display),
                                       reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.EDIT_WATERMARK)

    def edit_watermark(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        watermark_text = m.text.strip() if m.text.strip() != "-" else ""
        if re.fullmatch(r"\[[a-zA-Z]+]", watermark_text):
            self.bot.reply_to(m, _("watermark_error"))
            return
        self.cortex.MAIN_CFG["Other"]["watermark"] = watermark_text
        self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
        if watermark_text:
            logger.info(_("log_watermark_changed", m.from_user.username, m.from_user.id, watermark_text))
            self.bot.reply_to(m, _("watermark_changed", utils.escape(watermark_text)))
        else:
            logger.info(_("log_watermark_deleted", m.from_user.username, m.from_user.id))
            self.bot.reply_to(m, _("watermark_deleted"))

    def send_logs(self, m: Message):
        if utils.get_user_role(self.authorized_users, m.from_user.id) != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        progress_msg = self.bot.send_message(m.chat.id, _("logfile_sending"))
        def worker():
            log_path = os.path.join(self.cortex.base_path, "logs/log.log")
            if not os.path.exists(log_path):
                self.bot.edit_message_text(_("logfile_not_found"), progress_msg.chat.id, progress_msg.id)
                return
            try:
                with open(log_path, "rb") as f:
                    mode_info = _("gs_old_msg_mode").replace("{} ", "") if self.cortex.old_mode_enabled else _("old_mode_help").split('\n')[0].replace("<b>","").replace("</b>","").replace("🚀","").strip()
                    self.bot.send_document(m.chat.id, f,
                                           caption=f"📄 Лог-файл FunPayBot\n\n<b>Режим сообщений:</b> <i>{mode_info}</i>")
                self.bot.delete_message(progress_msg.chat.id, progress_msg.id)
            except Exception as e:
                self.bot.edit_message_text(_("logfile_error") + f"\n\n<i>{str(e)[:100]}</i>", progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при отправке логов: {e}")
                logger.debug("TRACEBACK", exc_info=True)
        self.cortex.executor.submit(worker)

    def del_logs(self, m: Message):
        if utils.get_user_role(self.authorized_users, m.from_user.id) != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        progress_msg = self.bot.send_message(m.chat.id, "🗑️ Удаляю старые логи...")
        def worker():
            logger.info(
                f"[ВАЖНО] Удаляю старые логи по запросу пользователя $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET.")
            deleted_count = 0
            logs_dir = os.path.join(self.cortex.base_path, "logs")
            if not os.path.isdir(logs_dir):
                self.bot.edit_message_text(_("logfile_deleted", 0), progress_msg.chat.id, progress_msg.id)
                return
            for file_name in os.listdir(logs_dir):
                if file_name == "log.log": continue
                try:
                    full_path = os.path.join(logs_dir, file_name)
                    if os.path.isfile(full_path):
                        os.remove(full_path)
                        deleted_count += 1
                except OSError as e:
                    logger.warning(f"Не удалось удалить файл {file_name}: {e}")
                except Exception as e:
                    logger.error(f"Непредвиденная ошибка при удалении файла {file_name}: {e}")
                    logger.debug("TRACEBACK", exc_info=True)
            self.bot.edit_message_text(_("logfile_deleted", deleted_count), progress_msg.chat.id, progress_msg.id)
        self.cortex.executor.submit(worker)

    def about(self, m: Message):
        self.bot.send_message(m.chat.id, _("about", self.cortex.VERSION), disable_web_page_preview=True)

    def get_backup(self, m: Message):
        if utils.get_user_role(self.authorized_users, m.from_user.id) != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        progress_msg = self.bot.send_message(m.chat.id, _("logfile_sending"))
        def worker():
            logger.info(
                f"[ВАЖНО] Запрос резервной копии от $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET.")
            backup_path = "backup.zip"
            if os.path.exists(backup_path):
                try:
                    with open(backup_path, 'rb') as file_to_send:
                        modification_timestamp = os.path.getmtime(backup_path)
                        formatted_time = time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(modification_timestamp))
                        self.bot.send_document(chat_id=m.chat.id, document=InputFile(file_to_send),
                                               caption=f'📦 Резервная копия FunPayBot\n\n🗓️ Создано: {formatted_time}')
                    self.bot.delete_message(progress_msg.chat.id, progress_msg.id)
                except Exception as e:
                    self.bot.edit_message_text(_("logfile_error") + f"\n\n<i>{str(e)[:100]}</i>", progress_msg.chat.id, progress_msg.id)
                    logger.error(f"Ошибка при отправке бэкапа: {e}")
                    logger.debug("TRACEBACK", exc_info=True)
            else:
                self.bot.edit_message_text("❌ Резервная копия еще не создана. Сначала создайте ее.", progress_msg.chat.id, progress_msg.id)
        self.cortex.executor.submit(worker)

    def create_backup(self, m: Message):
        progress_msg = self.bot.send_message(m.chat.id, "⚙️ Создаю резервную копию...")
        def worker():
            if cortex_tools.create_backup() != 0:
                self.bot.edit_message_text("⚠️ Ошибка при создании резервной копии.", progress_msg.chat.id, progress_msg.id)
                return
            self.bot.delete_message(progress_msg.chat.id, progress_msg.id)
            self.get_backup(m)
        self.cortex.executor.submit(worker)
        return True

    def send_system_info(self, m: Message):
        if self.cortex.IS_HOSTING_ENV:
            self.bot.send_message(m.chat.id, "Эта команда недоступна в режиме хостинга.")
            return
        current_timestamp = int(time.time())
        uptime_seconds = current_timestamp - self.cortex.start_time
        ram_info = psutil.virtual_memory()
        cpu_usage_per_core_list = psutil.cpu_percent(percpu=True)
        cpu_usage_per_core_str = "\n".join(
            f"    • <i>{_('v_cpu_core')} {i+1}:</i> <code>{usage}%</code>" for i, usage in enumerate(cpu_usage_per_core_list))
        self.bot.send_message(m.chat.id, _("sys_info", cpu_usage_per_core_str, psutil.Process().cpu_percent(),
                                           ram_info.total // 1048576, ram_info.used // 1048576, ram_info.free // 1048576,
                                           psutil.Process().memory_info().rss // 1048576,
                                           cortex_tools.time_to_str(uptime_seconds), m.chat.id))

    def restart_cortex(self, m: Message):
        if utils.get_user_role(self.authorized_users, m.from_user.id) != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        
        self.bot.send_message(m.chat.id, _("restarting"))
        
        def delayed_restart():
            time.sleep(2)
            cortex_tools.restart_program()
            
        self.cortex.executor.submit(delayed_restart)

    def ask_power_off(self, m: Message):
        if utils.get_user_role(self.authorized_users, m.from_user.id) != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        self.bot.send_message(m.chat.id, _("power_off_0"), reply_markup=kb.power_off(self.cortex.instance_id, 0))

    def cancel_power_off(self, c: CallbackQuery):
        self.bot.edit_message_text(_("power_off_cancelled"), c.message.chat.id, c.message.id)
        self.bot.answer_callback_query(c.id)

    def power_off(self, c: CallbackQuery):
        split_data = c.data.split(":")
        current_stage = int(split_data[1])
        instance_id_from_cb = int(split_data[2])
        if instance_id_from_cb != self.cortex.instance_id:
            self.bot.edit_message_text(_("power_off_error"), c.message.chat.id, c.message.id)
            self.bot.answer_callback_query(c.id)
            return
        if current_stage == 6:
            self.bot.edit_message_text(_("power_off_6"), c.message.chat.id, c.message.id)
            self.bot.answer_callback_query(c.id)
            cortex_tools.shut_down()
            return
        self.bot.edit_message_text(_(f"power_off_{current_stage}"), c.message.chat.id, c.message.id,
                                   reply_markup=kb.power_off(instance_id_from_cb, current_stage))
        self.bot.answer_callback_query(c.id)

    def act_send_funpay_message(self, c: CallbackQuery):
        split_data = c.data.split(":")
        node_id = int(split_data[1])
        username = split_data[2] if len(split_data) > 2 else None
        result_msg = self.bot.send_message(c.message.chat.id, _("enter_msg_text"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result_msg.id, c.from_user.id,
                       CBT.SEND_FP_MESSAGE, {"node_id": node_id, "username": username})
        self.bot.answer_callback_query(c.id)

    def send_funpay_message(self, message: Message):
        state_data = self.get_state(message.chat.id, message.from_user.id)["data"]
        node_id, username = state_data["node_id"], state_data["username"]
        self.clear_state(message.chat.id, message.from_user.id, True)
        response_text_to_send = message.text.strip()
        progress_msg = self.bot.send_message(message.chat.id, "✉️ Отправляю сообщение...")
        def worker():
            send_success = self.cortex.send_message(node_id, response_text_to_send, username, watermark=False)
            reply_kb = kb.reply(node_id, username, again=True, extend=True)
            if send_success:
                self.bot.edit_message_text(_("msg_sent", node_id, utils.escape(username or "Пользователь")),
                                           progress_msg.chat.id, progress_msg.id, reply_markup=reply_kb)
            else:
                self.bot.edit_message_text(_("msg_sending_error", node_id, utils.escape(username or "Пользователь")),
                                           progress_msg.chat.id, progress_msg.id, reply_markup=reply_kb)
        self.cortex.executor.submit(worker)

    def act_upload_image(self, m: Message):
        user_role = utils.get_user_role(self.authorized_users, m.from_user.id)
        if user_role != "admin":
            self.bot.send_message(m.chat.id, _("admin_only_command"))
            return
        cbt_state = CBT.UPLOAD_CHAT_IMAGE if m.text.startswith("/upload_chat_img") else CBT.UPLOAD_OFFER_IMAGE
        result_msg = self.bot.send_message(m.chat.id, _("send_img"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result_msg.id, m.from_user.id, cbt_state)

    def act_edit_greetings_text(self, c: CallbackQuery):
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_message_text", "v_chat_id", "v_chat_name", "v_photo", "v_sleep"]
        text_to_send = f"{_('v_edit_greeting_text')}\n\n{_('v_list')}:\n" + "\n".join(_(var) for var in variables)
        result_msg = self.bot.send_message(c.message.chat.id, text_to_send, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result_msg.id, c.from_user.id, CBT.EDIT_GREETINGS_TEXT)
        self.bot.answer_callback_query(c.id)

    def edit_greetings_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        new_greeting_text = m.text.strip()
        self.cortex.MAIN_CFG["Greetings"]["greetingsText"] = new_greeting_text
        logger.info(_("log_greeting_changed", m.from_user.username, m.from_user.id, new_greeting_text))
        self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
        reply_keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:gr"),
                 B(_("gl_edit"), callback_data=CBT.EDIT_GREETINGS_TEXT))
        self.bot.reply_to(m, _("greeting_changed"), reply_markup=reply_keyboard)

    def act_edit_greetings_cooldown(self, c: CallbackQuery):
        text_to_send = _('v_edit_greeting_cooldown')
        result_msg = self.bot.send_message(c.message.chat.id, text_to_send, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result_msg.id, c.from_user.id, CBT.EDIT_GREETINGS_COOLDOWN)
        self.bot.answer_callback_query(c.id)

    def edit_greetings_cooldown(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        try:
            cooldown_days = float(m.text.replace(",", "."))
            if cooldown_days < 0: raise ValueError("Cooldown не может быть отрицательным")
        except ValueError:
            self.bot.reply_to(m, _("gl_error_try_again") + " (введите число, например, 0.5 или 1)")
            return
        self.cortex.MAIN_CFG["Greetings"]["greetingsCooldown"] = str(cooldown_days)
        logger.info(_("log_greeting_cooldown_changed", m.from_user.username, m.from_user.id, str(cooldown_days)))
        self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
        reply_keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:gr"),
                 B(_("gl_edit"), callback_data=CBT.EDIT_GREETINGS_COOLDOWN))
        self.bot.reply_to(m, _("greeting_cooldown_changed", str(cooldown_days)), reply_markup=reply_keyboard)

    def act_edit_order_confirm_reply_text(self, c: CallbackQuery):
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_order_id", "v_order_link", "v_order_title", "v_game", "v_category", "v_category_fullname",
                     "v_photo", "v_sleep"]
        text_to_send = f"{_('v_edit_order_confirm_text')}\n\n{_('v_list')}:\n" + "\n".join(_(var) for var in variables)
        result_msg = self.bot.send_message(c.message.chat.id, text_to_send, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result_msg.id, c.from_user.id, CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT)
        self.bot.answer_callback_query(c.id)

    def edit_order_confirm_reply_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        new_reply_text = m.text.strip()
        self.cortex.MAIN_CFG["OrderConfirm"]["replyText"] = new_reply_text
        logger.info(_("log_order_confirm_changed", m.from_user.username, m.from_user.id, new_reply_text))
        self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
        reply_keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:oc"),
                 B(_("gl_edit"), callback_data=CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT))
        self.bot.reply_to(m, _("order_confirm_changed"), reply_markup=reply_keyboard)

    def act_edit_review_reply_text(self, c: CallbackQuery):
        stars_count = int(c.data.split(":")[1])
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_order_id", "v_order_link", "v_order_title", "v_order_params",
                     "v_order_desc_and_params", "v_order_desc_or_params", "v_game", "v_category", "v_category_fullname"]
        text_to_send = f"{_('v_edit_review_reply_text', '⭐' * stars_count)}\n\n{_('v_list')}:\n" + "\n".join(_(var) for var in variables)
        result_msg = self.bot.send_message(c.message.chat.id, text_to_send, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result_msg.id, c.from_user.id, CBT.EDIT_REVIEW_REPLY_TEXT, {"stars": stars_count})
        self.bot.answer_callback_query(c.id)

    def edit_review_reply_text(self, m: Message):
        state_data = self.get_state(m.chat.id, m.from_user.id)
        if not state_data or "data" not in state_data or "stars" not in state_data["data"]:
            logger.warning(f"Некорректное состояние для edit_review_reply_text, user: {m.from_user.id}")
            self.clear_state(m.chat.id, m.from_user.id, True)
            self.bot.reply_to(m, _("gl_error_try_again"))
            return
        stars_count = state_data["data"]["stars"]
        self.clear_state(m.chat.id, m.from_user.id, True)
        new_review_reply = m.text.strip()
        self.cortex.MAIN_CFG["ReviewReply"][f"star{stars_count}ReplyText"] = new_review_reply
        logger.info(_("log_review_reply_changed", m.from_user.username, m.from_user.id, stars_count, new_review_reply))
        self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
        reply_keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:rr"),
                 B(_("gl_edit"), callback_data=f"{CBT.EDIT_REVIEW_REPLY_TEXT}:{stars_count}"))
        self.bot.reply_to(m, _("review_reply_changed", '⭐' * stars_count), reply_markup=reply_keyboard)

    def open_reply_menu(self, c: CallbackQuery):
        split_data = c.data.split(":")
        node_id, username = int(split_data[1]), split_data[2]
        is_again_reply = int(split_data[3])
        should_extend = True if len(split_data) > 4 and int(split_data[4]) else False
        try:
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=kb.reply(node_id, username, bool(is_again_reply), should_extend))
        except ApiTelegramException as e:
            if e.error_code == 400 and "message is not modified" in e.description.lower():
                pass
            else:
                raise e
        self.bot.answer_callback_query(c.id)

    def extend_new_message_notification(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        chat_id_str, username = c.data.split(":")[1:]
        def worker():
            try:
                chat_obj = self.cortex.account.get_chat(int(chat_id_str))
            except Exception as e:
                logger.warning(f"Не удалось получить чат {chat_id_str} для расширения: {e}")
                logger.debug("TRACEBACK", exc_info=True)
                self.bot.edit_message_text(f"❌ {_('get_chat_error')}", c.message.chat.id, c.message.id)
                return
            text_to_send = ""
            if chat_obj.looking_link:
                text_to_send += f"<b>{_('viewing')}:</b> <a href=\"{chat_obj.looking_link}\">{utils.escape(chat_obj.looking_text)}</a>\n\n"
            chat_messages = chat_obj.messages[-10:]
            last_author_id = -1
            last_by_bot_flag = False
            last_author_badge = None
            last_by_fpcortex = False
            for msg_item in chat_messages:
                author_prefix = ""
                if msg_item.author_id == last_author_id and \
                   msg_item.by_bot == last_by_bot_flag and \
                   msg_item.badge == last_author_badge and \
                   last_by_fpcortex == (msg_item.by_bot and msg_item.author_id == self.cortex.account.id):
                    pass
                elif msg_item.author_id == self.cortex.account.id:
                    author_prefix = f"<i><b>🤖 {utils.escape(_('you'))} (FunPayBot):</b></i> " if msg_item.by_bot else f"<i><b>😎 {utils.escape(_('you'))}:</b></i> "
                    if msg_item.is_autoreply:
                        author_prefix = f"<i><b>📦 {utils.escape(_('you'))} ({utils.escape(msg_item.badge or '')}):</b></i> "
                elif msg_item.author_id == 0:
                    author_prefix = f"<i><b>🔵 {utils.escape(msg_item.author or 'FunPay')}: </b></i>"
                elif msg_item.is_employee:
                    author_prefix = f"<i><b>🛡️ {utils.escape(msg_item.author or 'Support')} ({utils.escape(msg_item.badge or '')}): </b></i>"
                elif msg_item.author == msg_item.chat_name:
                    author_prefix = f"<i><b>👤 {utils.escape(msg_item.author or 'User')}: </b></i>"
                    if msg_item.is_autoreply:
                        author_prefix = f"<i><b>🛍️ {utils.escape(msg_item.author or 'User')} ({utils.escape(msg_item.badge or '')}):</b></i> "
                    elif msg_item.author and msg_item.author in self.cortex.blacklist:
                        author_prefix = f"<i><b>🚷 {utils.escape(msg_item.author)}: </b></i>"
                    elif msg_item.by_bot and msg_item.author_id != self.cortex.account.id :
                         author_prefix = f"<i><b>👾 {utils.escape(msg_item.author or 'Bot')}: </b></i>"
                else:
                    author_prefix = f"<i><b>⚖️ {utils.escape(msg_item.author or 'Arbiter')} ({_('support')}): </b></i>"
                message_content_text = msg_item.text
                if msg_item.image_link:
                     message_content_text = f"<a href=\"{msg_item.image_link}\">" \
                                         f"{utils.escape(msg_item.image_name) if self.cortex.MAIN_CFG['NewMessageView'].getboolean('showImageName') and not (msg_item.author_id == self.cortex.account.id and msg_item.by_bot) else _('photo')}</a>"
                text_to_send += f"{author_prefix}{utils.escape(message_content_text or '')}\n\n"
                last_author_id = msg_item.author_id
                last_by_bot_flag = msg_item.by_bot
                last_author_badge = msg_item.badge
                last_by_fpcortex = msg_item.by_bot and msg_item.author_id == self.cortex.account.id
            text_to_send = text_to_send.strip()
            if not text_to_send: text_to_send = f"<i>({_('no_messages_to_display')})</i>"
            try:
                self.bot.edit_message_text(text_to_send, c.message.chat.id, c.message.id,
                                       reply_markup=kb.reply(int(chat_id_str), username, False, False))
            except ApiTelegramException as e:
                if e.error_code == 400 and "message is not modified" in e.description.lower(): pass
                else:
                    logger.error(f"Ошибка при расширении уведомления: {e}")
                    logger.debug("TRACEBACK", exc_info=True)
        self.cortex.executor.submit(worker)

    def ask_confirm_refund(self, call: CallbackQuery):
        split_data = call.data.split(":")
        order_id, node_id, username = split_data[1], int(split_data[2]), split_data[3]
        refund_confirm_keyboard = kb.new_order(order_id, username, node_id, confirmation=True)
        self.bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=refund_confirm_keyboard)
        self.bot.answer_callback_query(call.id)

    def cancel_refund(self, call: CallbackQuery):
        split_data = call.data.split(":")
        order_id, node_id, username = split_data[1], int(split_data[2]), split_data[3]
        order_keyboard = kb.new_order(order_id, username, node_id)
        self.bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=order_keyboard)
        self.bot.answer_callback_query(call.id)

    def refund(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        split_data = c.data.split(":")
        order_id, node_id, username = split_data[1], int(split_data[2]), split_data[3]
        progress_message = self.bot.send_message(c.message.chat.id, f"💸 Возвращаю средства по заказу <code>#{order_id}</code>...")
        def worker():
            attempts_left = 3
            refund_successful = False
            while attempts_left > 0:
                try:
                    self.cortex.account.refund(order_id)
                    refund_successful = True
                    break
                except Exception as e:
                    logger.error(f"Ошибка возврата заказа #{order_id}, попытка {4 - attempts_left}: {e}")
                    logger.debug("TRACEBACK", exc_info=True)
                    attempt_message_text = _("refund_attempt", order_id, attempts_left - 1)
                    try: self.bot.edit_message_text(attempt_message_text, progress_message.chat.id, progress_message.id)
                    except ApiTelegramException: pass
                    attempts_left -= 1
                    if attempts_left > 0: time.sleep(1)
            final_message_text = _("refund_complete", order_id) if refund_successful else _("refund_error", order_id)
            try: self.bot.edit_message_text(final_message_text, progress_message.chat.id, progress_message.id)
            except ApiTelegramException: pass
            order_keyboard_after_refund = kb.new_order(order_id, username, node_id, no_refund=refund_successful)
            try:
                self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=order_keyboard_after_refund)
            except ApiTelegramException as e:
                if "message to edit not found" in e.description:
                    logger.warning(f"Не удалось обновить клавиатуру для заказа {order_id}: исходное сообщение не найдено.")
                else:
                    logger.warning(f"Не удалось обновить клавиатуру для заказа {order_id}: {e}")
        self.cortex.executor.submit(worker)

    def open_order_menu(self, c: CallbackQuery):
        split_data = c.data.split(":")
        node_id, username, order_id = int(split_data[1]), split_data[2], split_data[3]
        no_refund_flag = bool(int(split_data[4]))
        try:
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=kb.new_order(order_id, username, node_id, no_refund=no_refund_flag))
        except ApiTelegramException as e:
            if e.error_code == 400 and "message is not modified" in e.description.lower(): pass
            else: raise e
        self.bot.answer_callback_query(c.id)

    def open_cp(self, c: CallbackQuery):
        desc_text = _("desc_main")
        try:
            if c.message.content_type == 'text':
                self.bot.edit_message_text(desc_text, c.message.chat.id, c.message.id,
                                       reply_markup=skb.SETTINGS_SECTIONS(self.cortex, c.from_user.id))
            else:
                try: self.bot.delete_message(c.message.chat.id, c.message.id)
                except: pass
                self.bot.send_message(c.message.chat.id, desc_text, reply_markup=skb.SETTINGS_SECTIONS(self.cortex, c.from_user.id))
        except ApiTelegramException as e:
            if "message is not modified" not in e.description:
                raise
        self.bot.answer_callback_query(c.id)

    def open_settings_section(self, c: CallbackQuery):
        section_key = c.data.split(":")[1]
        user_id = c.from_user.id
        user_role = utils.get_user_role(self.authorized_users, user_id)
        mp = self.cortex.MAIN_CFG["ManagerPermissions"]
        admin_only_sections = ["bl", "au"]
        manager_sections = {
            "ar": "autoResponse", "ad": "autoDelivery", "tmplt": "templates", "gr": "greetings",
            "oc": "orderConfirm", "rr": "reviewReply", "pl": "plugins", "proxy": "proxy",
            "stats": "statistics"
        }
        if section_key in admin_only_sections and user_role != "admin":
            self.bot.answer_callback_query(c.id, _("admin_only_command"), show_alert=True)
            return
        if user_role == "manager" and section_key in manager_sections and not mp.getboolean(manager_sections.get(section_key, "")):
            self.bot.answer_callback_query(c.id, _("admin_only_command"), show_alert=True)
            return
        sections_map = {
            "automation": (_("mm_automation_section"), skb.AUTOMATION_SETTINGS, [self.cortex, user_id]),
            "management": (_("mm_management_section"), skb.MANAGEMENT_SETTINGS, [self.cortex, user_id]),
            "system": (_("mm_system_section"), skb.SYSTEM_SETTINGS, [self.cortex, user_id]),
            "main": (_("desc_gs"), kb.main_settings, [self.cortex]),
            "raise": (_("desc_raise"), kb.auto_raise_settings, [self.cortex]),
            "tg": (_("desc_ns", c.message.chat.id), kb.notifications_settings, [self.cortex, c.message.chat.id]),
            "bl": (_("desc_bl"), kb.blacklist_settings, [self.cortex]),
            "ar": (_("desc_ar"), skb.AR_SETTINGS, []),
            "ad": (_("desc_ad"), skb.AD_SETTINGS, []),
            "mv": (_("desc_mv"), kb.new_message_view_settings, [self.cortex]),
            "rr": (_("desc_or"), kb.review_reply_settings, [self.cortex]),
            "gr": (_("desc_gr", utils.escape(self.cortex.MAIN_CFG['Greetings']['greetingsText'])),
                   kb.greeting_settings, [self.cortex]),
            "oc": (_("desc_oc", utils.escape(self.cortex.MAIN_CFG['OrderConfirm']['replyText'])),
                   kb.order_confirm_reply_settings, [self.cortex]),
            "au": (_("desc_au"), lambda c_instance, offset: kb.authorized_users(c_instance, offset, user_id), [self.cortex, 0]),
            "tmplt": (_("desc_tmplt"), lambda c_instance: kb.templates_list(c_instance, 0), [self.cortex]),
            "pl": (_("desc_pl"), lambda c_instance: kb.plugins_list(c_instance, 0), [self.cortex]),
            "proxy": (_("desc_proxy"), lambda c_instance: kb.proxy(c_instance, 0, getattr(c_instance.telegram, 'pr_dict', {})), [self.cortex]),
        }
        current_section_data = sections_map.get(section_key)
        if current_section_data:
            desc_text, kb_generator, kb_args = current_section_data
            try:
                if c.message.content_type == 'text':
                    self.bot.edit_message_text(desc_text, c.message.chat.id, c.message.id, reply_markup=kb_generator(*kb_args))
                else:
                    try: self.bot.delete_message(c.message.chat.id, c.message.id)
                    except: pass
                    self.bot.send_message(c.message.chat.id, desc_text, reply_markup=kb_generator(*kb_args))
            except ApiTelegramException as e:
                if "message is not modified" not in e.description: pass
                else: raise e
        else:
            self.bot.answer_callback_query(c.id, _("unknown_action"), show_alert=True)
            return
        self.bot.answer_callback_query(c.id)

    def switch_param(self, c: CallbackQuery):
        parts = c.data.split(":")
        section, param = parts[1], parts[2]
        offset = int(parts[3]) if len(parts) > 3 else 0
        current_value = self.cortex.MAIN_CFG.get(section, param, fallback='0')
        new_value = "0" if current_value == "1" else "1"
        self.cortex.MAIN_CFG.set(section, param, new_value)
        self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
        logger.info(_("log_param_changed", c.from_user.username, c.from_user.id, param, section, new_value))
        kb_map = {
            "FunPay": kb.main_settings,
            "BlockList": kb.blacklist_settings,
            "NewMessageView": kb.new_message_view_settings,
            "Greetings": kb.greeting_settings,
            "OrderConfirm": kb.order_confirm_reply_settings,
            "ReviewReply": kb.review_reply_settings,
            "ManagerPermissions": kb.manager_permissions_settings,
        }
        kb_to_render = None
        if section in kb_map:
            kb_to_render = kb_map[section](self.cortex)
        elif section == "Telegram":
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                               reply_markup=kb.authorized_users(self.cortex, offset, c.from_user.id))
            self.bot.answer_callback_query(c.id)
            return
        if kb_to_render:
            try: self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=kb_to_render)
            except ApiTelegramException as e:
                if "message is not modified" not in e.description: raise
        else:
            self.bot.answer_callback_query(c.id, "✅", show_alert=False)
            self.open_cp(c)
            return
        self.bot.answer_callback_query(c.id)

    def switch_chat_notification(self, c: CallbackQuery):
        try:
            __, chat_id_str, notification_type = c.data.split(":")
            chat_id = int(chat_id_str)
        except ValueError as e:
            logger.error(f"Некорректные данные в callback для переключения уведомлений: {c.data} - {e}")
            self.bot.answer_callback_query(c.id, _("gl_error"), show_alert=True)
            return
        new_status = self.toggle_notification(chat_id, notification_type)
        logger.info(_("log_notification_switched", c.from_user.username, c.from_user.id, 
                      notification_type, chat_id, "ON" if new_status else "OFF"))
        try:
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                               reply_markup=kb.notifications_settings(self.cortex, chat_id))
        except ApiTelegramException as e:
            if "message is not modified" not in e.description: raise
        self.bot.answer_callback_query(c.id)

    def cancel_action(self, call: CallbackQuery):
        clear_result = self.clear_state(call.message.chat.id, call.from_user.id, True)
        self.bot.answer_callback_query(call.id)

    def param_disabled(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id, _("param_disabled"), show_alert=True)

    def send_announcements_kb(self, m: Message):
        self.bot.send_message(m.chat.id, _("desc_an"), reply_markup=kb.announcements_settings(self.cortex, m.chat.id))

    def send_review_reply_text(self, c: CallbackQuery):
        stars_count = int(c.data.split(":")[1])
        reply_text = self.cortex.MAIN_CFG["ReviewReply"][f"star{stars_count}ReplyText"]
        edit_keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:rr"),
                 B(_("gl_edit"), callback_data=f"{CBT.EDIT_REVIEW_REPLY_TEXT}:{stars_count}"))
        if not reply_text:
            self.bot.send_message(c.message.chat.id, _("review_reply_empty", "⭐" * stars_count), reply_markup=edit_keyboard)
        else:
            self.bot.send_message(c.message.chat.id, _("review_reply_text", "⭐" * stars_count,
                                                       utils.escape(reply_text)),
                                  reply_markup=edit_keyboard)
        self.bot.answer_callback_query(c.id)

    def send_old_mode_help_text(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        self.bot.send_message(c.message.chat.id, _("old_mode_help"))

    def empty_callback(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)

    def switch_lang(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        selected_lang = c.data.split(":")[1]
        def worker():
            Localizer(selected_lang)
            self.cortex.MAIN_CFG["Other"]["language"] = selected_lang
            self.cortex.save_config(self.cortex.MAIN_CFG, os.path.join(self.cortex.base_path, "configs/_main.cfg"))
            c.data = f"{CBT.CATEGORY}:lang"
            self.open_settings_section(c)
        self.cortex.executor.submit(worker)

    def show_help(self, c: CallbackQuery):
        try:
            help_topic_key = c.data.split(":")[1]
            help_text = _(f"help_{help_topic_key}")
            self.bot.answer_callback_query(c.id, help_text, show_alert=True)
        except (IndexError, KeyError) as e:
            logger.warning(f"Не удалось найти текст подсказки для {c.data}: {e}")
            self.bot.answer_callback_query(c.id, _("gl_error"), show_alert=True)

    def __register_handlers(self):
        self.mdw_handler(self.setup_chat_notifications, update_types=['message'])
        self.msg_handler(self.reg_admin, func=lambda msg: msg.from_user.id not in self.authorized_users,
                         content_types=['text'], chat_types=['private'])
        self.cbq_handler(self.ignore_unauthorized_users, lambda c: c.from_user.id not in self.authorized_users)
        self.cbq_handler(self.param_disabled, lambda c: c.data.startswith(CBT.PARAM_DISABLED))
        self.msg_handler(self.run_file_handlers, content_types=["photo", "document"],
                         func=lambda m: self.is_file_handler(m))
        self.msg_handler(self.send_settings_menu, commands=["menu", "start"])
        self.msg_handler(self.send_profile, commands=["profile"])
        self.msg_handler(self.send_balance, commands=["balance"])
        self.cbq_handler(self.update_balance, lambda c: c.data == CBT.BALANCE_REFRESH)
        self.msg_handler(self.act_change_cookie, commands=["change_cookie", "golden_key"])
        self.msg_handler(self.change_cookie, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.CHANGE_GOLDEN_KEY))
        self.cbq_handler(self.update_profile, lambda c: c.data == CBT.UPDATE_PROFILE)
        self.cbq_handler(self.open_profile_menu, lambda c: c.data == CBT.PROFILE_MENU)
        self.msg_handler(self.act_manual_delivery_test, commands=["test_lot"])
        self.msg_handler(self.act_upload_image, commands=["upload_chat_img", "upload_offer_img"])
        self.cbq_handler(self.act_edit_greetings_text, lambda c: c.data == CBT.EDIT_GREETINGS_TEXT)
        self.msg_handler(self.edit_greetings_text, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_GREETINGS_TEXT))
        self.cbq_handler(self.act_edit_greetings_cooldown, lambda c: c.data == CBT.EDIT_GREETINGS_COOLDOWN)
        self.msg_handler(self.edit_greetings_cooldown, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_GREETINGS_COOLDOWN))
        self.cbq_handler(self.act_edit_order_confirm_reply_text, lambda c: c.data == CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT)
        self.msg_handler(self.edit_order_confirm_reply_text, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT))
        self.cbq_handler(self.act_edit_review_reply_text, lambda c: c.data.startswith(f"{CBT.EDIT_REVIEW_REPLY_TEXT}:"))
        self.msg_handler(self.edit_review_reply_text, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_REVIEW_REPLY_TEXT))
        self.msg_handler(self.manual_delivery_text, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.MANUAL_AD_TEST))
        self.msg_handler(self.act_ban, commands=["ban"])
        self.msg_handler(self.ban, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.BAN))
        self.msg_handler(self.act_unban, commands=["unban"])
        self.msg_handler(self.unban, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.UNBAN))
        self.msg_handler(self.send_ban_list, commands=["black_list"])
        self.msg_handler(self.act_edit_watermark, commands=["watermark"])
        self.msg_handler(self.edit_watermark, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_WATERMARK))
        self.msg_handler(self.send_logs, commands=["logs"])
        self.msg_handler(self.del_logs, commands=["del_logs"])
        self.msg_handler(self.about, commands=["about"])
        self.msg_handler(self.get_backup, commands=["get_backup"])
        self.msg_handler(self.create_backup, commands=["create_backup"])
        self.msg_handler(self.send_system_info, commands=["sys"])
        self.msg_handler(self.restart_cortex, commands=["restart"])
        self.msg_handler(self.ask_power_off, commands=["power_off"])
        self.msg_handler(self.send_announcements_kb, commands=["announcements"])
        self.cbq_handler(self.send_review_reply_text, lambda c: c.data.startswith(f"{CBT.SEND_REVIEW_REPLY_TEXT}:"))
        self.cbq_handler(self.act_send_funpay_message, lambda c: c.data.startswith(f"{CBT.SEND_FP_MESSAGE}:"))
        self.cbq_handler(self.open_reply_menu, lambda c: c.data.startswith(f"{CBT.BACK_TO_REPLY_KB}:"))
        self.cbq_handler(self.extend_new_message_notification, lambda c: c.data.startswith(f"{CBT.EXTEND_CHAT}:"))
        self.msg_handler(self.send_funpay_message, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.SEND_FP_MESSAGE))
        self.cbq_handler(self.ask_confirm_refund, lambda c: c.data.startswith(f"{CBT.REQUEST_REFUND}:"))
        self.cbq_handler(self.cancel_refund, lambda c: c.data.startswith(f"{CBT.REFUND_CANCELLED}:"))
        self.cbq_handler(self.refund, lambda c: c.data.startswith(f"{CBT.REFUND_CONFIRMED}:"))
        self.cbq_handler(self.open_order_menu, lambda c: c.data.startswith(f"{CBT.BACK_TO_ORDER_KB}:"))
        self.cbq_handler(self.open_cp, lambda c: c.data == CBT.MAIN)
        self.cbq_handler(self.open_settings_section, lambda c: c.data.startswith(f"{CBT.CATEGORY}:"))
        self.cbq_handler(self.switch_param, lambda c: c.data.startswith(f"{CBT.SWITCH}:"))
        self.cbq_handler(self.switch_chat_notification, lambda c: c.data.startswith(f"{CBT.SWITCH_TG_NOTIFICATIONS}:"))
        self.cbq_handler(self.power_off, lambda c: c.data.startswith(f"{CBT.SHUT_DOWN}:"))
        self.cbq_handler(self.cancel_power_off, lambda c: c.data == CBT.CANCEL_SHUTTING_DOWN)
        self.cbq_handler(self.cancel_action, lambda c: c.data == CBT.CLEAR_STATE)
        self.cbq_handler(self.send_old_mode_help_text, lambda c: c.data == CBT.OLD_MOD_HELP)
        self.cbq_handler(self.empty_callback, lambda c: c.data == CBT.EMPTY)
        self.cbq_handler(self.show_help, lambda c: c.data.startswith(f"{CBT.SHOW_HELP}:"))
        self.msg_handler(self.setup_proxy_mandatory, func=lambda m: self.check_state(m.chat.id, m.from_user.id, "SETUP_PROXY_MANDATORY"))

    def init(self):
        self.__register_handlers()

    def run(self):
        self.send_notification(_("bot_started"), notification_type=utils.NotificationTypes.bot_start)
        k_err_count = 0
        while True:
            try:
                bot_username = self.bot.get_me().username
                logger.info(_("log_tg_started", bot_username))
                self.bot.infinity_polling(logger_level=logging.WARNING, timeout=60, long_polling_timeout=30, skip_pending=True)
            except ApiTelegramException as e_api:
                k_err_count += 1
                logger.error(_("log_tg_update_error", k_err_count) + f" (API Error: {e_api.error_code} - {e_api.description})")
                logger.debug("TRACEBACK", exc_info=True)
                if e_api.error_code == 401:
                    logger.critical("Критическая ошибка: токен Telegram-бота недействителен. Проверьте токен в _main.cfg. Бот остановлен.")
                    cortex_tools.shut_down()
                    break
                elif e_api.error_code == 409:
                     logger.critical("Критическая ошибка: обнаружен конфликт (409). Возможно, запущена другая копия бота с этим же токеном. Бот остановлен.")
                     cortex_tools.shut_down()
                     break
                time.sleep(30)
            except requests.exceptions.ConnectionError as e_conn:
                k_err_count += 1
                logger.error(_("log_tg_update_error", k_err_count) + f" (Connection Error: {e_conn})")
                logger.debug("TRACEBACK", exc_info=True)
                time.sleep(60)
            except Exception as e:
                k_err_count += 1
                logger.error(_("log_tg_update_error", k_err_count) + f" (General Error: {e})")
                logger.debug("TRACEBACK", exc_info=True)
                time.sleep(15)

    def is_file_handler(self, m: Message) -> bool:
        state = self.get_state(m.chat.id, m.from_user.id)
        return state is not None and state["state"] in self.file_handlers

    # Добавлен аргумент mute=False
    def send_notification(self, text: str | None, reply_markup: K | None = None,
                          notification_type: str = NotificationTypes.other, photo: bytes | io.BytesIO | None = None,
                          pin: bool = False, exclude_chat_id: int | None = None, caption: str | None = None,
                          mute: bool = False): 
        if not self.authorized_users:
            return
        for user_id in self.authorized_users:
            if exclude_chat_id and user_id == exclude_chat_id:
                continue
            if not self.is_notification_enabled(user_id, notification_type):
                continue
            try:
                msg = None
                if photo:
                    if hasattr(photo, 'name'):
                        # Передаем disable_notification=mute
                        msg = self.bot.send_document(user_id, photo, caption=caption or text, reply_markup=reply_markup, disable_notification=mute)
                    else:
                        # Передаем disable_notification=mute
                        msg = self.bot.send_photo(user_id, photo, caption=caption or text, reply_markup=reply_markup, disable_notification=mute)
                elif text:
                    # Передаем disable_notification=mute
                    msg = self.bot.send_message(user_id, text, reply_markup=reply_markup, disable_notification=mute)
                if pin and msg:
                    try: self.bot.pin_chat_message(user_id, msg.id)
                    except: pass
            except Exception as e:
                logger.error(_("log_tg_notification_error", user_id) + f": {e}")
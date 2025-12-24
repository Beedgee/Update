# START OF FILE FunPayCortex/tg_bot/default_cp.py
# -*- coding: utf-8 -*-

"""
FunPayBot by @beedge
--------------------------
Модуль с обработчиком по умолчанию (fallback) для всех callback-запросов.
Также включает команду обновления бота.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import logging
import os 
import requests 
import json

if TYPE_CHECKING:
    from cortex import Cortex
from telebot.types import CallbackQuery, Message

from locales.localizer import Localizer
from tg_bot import keyboards as kb, CBT

localizer = Localizer()
_ = localizer.translate

def init_update_command(cortex_instance: Cortex, *args):
    """Инициализирует обработчик для команды /update."""
    tg = cortex_instance.telegram
    bot = tg.bot
    logger = logging.getLogger("TGBot.update_command")

    def handle_update(m: Message):
        if m.from_user.id not in tg.authorized_users:
            return

        current_version = cortex_instance.VERSION
        msg = bot.send_message(m.chat.id, f"⏳ **Проверяю наличие обновлений...**\n(Текущая версия: `{current_version}`)", parse_mode="Markdown")
        
        def do_request():
            """Выполняет API-запросы для проверки и обновления."""
            try:
                # URL для внутренней сети Docker
                base_url = os.getenv("FPCORTEX_INTERNAL_BACKEND_URL", "http://backend:8000")
                
                if not base_url or not cortex_instance.hosting_token:
                    bot.edit_message_text("⚠️ **Ошибка:** Бот не подключен к хостинг-панели. Обновление невозможно.", msg.chat.id, msg.id)
                    return

                headers = {"X-Bot-Token": cortex_instance.hosting_token}
                
                # 1. Проверяем актуальную версию на сервере
                version_url = f"{base_url}/api/bot/latest-version"
                try:
                    ver_response = requests.get(version_url, headers=headers, timeout=10)
                    if ver_response.ok:
                        latest_version = ver_response.json().get("version", "unknown").strip()
                    else:
                        raise Exception(f"Ошибка получения версии: {ver_response.status_code}")
                except Exception as e:
                    logger.error(f"Ошибка проверки версии: {e}")
                    bot.edit_message_text(f"⚠️ **Ошибка при проверке версии:**\n`{e}`", msg.chat.id, msg.id, parse_mode="Markdown")
                    return

                # 2. Сравниваем версии
                if latest_version == current_version:
                    bot.edit_message_text(
                        f"✅ **Обновлений нет.**\n\n"
                        f"Бот работает на самой актуальной версии: `{current_version}`.", 
                        msg.chat.id, msg.id, parse_mode="Markdown"
                    )
                    return

                # 3. Если есть новая версия - обновляем
                bot.edit_message_text(
                    f"🎉 **Найдено обновление!**\n"
                    f"Текущая версия: `{current_version}`\n"
                    f"Новая версия: `{latest_version}`\n\n"
                    f"🚀 **Начинаю обновление...**\n"
                    f"_Бот перезапустится автоматически._",
                    msg.chat.id, msg.id, parse_mode="Markdown"
                )

                update_url = f"{base_url}/api/bot/request-update"
                payload = {"user_id": cortex_instance.HOSTING_USER_ID}
                
                if not payload["user_id"]:
                     bot.send_message(m.chat.id, "⚠️ **Ошибка:** Не найден ID пользователя. Обратитесь к администратору.", parse_mode="Markdown")
                     return

                response = requests.post(update_url, headers=headers, json=payload, timeout=30)

                if not response.ok:
                    error_details = response.json().get("detail", response.text)
                    bot.send_message(m.chat.id, f"⚠️ **Ошибка при запуске обновления:**\nСервер вернул код {response.status_code}.\n`{error_details}`", parse_mode="Markdown")
                else:
                    # Успешный запуск обновления. Бот скоро перезагрузится
                    pass
                    
            except Exception as e:
                logger.error(f"Критическая ошибка в процессе обновления: {e}")
                try:
                    bot.edit_message_text(f"⚠️ **Критическая ошибка:**\n`{e}`", msg.chat.id, msg.id, parse_mode="Markdown")
                except: pass

        cortex_instance.executor.submit(do_request)
        
    tg.msg_handler(handle_update, commands=["update"])

def init_raise_category_updater(cortex_instance: Cortex, *args):
    """Инициализирует обработчик для кнопки обновления категорий."""
    tg = cortex_instance.telegram
    bot = tg.bot

    def update_raise_info(c: CallbackQuery):
        """Обновляет информацию о лотах и категориях в профиле."""
        bot.answer_callback_query(c.id)
        msg = bot.send_message(c.message.chat.id, _("ad_updating_lots_list"))

        def threaded_update():
            if cortex_instance.update_lots_and_categories():
                try:
                    bot.delete_message(msg.chat.id, msg.id)
                except:
                    pass
                bot.answer_callback_query(c.id, "✅ Информация о категориях успешно обновлена!", show_alert=True)
                try:
                    bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                                reply_markup=kb.auto_raise_settings(cortex_instance))
                except:
                    pass
            else:
                bot.edit_message_text(_("ad_lots_list_updating_err"), msg.chat.id, msg.id)
        
        cortex_instance.executor.submit(threaded_update)

    tg.cbq_handler(update_raise_info, func=lambda c: c.data == CBT.UPDATE_RAISE_CATEGORIES)

def init_default_cp(cortex_instance: Cortex, *args):
    """
    Инициализирует и регистрирует обработчик по умолчанию.
    """
    tg = cortex_instance.telegram
    bot = tg.bot

    def default_callback_answer(c: CallbackQuery):
        """
        Отвечает на колбэки, которые не поймал ни один хендлер.
        """
        translated_text = _(c.data, language=localizer.current_language)
        
        if translated_text != c.data:
            bot.answer_callback_query(c.id, text=translated_text, show_alert=True)
        else:
            bot.answer_callback_query(c.id, text=_("unknown_action"), show_alert=True)

    tg.cbq_handler(default_callback_answer, lambda c: True)


BIND_TO_POST_INIT = [init_update_command, init_raise_category_updater, init_default_cp]
# END OF FILE FunPayCortex/tg_bot/default_cp.py
# START OF FILE FunPayCortex/tg_bot/config_loader_cp.py

"""
FunPayBot by @beedge
--------------------------
Модуль для управления загрузкой и выгрузкой конфигурационных файлов (.cfg) через Telegram.
Позволяет пользователям получать и обновлять основные настройки бота.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex import Cortex

from tg_bot import CBT, static_keyboards
from telebot import types
import logging
import os

from locales.localizer import Localizer

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def init_config_loader_cp(cortex_instance: Cortex, *args):
    """
    Инициализирует и регистрирует обработчики для раздела "Конфигурации".
    """
    tg = cortex_instance.telegram
    bot = tg.bot

    def open_config_loader(c: types.CallbackQuery):
        """
        Открывает главное меню управления конфигурациями.
        """
        text_to_send = _("desc_cfg")
        # Используем статическую клавиатуру для этого меню
        reply_markup_kb = static_keyboards.CONFIGS_UPLOADER()

        # Если текущее сообщение не текстовое (например, фото), удаляем его и отправляем новое
        if c.message.content_type != 'text':
            try: bot.delete_message(c.message.chat.id, c.message.id)
            except: pass
            bot.send_message(c.message.chat.id, text_to_send, reply_markup=reply_markup_kb)
        else:
            bot.edit_message_text(text_to_send, c.message.chat.id, c.message.id,
                                  reply_markup=reply_markup_kb)
        bot.answer_callback_query(c.id)

    def send_config(c: types.CallbackQuery):
        """
        Отправляет пользователю запрошенный файл конфигурации.
        """
        config_type_key = c.data.split(":")[1]
        
        config_details = {
            "main": ("configs/_main.cfg", _("cfg_main")),
            "autoResponse": ("configs/auto_response.cfg", _("cfg_ar")),
            "autoDelivery": ("configs/auto_delivery.cfg", _("cfg_ad"))
        }

        if config_type_key not in config_details:
            bot.answer_callback_query(c.id, _("gl_error_try_again") + " (unknown config type)", show_alert=True)
            return

        path, caption_text = config_details[config_type_key]
        full_path = os.path.join(cortex_instance.base_path, path)

        if not os.path.exists(full_path):
            bot.answer_callback_query(c.id, _("cfg_not_found_err", path), show_alert=True)
            return

        try:
            with open(full_path, "rb") as f_send:
                # Проверяем, что файл не пустой
                if not f_send.read().strip():
                    bot.answer_callback_query(c.id, _("cfg_empty_err", path), show_alert=True)
                    return
                
                f_send.seek(0) # Возвращаем курсор в начало файла
                bot.send_document(c.message.chat.id, f_send, caption=caption_text)
            
            logger.info(_("log_cfg_downloaded", c.from_user.username, c.from_user.id, path))
            bot.answer_callback_query(c.id)
        except Exception as e:
            logger.error(f"Ошибка при отправке конфига {path}: {e}")
            bot.answer_callback_query(c.id, _("gl_error_try_again"), show_alert=True)

    # Регистрация обработчиков
    tg.cbq_handler(open_config_loader, lambda c: c.data == CBT.CONFIG_LOADER)
    tg.cbq_handler(send_config, lambda c: c.data.startswith(f"{CBT.DOWNLOAD_CFG}:"))

BIND_TO_PRE_INIT = [init_config_loader_cp]
# END OF FILE FunPayCortex/tg_bot/config_loader_cp.py
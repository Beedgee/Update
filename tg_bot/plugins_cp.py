"""
В данном модуле описаны функции для ПУ шаблонами ответа.
Модуль реализован в виде плагина.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex import Cortex
    from tg_bot.bot import TGBot

from tg_bot import utils, keyboards, CBT
from tg_bot.static_keyboards import CLEAR_STATE_BTN
from locales.localizer import Localizer

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery
import datetime
import logging

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def init_plugins_cp(cortex: Cortex, *args):
    tg = cortex.telegram
    bot = tg.bot

    def check_plugin_exists(uuid: str, message_obj: Message) -> bool:
        """
        Проверяет, существует ли плагин с переданным UUID.
        Если команда не существует - отправляет сообщение с кнопкой обновления списка плагинов.

        :param uuid: UUID плагина.

        :param message_obj: экземпляр Telegram-сообщения.

        :return: True, если плагин существует, False, если нет.
        """
        if uuid not in cortex.plugins:
            update_button = K().add(B(_("gl_refresh"), callback_data=f"{CBT.PLUGINS_LIST}:0"))
            bot.edit_message_text(_("pl_not_found_err", uuid), message_obj.chat.id, message_obj.id,
                                  reply_markup=update_button)
            return False
        return True

    def open_plugins_list(c: CallbackQuery):
        """
        Открывает список плагинов.
        """
        offset = int(c.data.split(":")[1])
        bot.edit_message_text(_("desc_pl"), c.message.chat.id, c.message.id,
                              reply_markup=keyboards.plugins_list(cortex, offset))
        bot.answer_callback_query(c.id)

    def open_edit_plugin_cp(c: CallbackQuery):
        """
        Открывает панель настроек плагина.
        """
        split = c.data.split(":")
        uuid, offset = split[1], int(split[2])

        if not check_plugin_exists(uuid, c.message):
            bot.answer_callback_query(c.id)
            return

        plugin_data = cortex.plugins[uuid]
        text = f"""<b><i>{utils.escape(plugin_data.name)} v{utils.escape(plugin_data.version)}</i></b>
        
{utils.escape(plugin_data.description)}

<b><i>UUID: </i></b><code>{utils.escape(plugin_data.uuid)}</code>

<b><i>{_('pl_author')}: </i></b>{utils.escape(plugin_data.credits)}

<i>{_('gl_last_update')}:</i>  <code>{datetime.datetime.now().strftime('%H:%M:%S')}</code>"""
        keyboard = keyboards.edit_plugin(cortex, uuid, offset)

        bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=keyboard)
        bot.answer_callback_query(c.id)

    def open_plugin_commands(c: CallbackQuery):
        split = c.data.split(":")
        uuid, offset = split[1], int(split[2])

        if not check_plugin_exists(uuid, c.message):
            bot.answer_callback_query(c.id)
            return

        pl_obj = cortex.plugins[uuid]
        commands_text_list = []
        for i in pl_obj.commands:
            translate = _(f"{pl_obj.commands[i]}")
            commands_text_list.append(f"/{i} - {translate}"
                                      f"{'' if translate.endswith('.') else '.'}")

        commands_text = "\n\n".join(commands_text_list)
        text = f"{_('pl_commands_list', pl_obj.name)}\n\n{commands_text}"

        keyboard = K().add(B(_("gl_back"), callback_data=f"{CBT.EDIT_PLUGIN}:{uuid}:{offset}"))

        bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=keyboard)

    def toggle_plugin(c: CallbackQuery):
        split = c.data.split(":")
        uuid, offset = split[1], int(split[2])

        if not check_plugin_exists(uuid, c.message):
            bot.answer_callback_query(c.id)
            return

        cortex.toggle_plugin(uuid)
        c.data = f"{CBT.EDIT_PLUGIN}:{uuid}:{offset}"
        logger.info(_("log_pl_activated" if cortex.plugins[uuid].enabled else "log_pl_deactivated",
                      c.from_user.username, c.from_user.id, cortex.plugins[uuid].name))
        open_edit_plugin_cp(c)

    def ask_delete_plugin(c: CallbackQuery):
        split = c.data.split(":")
        uuid, offset = split[1], int(split[2])

        if not check_plugin_exists(uuid, c.message):
            bot.answer_callback_query(c.id)
            return

        bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                      reply_markup=keyboards.edit_plugin(cortex, uuid, offset, True))
        bot.answer_callback_query(c.id)

    def cancel_delete_plugin(c: CallbackQuery):
        split = c.data.split(":")
        uuid, offset = split[1], int(split[2])

        if not check_plugin_exists(uuid, c.message):
            bot.answer_callback_query(c.id)
            return

        bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                      reply_markup=keyboards.edit_plugin(cortex, uuid, offset))
        bot.answer_callback_query(c.id)

    def delete_plugin(c: CallbackQuery):
        split = c.data.split(":")
        uuid, offset = split[1], int(split[2])

        if not check_plugin_exists(uuid, c.message):
            bot.answer_callback_query(c.id)
            return

        if not os.path.exists(cortex.plugins[uuid].path):
            bot.answer_callback_query(c.id, _("pl_file_not_found_err", utils.escape(cortex.plugins[uuid].path)),
                                      show_alert=True)
            return

        if cortex.plugins[uuid].delete_handler:
            try:
                cortex.plugins[uuid].delete_handler(cortex, c)
            except:
                logger.error(_("log_pl_delete_handler_err", cortex.plugins[uuid].name))
                logger.debug("TRACEBACK", exc_info=True)

        os.remove(cortex.plugins[uuid].path)
        logger.info(_("log_pl_deleted", c.from_user.username, c.from_user.id, cortex.plugins[uuid].name))
        cortex.plugins.pop(uuid)

        c.data = f"{CBT.PLUGINS_LIST}:{offset}"
        open_plugins_list(c)

    def act_upload_plugin(obj: CallbackQuery | Message):
        if isinstance(obj, CallbackQuery):
            offset = int(obj.data.split(":")[1])
            result = bot.send_message(obj.message.chat.id, _("pl_new"), reply_markup=CLEAR_STATE_BTN())
            tg.set_state(obj.message.chat.id, result.id, obj.from_user.id, CBT.UPLOAD_PLUGIN, {"offset": offset})
            bot.answer_callback_query(obj.id)
        else:
            result = bot.send_message(obj.chat.id, _("pl_new"), reply_markup=CLEAR_STATE_BTN())
            tg.set_state(obj.chat.id, result.id, obj.from_user.id, CBT.UPLOAD_PLUGIN, {"offset": 0})

    def save_uploaded_plugin(tg_inst: TGBot, msg: Message):
        """
        Функция для скачивания и сохранения плагина.
        """
        tg_inst.clear_state(msg.chat.id, msg.from_user.id, True)

        # Проверка расширения файла
        if not msg.document or not msg.document.file_name.endswith(".py"):
            bot.send_message(msg.chat.id, "❌ Ошибка: Файл должен иметь расширение .py")
            return

        progress_msg = bot.send_message(msg.chat.id, "📥 Скачиваю плагин...")

        try:
            # Скачивание файла
            file_info = bot.get_file(msg.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)

            plugin_name = msg.document.file_name
            # Убедимся, что папка существует
            if not os.path.exists("plugins"):
                os.makedirs("plugins")
            
            save_path = os.path.join("plugins", plugin_name)

            # Сохранение
            with open(save_path, 'wb') as new_file:
                new_file.write(downloaded_file)

            bot.edit_message_text(f"✅ Плагин <b>{utils.escape(plugin_name)}</b> успешно загружен!\n"
                                  f"Перезагрузите бота, чтобы он появился в списке.",
                                  progress_msg.chat.id, progress_msg.id)

            logger.info(f"Admin uploaded new plugin: {plugin_name}")

        except Exception as e:
            logger.error(f"Error saving plugin: {e}", exc_info=True)
            bot.edit_message_text(f"❌ Произошла ошибка при сохранении: {e}", progress_msg.chat.id, progress_msg.id)

    tg.cbq_handler(open_plugins_list, lambda c: c.data.startswith(f"{CBT.PLUGINS_LIST}:"))
    tg.cbq_handler(open_edit_plugin_cp, lambda c: c.data.startswith(f"{CBT.EDIT_PLUGIN}:"))
    tg.cbq_handler(open_plugin_commands, lambda c: c.data.startswith(f"{CBT.PLUGIN_COMMANDS}:"))
    tg.cbq_handler(toggle_plugin, lambda c: c.data.startswith(f"{CBT.TOGGLE_PLUGIN}:"))

    tg.cbq_handler(ask_delete_plugin, lambda c: c.data.startswith(f"{CBT.DELETE_PLUGIN}:"))
    tg.cbq_handler(cancel_delete_plugin, lambda c: c.data.startswith(f"{CBT.CANCEL_DELETE_PLUGIN}:"))
    tg.cbq_handler(delete_plugin, lambda c: c.data.startswith(f"{CBT.CONFIRM_DELETE_PLUGIN}:"))

    tg.cbq_handler(act_upload_plugin, lambda c: c.data.startswith(f"{CBT.UPLOAD_PLUGIN}:"))
    tg.msg_handler(act_upload_plugin, commands=["upload_plugin"])

    # Регистрация обработчика файла
    tg.file_handler(CBT.UPLOAD_PLUGIN, save_uploaded_plugin)


BIND_TO_PRE_INIT = [init_plugins_cp]
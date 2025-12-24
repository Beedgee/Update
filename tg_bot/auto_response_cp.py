# tg_bot/auto_response_cp.py (ОПТИМИЗИРОВАННАЯ ВЕРСИЯ)

# -*- coding: utf-8 -*-

"""
FunPayBot by @beedge
--------------------------
Модуль для управления командами автоответчика через Telegram.
Включает добавление, редактирование и удаление команд и их ответов.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from cortex import Cortex

from tg_bot import utils, keyboards, CBT, MENU_CFG
from tg_bot.static_keyboards import CLEAR_STATE_BTN
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery
import logging
from locales.localizer import Localizer
import os
import re

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def init_auto_response_cp(cortex_instance: Cortex, *args):
    """Инициализирует все обработчики для раздела "Автоответчик"."""
    tg = cortex_instance.telegram
    bot = tg.bot

    def check_command_exists(cmd_index: int, msg_obj: Message | CallbackQuery) -> bool:
        """Проверяет, существует ли команда по индексу, и отправляет ошибку, если нет."""
        if cmd_index >= len(cortex_instance.RAW_AR_CFG.sections()):
            kb_error = K().add(B(_("gl_refresh"), callback_data=f"{CBT.CMD_LIST}:0"))
            error_text = _("ar_cmd_not_found_err", cmd_index)
            
            chat_id = msg_obj.chat.id if isinstance(msg_obj, Message) else msg_obj.message.chat.id
            msg_id = msg_obj.id if isinstance(msg_obj, Message) else msg_obj.message.id
            if isinstance(msg_obj, Message):
                bot.reply_to(msg_obj, error_text, reply_markup=kb_error)
            else:
                bot.edit_message_text(error_text, chat_id, msg_id, reply_markup=kb_error)
            return False
        return True

    def open_commands_list(c: CallbackQuery):
        """Открывает список команд автоответчика."""
        offset = int(c.data.split(":")[1])
        bot.edit_message_text(_("desc_ar_list"), c.message.chat.id, c.message.id,
                              reply_markup=keyboards.commands_list(cortex_instance, offset))
        bot.answer_callback_query(c.id)

    def act_add_command(c: CallbackQuery):
        """Активирует состояние ожидания новой команды от пользователя."""
        result = bot.send_message(c.message.chat.id, _("ar_enter_new_cmd"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.ADD_CMD)
        bot.answer_callback_query(c.id)

    def add_command(m: Message):
        """Обрабатывает введенную пользователем новую команду."""
        tg.clear_state(m.chat.id, m.from_user.id, True)
        raw_cmd_input = m.text.strip().lower()
        cmd_list = [cmd.strip() for cmd in raw_cmd_input.split("|") if cmd.strip()]

        kb_error = K().row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ar"),
                                 B(_("ar_add_another"), callback_data=CBT.ADD_CMD))

        if not cmd_list:
            bot.reply_to(m, _("ar_no_valid_commands_entered"), reply_markup=kb_error)
            return

        # --- НАЧАЛО ИЗМЕНЕНИЙ: УДАЛЕНА ПРОВЕРКА НА СПЕЦИАЛЬНЫЕ СИМВОЛЫ ---
        # Проверка на валидность символов удалена, чтобы разрешить любые символы в командах.
        # --- КОНЕЦ ИЗМЕНЕНИЙ ---

        if len(cmd_list) != len(set(cmd_list)):
            seen, first_duplicate = set(), ""
            for cmd in cmd_list:
                if cmd in seen: first_duplicate = cmd; break
                seen.add(cmd)
            bot.reply_to(m, _("ar_subcmd_duplicate_err", utils.escape(first_duplicate)), reply_markup=kb_error)
            return
        
        for new_cmd in cmd_list:
            if new_cmd in cortex_instance.AR_CFG.sections():
                bot.reply_to(m, _("ar_cmd_already_exists_err", utils.escape(new_cmd)), reply_markup=kb_error)
                return
        
        def threaded_add():
            raw_cmd_for_cfg = "|".join(cmd_list)
            default_resp_text = _("ar_default_response_text")
            
            cortex_instance.RAW_AR_CFG.add_section(raw_cmd_for_cfg)
            cortex_instance.RAW_AR_CFG.set(raw_cmd_for_cfg, "response", default_resp_text)
            cortex_instance.RAW_AR_CFG.set(raw_cmd_for_cfg, "telegramNotification", "0")

            for cmd in cmd_list:
                cortex_instance.AR_CFG.add_section(cmd)
                cortex_instance.AR_CFG.set(cmd, "response", default_resp_text)
                cortex_instance.AR_CFG.set(cmd, "telegramNotification", "0")

            cortex_instance.save_config(cortex_instance.RAW_AR_CFG, os.path.join(cortex_instance.base_path, "configs/auto_response.cfg"))

            all_raw_cmds = cortex_instance.RAW_AR_CFG.sections()
            try: new_cmd_idx = all_raw_cmds.index(raw_cmd_for_cfg)
            except ValueError: new_cmd_idx = len(all_raw_cmds) - 1

            offset = utils.get_offset(new_cmd_idx, MENU_CFG.AR_BTNS_AMOUNT)
            kb_success = K().row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ar"),
                                       B(_("ar_add_more"), callback_data=CBT.ADD_CMD),
                                       B(_("gl_configure"), callback_data=f"{CBT.EDIT_CMD}:{new_cmd_idx}:{offset}"))
            logger.info(_("log_ar_added", m.from_user.username, m.from_user.id, raw_cmd_for_cfg))
            bot.reply_to(m, _("ar_cmd_added", utils.escape(raw_cmd_for_cfg)), reply_markup=kb_success)

        cortex_instance.executor.submit(threaded_add)


    def open_edit_command_cp(c: CallbackQuery):
        """Открывает меню редактирования для конкретной команды."""
        cmd_idx, offset = map(int, c.data.split(":")[1:])
        if not check_command_exists(cmd_idx, c): 
            bot.answer_callback_query(c.id)
            return

        raw_cmd = cortex_instance.RAW_AR_CFG.sections()[cmd_idx]
        cmd_obj = cortex_instance.RAW_AR_CFG[raw_cmd]
        
        notif_text = cmd_obj.get("notificationText", _("ar_default_notification_text"))
        
        text = f"""
🛠️ <b>Редактирование команды:</b>
<code>{utils.escape(raw_cmd)}</code>

💬 <b>{_('ar_response_text')}:</b>
<i>{utils.escape(cmd_obj.get("response", ""))}</i>

🔔 <b>{_('ar_notification_text')}:</b>
<i>{utils.escape(notif_text)}</i>
        """
        bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=keyboards.edit_command(cortex_instance, cmd_idx, offset))
        bot.answer_callback_query(c.id)

    def act_edit_command_response(c: CallbackQuery):
        """Активирует режим ввода текста ответа на команду."""
        cmd_idx, offset = map(int, c.data.split(":")[1:])
        variables = ["v_username", "v_message_text", "v_chat_name", "v_date", "v_time", "v_photo", "v_sleep"]
        prompt = f"{_('v_edit_response_text')}\n\n{_('v_list')}:\n" + "\n".join(_(v) for v in variables)
        result = bot.send_message(c.message.chat.id, prompt, reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.EDIT_CMD_RESPONSE_TEXT,
                     {"command_index": cmd_idx, "offset": offset})
        bot.answer_callback_query(c.id)

    def edit_command_response(m: Message):
        """Обрабатывает новый текст ответа на команду."""
        state_data = tg.get_state(m.chat.id, m.from_user.id)["data"]
        cmd_idx, offset = state_data["command_index"], state_data["offset"]
        tg.clear_state(m.chat.id, m.from_user.id, True)
        if not check_command_exists(cmd_idx, m): return

        new_resp_text = m.text.strip()
        
        def threaded_edit():
            raw_cmd = cortex_instance.RAW_AR_CFG.sections()[cmd_idx]
            cortex_instance.RAW_AR_CFG.set(raw_cmd, "response", new_resp_text)
            for cmd in raw_cmd.split("|"):
                if cmd.strip() in cortex_instance.AR_CFG:
                    cortex_instance.AR_CFG.set(cmd.strip(), "response", new_resp_text)

            cortex_instance.save_config(cortex_instance.RAW_AR_CFG, os.path.join(cortex_instance.base_path, "configs/auto_response.cfg"))

            logger.info(_("log_ar_response_text_changed", m.from_user.username, m.from_user.id, raw_cmd, new_resp_text))
            kb_reply = K().row(B(_("gl_back"), callback_data=f"{CBT.EDIT_CMD}:{cmd_idx}:{offset}"),
                                     B(_("gl_edit"), callback_data=f"{CBT.EDIT_CMD_RESPONSE_TEXT}:{cmd_idx}:{offset}"))
            bot.reply_to(m, _("ar_response_text_changed", utils.escape(raw_cmd), utils.escape(new_resp_text)),
                         reply_markup=kb_reply)
        
        cortex_instance.executor.submit(threaded_edit)

    def act_edit_command_notification(c: CallbackQuery):
        """Активирует режим ввода текста уведомления о команде."""
        cmd_idx, offset = map(int, c.data.split(":")[1:])
        variables = ["v_username", "v_message_text", "v_chat_name", "v_date", "v_time"]
        prompt = f"{_('v_edit_notification_text')}\n\n{_('v_list')}:\n" + "\n".join(_(v) for v in variables)
        result = bot.send_message(c.message.chat.id, prompt, reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.EDIT_CMD_NOTIFICATION_TEXT,
                     {"command_index": cmd_idx, "offset": offset})
        bot.answer_callback_query(c.id)

    def edit_command_notification(m: Message):
        """Обрабатывает новый текст уведомления о команде."""
        state_data = tg.get_state(m.chat.id, m.from_user.id)["data"]
        cmd_idx, offset = state_data["command_index"], state_data["offset"]
        tg.clear_state(m.chat.id, m.from_user.id, True)
        if not check_command_exists(cmd_idx, m): return

        new_notif_text = m.text.strip()
        
        def threaded_edit():
            raw_cmd = cortex_instance.RAW_AR_CFG.sections()[cmd_idx]
            cortex_instance.RAW_AR_CFG.set(raw_cmd, "notificationText", new_notif_text)
            for cmd in raw_cmd.split("|"):
                if cmd.strip() in cortex_instance.AR_CFG:
                    cortex_instance.AR_CFG.set(cmd.strip(), "notificationText", new_notif_text)
                    
            cortex_instance.save_config(cortex_instance.RAW_AR_CFG, os.path.join(cortex_instance.base_path, "configs/auto_response.cfg"))

            logger.info(_("log_ar_notification_text_changed", m.from_user.username, m.from_user.id, raw_cmd, new_notif_text))
            kb_reply = K().row(B(_("gl_back"), callback_data=f"{CBT.EDIT_CMD}:{cmd_idx}:{offset}"),
                                     B(_("gl_edit"), callback_data=f"{CBT.EDIT_CMD_NOTIFICATION_TEXT}:{cmd_idx}:{offset}"))
            bot.reply_to(m, _("ar_notification_text_changed", utils.escape(raw_cmd), utils.escape(new_notif_text)),
                         reply_markup=kb_reply)

        cortex_instance.executor.submit(threaded_edit)

    def switch_notification(c: CallbackQuery):
        """Включает/выключает уведомление для команды."""
        bot.answer_callback_query(c.id)
        cmd_idx, offset = map(int, c.data.split(":")[1:])
        if not check_command_exists(cmd_idx, c): return

        def threaded_switch():
            raw_cmd = cortex_instance.RAW_AR_CFG.sections()[cmd_idx]
            current_status = cortex_instance.RAW_AR_CFG[raw_cmd].get("telegramNotification", "0")
            new_status = "0" if current_status == "1" else "1"
            
            cortex_instance.RAW_AR_CFG.set(raw_cmd, "telegramNotification", new_status)
            for cmd in raw_cmd.split("|"):
                if cmd.strip() in cortex_instance.AR_CFG:
                    cortex_instance.AR_CFG.set(cmd.strip(), "telegramNotification", new_status)

            cortex_instance.save_config(cortex_instance.RAW_AR_CFG, os.path.join(cortex_instance.base_path, "configs/auto_response.cfg"))
            logger.info(_("log_param_changed", c.from_user.username, c.from_user.id, "telegramNotification", raw_cmd, new_status))
            
            # Обновляем меню после сохранения
            c.data = f"{CBT.EDIT_CMD}:{cmd_idx}:{offset}"
            open_edit_command_cp(c)

        cortex_instance.executor.submit(threaded_switch)


    def del_command(c: CallbackQuery):
        """Удаляет команду/набор команд."""
        bot.answer_callback_query(c.id)
        cmd_idx, offset = map(int, c.data.split(":")[1:])
        if not check_command_exists(cmd_idx, c): return

        cmd_to_delete = cortex_instance.RAW_AR_CFG.sections()[cmd_idx]
        
        def threaded_delete():
            cortex_instance.RAW_AR_CFG.remove_section(cmd_to_delete)
            for cmd in cmd_to_delete.split("|"):
                if cmd.strip() in cortex_instance.AR_CFG:
                    cortex_instance.AR_CFG.remove_section(cmd.strip())

            cortex_instance.save_config(cortex_instance.RAW_AR_CFG, os.path.join(cortex_instance.base_path, "configs/auto_response.cfg"))
            logger.info(_("log_ar_cmd_deleted", c.from_user.username, c.from_user.id, cmd_to_delete))
            
            new_offset = offset if len(cortex_instance.RAW_AR_CFG.sections()) > offset else max(0, offset - MENU_CFG.AR_BTNS_AMOUNT)
            bot.edit_message_text(_("desc_ar_list"), c.message.chat.id, c.message.id,
                                  reply_markup=keyboards.commands_list(cortex_instance, new_offset))
            bot.answer_callback_query(c.id, _("ar_command_deleted_successfully", command_name=utils.escape(cmd_to_delete)), show_alert=True)
        
        cortex_instance.executor.submit(threaded_delete)
    
    # Регистрация обработчиков
    tg.cbq_handler(open_commands_list, lambda c: c.data.startswith(f"{CBT.CMD_LIST}:"))
    tg.cbq_handler(act_add_command, lambda c: c.data == CBT.ADD_CMD)
    tg.msg_handler(add_command, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.ADD_CMD))
    tg.cbq_handler(open_edit_command_cp, lambda c: c.data.startswith(f"{CBT.EDIT_CMD}:"))
    tg.cbq_handler(act_edit_command_response, lambda c: c.data.startswith(f"{CBT.EDIT_CMD_RESPONSE_TEXT}:"))
    tg.msg_handler(edit_command_response, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.EDIT_CMD_RESPONSE_TEXT))
    tg.cbq_handler(act_edit_command_notification, lambda c: c.data.startswith(f"{CBT.EDIT_CMD_NOTIFICATION_TEXT}:"))
    tg.msg_handler(edit_command_notification, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.EDIT_CMD_NOTIFICATION_TEXT))
    tg.cbq_handler(switch_notification, lambda c: c.data.startswith(f"{CBT.SWITCH_CMD_NOTIFICATION}:"))
    tg.cbq_handler(del_command, lambda c: c.data.startswith(f"{CBT.DEL_CMD}:"))

BIND_TO_PRE_INIT = [init_auto_response_cp]
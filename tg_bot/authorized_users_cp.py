# FunPayCortex/tg_bot/authorized_users_cp.py (ПОЛНАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ)

# -*- coding: utf-8 -*-

"""
FunPayBot by @beedge
--------------------------
Модуль для управления пользователями Telegram-бота (администраторы, менеджеры).
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import telebot.apihelper
import logging
import os

if TYPE_CHECKING:
    from cortex import Cortex

from tg_bot import keyboards as kb, CBT, utils
from tg_bot.static_keyboards import CLEAR_STATE_BTN
from telebot.types import CallbackQuery, Message, InlineKeyboardMarkup as K, InlineKeyboardButton as B
from locales.localizer import Localizer

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def init_authorized_users_cp(cortex_instance: Cortex, *args):
    """Инициализирует все обработчики для раздела управления пользователями."""
    tg = cortex_instance.telegram
    bot = tg.bot

    def open_authorized_users_list(c: CallbackQuery):
        """
        Открывает главное меню управления пользователями, отображая список
        администраторов и менеджеров.
        """
        offset = int(c.data.split(":")[1])
        bot.edit_message_text(
            text=_("desc_au"),
            chat_id=c.message.chat.id,
            message_id=c.message.id,
            reply_markup=kb.authorized_users(cortex_instance, offset, c.from_user.id)
        )
        bot.answer_callback_query(c.id)

    def open_authorized_user_settings(c: CallbackQuery):
        """
        Открывает карточку с настройками для конкретного пользователя.
        """
        __, user_id_str, offset_str = c.data.split(":")
        user_id = int(user_id_str)
        offset = int(offset_str)

        user_info = cortex_instance.telegram.authorized_users.get(user_id)
        if not user_info:
            bot.answer_callback_query(c.id, _("user_not_found"), show_alert=True)
            return

        user_display_name = user_info.get("username", str(user_id))
        user_role_key = user_info.get("role", "manager") # Безопасное получение роли
        role_text = _(f"role_{user_role_key}")

        text = _("au_user_settings", f"<a href='tg:user?id={user_id}'>{utils.escape(user_display_name)}</a>\n<b>ID:</b> <code>{user_id}</code>\n<b>{_('user_role')}:</b> {role_text}")
        
        try:
            bot.edit_message_text(text, c.message.chat.id, c.message.id,
                                  reply_markup=kb.authorized_user_settings(cortex_instance, user_id, offset, True, c.from_user.id))
        except telebot.apihelper.ApiTelegramException:
            logger.warning(_("crd_tg_au_err", user_id), exc_info=True)
            bot.edit_message_text(text, c.message.chat.id, c.message.id,
                                  reply_markup=kb.authorized_user_settings(cortex_instance, user_id, offset, False, c.from_user.id))
        bot.answer_callback_query(c.id)


    def revoke_user_access(c: CallbackQuery):
        """
        Полностью удаляет пользователя из списка авторизованных.
        """
        __, user_id_str, offset_str = c.data.split(":")
        user_id_to_revoke = int(user_id_str)
        offset = int(offset_str)

        if user_id_to_revoke in tg.authorized_users:
            revoked_user_info = tg.authorized_users.pop(user_id_to_revoke)
            utils.save_authorized_users(cortex_instance, tg.authorized_users)
            
            logger.warning(_("log_user_revoked", c.from_user.username, c.from_user.id,
                             revoked_user_info.get("username", user_id_to_revoke), user_id_to_revoke))
            bot.answer_callback_query(c.id, _("user_access_revoked", revoked_user_info.get("username", user_id_to_revoke)), show_alert=True)

        c.data = f"{CBT.AUTHORIZED_USERS}:{offset}"
        open_authorized_users_list(c)

    def change_user_role(c: CallbackQuery):
        """
        Изменяет роль пользователя (администратор <-> менеджер).
        """
        __, user_id_str, offset_str, new_role = c.data.split(":")
        user_id_to_change = int(user_id_str)
        offset = int(offset_str)

        if user_id_to_change in tg.authorized_users:
            if new_role == "manager":
                admins = [uid for uid, uinfo in tg.authorized_users.items() if uinfo.get("role") == "admin"]
                if len(admins) <= 1 and tg.authorized_users[user_id_to_change].get("role") == "admin":
                    bot.answer_callback_query(c.id, _("demote_last_admin_error"), show_alert=True)
                    return

            tg.authorized_users[user_id_to_change]["role"] = new_role
            utils.save_authorized_users(cortex_instance, tg.authorized_users)

            logger.warning(_("log_user_role_changed", c.from_user.username, c.from_user.id,
                             tg.authorized_users[user_id_to_change].get("username", user_id_to_change),
                             user_id_to_change, new_role))
            bot.answer_callback_query(c.id, _("user_role_changed_success",
                                              tg.authorized_users[user_id_to_change].get("username", user_id_to_change),
                                              _(f"role_{new_role}")), show_alert=True)

        c.data = f"{CBT.AUTHORIZED_USER_SETTINGS}:{user_id_to_change}:{offset}"
        open_authorized_user_settings(c)

    def open_manager_settings(c: CallbackQuery):
        """
        Открывает меню настройки ключа регистрации для менеджеров.
        """
        if cortex_instance.access_level < 3:
            bot.answer_callback_query(c.id, "🔑 Эта функция доступна на тарифе 'Команда'.", show_alert=True)
            return

        key = cortex_instance.MAIN_CFG["Manager"].get("registration_key", "")
        key_text = f"<code>{utils.escape(key)}</code>" if key else _("manager_key_not_set")
        text = _("manager_settings_desc", key_text)
        
        kb = K().add(
            B(_("set_manager_key_btn"), callback_data=CBT.SET_MANAGER_KEY),
            B(_("gl_back"), callback_data=f"{CBT.AUTHORIZED_USERS}:0")
        )
        bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=kb)
        bot.answer_callback_query(c.id)

    def act_set_manager_key(c: CallbackQuery):
        """
        Активирует режим ожидания ввода нового ключа регистрации.
        """
        result = bot.send_message(c.message.chat.id, _("enter_manager_key_prompt"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.SET_MANAGER_KEY)
        bot.answer_callback_query(c.id)

    def set_manager_key(m: Message):
        """
        Сохраняет новый ключ регистрации для менеджеров.
        """
        tg.clear_state(m.chat.id, m.from_user.id, True)
        new_key = "" if m.text.strip() == "-" else m.text.strip()
        
        cortex_instance.MAIN_CFG.set("Manager", "registration_key", new_key)
        cortex_instance.save_config(cortex_instance.MAIN_CFG, os.path.join(cortex_instance.base_path, "configs/_main.cfg"))
        
        logger.warning(_("log_manager_key_changed", m.from_user.username, m.from_user.id, new_key))

        kb = K().add(B(_("gl_back"), callback_data=CBT.MANAGER_SETTINGS))
        bot.reply_to(m, _("manager_key_changed_success"), reply_markup=kb)

    def open_manager_permissions(c: CallbackQuery):
        """
        Открывает меню настройки прав для роли "менеджер".
        """
        user_role = utils.get_user_role(tg.authorized_users, c.from_user.id)
        if user_role != 'admin':
            bot.answer_callback_query(c.id, _("admin_only_command"), show_alert=True)
            return

        bot.edit_message_text(
            text=_("mp_desc"),
            chat_id=c.message.chat.id,
            message_id=c.message.id,
            reply_markup=kb.manager_permissions_settings(cortex_instance)
        )
        bot.answer_callback_query(c.id)
        
    def request_logout(c: CallbackQuery):
        """
        Запрашивает подтверждение на выход из панели управления.
        """
        # Разбираем callback_data, чтобы получить контекст для кнопки "Назад"
        # Пример: c.data будет "80:1" или "80:67:0"
        parts = c.data.split(":")
        # Собираем все части после первой (это и есть наш callback для кнопки "Нет")
        back_callback = ":".join(parts[1:])

        kb = K(row_width=2).add(
            # Теперь callback_data для кнопки "Нет" динамический
            B(_("gl_no"), callback_data=back_callback),
            B(_("gl_yes"), callback_data=CBT.LOG_OUT_CONFIRM)
        )
        bot.edit_message_text(_("logout_confirm_text"), c.message.chat.id, c.message.id, reply_markup=kb)
        bot.answer_callback_query(c.id)

    def confirm_logout(c: CallbackQuery):
        """
        Выполняет выход пользователя, удаляя его из списка авторизованных.
        """
        user_id_to_logout = c.from_user.id
        if user_id_to_logout in tg.authorized_users:
            admins = [uid for uid, uinfo in tg.authorized_users.items() if uinfo.get("role") == "admin"]
            if len(admins) <= 1 and tg.authorized_users[user_id_to_logout].get("role") == "admin":
                bot.answer_callback_query(c.id, _("demote_last_admin_error"), show_alert=True)
                c.data = f"{CBT.AUTHORIZED_USERS}:0"
                open_authorized_users_list(c)
                return

            del tg.authorized_users[user_id_to_logout]
            utils.save_authorized_users(cortex_instance, tg.authorized_users)
            
            bot.edit_message_text(_("logout_success"), c.message.chat.id, c.message.id)
            bot.answer_callback_query(c.id)
        else:
            bot.answer_callback_query(c.id, _("gl_error"), show_alert=True)


    # Регистрация обработчиков
    tg.cbq_handler(open_authorized_users_list, func=lambda c: c.data.startswith(f"{CBT.AUTHORIZED_USERS}:"))
    tg.cbq_handler(open_authorized_user_settings, func=lambda c: c.data.startswith(f"{CBT.AUTHORIZED_USER_SETTINGS}:"))
    tg.cbq_handler(revoke_user_access, func=lambda c: c.data.startswith(f"{CBT.REVOKE_USER_ACCESS}:"))
    tg.cbq_handler(change_user_role, func=lambda c: c.data.startswith(f"{CBT.CHANGE_USER_ROLE}:"))
    tg.cbq_handler(open_manager_settings, func=lambda c: c.data == CBT.MANAGER_SETTINGS)
    tg.cbq_handler(act_set_manager_key, func=lambda c: c.data == CBT.SET_MANAGER_KEY)
    tg.msg_handler(set_manager_key, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.SET_MANAGER_KEY))
    tg.cbq_handler(open_manager_permissions, func=lambda c: c.data == CBT.MANAGER_PERMISSIONS)
    tg.cbq_handler(request_logout, func=lambda c: c.data.startswith(f"{CBT.LOG_OUT_REQUEST}:"))
    tg.cbq_handler(confirm_logout, func=lambda c: c.data == CBT.LOG_OUT_CONFIRM)

# Переменная для привязки к запуску бота
BIND_TO_PRE_INIT = [init_authorized_users_cp]
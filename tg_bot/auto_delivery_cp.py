# tg_bot/auto_delivery_cp.py (ПОЛНАЯ ОПТИМИЗИРОВАННАЯ ВЕРСИЯ)

# -*- coding: utf-8 -*-

"""
FunPayBot by @beedge
--------------------------
Модуль-плагин для управления настройками автовыдачи через Telegram.
Обрабатывает всю логику, связанную с привязкой лотов,
управлением файлами товаров и редактированием текстов выдачи.
"""

from __future__ import annotations
import datetime
from typing import TYPE_CHECKING
import random
import string

if TYPE_CHECKING:
    from cortex import Cortex

from tg_bot import utils, keyboards as kb, CBT, MENU_CFG
from tg_bot.static_keyboards import CLEAR_STATE_BTN
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery
from Utils import cortex_tools
from locales.localizer import Localizer
import logging
import os
import re

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def init_auto_delivery_cp(cortex_instance: Cortex, *args):
    tg = cortex_instance.telegram
    bot = tg.bot
    filename_re = re.compile(r"^[А-Яа-яЁёA-Za-z0-9_\- .]+$")

    def check_ad_lot_exists(index: int, msg: Message | CallbackQuery, reply: bool = True) -> bool:
        """Проверяет, существует ли лот с таким индексом в конфиге автовыдачи."""
        if index >= len(cortex_instance.AD_CFG.sections()):
            kb = K().add(B(_("gl_refresh"), callback_data=f"{CBT.AD_LOTS_LIST}:0"))
            text = _("ad_lot_not_found_err", index)
            utils.send_or_edit_message(bot, msg, text, reply, kb)
            return False
        return True

    def check_products_file_exists(index: int, files: list[str], msg: Message | CallbackQuery, reply: bool = True) -> bool:
        """Проверяет, существует ли файл с товарами по индексу."""
        if index >= len(files):
            kb = K().add(B(_("gl_refresh"), callback_data=f"{CBT.PRODUCTS_FILES_LIST}:0"))
            text = _("gf_not_found_err", index)
            utils.send_or_edit_message(bot, msg, text, reply, kb)
            return False
        return True

    # ================================================================================= #
    # --------------------------- ОСНОВНЫЕ МЕНЮ АВТОВЫДАЧИ -------------------------- #
    # ================================================================================= #

    def open_ad_lots_list(c: CallbackQuery):
        """Открывает список лотов, уже привязанных к автовыдаче."""
        offset = int(c.data.split(":")[1])
        bot.edit_message_text(_("desc_ad_list"), c.message.chat.id, c.message.id,
                              reply_markup=kb.lots_list(cortex_instance, offset))
        bot.answer_callback_query(c.id)

    # --- НАЧАЛО ИЗМЕНЕНИЙ: Исправление ошибки AttributeError ---
    def open_fp_lots_list(c: CallbackQuery):
        """
        Открывает список лотов из профиля FunPay для новой привязки.
        Если кэш лотов пуст, сначала запускает его обновление.
        """
        if not cortex_instance.tg_profile:
            bot.answer_callback_query(c.id)
            update_funpay_lots_list(c)
            return

        offset = int(c.data.split(":")[1])
        last_update = cortex_instance.last_tg_profile_update.strftime("%H:%M:%S, %d.%m.%Y") if cortex_instance.last_tg_profile_update else _("never_updated")
        bot.edit_message_text(_("desc_ad_fp_lot_list", last_update),
                              c.message.chat.id, c.message.id, reply_markup=kb.funpay_lots_list(cortex_instance, offset))
        bot.answer_callback_query(c.id)
    # --- КОНЕЦ ИЗМЕНЕНИЙ ---

    def open_gf_list(c: CallbackQuery):
        """Открывает список файлов с товарами."""
        offset = int(c.data.split(":")[1])
        bot.edit_message_text(_("desc_gf"), c.message.chat.id, c.message.id,
                              reply_markup=kb.products_files_list(offset))
        bot.answer_callback_query(c.id)

    # ================================================================================= #
    # ----------------------------- ЛОГИКА ПРИВЯЗКИ ЛОТОВ ---------------------------- #
    # ================================================================================= #

    def act_add_lot_manually(c: CallbackQuery):
        """Активирует режим ручного ввода названия лота для привязки."""
        offset = int(c.data.split(":")[1])
        result = bot.send_message(c.message.chat.id, _("copy_lot_name"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.ADD_AD_TO_LOT_MANUALLY, data={"offset": offset})
        bot.answer_callback_query(c.id)

    def add_lot_manually(m: Message):
        """Обрабатывает ручной ввод названия лота и привязывает его."""
        fp_lots_offset = tg.get_state(m.chat.id, m.from_user.id)["data"]["offset"]
        tg.clear_state(m.chat.id, m.from_user.id, True)
        lot_title = m.text.strip()

        kb_error = K().row(B(_("gl_back"), callback_data=f"{CBT.FP_LOTS_LIST}:{fp_lots_offset}"),
                           B(_("ad_add_another_ad"), callback_data=f"{CBT.ADD_AD_TO_LOT_MANUALLY}:{fp_lots_offset}"))
        if lot_title in cortex_instance.AD_CFG.sections():
            bot.reply_to(m, _("ad_lot_already_exists", utils.escape(lot_title)), reply_markup=kb_error)
            return

        def _threaded_save():
            cortex_instance.AD_CFG.add_section(lot_title)
            cortex_instance.AD_CFG.set(lot_title, "response", _("ad_default_response_text_new_lot"))
            cortex_instance.save_config(cortex_instance.AD_CFG, "configs/auto_delivery.cfg")
        
        cortex_instance.executor.submit(_threaded_save)
        
        logger.info(_("log_ad_linked", m.from_user.username, m.from_user.id, lot_title))

        lot_index = len(cortex_instance.AD_CFG.sections()) - 1
        ad_lot_offset = utils.get_offset(lot_index, MENU_CFG.AD_BTNS_AMOUNT)
        kb_success = K().row(B(_("gl_back"), callback_data=f"{CBT.FP_LOTS_LIST}:{fp_lots_offset}"),
                             B(_("ad_add_more_ad"), callback_data=f"{CBT.ADD_AD_TO_LOT_MANUALLY}:{fp_lots_offset}"),
                             B(_("gl_configure"), callback_data=f"{CBT.EDIT_AD_LOT}:{lot_index}:{ad_lot_offset}"))
        bot.send_message(m.chat.id, _("ad_lot_linked", utils.escape(lot_title)), reply_markup=kb_success)

    def add_ad_to_lot(c: CallbackQuery):
        """Привязывает автовыдачу к лоту, выбранному из списка FunPay."""
        bot.answer_callback_query(c.id)
        split_data = c.data.split(":")
        fp_lot_index, fp_lots_offset = int(split_data[1]), int(split_data[2])
        
        all_fp_lots = cortex_instance.tg_profile.get_common_lots()
        if fp_lot_index >= len(all_fp_lots):
            bot.edit_message_text(_("ad_lot_not_found_err", fp_lot_index),
                                  c.message.chat.id, c.message.id,
                                  reply_markup=K().add(B(_("gl_refresh"), callback_data=f"{CBT.FP_LOTS_LIST}:0")))
            return

        lot_obj = all_fp_lots[fp_lot_index]
        lot_title = lot_obj.title

        if lot_title in cortex_instance.AD_CFG.sections():
            ad_lot_index = cortex_instance.AD_CFG.sections().index(lot_title)
            offset = utils.get_offset(ad_lot_index, MENU_CFG.AD_BTNS_AMOUNT)
            kb_info = K().row(B(_("gl_back"), callback_data=f"{CBT.FP_LOTS_LIST}:{fp_lots_offset}"),
                              B(_("gl_configure"), callback_data=f"{CBT.EDIT_AD_LOT}:{ad_lot_index}:{offset}"))
            bot.send_message(c.message.chat.id, _("ad_already_ad_err", utils.escape(lot_title)), reply_markup=kb_info)
            return

        def _threaded_save():
            cortex_instance.AD_CFG.add_section(lot_title)
            cortex_instance.AD_CFG.set(lot_title, "response", _("ad_default_response_text_new_lot"))
            cortex_instance.save_config(cortex_instance.AD_CFG, "configs/auto_delivery.cfg")
        
        cortex_instance.executor.submit(_threaded_save)

        new_ad_lot_index = len(cortex_instance.AD_CFG.sections()) - 1
        offset_new = utils.get_offset(new_ad_lot_index, MENU_CFG.AD_BTNS_AMOUNT)
        kb_success = K().row(B(_("gl_back"), callback_data=f"{CBT.FP_LOTS_LIST}:{fp_lots_offset}"),
                             B(_("gl_configure"), callback_data=f"{CBT.EDIT_AD_LOT}:{new_ad_lot_index}:{offset_new}"))
        logger.info(_("log_ad_linked", c.from_user.username, c.from_user.id, lot_title))
        bot.send_message(c.message.chat.id, _("ad_lot_linked", utils.escape(lot_title)), reply_markup=kb_success)


    def update_funpay_lots_list(c: CallbackQuery):
        """Обновляет список лотов из профиля FunPay в отдельном потоке."""
        bot.answer_callback_query(c.id)
        msg = bot.send_message(c.message.chat.id, _("ad_updating_lots_list"))
        
        def _threaded_update():
            if not cortex_instance.update_lots_and_categories():
                bot.edit_message_text(_("ad_lots_list_updating_err"), msg.chat.id, msg.id)
                return
            bot.delete_message(msg.chat.id, msg.id)
            c.data = f"{CBT.FP_LOTS_LIST}:{int(c.data.split(':')[1])}"
            open_fp_lots_list(c)

        cortex_instance.executor.submit(_threaded_update)


    # ================================================================================= #
    # --------------------------- РЕДАКТИРОВАНИЕ ЛОТА АВТОВЫДАЧИ -------------------------- #
    # ================================================================================= #

    def open_edit_lot_cp(c: CallbackQuery):
        """Открывает меню редактирования конкретного лота автовыдачи."""
        lot_index, offset = map(int, c.data.split(":")[1:])
        if not check_ad_lot_exists(lot_index, c, reply=False):
            bot.answer_callback_query(c.id)
            return
        
        lot_name = cortex_instance.AD_CFG.sections()[lot_index]
        lot_obj = cortex_instance.AD_CFG[lot_name]
        bot.edit_message_text(utils.generate_lot_info_text(cortex_instance, lot_obj), c.message.chat.id, c.message.id,
                              reply_markup=kb.edit_lot(cortex_instance, lot_index, offset))
        bot.answer_callback_query(c.id)

    def act_edit_delivery_text(c: CallbackQuery):
        """Активирует режим ввода текста автовыдачи."""
        lot_index, offset = map(int, c.data.split(":")[1:])
        variables = ["v_username", "v_product", "v_order_id", "v_order_title", "v_photo", "v_sleep"]
        text = f"{_('v_edit_delivery_text')}\n\n{_('v_list')}:\n" + "\n".join([_(v) for v in variables])
        result = bot.send_message(c.message.chat.id, text, reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.EDIT_LOT_DELIVERY_TEXT,
                     {"lot_index": lot_index, "offset": offset})
        bot.answer_callback_query(c.id)

    def edit_delivery_text(m: Message):
        """Сохраняет новый текст автовыдачи."""
        state = tg.get_state(m.chat.id, m.from_user.id)
        lot_index, offset = state["data"]["lot_index"], state["data"]["offset"]
        tg.clear_state(m.chat.id, m.from_user.id, True)
        if not check_ad_lot_exists(lot_index, m): return

        new_text = m.text.strip()
        lot_name = cortex_instance.AD_CFG.sections()[lot_index]
        lot_obj = cortex_instance.AD_CFG[lot_name]
        kb_reply = K().row(B(_("gl_back"), callback_data=f"{CBT.EDIT_AD_LOT}:{lot_index}:{offset}"),
                           B(_("gl_edit"), callback_data=f"{CBT.EDIT_LOT_DELIVERY_TEXT}:{lot_index}:{offset}"))

        if lot_obj.get("productsFileName") and "$product" not in new_text:
            bot.reply_to(m, _("ad_product_var_err", utils.escape(lot_name)), reply_markup=kb_reply)
            return

        def _threaded_save():
            cortex_instance.AD_CFG.set(lot_name, "response", new_text)
            cortex_instance.save_config(cortex_instance.AD_CFG, "configs/auto_delivery.cfg")
        
        cortex_instance.executor.submit(_threaded_save)

        logger.info(_("log_ad_text_changed", m.from_user.username, m.from_user.id, lot_name, new_text))
        bot.reply_to(m, _("ad_text_changed", utils.escape(lot_name), utils.escape(new_text)), reply_markup=kb_reply)

    def act_link_gf(c: CallbackQuery):
        """Активирует режим привязки файла товаров."""
        lot_index, offset = map(int, c.data.split(":")[1:])
        result = bot.send_message(c.message.chat.id, _("ad_link_gf"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.BIND_PRODUCTS_FILE,
                     {"lot_index": lot_index, "offset": offset})
        bot.answer_callback_query(c.id)

    def link_gf(m: Message):
        """Обрабатывает ввод имени файла и привязывает/создает его."""
        state = tg.get_state(m.chat.id, m.from_user.id)
        lot_index, offset = state["data"]["lot_index"], state["data"]["offset"]
        tg.clear_state(m.chat.id, m.from_user.id, True)
        if not check_ad_lot_exists(lot_index, m): return

        lot_name = cortex_instance.AD_CFG.sections()[lot_index]
        lot_obj = cortex_instance.AD_CFG[lot_name]
        file_name = m.text.strip()
        
        kb_reply = K().row(B(_("gl_back"), callback_data=f"{CBT.EDIT_AD_LOT}:{lot_index}:{offset}"),
                           B(_("ea_link_another_gf"), callback_data=f"{CBT.BIND_PRODUCTS_FILE}:{lot_index}:{offset}"))

        def _threaded_save():
            cortex_instance.save_config(cortex_instance.AD_CFG, "configs/auto_delivery.cfg")

        if file_name == "-":
            cortex_instance.AD_CFG.remove_option(lot_name, "productsFileName", fallback=None)
            cortex_instance.executor.submit(_threaded_save)
            
            logger.info(_("log_gf_unlinked", m.from_user.username, m.from_user.id, lot_name))
            bot.reply_to(m, _("ad_gf_unlinked", utils.escape(lot_name)), reply_markup=kb_reply)
            return

        if "$product" not in lot_obj.get("response", ""):
            bot.reply_to(m, _("ad_product_var_err2"), reply_markup=kb_reply)
            return

        if not filename_re.fullmatch(file_name):
            bot.reply_to(m, _("gf_name_invalid"), reply_markup=kb_reply)
            return
            
        file_name = file_name if file_name.lower().endswith(".txt") else f"{file_name}.txt"
        file_path = os.path.join("storage", "products", file_name)
        file_existed = os.path.exists(file_path)

        if not file_existed:
            bot.send_message(m.chat.id, _("ad_creating_gf", utils.escape(file_name)))
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8"): pass
            except Exception as e:
                logger.error(f"Ошибка создания файла при привязке: {file_path}, {e}", exc_info=True)
                bot.reply_to(m, _("gf_creation_err", utils.escape(file_name)), reply_markup=kb_reply)
                return

        cortex_instance.AD_CFG.set(lot_name, "productsFileName", file_name)
        cortex_instance.executor.submit(_threaded_save)
        
        log_key = "log_gf_linked" if file_existed else "log_gf_created_and_linked"
        reply_key = "ad_gf_linked" if file_existed else "ad_gf_created_and_linked"
        
        logger.info(_(log_key, m.from_user.username, m.from_user.id, file_name, lot_name))
        bot.reply_to(m, _(reply_key, utils.escape(file_name), utils.escape(lot_name)), reply_markup=kb_reply)

    def switch_lot_setting(c: CallbackQuery):
        """Переключает булевы настройки лота (вкл/выкл)."""
        bot.answer_callback_query(c.id)
        param_name, lot_index, offset = c.data.split(":")[1:]
        lot_index, offset = int(lot_index), int(offset)
        if not check_ad_lot_exists(lot_index, c, reply=False): return

        lot_name = cortex_instance.AD_CFG.sections()[lot_index]
        lot_obj = cortex_instance.AD_CFG[lot_name]
        current_value = lot_obj.getboolean(param_name, False)
        new_value = str(int(not current_value))
        
        def _threaded_save():
            cortex_instance.AD_CFG.set(lot_name, param_name, new_value)
            cortex_instance.save_config(cortex_instance.AD_CFG, "configs/auto_delivery.cfg")
        
        cortex_instance.executor.submit(_threaded_save)
        
        logger.info(_("log_param_changed", c.from_user.username, c.from_user.id, param_name, lot_name, new_value))
        
        bot.edit_message_text(utils.generate_lot_info_text(cortex_instance, lot_obj), c.message.chat.id, c.message.id,
                              reply_markup=kb.edit_lot(cortex_instance, lot_index, offset))
        
    def create_lot_delivery_test(c: CallbackQuery):
        """Создает одноразовый ключ для тестирования автовыдачи."""
        lot_index, offset = map(int, c.data.split(":")[1:])
        if not check_ad_lot_exists(lot_index, c, reply=False):
            bot.answer_callback_query(c.id)
            return

        lot_name = cortex_instance.AD_CFG.sections()[lot_index]
        test_key = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        cortex_instance.delivery_tests[test_key] = lot_name

        logger.info(_("log_new_ad_key", c.from_user.username, c.from_user.id, lot_name, test_key))
        kb_reply = K().row(B(_("gl_back"), callback_data=f"{CBT.EDIT_AD_LOT}:{lot_index}:{offset}"),
                           B(_("ea_more_test"), callback_data=f"test_auto_delivery:{lot_index}:{offset}"))
        bot.send_message(c.message.chat.id, _("test_ad_key_created", utils.escape(lot_name), test_key),
                         reply_markup=kb_reply)
        bot.answer_callback_query(c.id)

    def del_lot(c: CallbackQuery):
        """Удаляет лот из конфига автовыдачи."""
        bot.answer_callback_query(c.id, _("ar_command_deleted_successfully", command_name=utils.escape(cortex_instance.AD_CFG.sections()[int(c.data.split(":")[1])])), show_alert=True)
        bot.edit_message_text("🔄 Обновляю список...", c.message.chat.id, c.message.id)
        
        def _threaded_delete():
            lot_index, offset = map(int, c.data.split(":")[1:])
            if not check_ad_lot_exists(lot_index, c, reply=False): return

            lot_name = cortex_instance.AD_CFG.sections()[lot_index]
            cortex_instance.AD_CFG.remove_section(lot_name)
            cortex_instance.save_config(cortex_instance.AD_CFG, "configs/auto_delivery.cfg")
            logger.info(_("log_ad_deleted", c.from_user.username, c.from_user.id, lot_name))
            
            new_offset = offset if len(cortex_instance.AD_CFG.sections()) > offset else max(0, offset - MENU_CFG.AD_BTNS_AMOUNT)
            bot.edit_message_text(_("desc_ad_list"), c.message.chat.id, c.message.id,
                                  reply_markup=kb.lots_list(cortex_instance, new_offset))
        
        cortex_instance.executor.submit(_threaded_delete)

    # ================================================================================= #
    # ----------------------------- УПРАВЛЕНИЕ ФАЙЛАМИ ТОВАРОВ ---------------------------- #
    # ================================================================================= #
    
    def act_create_gf(c: CallbackQuery):
        """Активирует режим создания нового файла товаров."""
        result = bot.send_message(c.message.chat.id, _("act_create_gf"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.CREATE_PRODUCTS_FILE)
        bot.answer_callback_query(c.id)

    def create_gf(m: Message):
        """Создает новый файл для товаров."""
        tg.clear_state(m.chat.id, m.from_user.id, True)
        file_name = m.text.strip()
        kb_error = K().row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ad"),
                           B(_("gf_create_another"), callback_data=CBT.CREATE_PRODUCTS_FILE))

        if not filename_re.fullmatch(file_name):
            bot.reply_to(m, _("gf_name_invalid"), reply_markup=kb_error)
            return
            
        file_name = file_name if file_name.lower().endswith(".txt") else f"{file_name}.txt"
        file_path = os.path.join("storage", "products", file_name)

        if os.path.exists(file_path):
            all_files = sorted([f for f in os.listdir("storage/products") if f.endswith(".txt")])
            file_index = all_files.index(file_name)
            offset = utils.get_offset(file_index, MENU_CFG.PF_BTNS_AMOUNT)
            kb = K().row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ad"),
                         B(_("gf_create_another"), callback_data=CBT.CREATE_PRODUCTS_FILE),
                         B(_("gl_configure"), callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{file_index}:{offset}"))
            bot.reply_to(m, _("gf_already_exists_err", utils.escape(file_name)), reply_markup=kb)
            return
        
        def threaded_create():
            try:
                with open(file_path, "w", encoding="utf-8"): pass
                all_files = sorted([f for f in os.listdir("storage/products") if f.endswith(".txt")])
                new_index = all_files.index(file_name)
                new_offset = utils.get_offset(new_index, MENU_CFG.PF_BTNS_AMOUNT)
                kb_success = K().row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ad"),
                                     B(_("gf_create_more"), callback_data=CBT.CREATE_PRODUCTS_FILE),
                                     B(_("gl_configure"), callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{new_index}:{new_offset}"))
                logger.info(_("log_gf_created", m.from_user.username, m.from_user.id, file_name))
                bot.send_message(m.chat.id, _("gf_created", utils.escape(file_name)), reply_markup=kb_success)
            except Exception as e:
                logger.error(f"Ошибка создания файла {file_path}: {e}", exc_info=True)
                bot.reply_to(m, _("gf_creation_err", utils.escape(file_name)), reply_markup=kb_error)

        cortex_instance.executor.submit(threaded_create)

    def open_gf_settings(c: CallbackQuery):
        """Открывает настройки конкретного файла товаров."""
        split_data = c.data.split(":")
        file_index, offset = int(split_data[1]), int(split_data[2])
        
        products_dir = "storage/products"
        all_product_files = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt")]) if os.path.exists(products_dir) else []

        if not check_products_file_exists(file_index, all_product_files, c, reply=False):
            bot.answer_callback_query(c.id)
            return

        selected_file_name = all_product_files[file_index]
        full_selected_file_path = os.path.join(products_dir, selected_file_name)
        
        products_amount_str = "⚠️"
        try:
            products_amount_str = str(cortex_tools.count_products(full_selected_file_path))
        except Exception:
            pass

        nl = "\n"
        linked_lots_list = [lot_name for lot_name in cortex_instance.AD_CFG.sections() 
                            if cortex_instance.AD_CFG[lot_name].get("productsFileName") == selected_file_name]
        
        linked_lots_display = nl.join(f"<code> • {utils.escape(lot)}</code>" for lot in linked_lots_list) if linked_lots_list \
                              else f"<i>({_('no_lots_using_file')})</i>"

        text_to_send = f"""📄 <b><u>{utils.escape(selected_file_name)}</u></b>

🔢 <b><i>{_('gf_amount')}:</i></b>  <code>{products_amount_str}</code>
🔗 <b><i>{_('gf_uses')}:</i></b>
{linked_lots_display}

⏱️ <i>{_('gl_last_update')}:</i>  <code>{datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}</code>"""

        bot.edit_message_text(text_to_send, c.message.chat.id, c.message.id,
                              reply_markup=kb.products_file_edit(file_index, offset))
        bot.answer_callback_query(c.id)

    # --- НАЧАЛО ИЗМЕНЕНИЙ: Исправление ошибки локализации ---
    def act_add_products_to_file(c: CallbackQuery):
        """Активирует режим добавления товаров в файл."""
        split_data = c.data.split(":")
        file_index, el_index, offset, prev_page = int(split_data[1]), int(split_data[2]), int(split_data[3]), int(split_data[4])
        # Используем _() для получения переведенного текста
        result = bot.send_message(c.message.chat.id, _("gf_send_new_goods"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.ADD_PRODUCTS_TO_FILE,
                     {"file_index": file_index, "element_index": el_index,
                      "offset": offset, "previous_page": prev_page})
        bot.answer_callback_query(c.id)
    # --- КОНЕЦ ИЗМЕНЕНИЙ ---

    def add_products_to_file(m: Message):
        """Добавляет товары в указанный файл."""
        state_data = tg.get_state(m.chat.id, m.from_user.id)["data"]
        file_index, el_index, offset, prev_page = (state_data["file_index"], state_data["element_index"],
                                                   state_data["offset"], state_data["previous_page"])
        tg.clear_state(m.chat.id, m.from_user.id, True)

        products_dir = "storage/products"
        all_product_files = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt")]) if os.path.exists(products_dir) else []
        
        if file_index >= len(all_product_files):
            update_btn_cb = f"{CBT.PRODUCTS_FILES_LIST}:0" if prev_page == 0 else f"{CBT.EDIT_AD_LOT}:{el_index}:{offset}"
            error_keyboard = K().add(B(_("gl_refresh") if prev_page == 0 else _("gl_back"), callback_data=update_btn_cb))
            bot.reply_to(m, _("gf_not_found_err", file_index), reply_markup=error_keyboard)
            return

        selected_file_name = all_product_files[file_index]
        full_selected_file_path = os.path.join(products_dir, selected_file_name)
        
        products_to_add = [prod.strip() for prod in m.text.strip().split("\n") if prod.strip()]

        back_btn_cb = f"{CBT.EDIT_PRODUCTS_FILE}:{file_index}:{offset}" if prev_page == 0 else f"{CBT.EDIT_AD_LOT}:{el_index}:{offset}"
        try_again_btn_cb = f"{CBT.ADD_PRODUCTS_TO_FILE}:{file_index}:{el_index}:{offset}:{prev_page}"
        add_more_btn_cb = try_again_btn_cb

        if not products_to_add:
            bot.reply_to(m, _("gf_no_products_to_add"), 
                         reply_markup=K().row(B(_("gl_back"), callback_data=back_btn_cb), 
                                            B(_("gf_try_add_again"), callback_data=try_again_btn_cb)))
            return

        def _threaded_write():
            try:
                with open(full_selected_file_path, "a", encoding="utf-8") as f:
                    if os.path.getsize(full_selected_file_path) > 0: f.write("\n")
                    f.write("\n".join(products_to_add))
                
                logger.info(_("log_gf_new_goods", m.from_user.username, m.from_user.id, len(products_to_add), selected_file_name))
                keyboard_success = K().row(B(_("gl_back"), callback_data=back_btn_cb), B(_("gf_add_more"), callback_data=add_more_btn_cb))
                bot.reply_to(m, _("gf_new_goods", len(products_to_add), utils.escape(selected_file_name)), reply_markup=keyboard_success)
            except Exception as e:
                logger.error(f"Ошибка добавления товаров в {full_selected_file_path}: {e}")
                logger.debug("TRACEBACK", exc_info=True)
                keyboard_error = K().row(B(_("gl_back"), callback_data=back_btn_cb), B(_("gf_try_add_again"), callback_data=try_again_btn_cb))
                bot.reply_to(m, _("gf_add_goods_err"), reply_markup=keyboard_error)

        cortex_instance.executor.submit(_threaded_write)

    def send_products_file(c: CallbackQuery):
        """Отправляет файл товаров пользователю."""
        bot.answer_callback_query(c.id)
        
        def _threaded_send():
            split_data = c.data.split(":")
            file_index, offset = int(split_data[1]), int(split_data[2])
            
            products_dir = "storage/products"
            all_product_files = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt")]) if os.path.exists(products_dir) else []

            if not check_products_file_exists(file_index, all_product_files, c, reply=False): return

            selected_file_name = all_product_files[file_index]
            full_selected_file_path = os.path.join(products_dir, selected_file_name)

            try:
                with open(full_selected_file_path, "r", encoding="utf-8") as f:
                    if not f.read().strip():
                        bot.answer_callback_query(c.id, _("gf_empty_error", utils.escape(selected_file_name)), show_alert=True)
                        return
                    
                with open(full_selected_file_path, "rb") as file_to_send:
                    bot.send_document(c.message.chat.id, file_to_send, caption=f"📄 {utils.escape(selected_file_name)}")
                logger.info(_("log_gf_downloaded", c.from_user.username, c.from_user.id, selected_file_name))
            except FileNotFoundError:
                 bot.answer_callback_query(c.id, _("gf_not_found_err", file_index), show_alert=True)
            except Exception as e:
                logger.error(f"Ошибка при отправке файла {selected_file_name}: {e}")
                bot.answer_callback_query(c.id, _("gl_error_try_again"), show_alert=True)

        cortex_instance.executor.submit(_threaded_send)

    def ask_del_products_file(c: CallbackQuery):
        """Запрашивает подтверждение удаления файла товаров."""
        split_data = c.data.split(":")
        file_index, offset = int(split_data[1]), int(split_data[2])
        
        products_dir = "storage/products"
        all_product_files = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt")]) if os.path.exists(products_dir) else []

        if not check_products_file_exists(file_index, all_product_files, c, reply=False):
            bot.answer_callback_query(c.id)
            return
        bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                      reply_markup=kb.products_file_edit(file_index, offset, confirmation=True))
        bot.answer_callback_query(c.id)

    def del_products_file(c: CallbackQuery):
        """Удаляет файл товаров после подтверждения."""
        bot.answer_callback_query(c.id)
        
        def _threaded_delete():
            split_data = c.data.split(":")
            file_index_to_delete, offset = int(split_data[1]), int(split_data[2])
            
            products_dir = "storage/products"
            all_product_files = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt")]) if os.path.exists(products_dir) else []

            if file_index_to_delete >= len(all_product_files):
                bot.answer_callback_query(c.id, _("gf_not_found_err", file_index_to_delete) + " " + _("gl_refresh_and_try_again"), show_alert=True)
                c.data = f"{CBT.PRODUCTS_FILES_LIST}:{offset}"
                open_gf_list(c)
                return

            file_name_to_delete = all_product_files[file_index_to_delete]
            full_path_to_delete = os.path.join(products_dir, file_name_to_delete)

            linked_lots = [lot_name for lot_name in cortex_instance.AD_CFG.sections() 
                           if cortex_instance.AD_CFG[lot_name].get("productsFileName") == file_name_to_delete]
            if linked_lots:
                keyboard_error = K().add(B(_("gl_back"), callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{file_index_to_delete}:{offset}"))
                bot.edit_message_text(_("gf_linked_err", utils.escape(file_name_to_delete)),
                                      c.message.chat.id, c.message.id, reply_markup=keyboard_error)
                return

            try:
                os.remove(full_path_to_delete)
                logger.info(_("log_gf_deleted", c.from_user.username, c.from_user.id, file_name_to_delete))
                
                new_offset = max(0, offset - MENU_CFG.PF_BTNS_AMOUNT if len(all_product_files)-1 < offset + MENU_CFG.PF_BTNS_AMOUNT else offset)
                new_offset = 0 if len(all_product_files) -1 <= MENU_CFG.PF_BTNS_AMOUNT else new_offset

                c.data = f"{CBT.PRODUCTS_FILES_LIST}:{new_offset}"
                open_gf_list(c)
                bot.answer_callback_query(c.id, _("gf_deleted_successfully", file_name=utils.escape(file_name_to_delete)), show_alert=True)
            except FileNotFoundError:
                logger.warning(f"Попытка удалить уже удаленный файл: {full_path_to_delete}")
                c.data = f"{CBT.PRODUCTS_FILES_LIST}:{offset}"
                open_gf_list(c)
                bot.answer_callback_query(c.id, _("gf_already_deleted", file_name=utils.escape(file_name_to_delete)), show_alert=True)
            except Exception as e:
                logger.error(f"Ошибка удаления файла {full_path_to_delete}: {e}")
                logger.debug("TRACEBACK", exc_info=True)
                keyboard_error_del = K().add(B(_("gl_back"), callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{file_index_to_delete}:{offset}"))
                bot.edit_message_text(_("gf_deleting_err", utils.escape(file_name_to_delete)),
                                      c.message.chat.id, c.message.id, reply_markup=keyboard_error_del)
                return

        cortex_instance.executor.submit(_threaded_delete)
    
    # Регистрация обработчиков
    tg.cbq_handler(open_ad_lots_list, lambda c: c.data.startswith(f"{CBT.AD_LOTS_LIST}:"))
    tg.cbq_handler(open_fp_lots_list, lambda c: c.data.startswith(f"{CBT.FP_LOTS_LIST}:"))
    tg.cbq_handler(open_gf_list, lambda c: c.data.startswith(f"{CBT.PRODUCTS_FILES_LIST}:"))
    
    tg.cbq_handler(act_add_lot_manually, lambda c: c.data.startswith(f"{CBT.ADD_AD_TO_LOT_MANUALLY}:"))
    tg.msg_handler(add_lot_manually, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.ADD_AD_TO_LOT_MANUALLY))
    tg.cbq_handler(add_ad_to_lot, lambda c: c.data.startswith(f"{CBT.ADD_AD_TO_LOT}:"))
    tg.cbq_handler(update_funpay_lots_list, lambda c: c.data.startswith("update_funpay_lots:"))

    tg.cbq_handler(open_edit_lot_cp, lambda c: c.data.startswith(f"{CBT.EDIT_AD_LOT}:"))
    tg.cbq_handler(act_edit_delivery_text, lambda c: c.data.startswith(f"{CBT.EDIT_LOT_DELIVERY_TEXT}:"))
    tg.msg_handler(edit_delivery_text, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.EDIT_LOT_DELIVERY_TEXT))
    tg.cbq_handler(act_link_gf, lambda c: c.data.startswith(f"{CBT.BIND_PRODUCTS_FILE}:"))
    tg.msg_handler(link_gf, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.BIND_PRODUCTS_FILE))
    tg.cbq_handler(switch_lot_setting, lambda c: c.data.startswith("switch_lot:"))
    tg.cbq_handler(create_lot_delivery_test, lambda c: c.data.startswith("test_auto_delivery:"))
    tg.cbq_handler(del_lot, lambda c: c.data.startswith(f"{CBT.DEL_AD_LOT}:"))

    tg.cbq_handler(act_create_gf, lambda c: c.data == CBT.CREATE_PRODUCTS_FILE)
    tg.msg_handler(create_gf, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.CREATE_PRODUCTS_FILE))
    tg.cbq_handler(open_gf_settings, lambda c: c.data.startswith(f"{CBT.EDIT_PRODUCTS_FILE}:"))
    tg.cbq_handler(act_add_products_to_file, lambda c: c.data.startswith(f"{CBT.ADD_PRODUCTS_TO_FILE}:"))
    tg.msg_handler(add_products_to_file, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.ADD_PRODUCTS_TO_FILE))
    tg.cbq_handler(send_products_file, lambda c: c.data.startswith("download_products_file:"))
    tg.cbq_handler(ask_del_products_file, lambda c: c.data.startswith("del_products_file:"))
    tg.cbq_handler(del_products_file, lambda c: c.data.startswith("confirm_del_products_file:"))


BIND_TO_PRE_INIT = [init_auto_delivery_cp]
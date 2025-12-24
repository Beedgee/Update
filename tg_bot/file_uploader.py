# --- START OF FILE FunPayCortex/tg_bot/file_uploader.py ---
# -*- coding: utf-8 -*-

"""
FunPayBot by @beedge
--------------------------
Модуль-загрузчик файлов из Telegram.
Обрабатывает получение документов (конфигов, товаров) и изображений.
ПРИМЕЧАНИЕ: Загрузка плагинов (.py) отключена в режиме Hosting Only.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Literal
if TYPE_CHECKING:
    from cortex import Cortex
    from tg_bot.bot import TGBot

from Utils import config_loader as cfg_loader, exceptions as excs, cortex_tools
from telebot.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as K
from tg_bot import utils, keyboards, CBT, MENU_CFG
from tg_bot.static_keyboards import CLEAR_STATE_BTN
from telebot import types, apihelper
import logging
import os
import re
from locales.localizer import Localizer

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def check_file(tg: TGBot, msg: types.Message, type_: Literal["cfg", "json", "txt"] | None = None) -> bool:
    """
    Проверяет валидность присланного файла (расширение, размер).
    """
    if not msg.document:
        tg.bot.send_message(msg.chat.id, _("file_err_not_detected"))
        return False

    file_name = msg.document.file_name
    actual_ext = file_name.split('.')[-1].lower() if '.' in file_name else ""

    # Разрешенные расширения (py удален для безопасности)
    allowed_text_exts = ["cfg", "txt", "json", "ini", "log"]
    
    if type_ and type_ not in allowed_text_exts:
        if actual_ext != type_.lower():
            tg.bot.send_message(msg.chat.id, _("file_err_wrong_format", actual_ext=actual_ext, expected_ext=type_))
            return False
    elif actual_ext not in allowed_text_exts:
        tg.bot.send_message(msg.chat.id, _("file_err_must_be_text"))
        return False
    elif type_ and actual_ext != type_.lower():
        tg.bot.send_message(msg.chat.id, _("file_err_wrong_format", actual_ext=actual_ext, expected_ext=type_))
        return False

    if msg.document.file_size >= 20971520: # 20MB
        tg.bot.send_message(msg.chat.id, _("file_err_too_large"))
        return False
    return True


def download_file(tg: TGBot, msg: types.Message, progress_msg: types.Message, file_name: str = "temp_file.txt",
                  custom_path: str = "") -> str | None:
    """
    Скачивает файл с серверов Telegram и сохраняет локально.
    """
    try:
        tg.bot.edit_message_text(_("file_info_downloading"), progress_msg.chat.id, progress_msg.id)
        file_info = tg.bot.get_file(msg.document.file_id)
        downloaded_file_bytes = tg.bot.download_file(file_info.file_path)
    except apihelper.ApiTelegramException as e:
        logger.error(f"Ошибка Telegram API при скачивании файла: {e}")
        tg.bot.edit_message_text(_("file_err_download_failed") + f" (API Error: {e.error_code})", progress_msg.chat.id, progress_msg.id)
        return None
    except Exception as e:
        logger.error(f"Ошибка скачивания файла от Telegram: {e}")
        tg.bot.edit_message_text(_("file_err_download_failed"), progress_msg.chat.id, progress_msg.id)
        logger.debug("TRACEBACK", exc_info=True)
        return None

    base_path = tg.cortex.base_path
    if custom_path:
        target_dir = os.path.join(base_path, custom_path)
    else:
        target_dir = os.path.join(base_path, "storage", "cache")
    os.makedirs(target_dir, exist_ok=True)

    final_file_name = msg.document.file_name if file_name == "temp_file.txt" else file_name
    full_path = os.path.join(target_dir, final_file_name)

    try:
        with open(full_path, "wb") as new_file:
            new_file.write(downloaded_file_bytes)
        return full_path
    except IOError as e:
        logger.error(f"Ошибка сохранения скачанного файла {full_path}: {e}")
        tg.bot.edit_message_text(_("file_err_download_failed") + " (Save Error)", progress_msg.chat.id, progress_msg.id)
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при сохранении скачанного файла {full_path}: {e}")
        tg.bot.edit_message_text(_("file_err_download_failed") + " (Unexpected Save Error)", progress_msg.chat.id, progress_msg.id)
        logger.debug("TRACEBACK", exc_info=True)
        return None


def init_uploader(cortex_instance: Cortex):
    tg = cortex_instance.telegram
    bot = tg.bot

    # --- Загрузка файлов товаров ---
    def act_upload_products_file(c: types.CallbackQuery):
        result = tg.bot.send_message(c.message.chat.id, _("products_file_provide_prompt"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.UPLOAD_PRODUCTS_FILE)
        tg.bot.answer_callback_query(c.id)

    def upload_products_file(tg: TGBot, m: types.Message):
        tg.clear_state(m.chat.id, m.from_user.id, True)
        progress_msg = bot.send_message(m.chat.id, _("file_info_processing"))

        def threaded_task():
            if not check_file(tg, m, type_="txt"):
                bot.delete_message(progress_msg.chat.id, progress_msg.id)
                return

            saved_file_path = download_file(tg, m, progress_msg, custom_path="storage/products")
            if not saved_file_path:
                return

            try:
                products_count_str = str(cortex_tools.count_products(saved_file_path))
            except Exception as e:
                products_count_str = "⚠️"
                bot.send_message(m.chat.id, _("products_file_count_error") + f"\n\n<pre>{utils.escape(str(e))}</pre>")
                logger.error(f"Ошибка подсчета товаров в файле {saved_file_path}: {e}", exc_info=True)

            products_dir = os.path.join(tg.cortex.base_path, "storage/products")
            all_files_in_storage = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt") and os.path.isfile(os.path.join(products_dir, f))])
            
            try:
                file_index = all_files_in_storage.index(os.path.basename(saved_file_path))
                offset = utils.get_offset(file_index, MENU_CFG.PF_BTNS_AMOUNT)
                edit_button = Button(_("gl_edit"), callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{file_index}:{offset}")
            except ValueError:
                edit_button = Button(_("ad_edit_goods_file"), callback_data=f"{CBT.PRODUCTS_FILES_LIST}:0")
            
            keyboard_reply = K().add(edit_button)
            logger.info(f"Пользователь $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET загрузил файл с товарами $YELLOW{saved_file_path}$RESET.")
            bot.edit_message_text(_("products_file_upload_success", filepath=utils.escape(saved_file_path.replace(tg.cortex.base_path, '.')), count=products_count_str),
                                  progress_msg.chat.id, progress_msg.id, reply_markup=keyboard_reply)

        tg.cortex.executor.submit(threaded_task)

    # --- Загрузка основного конфига ---
    def act_upload_main_config(c: types.CallbackQuery):
        result = tg.bot.send_message(c.message.chat.id, _("main_config_provide_prompt"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, "upload_main_config")
        tg.bot.answer_callback_query(c.id)

    def upload_main_config(tg: TGBot, m: types.Message):
        tg.clear_state(m.chat.id, m.from_user.id, True)
        progress_msg = bot.send_message(m.chat.id, _("file_info_processing"))

        def threaded_task():
            if not check_file(tg, m, type_="cfg"):
                bot.delete_message(progress_msg.chat.id, progress_msg.id)
                return

            temp_path = download_file(tg, m, progress_msg, file_name="temp_main.cfg")
            if not temp_path: return

            try:
                bot.edit_message_text(_("file_info_checking_validity"), progress_msg.chat.id, progress_msg.id)
                new_config = cfg_loader.load_main_config(temp_path)
                tg.cortex.save_config(new_config, os.path.join(tg.cortex.base_path, "configs/_main.cfg"))
                bot.edit_message_text(_("file_info_main_cfg_loaded"), progress_msg.chat.id, progress_msg.id)
                logger.info(f"Пользователь $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET загрузил основной конфиг.")
            except excs.ConfigParseError as e:
                bot.edit_message_text(_("file_err_processing_generic", error_message=utils.escape(str(e))), progress_msg.chat.id, progress_msg.id)
            except Exception as e:
                bot.edit_message_text(_("file_err_processing_generic", error_message=utils.escape(str(e))), progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при парсинге основного конфига {temp_path}: {e}", exc_info=True)
            finally:
                if os.path.exists(temp_path): os.remove(temp_path)
        
        tg.cortex.executor.submit(threaded_task)

    # --- Загрузка конфига автоответчика ---
    def act_upload_auto_response_config(c: types.CallbackQuery):
        result = tg.bot.send_message(c.message.chat.id, _("ar_config_provide_prompt"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, "upload_auto_response_config")
        tg.bot.answer_callback_query(c.id)

    def upload_auto_response_config(tg: TGBot, m: types.Message):
        tg.clear_state(m.chat.id, m.from_user.id, True)
        progress_msg = bot.send_message(m.chat.id, _("file_info_processing"))
        
        def threaded_task():
            if not check_file(tg, m, type_="cfg"):
                bot.delete_message(progress_msg.chat.id, progress_msg.id)
                return
                
            temp_path = download_file(tg, m, progress_msg, file_name="temp_ar.cfg")
            if not temp_path: return
            
            try:
                bot.edit_message_text(_("file_info_checking_validity"), progress_msg.chat.id, progress_msg.id)
                tg.cortex.RAW_AR_CFG = cfg_loader.load_raw_auto_response_config(temp_path)
                tg.cortex.AR_CFG = cfg_loader.load_auto_response_config(temp_path)
                tg.cortex.save_config(tg.cortex.RAW_AR_CFG, os.path.join(tg.cortex.base_path, "configs/auto_response.cfg"))
                bot.edit_message_text(_("file_info_ar_cfg_applied"), progress_msg.chat.id, progress_msg.id)
                logger.info(f"Пользователь $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET загрузил конфиг автоответчика.")
            except excs.ConfigParseError as e:
                bot.edit_message_text(_("file_err_processing_generic", error_message=utils.escape(str(e))), progress_msg.chat.id, progress_msg.id)
            except Exception as e:
                bot.edit_message_text(_("file_err_processing_generic", error_message=utils.escape(str(e))), progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при парсинге конфига автоответчика {temp_path}: {e}", exc_info=True)
            finally:
                if os.path.exists(temp_path): os.remove(temp_path)
        
        tg.cortex.executor.submit(threaded_task)

    # --- Загрузка конфига автовыдачи ---
    def act_upload_auto_delivery_config(c: types.CallbackQuery):
        result = tg.bot.send_message(c.message.chat.id, _("ad_config_provide_prompt"), reply_markup=CLEAR_STATE_BTN())
        tg.set_state(c.message.chat.id, result.id, c.from_user.id, "upload_auto_delivery_config")
        tg.bot.answer_callback_query(c.id)
        
    def upload_auto_delivery_config(tg: TGBot, m: types.Message):
        tg.clear_state(m.chat.id, m.from_user.id, True)
        progress_msg = bot.send_message(m.chat.id, _("file_info_processing"))

        def threaded_task():
            if not check_file(tg, m, type_="cfg"):
                bot.delete_message(progress_msg.chat.id, progress_msg.id)
                return

            temp_path = download_file(tg, m, progress_msg, file_name="temp_ad.cfg")
            if not temp_path: return
            
            try:
                bot.edit_message_text(_("file_info_checking_validity"), progress_msg.chat.id, progress_msg.id)
                tg.cortex.AD_CFG = cfg_loader.load_auto_delivery_config(temp_path)
                tg.cortex.save_config(tg.cortex.AD_CFG, os.path.join(tg.cortex.base_path, "configs/auto_delivery.cfg"))
                bot.edit_message_text(_("file_info_ad_cfg_applied"), progress_msg.chat.id, progress_msg.id)
                logger.info(f"Пользователь $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET загрузил конфиг автовыдачи.")
            except excs.ConfigParseError as e:
                bot.edit_message_text(_("file_err_processing_generic", error_message=utils.escape(str(e))), progress_msg.chat.id, progress_msg.id)
            except Exception as e:
                bot.edit_message_text(_("file_err_processing_generic", error_message=utils.escape(str(e))), progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при парсинге конфига автовыдачи {temp_path}: {e}", exc_info=True)
            finally:
                if os.path.exists(temp_path): os.remove(temp_path)
        
        tg.cortex.executor.submit(threaded_task)

    # --- Загрузка изображений ---
    def upload_image_generic_handler(tg: TGBot, m: types.Message, image_type: Literal["chat", "offer"]):
        tg.clear_state(m.chat.id, m.from_user.id, True)
        
        photo_obj = None
        if m.photo:
            photo_obj = m.photo[-1]
        elif m.document and m.document.mime_type and m.document.mime_type.startswith("image/"):
            photo_obj = m.document
        else:
            tg.bot.send_message(m.chat.id, _("image_upload_unsupported_format"))
            return

        if photo_obj.file_size >= 20971520: # 20MB
            tg.bot.send_message(m.chat.id, _("file_err_too_large"))
            return
        
        progress_msg = tg.bot.send_message(m.chat.id, _("file_info_processing"))

        def threaded_task():
            try:
                bot.edit_message_text(_("file_info_downloading"), progress_msg.chat.id, progress_msg.id)
                file_info = tg.bot.get_file(photo_obj.file_id)
                downloaded_bytes = tg.bot.download_file(file_info.file_path)
                
                bot.edit_message_text(f"📤 Загружаю на FunPay ({image_type})...", progress_msg.chat.id, progress_msg.id)
                image_id = tg.cortex.account.upload_image(downloaded_bytes, type_=image_type)
                bot.delete_message(progress_msg.chat.id, progress_msg.id)
                
                success_header = _("image_upload_success_header", image_id=image_id)
                info_key = "image_upload_chat_success_info" if image_type == "chat" else "image_upload_offer_success_info"
                info_text = _(info_key, image_id=image_id)
                tg.bot.reply_to(m, f"{success_header}{info_text}")

            except Exception as e:
                bot.delete_message(progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при загрузке изображения ({image_type}): {e}", exc_info=True)
                tg.bot.reply_to(m, _("image_upload_error_generic"))

        tg.cortex.executor.submit(threaded_task)


    def send_funpay_image_handler(tg: TGBot, m: types.Message):
        """Обработчик отправки изображения непосредственно в чат FunPay (из меню 'Ответить')."""
        photo_obj = None
        if m.photo:
            photo_obj = m.photo[-1]
        elif m.document and m.document.mime_type and m.document.mime_type.startswith("image/"):
            photo_obj = m.document
        else:
            return

        state_data = tg.get_state(m.chat.id, m.from_user.id)
        if not state_data or state_data.get("state") != CBT.SEND_FP_MESSAGE:
            return
            
        node_id, username = state_data["data"]["node_id"], state_data["data"]["username"]
        tg.clear_state(m.chat.id, m.from_user.id, True)

        if photo_obj.file_size >= 20971520: # 20MB
            tg.bot.send_message(m.chat.id, _("file_err_too_large"))
            return

        progress_msg = tg.bot.send_message(m.chat.id, _("file_info_processing"))
        
        def threaded_task():
            try:
                bot.edit_message_text(_("file_info_downloading"), progress_msg.chat.id, progress_msg.id)
                file_info = tg.bot.get_file(photo_obj.file_id)
                downloaded_bytes = tg.bot.download_file(file_info.file_path)

                bot.edit_message_text(f"📤 Загружаю на FunPay (chat)...", progress_msg.chat.id, progress_msg.id)
                image_id_on_fp = tg.cortex.account.upload_image(downloaded_bytes, type_="chat")
                bot.delete_message(progress_msg.chat.id, progress_msg.id)

                send_success = tg.cortex.send_message(node_id, "", username, image_id=image_id_on_fp, watermark=False)
                reply_kb = keyboards.reply(node_id, username, again=True, extend=True)
                if send_success:
                    tg.bot.reply_to(m, _("msg_sent", node_id, utils.escape(username or "Пользователь")), reply_markup=reply_kb)
                else:
                    tg.bot.reply_to(m, _("msg_sending_error", node_id, utils.escape(username or "Пользователь")), reply_markup=reply_kb)
            except Exception as e:
                bot.delete_message(progress_msg.chat.id, progress_msg.id)
                logger.error(f"Ошибка при отправке изображения: {e}", exc_info=True)
                tg.bot.reply_to(m, _("image_upload_error_generic"))

        tg.cortex.executor.submit(threaded_task)


    def upload_chat_image_handler(tg: TGBot, m: types.Message):
        upload_image_generic_handler(tg, m, image_type="chat")

    def upload_offer_image_handler(tg: TGBot, m: types.Message):
        upload_image_generic_handler(tg, m, image_type="offer")

    # Регистрация обработчиков
    tg.cbq_handler(act_upload_products_file, lambda c: c.data == CBT.UPLOAD_PRODUCTS_FILE)
    tg.cbq_handler(act_upload_auto_response_config, lambda c: c.data == "upload_auto_response_config")
    tg.cbq_handler(act_upload_auto_delivery_config, lambda c: c.data == "upload_auto_delivery_config")
    tg.cbq_handler(act_upload_main_config, lambda c: c.data == "upload_main_config")

    tg.file_handler(CBT.UPLOAD_PRODUCTS_FILE, upload_products_file)
    tg.file_handler("upload_auto_response_config", upload_auto_response_config)
    tg.file_handler("upload_auto_delivery_config", upload_auto_delivery_config)
    tg.file_handler("upload_main_config", upload_main_config)
    # CBT.UPLOAD_PLUGIN удален специально
    tg.file_handler(CBT.SEND_FP_MESSAGE, send_funpay_image_handler)
    tg.file_handler(CBT.UPLOAD_CHAT_IMAGE, upload_chat_image_handler)
    tg.file_handler(CBT.UPLOAD_OFFER_IMAGE, upload_offer_image_handler)


BIND_TO_PRE_INIT = [init_uploader]
# --- END OF FILE FunPayCortex/tg_bot/file_uploader.py ---
# START OF FILE FunPayCortex/tg_bot/static_keyboards.py

# -*- coding: utf-8 -*-
"""
Полностью переработанный файл для генерации клавиатур FunPayBot.
Здесь определена структура и внешний вид всех статических меню,
которые не зависят от динамических списков (например, списка лотов).
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from cortex import Cortex

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
from tg_bot import CBT, utils
from locales.localizer import Localizer

localizer = Localizer()
_ = localizer.translate


def CLEAR_STATE_BTN() -> K:
    return K().add(B(f"🚫 {_('gl_cancel')}", callback_data=CBT.CLEAR_STATE))


def REFRESH_BTN() -> K:
    return K().add(B(f"🔄 {_('gl_refresh')}", callback_data=CBT.UPDATE_PROFILE))


def BALANCE_REFRESH_BTN() -> K:
    kb = K(row_width=2)
    back_button = B(f"⬅️ {_('gl_back')}", callback_data=f"{CBT.CATEGORY}:management")
    refresh_button = B(f"🔄 {_('gl_refresh')}", callback_data=CBT.BALANCE_REFRESH)
    kb.row(back_button, refresh_button)
    return kb


def SETTINGS_SECTIONS(cortex_instance: "Cortex", user_id: int) -> K:
    user_role = utils.get_user_role(cortex_instance.telegram.authorized_users, user_id)
    kb = K(row_width=1)
    
    if user_role == "admin":
        kb.add(B(_("mm_global"), callback_data=f"{CBT.CATEGORY}:main"))
        
    kb.add(B(_("mm_automation_section"), callback_data=f"{CBT.CATEGORY}:automation"))
    kb.add(B(_("mm_management_section"), callback_data=f"{CBT.CATEGORY}:management"))
    kb.add(B(_("mm_system_section"), callback_data=f"{CBT.CATEGORY}:system"))
    
    kb.row(B(_("mm_logout"), callback_data=f"{CBT.LOG_OUT_REQUEST}:{CBT.MAIN}"))
    
    return kb

def AUTOMATION_SETTINGS(cortex_instance: "Cortex", user_id: int) -> K:
    user_role = utils.get_user_role(cortex_instance.telegram.authorized_users, user_id)
    mp = cortex_instance.MAIN_CFG["ManagerPermissions"]
    kb = K(row_width=2)
    
    buttons = []
    if user_role == "admin" or mp.getboolean("autoResponse"):
        buttons.append(B(_("mm_autoresponse"), callback_data=f"{CBT.CATEGORY}:ar"))
    if user_role == "admin" or mp.getboolean("autoDelivery"):
        buttons.append(B(_("mm_autodelivery"), callback_data=f"{CBT.CATEGORY}:ad"))
    if user_role == "admin" or mp.getboolean("greetings"):
        buttons.append(B(_("mm_greetings"), callback_data=f"{CBT.CATEGORY}:gr"))
    if user_role == "admin" or mp.getboolean("orderConfirm"):
        buttons.append(B(_("mm_order_confirm"), callback_data=f"{CBT.CATEGORY}:oc"))
    if user_role == "admin" or mp.getboolean("reviewReply"):
        buttons.append(B(_("mm_review_reply"), callback_data=f"{CBT.CATEGORY}:rr"))
        
    kb.add(*buttons)
    kb.row(B(_("gl_back"), callback_data=CBT.MAIN))
    return kb

def MANAGEMENT_SETTINGS(cortex_instance: "Cortex", user_id: int) -> K:
    user_role = utils.get_user_role(cortex_instance.telegram.authorized_users, user_id)
    mp = cortex_instance.MAIN_CFG["ManagerPermissions"]
    kb = K(row_width=2)

    buttons = []
    if user_role == "admin" or mp.getboolean("statistics"):
        buttons.append(B("📊 Статистика", callback_data=f"{CBT.STATS_MENU}:main"))
        
    buttons.append(B(_("mm_balance"), callback_data=CBT.BALANCE_REFRESH))
    buttons.append(B(_("mm_templates"), callback_data=f"{CBT.TMPLT_LIST}:0"))
    
    if user_role == "admin":
        buttons.append(B(_("mm_blacklist"), callback_data=f"{CBT.CATEGORY}:bl"))
        buttons.append(B(_("mm_authorized_users"), callback_data=f"{CBT.AUTHORIZED_USERS}:0"))
    
    kb.add(*buttons)
    kb.row(B(_("gl_back"), callback_data=CBT.MAIN))
    return kb
    
def SYSTEM_SETTINGS(cortex_instance: "Cortex", user_id: int) -> K:
    user_role = utils.get_user_role(cortex_instance.telegram.authorized_users, user_id)
    mp = cortex_instance.MAIN_CFG["ManagerPermissions"]
    kb = K(row_width=2)
    
    buttons = []
    # УБРАНА КНОПКА ЯЗЫКА
    # buttons.append(B(_("mm_language"), callback_data=f"{CBT.CATEGORY}:lang")) 
    
    buttons.append(B(_("mm_notifications"), callback_data=f"{CBT.CATEGORY}:tg"))
    buttons.append(B(_("mm_new_msg_view"), callback_data=f"{CBT.CATEGORY}:mv"))
    
    if user_role == "admin" or mp.getboolean("plugins"):
         buttons.append(B(_("mm_plugins"), callback_data=f"{CBT.PLUGINS_LIST}:0"))
    if user_role == "admin" or mp.getboolean("proxy"):
        buttons.append(B(_("mm_proxy"), callback_data=f"{CBT.PROXY}:0"))
    if user_role == "admin":
        buttons.append(B(_("mm_configs"), callback_data=CBT.CONFIG_LOADER))
        
    kb.add(*buttons)
    kb.row(B(_("gl_back"), callback_data=CBT.MAIN))
    return kb

def AR_SETTINGS() -> K:
    return K() \
        .add(B(_("ar_edit_commands"), callback_data=f"{CBT.CMD_LIST}:0")) \
        .add(B(_("ar_add_command"), callback_data=CBT.ADD_CMD)) \
        .add(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:automation"))


def AD_SETTINGS() -> K:
    return K(row_width=2) \
        .add(B(_("ad_edit_autodelivery"), callback_data=f"{CBT.AD_LOTS_LIST}:0")) \
        .add(B(_("ad_add_autodelivery"), callback_data=f"{CBT.FP_LOTS_LIST}:0")) \
        .add(B(_("ad_edit_goods_file"), callback_data=f"{CBT.PRODUCTS_FILES_LIST}:0")) \
        .add(B(_("ad_upload_goods_file"), callback_data=CBT.UPLOAD_PRODUCTS_FILE),
             B(_("ad_create_goods_file"), callback_data=CBT.CREATE_PRODUCTS_FILE)) \
        .add(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:automation"))


def CONFIGS_UPLOADER() -> K:
    return K(row_width=2) \
        .add(B(_("cfg_download_main"), callback_data=f"{CBT.DOWNLOAD_CFG}:main"),
             B(_("cfg_upload_main"), callback_data="upload_main_config")) \
        .add(B(_("cfg_download_ar"), callback_data=f"{CBT.DOWNLOAD_CFG}:autoResponse"),
             B(_("cfg_upload_ar"), callback_data="upload_auto_response_config")) \
        .add(B(_("cfg_download_ad"), callback_data=f"{CBT.DOWNLOAD_CFG}:autoDelivery"),
             B(_("cfg_upload_ad"), callback_data="upload_auto_delivery_config")) \
        .add(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:system"))


def LINKS_KB(language: None | str = None) -> K:
    kb = K(row_width=1)
    kb.add(B("🌐 Наш сайт - funpaybot.ru", url="https://funpaybot.ru"))
    kb.add(B("📢 Telegram-канал @FunPayCortex", url="https://t.me/FunPayCortex"))
    return kb
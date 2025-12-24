from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex import Cortex

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
from tg_bot import CBT, utils, MENU_CFG
from tg_bot.utils import NotificationTypes, bool_to_text, add_navigation_buttons
import Utils.cortex_tools
from locales.localizer import Localizer
import logging
import random
import os
import math

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def power_off(instance_id: int, state: int) -> K:
    kb = K()
    if state == 0:
        kb.row(B(_("gl_yes"), callback_data=f"{CBT.SHUT_DOWN}:1:{instance_id}"),
               B(_("gl_no"), callback_data=CBT.CANCEL_SHUTTING_DOWN))
    elif state == 1:
        kb.row(B(_("gl_no"), callback_data=CBT.CANCEL_SHUTTING_DOWN),
               B(_("gl_yes"), callback_data=f"{CBT.SHUT_DOWN}:2:{instance_id}"))
    elif state == 2:
        yes_button_num = random.randint(1, 10)
        yes_button = B(_("gl_yes"), callback_data=f"{CBT.SHUT_DOWN}:3:{instance_id}")
        no_button = B(_("gl_no"), callback_data=CBT.CANCEL_SHUTTING_DOWN)
        buttons = [*[no_button] * (yes_button_num - 1), yes_button, *[no_button] * (10 - yes_button_num)]
        kb.add(*buttons, row_width=2)
    elif state == 3:
        yes_button_num = random.randint(1, 30)
        yes_button = B(_("gl_yes"), callback_data=f"{CBT.SHUT_DOWN}:4:{instance_id}")
        no_button = B(_("gl_no"), callback_data=CBT.CANCEL_SHUTTING_DOWN)
        buttons = [*[no_button] * (yes_button_num - 1), yes_button, *[no_button] * (30 - yes_button_num)]
        kb.add(*buttons, row_width=5)
    elif state == 4:
        yes_button_num = random.randint(1, 40)
        yes_button = B(_("gl_no"), callback_data=f"{CBT.SHUT_DOWN}:5:{instance_id}")
        no_button = B(_("gl_yes"), callback_data=CBT.CANCEL_SHUTTING_DOWN)
        buttons = [*[yes_button] * (yes_button_num - 1), no_button, *[yes_button] * (40 - yes_button_num)]
        kb.add(*buttons, row_width=7)
    elif state == 5:
        kb.add(B(_("gl_yep") + "💤", callback_data=f"{CBT.SHUT_DOWN}:6:{instance_id}"))
    return kb


def main_settings(c: Cortex) -> K:
    p = f"{CBT.SWITCH}:FunPay"
    def l(s): return '🟢' if c.MAIN_CFG["FunPay"].getboolean(s) else '🔴'
    
    kb = K(row_width=2)
    kb.add(
        B(_("gs_autoraise").split('{} ')[1], callback_data=f"{CBT.CATEGORY}:raise"),
        B(_("gs_autoresponse", l('autoResponse')), callback_data=f"{p}:autoResponse:0"),
        B(_("gs_autodelivery", l('autoDelivery')), callback_data=f"{p}:autoDelivery:0"),
        B(_("gs_nultidelivery", l('multiDelivery')), callback_data=f"{p}:multiDelivery:0"),
        B(_("gs_autorestore", l('autoRestore')), callback_data=f"{p}:autoRestore:0"),
        B(_("gs_autodisable", l('autoDisable')), callback_data=f"{p}:autoDisable:0")
    )
    kb.row(
        B(_("gs_old_msg_mode", l('oldMsgGetMode')), callback_data=f"{p}:oldMsgGetMode:0"),
        B("❔ Инфо", callback_data=CBT.OLD_MOD_HELP)
    )
    kb.add(B(_("gs_keep_sent_messages_unread", l('keepSentMessagesUnread')), callback_data=f"{p}:keepSentMessagesUnread:0"))
    kb.row(
        B(_("gl_back"), callback_data=CBT.MAIN),
        B("❓", callback_data=f"{CBT.SHOW_HELP}:gs")
    )
    return kb


def auto_raise_settings(c: Cortex) -> K:
    p = f"{CBT.SWITCH}:FunPay"
    def l(s): return '🟢' if c.MAIN_CFG["FunPay"].getboolean(s) else '🔴'

    kb = K(row_width=1)
    kb.add(B(_("gs_autoraise", l('autoRaise')), callback_data=f"{p}:autoRaise"))
    kb.add(B(_("raise_update_categories_btn"), callback_data=CBT.UPDATE_RAISE_CATEGORIES))
    kb.row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:main"))
    return kb


def new_message_view_settings(c: Cortex) -> K:
    p = f"{CBT.SWITCH}:NewMessageView"
    def l(s): return '🟢' if c.MAIN_CFG["NewMessageView"].getboolean(s) else '🔴'

    kb = K()
    kb.add(B(_("mv_incl_my_msg", l("includeMyMessages")), callback_data=f"{p}:includeMyMessages"))
    kb.add(B(_("mv_incl_fp_msg", l("includeFPMessages")), callback_data=f"{p}:includeFPMessages"))
    kb.add(B(_("mv_incl_bot_msg", l("includeBotMessages")), callback_data=f"{p}:includeBotMessages"))
    kb.add(B(_("mv_only_my_msg", l("notifyOnlyMyMessages")), callback_data=f"{p}:notifyOnlyMyMessages"))
    kb.add(B(_("mv_only_fp_msg", l("notifyOnlyFPMessages")), callback_data=f"{p}:notifyOnlyFPMessages"))
    kb.add(B(_("mv_only_bot_msg", l("notifyOnlyBotMessages")), callback_data=f"{p}:notifyOnlyBotMessages"))
    kb.add(B(_("mv_show_image_name", l("showImageName")), callback_data=f"{p}:showImageName"))
    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:system"),
        B("❓", callback_data=f"{CBT.SHOW_HELP}:mv")
    )
    return kb


def greeting_settings(c: Cortex) -> K:
    p = f"{CBT.SWITCH}:Greetings"
    def l(s): return '🟢' if c.MAIN_CFG["Greetings"].getboolean(s) else '🔴'
    
    cd = float(c.MAIN_CFG["Greetings"]["greetingsCooldown"])
    cd = int(cd) if int(cd) == cd else cd
    kb = K(row_width=1)
    kb.add(
        B(_("gr_greetings", l("sendGreetings")), callback_data=f"{p}:sendGreetings"),
        B(_("gr_ignore_sys_msgs", l("ignoreSystemMessages")), callback_data=f"{p}:ignoreSystemMessages"),
        B(_("gr_edit_message"), callback_data=CBT.EDIT_GREETINGS_TEXT),
        B(_("gr_edit_cooldown", cd), callback_data=CBT.EDIT_GREETINGS_COOLDOWN)
    )
    kb.row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:automation"))
    return kb


def order_confirm_reply_settings(c: Cortex) -> K:
    kb = K(row_width=1)
    kb.add(
        B(_("oc_send_reply", bool_to_text(c.MAIN_CFG['OrderConfirm']['sendReply'], '🟢', '🔴')), callback_data=f"{CBT.SWITCH}:OrderConfirm:sendReply"),
        B(_("oc_watermark", bool_to_text(c.MAIN_CFG['OrderConfirm']['watermark'], '🟢', '🔴')), callback_data=f"{CBT.SWITCH}:OrderConfirm:watermark"),
        B(_("oc_edit_message"), callback_data=CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT)
    )
    kb.row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:automation"))
    return kb


def authorized_users(c: Cortex, offset: int, current_user_id: int) -> K:
    kb = K()
    p = f"{CBT.SWITCH}:Telegram"
    user_role = utils.get_user_role(c.telegram.authorized_users, current_user_id)
    def l(s): return '🟢' if c.MAIN_CFG["Telegram"].getboolean(s) else '🔴'

    if user_role == "admin":
        kb.add(B(_("tg_block_login", l("blockLogin")), callback_data=f"{p}:blockLogin:{offset}"))

    users_dict = c.telegram.authorized_users
    sorted_users = sorted(users_dict.items(), key=lambda item: (item[1].get('role', 'z'), item[1].get('username', str(item[0])).lower()))
    
    users_on_page = sorted_users[offset : offset + MENU_CFG.AUTHORIZED_USERS_BTNS_AMOUNT]
    for user_id, user_info in users_on_page:
        username = user_info.get("username", f"ID: {user_id}")
        role_emoji = "👑" if user_info.get("role") == 'admin' else '👤'
        kb.row(B(f"{role_emoji} {username}", callback_data=f"{CBT.AUTHORIZED_USER_SETTINGS}:{user_id}:{offset}"))

    add_navigation_buttons(kb, offset, MENU_CFG.AUTHORIZED_USERS_BTNS_AMOUNT, len(users_on_page), len(sorted_users), CBT.AUTHORIZED_USERS)
    
    if user_role == "admin":
        kb.row(
            B(_("mm_manager_settings"), callback_data=CBT.MANAGER_SETTINGS),
            B(_("mm_manager_permissions"), callback_data=CBT.MANAGER_PERMISSIONS)
        )
    
    kb.row(
        B(_("mm_logout"), callback_data=f"{CBT.LOG_OUT_REQUEST}:{CBT.AUTHORIZED_USERS}:{offset}"),
        B("❓", callback_data=f"{CBT.SHOW_HELP}:au")
    )
    kb.add(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:management"))
    return kb


def manager_permissions_settings(c: Cortex) -> K:
    kb = K(row_width=2)
    p = f"{CBT.SWITCH}:ManagerPermissions"
    def l(s): return '🟢' if c.MAIN_CFG["ManagerPermissions"].getboolean(s) else '🔴'
    
    permissions = {
        "autoResponse": "mm_autoresponse", "autoDelivery": "mm_autodelivery",
        "templates": "mm_templates", "greetings": "mm_greetings",
        "orderConfirm": "mm_order_confirm", "reviewReply": "mm_review_reply",
        "plugins": "mm_plugins", "proxy": "mm_proxy", "statistics": "📊 Статистика",
    }
    
    buttons = [B(f"{_(lang_key).split(' ', 1)[-1]} {l(perm_key)}", callback_data=f"{p}:{perm_key}") for perm_key, lang_key in permissions.items()]
    kb.add(*buttons)
    kb.row(B(_("gl_back"), callback_data=f"{CBT.AUTHORIZED_USERS}:0"))
    return kb


def authorized_user_settings(c: Cortex, user_id: int, offset: int, user_link: bool, current_user_id: int) -> K:
    kb = K()
    user_info = c.telegram.authorized_users.get(user_id, {})
    username = user_info.get("username", str(user_id))
    user_role = user_info.get("role")
    current_user_role = utils.get_user_role(c.telegram.authorized_users, current_user_id)

    kb.add(B(f"👤 {username}", url=f"tg:user?id={user_id}" if user_link else None, callback_data=CBT.EMPTY if not user_link else None))
    
    if current_user_role == 'admin' and current_user_id != user_id:
        if user_role == 'manager':
            kb.add(B(_("promote_to_admin"), callback_data=f"{CBT.CHANGE_USER_ROLE}:{user_id}:{offset}:admin"))
        elif user_role == 'admin':
            admins = [uid for uid, uinfo in c.telegram.authorized_users.items() if uinfo.get("role") == "admin"]
            if len(admins) > 1:
                kb.add(B(_("demote_to_manager"), callback_data=f"{CBT.CHANGE_USER_ROLE}:{user_id}:{offset}:manager"))
        
        kb.add(B(_("revoke_access"), callback_data=f"{CBT.REVOKE_USER_ACCESS}:{user_id}:{offset}"))

    kb.add(B(_("gl_back"), callback_data=f"{CBT.AUTHORIZED_USERS}:{offset}"))
    return kb


def proxy(c: Cortex, offset: int, proxies: dict[str, bool]) -> K:
    kb = K()
    ps = list(c.proxy_dict.items())[offset : offset + MENU_CFG.PROXY_BTNS_AMOUNT]
    
    current_proxy_str = utils.get_current_proxy_str(c.MAIN_CFG["Proxy"])

    for proxy_id, proxy_string in ps:
        status_emoji = "🟢" if proxies.get(proxy_string) else "🟡" if proxies.get(proxy_string) is None else "🔴"
        is_current = proxy_string == current_proxy_str and c.MAIN_CFG["Proxy"].getboolean("enable")
        
        display_text = f"{'✅ ' if is_current else ''}{status_emoji} {utils.mask_proxy_string(proxy_string)}"
        
        kb.row(
            B(display_text, callback_data=f"{CBT.CHOOSE_PROXY}:{offset}:{proxy_id}" if not is_current else CBT.EMPTY),
            B("🗑️", callback_data=f"{CBT.DELETE_PROXY}:{offset}:{proxy_id}")
        )
        
    add_navigation_buttons(kb, offset, MENU_CFG.PROXY_BTNS_AMOUNT, len(ps), len(c.proxy_dict), CBT.PROXY)
    kb.row(B(_("prx_proxy_add"), callback_data=f"{CBT.ADD_PROXY}:{offset}"))
    kb.add(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:system"))
    return kb


def review_reply_settings(c: Cortex) -> K:
    kb = K()
    for i in range(1, 6):
        stars_text = '⭐' * i
        reply_enabled = c.MAIN_CFG['ReviewReply'].getboolean(f'star{i}Reply')
        reply_text_exists = bool(c.MAIN_CFG['ReviewReply'][f'star{i}ReplyText'])
        
        kb.row(
            B(f"{stars_text} {('🟢' if reply_enabled else '🔴')}", callback_data=f"{CBT.SWITCH}:ReviewReply:star{i}Reply"),
            B(f"{'✏️' if reply_text_exists else '➕'} {_('oc_edit_message').split(' ', 1)[1]}", callback_data=f"{CBT.EDIT_REVIEW_REPLY_TEXT}:{i}")
        )
    kb.row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:automation"))
    return kb


def notifications_settings(c: Cortex, chat_id: int) -> K:
    p = f"{CBT.SWITCH_TG_NOTIFICATIONS}:{chat_id}"
    n = NotificationTypes
    def l(nt): return '🔔' if c.telegram.is_notification_enabled(chat_id, nt) else '🔕'

    kb = K(row_width=2)
    kb.add(
        B(f"{l(n.new_message)} {_('ns_new_msg').split(' ', 1)[1]}", callback_data=f"{p}:{n.new_message}"),
        B(f"{l(n.new_order)} {_('ns_new_order').split(' ', 1)[1]}", callback_data=f"{p}:{n.new_order}"),
        B(f"{l(n.order_confirmed)} {_('ns_order_confirmed').split(' ', 1)[1]}", callback_data=f"{p}:{n.order_confirmed}"),
        B(f"{l(n.review)} {_('ns_new_review').split(' ', 1)[1]}", callback_data=f"{p}:{n.review}"),
        B(f"{l(n.delivery)} {_('ns_delivery').split(' ', 1)[1]}", callback_data=f"{p}:{n.delivery}"),
        B(f"{l(n.lots_raise)} {_('ns_raise').split(' ', 1)[1]}", callback_data=f"{p}:{n.lots_raise}"),
        B(f"{l(n.lots_restore)} {_('ns_lot_activate').split(' ', 1)[1]}", callback_data=f"{p}:{n.lots_restore}"),
        B(f"{l(n.lots_deactivate)} {_('ns_lot_deactivate').split(' ', 1)[1]}", callback_data=f"{p}:{n.lots_deactivate}"),
        B(f"{l(n.command)} {_('ns_cmd').split(' ', 1)[1]}", callback_data=f"{p}:{n.command}"),
        B(f"{l(n.bot_start)} {_('ns_bot_start').split(' ', 1)[1]}", callback_data=f"{p}:{n.bot_start}"),
        B(f"{l(n.other)} {_('ns_other').split(' ', 1)[0]}", callback_data=f"{p}:{n.other}")
    )
    kb.row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:system"))
    return kb


def announcements_settings(c: Cortex, chat_id: int) -> K:
    p = f"{CBT.SWITCH_TG_NOTIFICATIONS}:{chat_id}"
    n = NotificationTypes
    def l(nt): return '🔔' if c.telegram.is_notification_enabled(chat_id, nt) else '🔕'
    
    kb = K(row_width=2)
    kb.add(
        B(f"{l(n.announcement)} {_('an_an').split(' ', 1)[1]}", callback_data=f"{p}:{n.announcement}"),
        B(f"{l(n.ad)} {_('an_ad').split(' ', 1)[1]}", callback_data=f"{p}:{n.ad}")
    )
    return kb


def blacklist_settings(c: Cortex) -> K:
    p = f"{CBT.SWITCH}:BlockList"
    def l(s): return '🟢' if c.MAIN_CFG["BlockList"].getboolean(s) else '🔴'
    
    kb = K(row_width=1)
    kb.add(
        B(f"{l('blockDelivery')} {_('bl_autodelivery').split(' ', 1)[1]}", callback_data=f"{p}:blockDelivery"),
        B(f"{l('blockResponse')} {_('bl_autoresponse').split(' ', 1)[1]}", callback_data=f"{p}:blockResponse"),
        B(f"{l('blockNewMessageNotification')} {_('bl_new_msg_notifications').split(' ', 1)[1]}", callback_data=f"{p}:blockNewMessageNotification"),
        B(f"{l('blockNewOrderNotification')} {_('bl_new_order_notifications').split(' ', 1)[1]}", callback_data=f"{p}:blockNewOrderNotification"),
        B(f"{l('blockCommandNotification')} {_('bl_command_notifications').split(' ', 1)[1]}", callback_data=f"{p}:blockCommandNotification")
    )
    kb.row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:management"))
    return kb


def commands_list(c: Cortex, offset: int) -> K:
    kb = K()
    all_commands = c.RAW_AR_CFG.sections()
    commands_on_page = all_commands[offset: offset + MENU_CFG.AR_BTNS_AMOUNT]
    if not commands_on_page and offset != 0:
        offset = 0
        commands_on_page = all_commands[offset : offset + MENU_CFG.AR_BTNS_AMOUNT]

    if not commands_on_page and offset == 0:
        kb.add(B("🤖 Команд пока нет. Добавьте первую!", callback_data=CBT.ADD_CMD))
    else:
        for index, cmd_raw in enumerate(commands_on_page):
            cmd_display = cmd_raw.split("|")[0].strip()
            if "|" in cmd_raw: cmd_display += " | ..."
            kb.add(B(f"💬 {cmd_display}", callback_data=f"{CBT.EDIT_CMD}:{all_commands.index(cmd_raw)}:{offset}"))

    add_navigation_buttons(kb, offset, MENU_CFG.AR_BTNS_AMOUNT, len(commands_on_page), len(all_commands), CBT.CMD_LIST)
    
    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ar"),
        B(_("ar_add_command"), callback_data=CBT.ADD_CMD)
    )
    return kb


def edit_command(c: Cortex, command_index: int, offset: int) -> K:
    command_set = c.RAW_AR_CFG.sections()[command_index]
    notif_status = bool_to_text(c.RAW_AR_CFG[command_set].get('telegramNotification'), '🔔', '🔕')

    kb = K(row_width=2)
    kb.add(
        B(_("ar_edit_response"), callback_data=f"{CBT.EDIT_CMD_RESPONSE_TEXT}:{command_index}:{offset}"),
        B(_("ar_edit_notification"), callback_data=f"{CBT.EDIT_CMD_NOTIFICATION_TEXT}:{command_index}:{offset}")
    )
    kb.add(B(f"{_('ar_notification').split(' ', 1)[0]} {notif_status}", callback_data=f"{CBT.SWITCH_CMD_NOTIFICATION}:{command_index}:{offset}"))
    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.CMD_LIST}:{offset}"),
        B(_("gl_delete"), callback_data=f"{CBT.DEL_CMD}:{command_index}:{offset}")
    )
    return kb


def products_files_list(offset: int) -> K:
    kb = K()
    products_dir = "storage/products"
    if not os.path.exists(products_dir): os.makedirs(products_dir)
    all_files = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt")])
    files_on_page = all_files[offset:offset + MENU_CFG.PF_BTNS_AMOUNT]
    if not files_on_page and offset != 0:
        offset = 0
        files_on_page = all_files[offset:offset + MENU_CFG.PF_BTNS_AMOUNT]
        
    if not files_on_page and offset == 0:
        kb.add(B("📂 Файлов пока нет. Создайте первый!", callback_data=CBT.CREATE_PRODUCTS_FILE))
    else:
        for index, name in enumerate(files_on_page):
            try: amount = Utils.cortex_tools.count_products(os.path.join(products_dir, name))
            except Exception: amount = "⚠️" 
            kb.add(B(f"📄 {name} ({amount} {_('gl_pcs')})", callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{all_files.index(name)}:{offset}"))

    add_navigation_buttons(kb, offset, MENU_CFG.PF_BTNS_AMOUNT, len(files_on_page), len(all_files), CBT.PRODUCTS_FILES_LIST)

    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ad"),
        B(_("ad_create_goods_file"), callback_data=CBT.CREATE_PRODUCTS_FILE)
    )
    return kb


def products_file_edit(file_index: int, offset: int, confirmation: bool = False) -> K:
    kb = K()
    kb.add(
        B(_("gf_add_goods"), callback_data=f"{CBT.ADD_PRODUCTS_TO_FILE}:{file_index}:{file_index}:{offset}:0"),
        B(_("gf_download"), callback_data=f"download_products_file:{file_index}:{offset}")
    )
    if not confirmation:
        kb.row(B(_("gl_delete"), callback_data=f"del_products_file:{file_index}:{offset}"))
    else:
        kb.row(
            B(_("gl_no") + ", оставить", callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{file_index}:{offset}"),
            B(_("gl_yes") + ", удалить", callback_data=f"confirm_del_products_file:{file_index}:{offset}")
        )
    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.PRODUCTS_FILES_LIST}:{offset}"),
        B(_("gl_refresh"), callback_data=f"{CBT.EDIT_PRODUCTS_FILE}:{file_index}:{offset}")
    )
    return kb


def lots_list(c: Cortex, offset: int) -> K:
    kb = K()
    all_lots = c.AD_CFG.sections()
    lots_on_page = all_lots[offset:offset + MENU_CFG.AD_BTNS_AMOUNT]
    if not lots_on_page and offset != 0:
        offset = 0
        lots_on_page = all_lots[offset:offset + MENU_CFG.AD_BTNS_AMOUNT]

    if not lots_on_page and offset == 0:
        kb.add(B("🧾 Лотов с автовыдачей пока нет", callback_data=f"{CBT.FP_LOTS_LIST}:0"))
    else:
        for index, lot_name in enumerate(lots_on_page):
            kb.add(B(f"📦 {lot_name}", callback_data=f"{CBT.EDIT_AD_LOT}:{all_lots.index(lot_name)}:{offset}"))

    add_navigation_buttons(kb, offset, MENU_CFG.AD_BTNS_AMOUNT, len(lots_on_page), len(all_lots), CBT.AD_LOTS_LIST)
    
    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:ad"),
        B(_("ad_add_autodelivery"), callback_data=f"{CBT.FP_LOTS_LIST}:0")
    )
    return kb


def funpay_lots_list(c: Cortex, offset: int) -> K:
    kb = K()
    all_fp_lots = c.tg_profile.get_common_lots()
    lots_on_page = all_fp_lots[offset: offset + MENU_CFG.FP_LOTS_BTNS_AMOUNT]
    if not lots_on_page and offset != 0:
        offset = 0
        lots_on_page = all_fp_lots[offset:offset + MENU_CFG.FP_LOTS_BTNS_AMOUNT]
    
    if not lots_on_page and offset == 0:
        kb.add(B("🤷 Лотов на FunPay не найдено. Попробуйте обновить.", callback_data=f"update_funpay_lots:{offset}"))
    else:
        for lot_obj in lots_on_page:
            is_ad_on = lot_obj.title in c.AD_CFG.sections()
            prefix = "✅" if is_ad_on else "➕"
            display_text = f"{prefix} {lot_obj.description[:40]}" + ("..." if len(lot_obj.description) > 40 else "")
            kb.add(B(display_text, callback_data=f"{CBT.ADD_AD_TO_LOT}:{all_fp_lots.index(lot_obj)}:{offset}"))

    add_navigation_buttons(kb, offset, MENU_CFG.FP_LOTS_BTNS_AMOUNT, len(lots_on_page), len(all_fp_lots), CBT.FP_LOTS_LIST)
    
    kb.row(
        B(_("ad_to_ad"), callback_data=f"{CBT.CATEGORY}:ad"),
        B(_("fl_manual"), callback_data=f"{CBT.ADD_AD_TO_LOT_MANUALLY}:{offset}"),
        B(_("gl_refresh"), callback_data=f"update_funpay_lots:{offset}")
    )
    return kb


def edit_lot(c: Cortex, lot_index: int, offset: int) -> K:
    lot_name = c.AD_CFG.sections()[lot_index]
    lot_obj = c.AD_CFG[lot_name]
    file_name = lot_obj.get("productsFileName")
    
    p = {"ad": (c.MAIN_CFG["FunPay"].getboolean("autoDelivery"), "disable"),
         "md": (c.MAIN_CFG["FunPay"].getboolean("multiDelivery"), "disableMultiDelivery"),
         "ares": (c.MAIN_CFG["FunPay"].getboolean("autoRestore"), "disableAutoRestore"),
         "adis": (c.MAIN_CFG["FunPay"].getboolean("autoDisable"), "disableAutoDisable")}

    def status(key):
        global_on, local_option = p[key]
        if not global_on: return '⚪️'
        return '🔴' if lot_obj.getboolean(local_option, False) else '🟢'

    kb = K(row_width=2)
    kb.add(B(_("ea_edit_delivery_text"), callback_data=f"{CBT.EDIT_LOT_DELIVERY_TEXT}:{lot_index}:{offset}"))

    if file_name:
        products_dir = os.path.join(c.base_path, "storage/products")
        all_files = sorted([f for f in os.listdir(products_dir) if f.endswith(".txt") and os.path.isfile(os.path.join(products_dir, f))])
        if file_name in all_files:
            file_idx = all_files.index(file_name)
            kb.row(
                B(f"🔗 {file_name}", callback_data=f"{CBT.BIND_PRODUCTS_FILE}:{lot_index}:{offset}"),
                B(_("gf_add_goods"), callback_data=f"{CBT.ADD_PRODUCTS_TO_FILE}:{file_idx}:{lot_index}:{offset}:1")
            )
        else:
            kb.add(B(f"🔗 ⚠️ {file_name} (не найден)", callback_data=f"{CBT.BIND_PRODUCTS_FILE}:{lot_index}:{offset}"))
    else:
        kb.add(B(_("ea_link_goods_file"), callback_data=f"{CBT.BIND_PRODUCTS_FILE}:{lot_index}:{offset}"))
        
    kb.row(
        B(f"{_('ea_delivery').split(' ', 1)[0]} {status('ad')}", callback_data=f"{'switch_lot:disable' if p['ad'][0] else CBT.PARAM_DISABLED}:{lot_index}:{offset}"),
        B(f"{_('ea_multidelivery').split(' ', 1)[0]} {status('md')}", callback_data=f"{'switch_lot:disableMultiDelivery' if p['md'][0] else CBT.PARAM_DISABLED}:{lot_index}:{offset}")
    )
    kb.row(
        B(f"{_('ea_restore').split(' ', 1)[0]} {status('ares')}", callback_data=f"{'switch_lot:disableAutoRestore' if p['ares'][0] else CBT.PARAM_DISABLED}:{lot_index}:{offset}"),
        B(f"{_('ea_deactivate').split(' ', 1)[0]} {status('adis')}", callback_data=f"{'switch_lot:disableAutoDisable' if p['adis'][0] else CBT.PARAM_DISABLED}:{lot_index}:{offset}")
    )
    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.AD_LOTS_LIST}:{offset}"),
        B(_("ea_test"), callback_data=f"test_auto_delivery:{lot_index}:{offset}"),
        B(_("gl_delete"), callback_data=f"{CBT.DEL_AD_LOT}:{lot_index}:{offset}")
    )
    return kb


def new_order(order_id: str, username: str, node_id: int, confirmation: bool = False, no_refund: bool = False) -> K:
    kb = K()
    if not no_refund:
        if confirmation:
            kb.row(
                B(_("gl_no") + ", не возвращать", callback_data=f"{CBT.REFUND_CANCELLED}:{order_id}:{node_id}:{username}"),
                B(_("gl_yes") + ", вернуть", callback_data=f"{CBT.REFUND_CONFIRMED}:{order_id}:{node_id}:{username}")
            )
        else:
            kb.add(B(_("ord_refund"), callback_data=f"{CBT.REQUEST_REFUND}:{order_id}:{node_id}:{username}"))

    kb.row(
        B(_("ord_answer"), callback_data=f"{CBT.SEND_FP_MESSAGE}:{node_id}:{username}"),
        B(_("ord_templates"), callback_data=f"{CBT.TMPLT_LIST_ANS_MODE}:0:{node_id}:{username}:2:{order_id}:{int(no_refund)}")
    )
    kb.add(B(_("ord_open"), url=f"https://funpay.com/orders/{order_id}/"))
    return kb


def reply(node_id: int, username: str, again: bool = False, extend: bool = False) -> K:
    buttons = [
        B(_("msg_reply2") if again else _("msg_reply"), callback_data=f"{CBT.SEND_FP_MESSAGE}:{node_id}:{username}"),
        B(_("msg_templates"), callback_data=f"{CBT.TMPLT_LIST_ANS_MODE}:0:{node_id}:{username}:{int(again)}:{int(extend)}")
    ]
    if extend:
        buttons.append(B(_("msg_more"), callback_data=f"{CBT.EXTEND_CHAT}:{node_id}:{username}"))
    buttons.append(B(f"💬 FunPay: {username}", url=f"https://funpay.com/chat/?node={node_id}"))
    
    kb = K(row_width=2).add(*buttons)
    return kb


def templates_list(c: Cortex, offset: int) -> K:
    kb = K()
    all_templates = c.telegram.answer_templates
    templates_on_page = all_templates[offset : offset + MENU_CFG.TMPLT_BTNS_AMOUNT]
    if not templates_on_page and offset != 0:
        offset = 0
        templates_on_page = all_templates[offset : offset + MENU_CFG.TMPLT_BTNS_AMOUNT]

    if not templates_on_page and offset == 0:
        kb.add(B("📝 Шаблонов пока нет. Добавьте первый!", callback_data=f"{CBT.ADD_TMPLT}:{offset}"))
    else:
        for tmplt_text in templates_on_page:
            display_text = tmplt_text[:30] + ("..." if len(tmplt_text) > 30 else "")
            kb.add(B(f"📄 {display_text}", callback_data=f"{CBT.EDIT_TMPLT}:{all_templates.index(tmplt_text)}:{offset}"))
            
    add_navigation_buttons(kb, offset, MENU_CFG.TMPLT_BTNS_AMOUNT, len(templates_on_page), len(all_templates), CBT.TMPLT_LIST)

    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:management"),
        B(_("tmplt_add"), callback_data=f"{CBT.ADD_TMPLT}:{offset}")
    )
    return kb


def edit_template(c: Cortex, template_index: int, offset: int) -> K:
    kb = K(row_width=2)
    kb.add(
        B(_("gl_back"), callback_data=f"{CBT.TMPLT_LIST}:{offset}"),
        B(_("gl_delete"), callback_data=f"{CBT.DEL_TMPLT}:{template_index}:{offset}")
    )
    return kb


def templates_list_ans_mode(c: Cortex, offset: int, node_id: int, username: str, prev_page: int, extra: list | None = None) -> K:
    kb = K()
    all_templates = c.telegram.answer_templates
    templates_on_page = all_templates[offset: offset + MENU_CFG.TMPLT_BTNS_AMOUNT]
    extra_str = (":" + ":".join(str(i) for i in extra)) if extra else ""

    if not templates_on_page and offset != 0:
        offset = 0
        templates_on_page = all_templates[offset: offset + MENU_CFG.TMPLT_BTNS_AMOUNT]

    if not templates_on_page and offset == 0:
        kb.add(B("📝 Шаблонов для ответа нет", callback_data=CBT.EMPTY))
    else:
        for tmplt_text in templates_on_page:
            display_text = (tmplt_text.replace("$username", username))[:30] + ("..." if len(tmplt_text) > 30 else "")
            kb.add(B(f"💬 {display_text}", callback_data=f"{CBT.SEND_TMPLT}:{all_templates.index(tmplt_text)}:{node_id}:{username}:{prev_page}{extra_str}"))

    extra_nav = [node_id, username, prev_page]
    if extra: extra_nav.extend(extra)
    add_navigation_buttons(kb, offset, MENU_CFG.TMPLT_BTNS_AMOUNT, len(templates_on_page), len(all_templates), CBT.TMPLT_LIST_ANS_MODE, extra_nav)

    back_callbacks = {0: f"{CBT.BACK_TO_REPLY_KB}:{node_id}:{username}:0{extra_str}",
                      1: f"{CBT.BACK_TO_REPLY_KB}:{node_id}:{username}:1{extra_str}",
                      2: f"{CBT.BACK_TO_ORDER_KB}:{node_id}:{username}{extra_str}"}
    kb.add(B(_("gl_back"), callback_data=back_callbacks.get(prev_page, CBT.MAIN)))
    return kb


def plugins_list(c: Cortex, offset: int) -> K:
    kb = K()
    all_features = sorted(c.features.values(), key=lambda f: (not f.is_available, f.name))
    features_on_page = all_features[offset : offset + MENU_CFG.PLUGINS_BTNS_AMOUNT]
    
    if not features_on_page and offset != 0:
        offset = 0
        features_on_page = all_features[offset : offset + MENU_CFG.PLUGINS_BTNS_AMOUNT]

    if not features_on_page and offset == 0:
        kb.add(B("🧩 Нет функций", callback_data=CBT.EMPTY))
    else:
        for feature in features_on_page:
            if feature.is_available:
                status_icon = "🟢" if feature.is_active else "🔴"
                kb.add(B(f"{status_icon} {feature.name}", callback_data=f"{CBT.EDIT_PLUGIN}:{feature.uid}:{offset}"))
            else:
                kb.add(B(f"🔒 {feature.name}", callback_data=f"{CBT.EDIT_PLUGIN}:{feature.uid}:{offset}"))

    add_navigation_buttons(kb, offset, MENU_CFG.PLUGINS_BTNS_AMOUNT, len(features_on_page), len(all_features), CBT.PLUGINS_LIST)
    
    kb.row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:system"))
    return kb


def edit_plugin(c: Cortex, uid: str, offset: int) -> K:
    kb = K()
    
    if uid in c.features:
        feature = c.features[uid]
        
        if feature.is_available:
            toggle_text = "🛑 Выключить" if feature.is_active else "🚀 Включить"
            kb.add(B(toggle_text, callback_data=f"{CBT.TOGGLE_PLUGIN}:{feature.uid}:{offset}"))

            if feature.is_active:
                settings_kb = feature.get_settings_menu()
                if settings_kb:
                    kb.add(B("⚙️ Открыть настройки", callback_data=f"{feature.uid}:menu"))
                 
        else:
            price = "50₽" if feature.required_access_level == 2 else "150₽" if feature.required_access_level == 3 else "???"
            buy_url = f"https://funpaybot.ru/plugins/{feature.uid}"
            kb.add(B(f"💎 Купить навсегда ({price})", url=buy_url))
            kb.add(B("⬆️ Или повысить тариф", url="https://funpaybot.ru/billing"))

        kb.add(B(_("gl_back"), callback_data=f"{CBT.PLUGINS_LIST}:{offset}"))
        return kb

    if uid in c.plugins:
        plugin = c.plugins[uid]
        if plugin.is_broken:
            kb.add(B(_("gl_back"), callback_data=f"{CBT.PLUGINS_LIST}:{offset}"))
            return kb

        active_text = _("pl_deactivate") if plugin.enabled else _("pl_activate")
        kb.add(B(active_text, callback_data=f"{CBT.TOGGLE_PLUGIN}:{uid}:{offset}"))
        
        if plugin.commands:
            kb.add(B(_("pl_commands"), callback_data=f"{CBT.PLUGIN_COMMANDS}:{uid}:{offset}"))
        if plugin.settings_page:
            kb.add(B(_("pl_settings"), callback_data=f"{CBT.PLUGIN_SETTINGS}:{uid}:{offset}"))

        kb.add(B(_("gl_back"), callback_data=f"{CBT.PLUGINS_LIST}:{offset}"))
        return kb
        
    kb.add(B(_("gl_back"), callback_data=f"{CBT.PLUGINS_LIST}:{offset}"))
    return kb


def profile_menu() -> K:
    kb = K(row_width=2)
    kb.add(
        B(_("gl_refresh"), callback_data=CBT.UPDATE_PROFILE),
        B("📊 Статистика", callback_data=f"{CBT.STATS_MENU}:main")
    )
    return kb


def statistics_menu(c: Cortex) -> K:
    kb = K(row_width=2)
    period = c.MAIN_CFG["Statistics"].getint("analysis_period", 30)
    
    kb.add(
        B("☀️ День", callback_data=f"{CBT.STATS_MENU}:day"),
        B("📅 Неделя", callback_data=f"{CBT.STATS_MENU}:week"),
        B("🗓️ Месяц", callback_data=f"{CBT.STATS_MENU}:month"),
        B("♾️ За все время", callback_data=f"{CBT.STATS_MENU}:all")
    )
    kb.row(
        B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:management"),
        B(f"⚙️ Период: {period} дн.", callback_data=f"{CBT.STATS_CONFIG_MENU}:main")
    )
    return kb


def statistics_config_menu(c: Cortex) -> K:
    kb = K(row_width=1)
    report_interval = c.MAIN_CFG["Statistics"].getint("report_interval", 0)
    interval_text = f"Каждые {report_interval} ч." if report_interval > 0 else "Выкл."

    kb.add(
        B("🔢 Изменить период анализа", callback_data=f"{CBT.STATS_CONFIG_MENU}:set_period"),
        B(f"⏰ Авто-отчет: {interval_text}", callback_data=f"{CBT.STATS_CONFIG_MENU}:set_interval"),
        B(_("gl_back"), callback_data=f"{CBT.STATS_MENU}:main")
    )
    return kb

def LINKS_KB(language: None | str = None) -> K:
    kb = K(row_width=1)
    kb.add(B("🌐 Наш сайт - funpaybot.ru", url="https://funpaybot.ru"))
    kb.add(B("📢 Telegram-канал @RobotFunPay", url="https://t.me/RobotFunPay"))
    return kb
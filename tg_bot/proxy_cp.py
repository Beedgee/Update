from __future__ import annotations
import time
import telebot.apihelper
import logging
import os
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from cortex import Cortex

from tg_bot import utils, static_keyboards as skb, keyboards as kb, CBT
from Utils.cortex_tools import validate_proxy, cache_proxy_dict, check_proxy
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, CallbackQuery, Message
from locales.localizer import Localizer

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def init_proxy_cp(cortex_instance: Cortex, *args):
    tg = cortex_instance.telegram
    bot = tg.bot
    if not hasattr(tg, 'pr_dict'):
        tg.pr_dict = {}

    def check_one_proxy_thread_target(proxy_str: str):
        try:
            proxy_for_check = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}
            tg.pr_dict[proxy_str] = check_proxy(proxy_for_check)
        except Exception as e:
            logger.warning(f"Ошибка при проверке прокси {proxy_str} в потоке: {e}")
            tg.pr_dict[proxy_str] = False

    def check_all_proxies_periodically():
        if cortex_instance.MAIN_CFG["Proxy"].getboolean("enable") and cortex_instance.MAIN_CFG["Proxy"].getboolean("check"):
            logger.info("Запущен периодический чекер прокси.")
            while True:
                proxies_to_check = list(cortex_instance.proxy_dict.values())
                if proxies_to_check:
                    logger.info(f"Начинаю плановую проверку {len(proxies_to_check)} прокси...")
                    for proxy_item_str in proxies_to_check:
                        check_one_proxy_thread_target(proxy_item_str)
                        time.sleep(0.1) 
                    logger.info("Проверка прокси завершена.")
                
                check_interval = cortex_instance.MAIN_CFG["Proxy"].getint("checkInterval", 3600)
                time.sleep(check_interval)
        else:
            logger.info("Периодическая проверка прокси отключена.")
    
    if not getattr(init_proxy_cp, "_checker_thread_started", False):
        init_proxy_cp._checker_thread_started = True
        cortex_instance.executor.submit(check_all_proxies_periodically)


    def open_proxy_list(c: CallbackQuery):
        offset = int(c.data.split(":")[1])
        is_enabled = cortex_instance.MAIN_CFG["Proxy"].getboolean("enable")
        is_check_enabled = cortex_instance.MAIN_CFG["Proxy"].getboolean("check")
        proxy_enabled_text = _("proxy_status_enabled") if is_enabled else _("proxy_status_disabled")
        check_enabled_text = _("proxy_check_status_enabled") if is_check_enabled else _("proxy_check_status_disabled")
        
        current_proxy_display = "<i>(" + _("proxy_not_used_currently") + ")</i>"
        if is_enabled:
            current_proxy_str = utils.get_current_proxy_str(cortex_instance.MAIN_CFG['Proxy'])
            current_proxy_display = f"<code>{utils.mask_proxy_string(current_proxy_str)}</code>" if current_proxy_str else "<i>(" + _("proxy_not_selected") + ")</i>"

        interval_min = cortex_instance.MAIN_CFG["Proxy"].getint("checkInterval", 3600) // 60
        status_text = f"""
🚦 <b>{_('proxy_global_status_header')}</b>
  • {_('proxy_module_status_label')} {proxy_enabled_text}
  • {_('proxy_health_check_label')} {check_enabled_text}
  • {_('proxy_check_interval_info', interval=interval_min)}

🔌 <b>{_('proxy_current_in_use_label')}</b> {current_proxy_display}
"""
        try:
            bot.edit_message_text(f'{_("desc_proxy")}\n{status_text}', c.message.chat.id, c.message.id,
                                  reply_markup=kb.proxy(cortex_instance, offset, tg.pr_dict))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in e.description:
                raise e
                
        bot.answer_callback_query(c.id)

    def act_add_proxy(c: CallbackQuery):
        offset = int(c.data.split(":")[-1])
        result = bot.send_message(c.message.chat.id, _("act_proxy"), reply_markup=skb.CLEAR_STATE_BTN())
        tg.set_state(result.chat.id, result.id, c.from_user.id, CBT.ADD_PROXY, {"offset": offset})
        bot.answer_callback_query(c.id)

    def add_proxy(m: Message):
        offset = tg.get_state(m.chat.id, m.from_user.id)["data"]["offset"]
        reply_kb = K().add(B(_("gl_back"), callback_data=f"{CBT.PROXY}:{offset}"))
        tg.clear_state(m.chat.id, m.from_user.id, True)
        
        try:
            login, password, ip, port = validate_proxy(m.text.strip())
            proxy_str = f"{f'{login}:{password}@' if login and password else ''}{ip}:{port}"
            
            if proxy_str in cortex_instance.proxy_dict.values():
                bot.send_message(m.chat.id, _("proxy_already_exists", proxy_str=utils.mask_proxy_string(proxy_str)), reply_markup=reply_kb)
                return

            max_id = max(cortex_instance.proxy_dict.keys()) if cortex_instance.proxy_dict else -1
            cortex_instance.proxy_dict[max_id + 1] = proxy_str
            cache_proxy_dict(cortex_instance.proxy_dict, cortex_instance.base_path)
            
            bot.send_message(m.chat.id, _("proxy_added", proxy_str=utils.mask_proxy_string(proxy_str)), reply_markup=reply_kb)
            
            if cortex_instance.MAIN_CFG["Proxy"].getboolean("enable") and cortex_instance.MAIN_CFG["Proxy"].getboolean("check"):
                cortex_instance.executor.submit(check_one_proxy_thread_target, proxy_str)
                
        except ValueError:
            bot.send_message(m.chat.id, _("proxy_format"), reply_markup=reply_kb)
        except Exception:
            logger.error(f"Ошибка при добавлении прокси: {m.text.strip()}", exc_info=True)
            bot.send_message(m.chat.id, _("proxy_adding_error"), reply_markup=reply_kb)

    def choose_proxy(c: CallbackQuery):
        bot.answer_callback_query(c.id)
        bot.edit_message_text(f'{_("desc_proxy")}\n🔄 Проверяю и применяю прокси...', c.message.chat.id, c.message.id)

        def _threaded_choose():
            __, offset_str, proxy_id_str = c.data.split(":")
            offset = int(offset_str)
            proxy_id = int(proxy_id_str)
            
            proxy_str = cortex_instance.proxy_dict.get(proxy_id)
            if not proxy_str:
                bot.answer_callback_query(c.id, _("proxy_select_error_not_found"), show_alert=True)
                c.data = f"{CBT.PROXY}:{offset}"
                open_proxy_list(c)
                return

            try:
                proxy_for_check = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}
                is_working = check_proxy(proxy_for_check)
                tg.pr_dict[proxy_str] = is_working

                if not is_working:
                    bot.answer_callback_query(c.id, f"❌ Прокси {utils.mask_proxy_string(proxy_str)} не работает.", show_alert=True)
                    c.data = f"{CBT.PROXY}:{offset}"
                    open_proxy_list(c)
                    return

                login, password, ip, port = validate_proxy(proxy_str)
                cortex_instance.MAIN_CFG["Proxy"]["enable"] = "1"
                cortex_instance.MAIN_CFG["Proxy"].update({"ip": ip, "port": str(port), "login": login, "password": password})
                
                cortex_instance.save_config(cortex_instance.MAIN_CFG, os.path.join(cortex_instance.base_path, "configs/_main.cfg"))
                
                cortex_instance.account.proxy = proxy_for_check
                
                bot.answer_callback_query(c.id, _("proxy_selected_and_applied", proxy_str=utils.mask_proxy_string(proxy_str)), show_alert=True)
                
            except ValueError:
                bot.answer_callback_query(c.id, _("proxy_select_error_invalid_format"), show_alert=True)
            except Exception as e:
                logger.error(f"Непредвиденная ошибка при выборе прокси {proxy_str}: {e}", exc_info=True)
                bot.answer_callback_query(c.id, _("gl_error"), show_alert=True)
            
            c.data = f"{CBT.PROXY}:{offset}"
            open_proxy_list(c)

        cortex_instance.executor.submit(_threaded_choose)

    def delete_proxy(c: CallbackQuery):
        __, offset_str, proxy_id_str = c.data.split(":")
        offset = int(offset_str)
        proxy_id = int(proxy_id_str)
        
        if proxy_id in cortex_instance.proxy_dict:
            proxy_to_delete_str = cortex_instance.proxy_dict[proxy_id]
            current_proxy_str = utils.get_current_proxy_str(cortex_instance.MAIN_CFG["Proxy"])

            if cortex_instance.MAIN_CFG["Proxy"].getboolean("enable") and proxy_to_delete_str == current_proxy_str:
                for key in ("ip", "port", "login", "password"):
                    cortex_instance.MAIN_CFG["Proxy"][key] = ""
                cortex_instance.MAIN_CFG["Proxy"]["enable"] = "0"
                
                cortex_instance.account.proxy = None
                cortex_instance.funpay_connection_ok = False
                cortex_instance._enter_degraded_mode(
                    "Активный прокси был удален пользователем.",
                    "🛑 <b>Прокси удален!</b>\nРабота остановлена для защиты IP. Отправьте новый прокси в чат."
                )

                tg.set_state(c.message.chat.id, c.message.id, c.from_user.id, "SETUP_PROXY_MANDATORY")
                
                def _threaded_save():
                    cortex_instance.save_config(cortex_instance.MAIN_CFG, os.path.join(cortex_instance.base_path, "configs/_main.cfg"))
                cortex_instance.executor.submit(_threaded_save)
                
                bot.answer_callback_query(c.id, "✅ Прокси удален. Работа остановлена.", show_alert=True)
            else:
                 bot.answer_callback_query(c.id, _("proxy_deleted_successfully", proxy_str=utils.mask_proxy_string(proxy_to_delete_str)), show_alert=True)

            del cortex_instance.proxy_dict[proxy_id]
            cache_proxy_dict(cortex_instance.proxy_dict, cortex_instance.base_path)
            if proxy_to_delete_str in tg.pr_dict:
                del tg.pr_dict[proxy_to_delete_str]
            
            logger.info(f"Прокси {utils.mask_proxy_string(proxy_to_delete_str)} удален пользователем {c.from_user.username}.")
        else:
            bot.answer_callback_query(c.id, _("proxy_delete_error_not_found"), show_alert=True)
        
        c.data = f"{CBT.PROXY}:{offset}"
        open_proxy_list(c)

    tg.cbq_handler(open_proxy_list, func=lambda c: c.data.startswith(f"{CBT.PROXY}:"))
    tg.cbq_handler(act_add_proxy, func=lambda c: c.data.startswith(f"{CBT.ADD_PROXY}:"))
    tg.cbq_handler(choose_proxy, func=lambda c: c.data.startswith(f"{CBT.CHOOSE_PROXY}:"))
    tg.cbq_handler(delete_proxy, func=lambda c: c.data.startswith(f"{CBT.DELETE_PROXY}:"))
    tg.msg_handler(add_proxy, func=lambda m: tg.check_state(m.chat.id, m.from_user.id, CBT.ADD_PROXY))


BIND_TO_PRE_INIT = [init_proxy_cp]
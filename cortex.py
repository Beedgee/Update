from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Dict, Type, Any
from FunPayAPI import types, exceptions as FunPayExceptions
from FunPayAPI.common.enums import SubCategoryTypes

if TYPE_CHECKING:
    from configparser import ConfigParser
    from core.feature import BaseFeature

from tg_bot import auto_response_cp, config_loader_cp, auto_delivery_cp, templates_cp, \
    file_uploader, authorized_users_cp, proxy_cp, plugins_cp, default_cp, utils as tg_utils

from types import ModuleType
import Utils.exceptions
import Utils.config_loader as cfg_loader
from uuid import UUID
import importlib.util
import configparser
import requests
import io
import itertools
import datetime
import logging
import random
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor
import time
import sys
import os
import FunPayAPI
import handlers
import announcements
from tg_bot import statistics_cp
import json
from locales.localizer import Localizer
from FunPayAPI import utils as fp_utils
from Utils import cortex_tools
import tg_bot.bot
import types as py_types
import pkgutil
import inspect
from core.feature import BaseFeature
import collections

logger = logging.getLogger("FPC")
localizer = Localizer()
_ = localizer.translate

def get_cortex() -> None | Cortex:
    if hasattr(Cortex, "instance"):
        return getattr(Cortex, "instance")

class Cortex(object):
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "instance"):
            cls.instance = super(Cortex, cls).__new__(cls)
        return getattr(cls, "instance")

    def __init__(self, main_config: ConfigParser, raw_auto_response_config: ConfigParser, version: str, base_path: str, is_hosting_env: bool):
        self.funpay_connection_ok = False
        self.is_in_degraded_mode = False
        self.degraded_mode_start_time: float | None = None
        self.IS_HOSTING_ENV = is_hosting_env
        
        self.HOSTING_USER_ID = os.getenv("FPCORTEX_USER_ID")
        if self.HOSTING_USER_ID:
            try:
                self.HOSTING_USER_ID = int(self.HOSTING_USER_ID)
            except ValueError:
                logger.error("FPCORTEX_USER_ID is not an integer.")
                self.HOSTING_USER_ID = None
        
        self.next_retry_timestamp = 0
        self.AR_CFG_LOAD_ERROR = False
        self.AD_CFG_LOAD_ERROR = False

        self.VERSION = version
        self.base_path = base_path
        self.instance_id = random.randint(0, 999999999)
        self.delivery_tests = {}

        self.MAIN_CFG = main_config
        self.AD_CFG: ConfigParser | None = None
        self.AR_CFG: ConfigParser | None = None
        self.RAW_AR_CFG = raw_auto_response_config
        
        self.executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix='CortexWorker')

        if self.IS_HOSTING_ENV:
            self.hosting_url = os.getenv("FPCORTEX_INTERNAL_BACKEND_URL", "http://backend:8000")
            self.hosting_token = os.getenv("FPCORTEX_BOT_TOKEN")
        else:
            self.hosting_url = self.MAIN_CFG["CortexHosting"].get("url")
            self.hosting_token = self.MAIN_CFG["CortexHosting"].get("token")

        self.is_subscription_active = False
        self.access_level = 0
        self.purchased_features: list[str] = []

        self.last_successful_check = 0
        self.grace_period_seconds = 3 * 3600
        self.backend_unreachable = False
        self.backend_unreachable_notified = False
        self.subscription_cache_path = os.path.join(self.base_path, "storage/cache/subscription.json")
        self.subscription_check_lock = Lock()
        
        self.save_json_setting = self._default_save_json_setting

        self.proxy = {}
        self.proxy_dict = cortex_tools.load_proxy_dict(self.base_path)

        unique_proxies = set()
        keys_to_delete = []
        for pid, pstr in self.proxy_dict.items():
            clean_pstr = pstr.strip()
            if clean_pstr in unique_proxies:
                keys_to_delete.append(pid)
            else:
                unique_proxies.add(clean_pstr)
        
        if keys_to_delete:
            for k in keys_to_delete:
                del self.proxy_dict[k]
            cortex_tools.cache_proxy_dict(self.proxy_dict, self.base_path)
            logger.info(f"Removed {len(keys_to_delete)} duplicate proxies.")
        
        if self.MAIN_CFG["Proxy"]["ip"] and self.MAIN_CFG["Proxy"]["port"]:
            if self.MAIN_CFG["Proxy"].getboolean("enable"):
                logger.info(_("crd_proxy_detected"))
                ip, port = self.MAIN_CFG["Proxy"]["ip"], self.MAIN_CFG["Proxy"]["port"]
                login, password = self.MAIN_CFG["Proxy"]["login"], self.MAIN_CFG["Proxy"]["password"]
                proxy_str = f"{f'{login}:{password}@' if login and password else ''}{ip}:{port}"
                self.proxy = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}
                
                if proxy_str not in self.proxy_dict.values():
                    max_id = max(self.proxy_dict.keys(), default=-1)
                    self.proxy_dict[max_id + 1] = proxy_str
                    cortex_tools.cache_proxy_dict(self.proxy_dict, self.base_path)
            else:
                logger.warning("Proxy detected but disabled.")
                self.proxy = {}
        else:
            self.proxy = {}
        
        g_key = self.MAIN_CFG["FunPay"]["golden_key"] or ""
        
        self.account = FunPayAPI.Account(g_key,
                                         self.MAIN_CFG["FunPay"]["user_agent"],
                                         proxy=self.proxy,
                                         locale=self.MAIN_CFG["FunPay"].get("locale", "ru"))
        self.runner: FunPayAPI.Runner | None = None
        self.telegram: tg_bot.bot.TGBot | None = None
        self.running = False
        self.run_id = 0
        self.start_time = int(time.time())
        self.balance: FunPayAPI.types.Balance | None = None
        self.raise_time = {}
        self.raised_time = {}
        self.__exchange_rates = {}
        
        self.profile: FunPayAPI.types.UserProfile | None = None
        self.profile_cache_time = 0
        self.PROFILE_CACHE_SECONDS = 120
        
        self.order_cache = {}
        self.ORDER_CACHE_TTL = 3600
        
        self.tg_profile: FunPayAPI.types.UserProfile | None = None
        self.last_tg_profile_update = datetime.datetime.now()
        self.curr_profile: FunPayAPI.types.UserProfile | None = None
        self.curr_profile_last_tag: str | None = None
        self.profile_last_tag: str | None = None
        self.last_state_change_tag: str | None = None
        self.blacklist = []
        self.old_users = {}
        
        self.sales_history = []
        self.withdrawal_forecast = {}
        
        self.greeting_lock = Lock()

        self.pre_init_handlers = []
        self.post_init_handlers = []
        self.pre_start_handlers = []
        self.post_start_handlers = []
        self.pre_stop_handlers = []
        self.post_stop_handlers = []
        self.init_message_handlers = []
        self.messages_list_changed_handlers = []
        self.last_chat_message_changed_handlers = []
        self.new_message_handlers = []
        self.init_order_handlers = []
        self.orders_list_changed_handlers = []
        self.new_order_handlers = []
        self.order_status_changed_handlers = []
        self.pre_delivery_handlers = []
        self.post_delivery_handlers = []
        self.pre_lots_raise_handlers = []
        self.post_lots_raise_handlers = []
        
        self.handler_bind_var_names = {
            "BIND_TO_PRE_INIT": self.pre_init_handlers, "BIND_TO_POST_INIT": self.post_init_handlers,
            "BIND_TO_PRE_START": self.pre_start_handlers, "BIND_TO_POST_START": self.post_start_handlers,
            "BIND_TO_PRE_STOP": self.pre_stop_handlers, "BIND_TO_POST_STOP": self.post_stop_handlers,
            "BIND_TO_INIT_MESSAGE": self.init_message_handlers,
            "BIND_TO_MESSAGES_LIST_CHANGED": self.messages_list_changed_handlers,
            "BIND_TO_LAST_CHAT_MESSAGE_CHANGED": self.last_chat_message_changed_handlers,
            "BIND_TO_NEW_MESSAGE": self.new_message_handlers, "BIND_TO_INIT_ORDER": self.init_order_handlers,
            "BIND_TO_NEW_ORDER": self.new_order_handlers,
            "BIND_TO_ORDERS_LIST_CHANGED": self.orders_list_changed_handlers,
            "BIND_TO_ORDER_STATUS_CHANGED": self.order_status_changed_handlers,
            "BIND_TO_PRE_DELIVERY": self.pre_delivery_handlers, "BIND_TO_POST_DELIVERY": self.post_delivery_handlers,
            "BIND_TO_PRE_LOTS_RAISE": self.pre_lots_raise_handlers, "BIND_TO_POST_LOTS_RAISE": self.post_lots_raise_handlers,
        }
        
        self.features: Dict[str, BaseFeature] = {}
        
        self.allowed_features: list[str] = []

        self.processed_message_ids = collections.deque(maxlen=2000)
        
        self.watchdog_enabled = True

    def _sync_settings_from_backend(self):
        if not self.hosting_url or not self.hosting_token:
            logger.info("Hosting not configured. Working locally.")
            return

        if not self.HOSTING_USER_ID:
            logger.warning("Hosting mode active but FPCORTEX_USER_ID not found.")
            return

        logger.info(f"Syncing settings with server (User ID: {self.HOSTING_USER_ID})...")
        
        headers = {"X-Bot-Token": self.hosting_token}
        params = {"user_id": self.HOSTING_USER_ID}

        config_files = ["_main.cfg", "auto_response.cfg", "auto_delivery.cfg"]
        for filename in config_files:
            try:
                url = f"{self.hosting_url}/api/bot/settings/config/{filename}"
                response = requests.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code == 200:
                    file_path = os.path.join(self.base_path, "configs", filename)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(response.text)
                    logger.info(f"Config '{filename}' synced.")
                else:
                    logger.warning(f"Backend returned {response.status_code} for '{filename}': {response.text}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to sync '{filename}': {e}. Using local version.")
            except Exception as e:
                logger.error(f"Unexpected error syncing '{filename}': {e}")

        json_settings = ["blacklist", "templates", "notifications"]
        for setting_name in json_settings:
            try:
                url = f"{self.hosting_url}/api/bot/settings/json/{setting_name}"
                response = requests.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if setting_name == "blacklist":
                        cortex_tools.cache_blacklist(data, self.base_path)
                    elif setting_name == "templates":
                        templates_path = os.path.join(self.base_path, "storage/cache/answer_templates.json")
                        with open(templates_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
                    elif setting_name == "notifications":
                        notif_path = os.path.join(self.base_path, "storage/cache/notifications.json")
                        with open(notif_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
                            
                    logger.info(f"Setting '{setting_name}' synced.")
                else:
                    logger.warning(f"Backend returned {response.status_code} for '{setting_name}'")

            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to sync '{setting_name}': {e}. Using local version.")
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Unexpected error syncing '{setting_name}': {e}")

    def _default_save_json_setting(self, setting_name: str, data: dict | list):
        pass

    def load_subscription_cache(self):
        if not os.path.exists(self.subscription_cache_path):
            return
        try:
            with open(self.subscription_cache_path, 'r') as f:
                cache = json.load(f)
            
            if time.time() - cache.get("last_successful_check", 0) < 24 * 3600:
                self.is_subscription_active = cache.get("is_active", False)
                self.access_level = cache.get("access_level", 0)
                self.purchased_features = cache.get("purchased_features", [])
                self.last_successful_check = cache.get("last_successful_check", 0)
                logger.info(f"Loaded sub cache: Active={self.is_subscription_active}, Level={self.access_level}, Features={len(self.purchased_features)}")
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            logger.warning(f"Failed to load sub cache: {e}")

    def save_subscription_cache(self):
        try:
            with open(self.subscription_cache_path, 'w') as f:
                json.dump({
                    "is_active": self.is_subscription_active,
                    "access_level": self.access_level,
                    "purchased_features": self.purchased_features,
                    "last_successful_check": self.last_successful_check
                }, f)
        except IOError as e:
            logger.error(f"Failed to save sub cache: {e}")

    def check_subscription_status(self):
        if not self.hosting_url:
            self.is_subscription_active = True
            self.access_level = 99
            logger.info("Local mode: Max access level (99).")
            return
        
        with self.subscription_check_lock:
            try:
                headers = {"X-Bot-Token": self.hosting_token} if self.hosting_token else {}
                payload = {"user_id": self.HOSTING_USER_ID} if self.HOSTING_USER_ID else {"golden_key": self.account.golden_key}
                
                response = requests.post(
                    f"{self.hosting_url}/api/bot/check-access",
                    json=payload,
                    headers=headers, timeout=15
                )
                response.raise_for_status()
                data = response.json()
                
                is_now_active = data.get("is_active", False)
                new_access_level = data.get("access_level", 0)
                new_owned_features = data.get("owned_features", [])
                
                if self.access_level != new_access_level or set(self.purchased_features) != set(new_owned_features):
                    logger.info(f"Access changed. Level: {new_access_level}, Features: {len(new_owned_features)}")
                    self.access_level = new_access_level
                    self.purchased_features = new_owned_features
                    self._refresh_features_state()

                if self.is_subscription_active and not is_now_active:
                    logger.critical("Subscription expired or revoked. Shutting down.")
                    if self.telegram:
                        try:
                            self.telegram.send_notification("⚠️ Subscription expired! Shutting down.", notification_type=tg_utils.NotificationTypes.critical)
                            time.sleep(3)
                        except Exception as e:
                            logger.error(f"Failed to send final notification: {e}")
                    os._exit(0)

                self.is_subscription_active = is_now_active
                self.last_successful_check = time.time()
                self.save_subscription_cache()
                
                if self.backend_unreachable:
                    logger.info("Connection to server restored.")
                    if self.telegram and self.backend_unreachable_notified:
                        self.telegram.send_notification("✅ Connection to server restored.", notification_type=tg_utils.NotificationTypes.critical)
                    self.backend_unreachable = False
                    self.backend_unreachable_notified = False

            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to check subscription: {e}")
                self.backend_unreachable = True

                if time.time() - self.last_successful_check > self.grace_period_seconds:
                    if self.is_subscription_active:
                        logger.critical("Grace period expired. Server unreachable. Pausing.")
                        if self.telegram and not self.backend_unreachable_notified:
                             self.telegram.send_notification("⚠️ <b>Critical:</b> Server unreachable > 3 hours. Pausing.", notification_type=tg_utils.NotificationTypes.critical)
                             self.backend_unreachable_notified = True
                    self.is_subscription_active = False
                else:
                    remaining_grace = self.grace_period_seconds - (time.time() - self.last_successful_check)
                    logger.warning(f"Using cached subscription. Grace period left: {cortex_tools.time_to_str(int(remaining_grace))}.")
                    if self.telegram and not self.backend_unreachable_notified:
                        self.telegram.send_notification(f"⚠️ Server unreachable. Continuing in offline mode for <b>{cortex_tools.time_to_str(int(remaining_grace))}</b>.", notification_type=tg_utils.NotificationTypes.critical)
                        self.backend_unreachable_notified = True

    def subscription_check_loop(self):
        if not self.hosting_url: return
        logger.info("Subscription check loop started.")
        while self.running:
            self.check_subscription_status()
            time.sleep(600)

    def is_proxy_configured(self) -> bool:
        p = self.MAIN_CFG["Proxy"]
        return p.getboolean("enable") and bool(p["ip"]) and bool(p["port"])

    def _wait_for_funpay_connection(self):
        while True:
            if self.degraded_mode_start_time and (time.time() - self.degraded_mode_start_time > 10800):
                logger.critical("Shutdown due to inactivity (3 hours in degraded mode).")
                if self.telegram:
                    try:
                        self.telegram.send_notification(
                            "💤 <b>Бот отключается</b>\n\n"
                            "Бот находился в режиме ожидания настройки более 3 часов.\n"
                            "Чтобы включить его снова, зайдите в панель управления: https://funpaybot.ru/dashboard", 
                            notification_type=tg_utils.NotificationTypes.critical
                        )
                        time.sleep(3) 
                    except Exception: pass
                os._exit(0)

            if not self.is_proxy_configured():
                self._enter_degraded_mode(
                    "PROXY NOT CONFIGURED! Requests blocked.",
                    "🚫 <b>Работа остановлена!</b>\n\n"
                    "Для безопасности VDS работа без прокси <b>запрещена</b>.\n"
                    "Пожалуйста, отправьте новый прокси (ip:port или login:pass@ip:port) прямо сейчас."
                )
                
                if self.telegram and self.telegram.authorized_users:
                    for user_id in self.telegram.authorized_users:
                        state = self.telegram.get_state(user_id, user_id)
                        if not state or state.get("state") != "SETUP_PROXY_MANDATORY":
                            try:
                                self.telegram.set_state(user_id, 0, user_id, "SETUP_PROXY_MANDATORY")
                                logger.info(f"Admin {user_id} put into proxy setup mode.")
                            except Exception:
                                pass
                time.sleep(5)
                continue

            if not self.account.golden_key:
                self._enter_degraded_mode(
                    "Golden Key missing.",
                    "⚠️ <b>Отсутствует Golden Key!</b>\n\n"
                    "Бот не может войти в аккаунт. Введите токен через /golden_key или меню."
                )
                time.sleep(30)
                continue

            if not cortex_tools.check_proxy(self.account.proxy):
                self._enter_degraded_mode(
                    "Proxy unreachable.",
                    "⚠️ <b>Критическая ошибка: Прокси недоступен!</b>\n\n"
                    "Бот не может подключиться к интернету через ваш прокси.\n"
                    "Работа с FunPay остановлена во избежание блокировки.\n\n"
                    "👉 <b>Отправьте новый прокси прямо в этот чат для замены.</b>"
                )
                
                if self.telegram and self.telegram.authorized_users:
                    for user_id in self.telegram.authorized_users:
                        self.telegram.set_state(user_id, 0, user_id, "SETUP_PROXY_MANDATORY")
                
                time.sleep(30)
                continue

            try:
                self.account.get(update_phpsessid=True)
                self.balance = self.get_balance()
                
                if self.is_in_degraded_mode and self.telegram:
                    self.telegram.send_notification("✅ <b>Соединение с FunPay восстановлено!</b>\n\nБот возвращается в штатный режим работы.",
                                                    notification_type=tg_utils.NotificationTypes.critical)

                self.funpay_connection_ok = True
                self.is_in_degraded_mode = False
                self.degraded_mode_start_time = None 
                
                greeting_text = cortex_tools.create_greeting_text(self)
                for line in greeting_text.split("\n"):
                    logger.info(line)
                
                if self.runner:
                    self.runner.last_flood_err_time = 0
                
                break 

            except FunPayExceptions.UnauthorizedError:
                self._enter_degraded_mode(
                    "Invalid golden_key (403/401).",
                    "⚠️ <b>Ошибка авторизации</b>\n\nGolden Key недействителен. Получите новый токен и введите команду /golden_key"
                )
            except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout, requests.exceptions.RequestException) as e:
                self._enter_degraded_mode(
                    f"Network error connecting to FunPay: {e}",
                    f"⚠️ <b>Ошибка подключения к FunPay</b>\n\nПрокси настроен, но FunPay недоступен: <code>{tg_utils.escape(str(e))}</code>\nБот ждет восстановления связи."
                )
            
            except FunPayExceptions.RequestFailedError as e:
                err_str = str(e)
                if "EOF" in err_str or "RemoteDisconnected" in err_str:
                    self._enter_degraded_mode(
                        f"FunPay dropped connection (EOF/Ban): {e}",
                        "🚫 <b>FunPay блокирует соединение!</b>\n\n"
                        "Ваш прокси проходит проверку связи, но <b>FunPay сбрасывает подключение</b> (ошибка EOF).\n"
                        "Скорее всего, этот IP-адрес или подсеть находятся в черном списке Cloudflare/FunPay.\n\n"
                        "👉 <b>Решение:</b> Смените прокси на другой (желательно другой страны или провайдера)."
                    )
                else:
                    self._enter_degraded_mode(
                        f"FunPay API Error: {e}",
                        f"⚠️ <b>Ошибка FunPay API</b>\n\nСервер вернул ошибку при входе: <code>{tg_utils.escape(str(e))}</code>"
                    )

            except Exception as e:
                if "EOF" in str(e):
                    self._enter_degraded_mode(
                        f"Connection dropped (EOF): {e}",
                        "🚫 <b>FunPay сбрасывает соединение (EOF)</b>\n\nВаш прокси, вероятно, заблокирован FunPay, хотя интернет через него работает.\n👉 <b>Пожалуйста, замените прокси.</b>"
                    )
                else:
                    self._enter_degraded_mode(
                        f"Unexpected init error: {e}",
                        f"⚠️ <b>Критическая ошибка</b>\n\n<code>{tg_utils.escape(str(e))}</code>"
                    )
            
            logger.info("Retrying connection in 30 seconds...")
            time.sleep(30)

    def _enter_degraded_mode(self, log_message: str, tg_notification: str):
        self.funpay_connection_ok = False
        
        if not self.is_in_degraded_mode:
            logger.critical(f"🛑 {log_message}")
            
            if self.degraded_mode_start_time is None:
                self.degraded_mode_start_time = time.time()
                
            if self.telegram:
                try:
                    self.telegram.send_notification(tg_notification, notification_type=tg_utils.NotificationTypes.critical)
                except Exception:
                    pass
            self.is_in_degraded_mode = True

    def __init_telegram(self) -> None:
        self.telegram = tg_bot.bot.TGBot(self)
        self.telegram.init()

    def get_balance(self, attempts: int = 3) -> FunPayAPI.types.Balance:
        subcategories = self.account.get_sorted_subcategories()[FunPayAPI.enums.SubCategoryTypes.COMMON]
        lots = []
        if not subcategories:
             raise Exception("No common subcategories found for balance check.")
        current_attempts = 0
        while current_attempts < attempts:
            try:
                subcat_id = random.choice(list(subcategories.keys()))
                lots = self.account.get_subcategory_public_lots(FunPayAPI.enums.SubCategoryTypes.COMMON, subcat_id)
                if lots:
                    break
            except Exception as e:
                 logger.warning(f"Error getting lots for balance check (Subcat ID: {subcat_id}): {e}")
                 logger.debug("TRACEBACK", exc_info=True)
                 time.sleep(1)
            current_attempts +=1
        if not lots:
             raise Exception(f"Failed to find public lots for balance check after {attempts} attempts.")
        balance = self.account.get_balance(random.choice(lots).id)
        return balance

    def raise_lots(self) -> int:
        if not self.funpay_connection_ok: return 300
        
        self._dispatch_feature_event("on_pre_lots_raise")

        next_call = float("inf")
        unique_categories = []
        seen_category_ids = set()
        if not self.profile or not self.profile.get_lots():
            logger.info("No lots in profile to raise. Skipping loop.")
            return 300

        for subcat_obj in self.profile.get_sorted_lots(2).keys():
            if subcat_obj.category.id not in seen_category_ids:
                unique_categories.append(subcat_obj.category)
                seen_category_ids.add(subcat_obj.category.id)
        sorted_categories_to_raise = sorted(unique_categories, key=lambda cat: cat.position)

        for category_obj in sorted_categories_to_raise:
            if (saved_raise_time := self.raise_time.get(category_obj.id)) and saved_raise_time > int(time.time()):
                next_call = min(next_call, saved_raise_time)
                continue

            active_common_subcategories_in_game = []
            for sub_category_obj_from_profile, lots_dict_in_subcategory in self.profile.get_sorted_lots(2).items():
                if sub_category_obj_from_profile.category.id == category_obj.id and \
                   sub_category_obj_from_profile.type == SubCategoryTypes.COMMON and \
                   lots_dict_in_subcategory:
                    active_common_subcategories_in_game.append(sub_category_obj_from_profile)
            unique_common_subcats = list(set(sc.id for sc in active_common_subcategories_in_game))

            if not unique_common_subcats:
                logger.debug(f"Category '{category_obj.name}' has no active COMMON lots, skipping.")
                self.raise_time[category_obj.id] = int(time.time()) + 7200
                next_call = min(next_call, self.raise_time[category_obj.id])
                continue

            raise_ok = False
            error_text_msg = ""
            time_delta_str = ""

            try:
                time.sleep(random.uniform(0.5, 1.5))
                self.account.raise_lots(category_obj.id, subcategories=unique_common_subcats)
                logger.info(_("crd_lots_raised", category_obj.name))
                raise_ok = True
                last_raised_timestamp = self.raised_time.get(category_obj.id)
                current_timestamp = int(time.time())
                self.raised_time[category_obj.id] = current_timestamp
                if last_raised_timestamp:
                    time_delta_str = f" Last raised: {cortex_tools.time_to_str(current_timestamp - last_raised_timestamp)} ago."
                next_raise_attempt_time = current_timestamp + 7200
                self.raise_time[category_obj.id] = next_raise_attempt_time
                next_call = min(next_call, next_raise_attempt_time)

            except FunPayExceptions.UnauthorizedError:
                logger.warning(f"Golden Key expired during raise loop for category {category_obj.name}!")
                self._enter_degraded_mode(
                    "Golden Key invalid (Raise Loop 403)",
                    "⚠️ <b>Ошибка авторизации</b>\n\nFunPay отклонил запрос на поднятие лотов (403). Похоже, Golden Key устарел или был сброшен.\n\n👉 <b>Введите /golden_key для восстановления работы.</b>"
                )
                return int(time.time()) + 300 

            except FunPayExceptions.RaiseError as e:
                error_text_msg = e.error_message if e.error_message else "Unknown FunPay error."
                wait_duration = e.wait_time if e.wait_time is not None else 60
                logger.warning(_("crd_raise_time_err", category_obj.name, error_text_msg, cortex_tools.time_to_str(wait_duration)))
                next_raise_attempt_time = int(time.time()) + wait_duration
                self.raise_time[category_obj.id] = next_raise_attempt_time
                next_call = min(next_call, next_raise_attempt_time)
            
            except Exception as e:
                default_retry_delay = 60
                
                if isinstance(e, (requests.exceptions.RequestException, FunPayExceptions.RequestFailedError)):
                    logger.error(f"Raise loop network error: {e}")
                    return int(time.time()) + 60 

                error_log_message = _("crd_raise_unexpected_err", category_obj.name)
                logger.error(error_log_message)
                logger.debug("TRACEBACK", exc_info=True)
                time.sleep(random.uniform(default_retry_delay / 2, default_retry_delay))
                next_raise_attempt_time = int(time.time()) + 1
                next_call = min(next_call, next_raise_attempt_time)

            if raise_ok:
                self.run_handlers(self.post_lots_raise_handlers, (self, category_obj, error_text_msg + time_delta_str))
                self._dispatch_feature_event("on_post_lots_raise", category_obj)

        return next_call if next_call < float("inf") else 300
    
    def get_order_from_object(self, obj: types.OrderShortcut | types.Message | types.ChatShortcut,
                              order_id_str: str | None = None) -> None | types.Order:
        if obj._order_attempt_error:
            return None
        if obj._order_attempt_made and obj._order is not None:
            return obj._order
        if obj._order_attempt_made and obj._order is None:
            wait_count = 0
            while obj._order is None and not obj._order_attempt_error and wait_count < 50:
                time.sleep(0.1)
                wait_count +=1
            return obj._order

        obj._order_attempt_made = True
        if not isinstance(obj, (types.Message, types.ChatShortcut, types.OrderShortcut)):
            obj._order_attempt_error = True
            logger.error(f"Invalid object type for get_order_from_object: {type(obj)}")
            return None

        final_order_id = order_id_str
        if not final_order_id:
            if isinstance(obj, types.OrderShortcut):
                final_order_id = obj.id
                if final_order_id == "ADTEST":
                    obj._order_attempt_error = True
                    return None
            elif isinstance(obj, (types.Message, types.ChatShortcut)):
                match = fp_utils.RegularExpressions().ORDER_ID.search(str(obj))
                if not match:
                    obj._order_attempt_error = True
                    return None
                final_order_id = match.group(0)[1:]
        if not final_order_id:
            obj._order_attempt_error = True
            return None
            
        now = time.time()
        if final_order_id in self.order_cache:
            order, cache_time = self.order_cache[final_order_id]
            if now < cache_time + self.ORDER_CACHE_TTL:
                logger.info(f"Using cached order #{final_order_id}")
                obj._order = order
                return order

        for attempt_num in range(3, 0, -1):
            try:
                fetched_order = self.account.get_order(final_order_id)
                obj._order = fetched_order
                if fetched_order:
                    self.order_cache[final_order_id] = (fetched_order, now)
                logger.info(f"Fetched order #{final_order_id}")
                return fetched_order
            except Exception as e:
                logger.warning(f"Error fetching order #{final_order_id} (attempt {4-attempt_num}): {e}")
                logger.debug("TRACEBACK", exc_info=True)
                if attempt_num > 1: time.sleep(random.uniform(0.5, 1.5))
        obj._order_attempt_error = True
        return None

    @staticmethod
    def split_text(text: str) -> list[str]:
        output = []
        lines = text.split("\n")
        while lines:
            subtext = "\n".join(lines[:20])
            del lines[:20]
            if (strip := subtext.strip()) and strip != "[a][/a]":
                output.append(subtext)
        return output

    def parse_message_entities(self, msg_text: str) -> list[str | int | float]:
        msg_text = "\n".join(i.strip() for i in msg_text.split("\n"))
        while "\n\n" in msg_text:
            msg_text = msg_text.replace("\n\n", "\n[a][/a]\n")
        pos = 0
        entities = []
        while entity := cortex_tools.ENTITY_RE.search(msg_text, pos=pos):
            if text := msg_text[pos:entity.span()[0]].strip():
                entities.extend(self.split_text(text))
            variable = msg_text[entity.span()[0]:entity.span()[1]]
            if variable.startswith("$photo"):
                entities.append(int(variable.split("=")[1]))
            elif variable.startswith("$sleep"):
                entities.append(float(variable.split("=")[1]))
            pos = entity.span()[1]
        else:
            if text := msg_text[pos:].strip():
                entities.extend(self.split_text(text))
        return entities

    def send_message(self, chat_id: int | str, message_text: str, chat_name: str | None = None,
                     interlocutor_id: int | None = None, attempts: int = 3,
                     watermark: bool = True) -> list[FunPayAPI.types.Message] | None:
        if not self.account.is_initiated:
            logger.warning(f"⚠️ Попытка отправить сообщение в {chat_id}, но аккаунт еще не инициализирован. Пропуск.")
            return None

        if self.MAIN_CFG["Other"].get("watermark") and watermark and not message_text.strip().startswith("$photo="):
            message_text = f"{self.MAIN_CFG['Other']['watermark']}\n" + message_text
        entities = self.parse_message_entities(message_text)
        if all(isinstance(i, float) for i in entities) or not entities:
            return None
        result = []
        for entity in entities:
            current_attempts = attempts
            while current_attempts:
                try:
                    if isinstance(entity, str):
                        msg = self.account.send_message(chat_id, entity, chat_name,
                                                        interlocutor_id or self.account.interlocutor_ids.get(chat_id),
                                                        None, not self.old_mode_enabled,
                                                        self.old_mode_enabled,
                                                        self.keep_sent_messages_unread)
                        result.append(msg)
                        logger.info(_("crd_msg_sent", chat_id))
                    elif isinstance(entity, int):
                        msg = self.account.send_image(chat_id, entity, chat_name,
                                                      interlocutor_id or self.account.interlocutor_ids.get(chat_id),
                                                      not self.old_mode_enabled,
                                                      self.old_mode_enabled,
                                                      self.keep_sent_messages_unread)
                        result.append(msg)
                        logger.info(_("crd_msg_sent", chat_id))
                    elif isinstance(entity, float):
                        time.sleep(entity)
                    break
                
                except FunPayExceptions.RequestFailedError as ex:
                    if ex.status_code == 400 and ("Обновите страницу" in str(ex) or "Refresh" in str(ex)):
                        logger.warning(f"⚠️ Токен устарел (400) при отправке в чат {chat_id}. Обновляю сессию...")
                        if self.update_session():
                            time.sleep(1)
                            continue 
                    
                    logger.warning(_("crd_msg_send_err", chat_id) + f": {ex}")
                    logger.debug("TRACEBACK", exc_info=True)
                    logger.info(_("crd_msg_attempts_left", current_attempts))
                    current_attempts -= 1
                    time.sleep(1)

                except Exception as ex:
                    logger.warning(_("crd_msg_send_err", chat_id) + f": {ex}")
                    logger.debug("TRACEBACK", exc_info=True)
                    logger.info(_("crd_msg_attempts_left", current_attempts))
                    current_attempts -= 1
                    time.sleep(1)
            else:
                logger.error(_("crd_msg_no_more_attempts_err", chat_id))
                return []
        return result

    def get_exchange_rate(self, base_currency: types.Currency, target_currency: types.Currency, min_interval: int = 60):
        assert base_currency != types.Currency.UNKNOWN and target_currency != types.Currency.UNKNOWN
        if base_currency == target_currency:
            return 1.0
        cached_rate, cache_time = self.__exchange_rates.get((base_currency, target_currency), (None, 0))
        if cached_rate is not None and time.time() < cache_time + min_interval:
            return cached_rate
        cached_rate_reverse, cache_time_reverse = self.__exchange_rates.get((target_currency, base_currency), (None, 0))
        if cached_rate_reverse is not None and time.time() < cache_time_reverse + min_interval:
            if cached_rate_reverse == 0:
                logger.error(f"Reverse rate {target_currency.name} -> {base_currency.name} is zero.")
                return float('inf')
            return 1.0 / cached_rate_reverse

        for attempt in range(3):
            try:
                rate_to_base, actual_acc_currency_after_base_req = self.account.get_exchange_rate(base_currency)
                current_time = time.time()
                self.__exchange_rates[(actual_acc_currency_after_base_req, base_currency)] = (rate_to_base, current_time)
                if rate_to_base != 0: self.__exchange_rates[(base_currency, actual_acc_currency_after_base_req)] = (1.0 / rate_to_base, current_time)
                time.sleep(random.uniform(0.5, 1.0))
                rate_to_target, actual_acc_currency_after_target_req = self.account.get_exchange_rate(target_currency)
                current_time = time.time()
                self.__exchange_rates[(actual_acc_currency_after_target_req, target_currency)] = (rate_to_target, current_time)
                if rate_to_target != 0: self.__exchange_rates[(target_currency, actual_acc_currency_after_target_req)] = (1.0 / rate_to_target, current_time)

                if actual_acc_currency_after_base_req == base_currency:
                    final_rate = rate_to_target
                elif actual_acc_currency_after_target_req == target_currency:
                    if rate_to_base == 0:
                        logger.error(f"Rate {actual_acc_currency_after_target_req.name} -> {base_currency.name} is zero.")
                        final_rate = float('inf')
                    else:
                        final_rate = 1.0 / rate_to_base
                elif actual_acc_currency_after_base_req == actual_acc_currency_after_target_req:
                    if rate_to_base == 0:
                        logger.error(f"Rate {actual_acc_currency_after_base_req.name} -> {base_currency.name} is zero.")
                        final_rate = float('inf')
                    else:
                        final_rate = rate_to_target / rate_to_base
                else:
                    logger.warning(f"Currency mismatch: {actual_acc_currency_after_base_req.name} vs {actual_acc_currency_after_target_req.name}. Attempt {attempt + 1}.")
                    if attempt < 2: continue
                    raise Exception("Failed to calculate rate due to unpredictable currency switch.")


                self.__exchange_rates[(base_currency, target_currency)] = (final_rate, time.time())
                if final_rate != 0 and final_rate != float('inf'): self.__exchange_rates[(target_currency, base_currency)] = (1.0 / final_rate, time.time())
                return final_rate
            except Exception as e:
                logger.warning(f"Error getting exchange rate (attempt {attempt + 1}): {e}")
                logger.debug("TRACEBACK", exc_info=True)
                if attempt < 2: time.sleep(random.uniform(1, 2))
        logger.error("Failed to get exchange rate after attempts.")
        raise Exception("Failed to get exchange rate.")

    def update_session(self, attempts: int = 3) -> bool:
        if not self.funpay_connection_ok:
            return False
        while attempts:
            try:
                self.account.get(update_phpsessid=True)
                logger.info(_("crd_session_updated"))
                return True
            except TimeoutError:
                logger.warning(_("crd_session_timeout_err"))
            except (FunPayExceptions.UnauthorizedError, FunPayExceptions.RequestFailedError) as e:
                logger.error(e.short_str())
                logger.debug("TRACEBACK", exc_info=True)
            except Exception as e:
                logger.error(_("crd_session_unexpected_err") + f": {e}")
                logger.debug("TRACEBACK", exc_info=True)
            attempts -= 1
            if attempts > 0:
                 logger.warning(_("crd_try_again_in_n_secs", 2))
                 time.sleep(2)
        else:
            logger.error(_("crd_session_no_more_attempts_err"))
            return False

    def watchdog_loop(self):
        logger.info("Watchdog started.")
        while self.running:
            time.sleep(10)
            
            if not self.runner:
                continue
            
            if not self.funpay_connection_ok or self.is_in_degraded_mode:
                continue
            
            if self.runner.last_activity == 0:
                continue

            if time.time() - self.runner.last_activity > 100:
                logger.critical("Watchdog: Runner freeze detected (>100s silence). Restarting...")
                
                if self.telegram:
                    try:
                        self.telegram.send_notification("⚠️ <b>Watchdog:</b> Зависание ядра. Перезагрузка...", notification_type=tg_utils.NotificationTypes.critical)
                    except: pass
                
                cortex_tools.restart_program()

    def process_events(self):
        instance_id = self.run_id
        
        events_handlers = {
            FunPayAPI.events.EventTypes.INITIAL_CHAT: self.init_message_handlers,
            FunPayAPI.events.EventTypes.CHATS_LIST_CHANGED: self.messages_list_changed_handlers,
            FunPayAPI.events.EventTypes.LAST_CHAT_MESSAGE_CHANGED: self.last_chat_message_changed_handlers,
            FunPayAPI.events.EventTypes.NEW_MESSAGE: self.new_message_handlers,
            FunPayAPI.events.EventTypes.INITIAL_ORDER: self.init_order_handlers,
            FunPayAPI.events.EventTypes.ORDERS_LIST_CHANGED: self.orders_list_changed_handlers,
            FunPayAPI.events.EventTypes.NEW_ORDER: self.new_order_handlers,
            FunPayAPI.events.EventTypes.ORDER_STATUS_CHANGED: self.order_status_changed_handlers,
        }
        
        feature_hooks = {
            FunPayAPI.events.EventTypes.NEW_MESSAGE: "on_new_message",
            FunPayAPI.events.EventTypes.NEW_ORDER: "on_new_order",
            FunPayAPI.events.EventTypes.ORDER_STATUS_CHANGED: "on_order_status_changed",
        }

        for event in self.runner.listen(requests_delay=int(self.MAIN_CFG["Other"]["requestsDelay"])):
            if instance_id != self.run_id:
                break
            if not self.funpay_connection_ok:
                time.sleep(10)
                continue
            
            if self.hosting_url and not self.is_subscription_active:
                logger.critical("Subscription inactive. Shutting down.")
                time.sleep(5)
                os._exit(0)

            self.run_handlers(events_handlers.get(event.type, []), (self, event))
            
            if event.type in feature_hooks:
                self._dispatch_feature_event(feature_hooks[event.type], event)

    def lots_raise_loop(self):
        if not self.profile or not self.profile.get_lots():
            logger.info(_("crd_raise_loop_not_started"))
            return
        logger.info(_("crd_raise_loop_started"))
        while self.running:
            try:
                if not self.funpay_connection_ok:
                    time.sleep(10)
                    continue
                
                if self.hosting_url and not self.is_subscription_active:
                    logger.critical("Subscription inactive. Stopping raise loop.")
                    return
                if not self.MAIN_CFG["FunPay"].getboolean("autoRaise"):
                    time.sleep(10)
                    continue
                next_time = self.raise_lots()
                delay = next_time - int(time.time())
                if delay <= 0:
                    logger.debug(f"Short delay before next raise (delay={delay}).")
                    time.sleep(random.uniform(1,3))
                    continue
                logger.debug(f"Next raise in: {cortex_tools.time_to_str(delay)}")
                time.sleep(delay)
            except Exception as e:
                logger.error(f"Error in raise loop: {e}")
                logger.debug("TRACEBACK", exc_info=True)
                time.sleep(60)

    def update_session_loop(self):
        logger.info(_("crd_session_loop_started"))
        default_sleep_time = 3600
        while self.running:
            time.sleep(default_sleep_time)
            if self.funpay_connection_ok:
                self.update_session()

    def load_features(self):
        allowed_slugs = []
        try:
            with open(os.path.join(self.base_path, "configs/features_config.json"), "r") as f:
                data = json.load(f)
                allowed_slugs = data.get("allowed_features", [])
                self.access_level = data.get("access_level", self.access_level)
                self.purchased_features = data.get("purchased_features", [])
        except FileNotFoundError:
            logger.warning("features_config.json not found. Using defaults.")
        
        self.allowed_features = allowed_slugs

        features_dir = os.path.join(self.base_path, "features")
        if not os.path.exists(features_dir):
             logger.info("features folder not found.")
             return

        logger.info(f"Scanning features in {features_dir}...")
        
        for _, name, _ in pkgutil.iter_modules([features_dir]):
            try:
                module = importlib.import_module(f"features.{name}")
                
                for attribute_name in dir(module):
                    attribute = getattr(module, attribute_name)
                    
                    if (isinstance(attribute, type) and 
                        issubclass(attribute, BaseFeature) and 
                        attribute is not BaseFeature):
                        
                        try:
                            feature_instance = attribute(self)
                            self.features[feature_instance.uid] = feature_instance
                            logger.info(f"Feature loaded: {feature_instance.name}")
                                
                        except Exception as e:
                            logger.error(f"Error initializing feature {attribute_name}: {e}", exc_info=True)
                            
            except Exception as e:
                logger.error(f"Failed to load module {name}: {e}")

    def _refresh_features_state(self):
        for feature in self.features.values():
            if feature.settings.get("enabled") and not feature.is_available:
                logger.info(f"Feature {feature.name} disabled due to access loss.")
                feature.toggle()

    def _dispatch_feature_event(self, method_name: str, *args, **kwargs):
        for feature in self.features.values():
            if feature.is_active:
                try:
                    method = getattr(feature, method_name, None)
                    if method and callable(method):
                        method(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error in feature {feature.name} (method {method_name}): {e}", exc_info=True)

    def init(self):
        if not self.hosting_url:
            self.is_subscription_active = True
            self.access_level = 99
            logger.info("Local mode: Max access level (99).")

        def save_config_with_sync(self, config_obj: configparser.ConfigParser, file_path: str) -> None:
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    config_obj.write(f)
            except Exception as e:
                logger.error(f"Error saving config locally {file_path}: {e}")
            
            if self.hosting_url and self.hosting_token and self.HOSTING_USER_ID:
                config_filename = os.path.basename(file_path)
                
                api_endpoint = f"{self.hosting_url}/api/bot/settings/config/{config_filename}"
                string_io = io.StringIO()
                config_obj.write(string_io)
                config_content = string_io.getvalue()
                
                try:
                    headers = {"X-Bot-Token": self.hosting_token}
                    json_payload = {
                        "content": config_content,
                        "user_id": self.HOSTING_USER_ID
                    }
                    response = requests.put(api_endpoint, headers=headers, json=json_payload, timeout=10)
                    response.raise_for_status()
                    logger.info(f"Config {config_filename} synced with hosting.")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Failed to sync config {config_filename} with hosting: {e}")

        def save_json_setting_with_sync(self, setting_name: str, data: dict | list):
            if self.hosting_url and self.hosting_token and self.HOSTING_USER_ID:
                api_endpoint = f"{self.hosting_url}/api/bot/settings/json/{setting_name}"
                try:
                    headers = {"X-Bot-Token": self.hosting_token}
                    json_payload = {
                        "content": data,
                        "user_id": self.HOSTING_USER_ID
                    }
                    response = requests.put(api_endpoint, headers=headers, json=json_payload, timeout=10)
                    response.raise_for_status()
                    logger.info(f"Setting '{setting_name}' successfully synced with hosting.")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Failed to sync setting '{setting_name}' with hosting: {e}")

        if self.IS_HOSTING_ENV:
             self.save_config = py_types.MethodType(save_config_with_sync, self)
             self.save_json_setting = py_types.MethodType(save_json_setting_with_sync, self)
        
        self._sync_settings_from_backend()
        
        try:
            main_cfg_path = os.path.join(self.base_path, "configs/_main.cfg")
            self.MAIN_CFG = cfg_loader.load_main_config(main_cfg_path)
            localizer = Localizer(self.MAIN_CFG["Other"]["language"])
            
            if self.MAIN_CFG["Proxy"].getboolean("enable"):
                ip = self.MAIN_CFG["Proxy"]["ip"]
                port = self.MAIN_CFG["Proxy"]["port"]
                login = self.MAIN_CFG["Proxy"]["login"]
                password = self.MAIN_CFG["Proxy"]["password"]
                if ip and port:
                     proxy_str = f"{f'{login}:{password}@' if login and password else ''}{ip}:{port}"
                     self.account.proxy = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}

            ar_cfg_path = os.path.join(self.base_path, "configs/auto_response.cfg")
            ad_cfg_path = os.path.join(self.base_path, "configs/auto_delivery.cfg")
            self.AR_CFG = cfg_loader.load_auto_response_config(ar_cfg_path)
            self.AD_CFG = cfg_loader.load_auto_delivery_config(ad_cfg_path)
            
            self.blacklist = cortex_tools.load_blacklist(self.base_path)
            self.disabled_plugins = cortex_tools.load_disabled_plugins(self.base_path)
            greetings_cooldown = float(self.MAIN_CFG["Greetings"]["greetingsCooldown"])
            self.old_users = cortex_tools.load_old_users(greetings_cooldown, self.base_path)
            
        except Exception as e:
            logger.critical(f"Critical error loading local configs: {e}")
            sys.exit(1)

        self.add_handlers_from_plugin(handlers)
        self.add_handlers_from_plugin(announcements)
        self.add_handlers_from_plugin(statistics_cp)
        
        self.load_features()
        
        self.add_handlers()
        
        if self.MAIN_CFG["Telegram"].getboolean("enabled"):
            self.__init_telegram()
            for module in [auto_response_cp, auto_delivery_cp, config_loader_cp, templates_cp, 
                           file_uploader, authorized_users_cp, proxy_cp, plugins_cp, default_cp]:
                self.add_handlers_from_plugin(module)
            
            self.telegram.setup_commands()
            try:
                self.telegram.edit_bot()
            except Exception as e:
                logger.warning(f"Error setting bot profile: {e}")
        
        if self.hosting_url:
            self.load_subscription_cache()
        
        logger.info("Initializing features...")
        for feature in self.features.values():
            if feature.is_active:
                try:
                    feature.on_enable()
                    logger.info(f"Feature started: {feature.name}")
                except Exception as e:
                    logger.error(f"Error starting {feature.name}: {e}")
            else:
                pass

        self.run_handlers(self.pre_init_handlers, (self,))
        self.run_handlers(self.post_init_handlers, (self,))
        return self
    
    def add_handlers_from_plugin(self, plugin, uuid: str | None = None):
        if not plugin:
            return
        for name in self.handler_bind_var_names:
            try:
                functions = getattr(plugin, name)
            except AttributeError:
                continue
            for func in functions:
                func.plugin_uuid = uuid
            self.handler_bind_var_names[name].extend(functions)
        logger.info(_("crd_handlers_registered", plugin.__name__))

    def add_handlers(self):
        pass

    def run_handlers(self, handlers_list: list[Callable], args) -> None:
        for func in handlers_list:
            try:
                func(*args)
            except Exception as ex:
                error_message_short = str(ex)
                logger.error(_("crd_handler_err") + f" ({error_message_short})")
                logger.debug("TRACEBACK", exc_info=True)
                continue

    def add_telegram_commands(self, uuid: str, commands: list[tuple[str, str, bool]]):
        if self.telegram:
            logger.info(f"Commands for UUID {uuid} registered.")

    def toggle_plugin(self, uuid):
        if uuid in self.features:
            feature = self.features[uuid]
            if not feature.is_available:
                return False
            
            new_state = feature.toggle()

            status = "enabled" if new_state else "disabled"
            logger.info(f"Feature {feature.name} {status} by user.")
            return True
        else:
            logger.warning(f"Attempt to toggle non-existent plugin UUID: {uuid}")
            return False

    @property
    def autoraise_enabled(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("autoRaise")
    @property
    def autoresponse_enabled(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("autoResponse")
    @property
    def autodelivery_enabled(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("autoDelivery")
    @property
    def multidelivery_enabled(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("multiDelivery")
    @property
    def autorestore_enabled(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("autoRestore")
    @property
    def autodisable_enabled(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("autoDisable")
    @property
    def old_mode_enabled(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("oldMsgGetMode")
    @property
    def keep_sent_messages_unread(self) -> bool: return self.MAIN_CFG["FunPay"].getboolean("keepSentMessagesUnread")
    @property
    def show_image_name(self) -> bool: return self.MAIN_CFG["NewMessageView"].getboolean("showImageName")
    @property
    def bl_delivery_enabled(self) -> bool: return self.MAIN_CFG["BlockList"].getboolean("blockDelivery")
    @property
    def bl_response_enabled(self) -> bool: return self.MAIN_CFG["BlockList"].getboolean("blockResponse")
    @property
    def bl_msg_notification_enabled(self) -> bool: return self.MAIN_CFG["BlockList"].getboolean("blockNewMessageNotification")
    @property
    def bl_order_notification_enabled(self) -> bool: return self.MAIN_CFG["BlockList"].getboolean("blockNewOrderNotification")
    @property
    def bl_cmd_notification_enabled(self) -> bool: return self.MAIN_CFG["BlockList"].getboolean("blockCommandNotification")
    @property
    def include_my_msg_enabled(self) -> bool: return self.MAIN_CFG["NewMessageView"].getboolean("includeMyMessages")
    @property
    def include_fp_msg_enabled(self) -> bool: return self.MAIN_CFG["NewMessageView"].getboolean("includeFPMessages")
    @property
    def include_bot_msg_enabled(self) -> bool: return self.MAIN_CFG["NewMessageView"].getboolean("includeBotMessages")
    @property
    def only_my_msg_enabled(self) -> bool: return self.MAIN_CFG["NewMessageView"].getboolean("notifyOnlyMyMessages")
    @property
    def only_fp_msg_enabled(self) -> bool: return self.MAIN_CFG["NewMessageView"].getboolean("notifyOnlyFPMessages")
    @property
    def only_bot_msg_enabled(self) -> bool: return self.MAIN_CFG["NewMessageView"].getboolean("notifyOnlyBotMessages")
    @property
    def block_tg_login(self) -> bool: return self.MAIN_CFG["Telegram"].getboolean("blockLogin")

    def run(self):
        if self.running:
            logger.warning("Attempt to restart Cortex. Ignoring.")
            return

        self.run_id += 1
        self.running = True
        
        if self.telegram:
            logger.info("Telegram Bot ready.")

        self._wait_for_funpay_connection()
        
        logger.info("Initializing FunPay systems...")
        
        if self.hosting_url:
            self.check_subscription_status()
            if not self.is_subscription_active:
                 logger.critical("Subscription inactive. Functionality limited.")

        self.runner = FunPayAPI.Runner(self.account,
                                       disable_message_requests=self.old_mode_enabled,
                                       disabled_order_requests=False,
                                       disabled_buyer_viewing_requests=True)
        
        self.__update_profile(infinite_polling=False, attempts=5, update_main_profile=True)
        
        self.start_time = int(time.time())
        
        self.run_handlers(self.pre_start_handlers, (self,))
        
        if self.hosting_url:
            self.executor.submit(self.subscription_check_loop)
        if self.MAIN_CFG["Statistics"].getboolean("enabled"):
            self.executor.submit(statistics_cp.periodic_sales_update, self)
            
        self.run_handlers(self.post_start_handlers, (self,))
        
        Thread(target=self.lots_raise_loop, daemon=True).start()
        Thread(target=self.update_session_loop, daemon=True).start()
        
        self.executor.submit(self.watchdog_loop)
        
        while self.running:
            try:
                self.process_events()
            except requests.exceptions.RequestException:
                logger.error("Runner connection failed definitively. Entering recovery mode...")
                self._wait_for_funpay_connection()
            except Exception as e:
                logger.critical(f"Critical error in main loop: {e}", exc_info=True)
                time.sleep(10)

    def start(self):
        self.run_id += 1
        self.running = True
        self.run_handlers(self.pre_start_handlers, (self,))
        self.run_handlers(self.post_start_handlers, (self,))
        self.process_events()

    def stop(self):
        self.run_id += 1
        self.running = False
        logger.info("Stopping Cortex...")
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.run_handlers(self.pre_stop_handlers, (self,))
        self.run_handlers(self.post_stop_handlers, (self,))
    
    def update_lots_and_categories(self):
        result = self.__update_profile(infinite_polling=False, attempts=3, update_main_profile=False)
        return result

    def __update_profile(self, infinite_polling: bool = False, attempts: int = 5, update_main_profile: bool = True) -> bool:
        logger.info(_("crd_getting_profile_data"))
        while attempts:
            try:
                profile = self.account.get_user(self.account.id)
                if update_main_profile:
                    self.profile = profile
                    self.profile_cache_time = time.time()
                    logger.info(_("crd_profile_updated", len(self.profile.get_lots()), len(self.account.categories)))
                else:
                    self.tg_profile = profile
                    self.last_tg_profile_update = datetime.datetime.now()
                    logger.info(_("crd_tg_profile_updated", len(self.tg_profile.get_lots()), len(self.account.categories)))
                return True
            except FunPayExceptions.UnauthorizedError:
                logger.warning("Golden Key expired during profile update!")
                self._enter_degraded_mode(
                    "Golden Key invalid (runtime)",
                    "⚠️ <b>Ошибка авторизации (Runtime)</b>\n\nGolden Key сбросился во время работы. Получите новый токен и введите команду /golden_key"
                )
                return False
            except requests.exceptions.Timeout:
                logger.error(_("crd_profile_get_timeout_err"))
            except Exception:
                logger.error(_("crd_profile_get_unexpected_err"))
                logger.debug("TRACEBACK", exc_info=True)
            
            attempts -= 1
            if attempts > 0:
                logger.warning(_("crd_try_again_in_n_secs", 2))
                time.sleep(2)
        else:
            if infinite_polling:
                logger.error(_("crd_profile_get_too_many_attempts_err", 5))
                time.sleep(10)
                return self.__update_profile(infinite_polling, 5, update_main_profile)
            return False

    def switch_msg_get_mode(self):
        self.MAIN_CFG["FunPay"]["oldMsgGetMode"] = str(int(not self.old_mode_enabled))
        self.save_config(self.MAIN_CFG, os.path.join(self.base_path, "configs/_main.cfg"))
        if not self.runner:
            return
        self.runner.make_msg_requests = not self.old_mode_enabled
        if self.old_mode_enabled:
            self.runner.last_messages_ids = {}
            self.runner.by_bot_ids = {}
        else:
            self.runner.last_messages_ids = {k: v for k, v in self.runner.runner_last_messages.items()}

    def save_config(self, config: configparser.ConfigParser, file_path: str) -> None:
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                config.write(f)
        except Exception as e:
            logger.error(f"Error saving config locally {file_path}: {e}")

    @staticmethod
    def is_uuid_valid(uuid_str: str) -> bool:
        try:
            uuid_obj = UUID(uuid_str, version=4)
        except ValueError:
            return False
        return str(uuid_obj) == uuid_str.lower()
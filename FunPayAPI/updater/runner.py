# START OF FILE FunPayCortex/FunPayAPI/updater/runner.py

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Generator

if TYPE_CHECKING:
    from ..account import Account

import json
import logging
from bs4 import BeautifulSoup
import time
import random
import requests

from ..common import exceptions, utils
from .events import *

logger = logging.getLogger("FunPayAPI.runner")


class Runner:
    def __init__(self, account: Account, disable_message_requests: bool = False,
                 disabled_order_requests: bool = False,
                 disabled_buyer_viewing_requests: bool = True):
        if not account.is_initiated:
            raise exceptions.AccountNotInitiatedError()
        if account.runner:
            raise Exception("К аккаунту уже привязан Runner!")

        self.make_msg_requests: bool = not disable_message_requests
        self.make_order_requests: bool = not disabled_order_requests
        self.make_buyer_viewing_requests: bool = not disabled_buyer_viewing_requests

        self.__first_request = True
        self.__last_msg_event_tag = utils.random_tag()
        self.__last_order_event_tag = utils.random_tag()

        self.saved_orders: dict[str, types.OrderShortcut] = {}
        self.runner_last_messages: dict[int, list[int, int, str | None]] = {}
        self.by_bot_ids: dict[int, list[int]] = {}
        self.last_messages_ids: dict[int, int] = {}
        self.buyers_viewing: dict[int, types.BuyerViewing] = {}
        self.runner_len: int = 10
        self.__interlocutor_ids: set = set()

        self.account: Account = account
        self.account.runner = self

        self.__msg_time_re = re.compile(r"\d{2}:\d{2}")
        
        # --- WATCHDOG UPDATE ---
        self.last_activity = time.time()

    def get_updates(self) -> dict:
        orders = {
            "type": "orders_counters",
            "id": self.account.id,
            "tag": self.__last_order_event_tag,
            "data": False
        }
        chats = {
            "type": "chat_bookmarks",
            "id": self.account.id,
            "tag": self.__last_msg_event_tag,
            "data": False
        }
        buyers = [{"type": "c-p-u",
                   "id": str(buyer),
                   "tag": utils.random_tag(),
                   "data": False} for buyer in self.__interlocutor_ids or []]
        payload = {
            "objects": json.dumps([*chats, *buyers] if self.make_buyer_viewing_requests else [orders, chats]),
            "request": False,
            "csrf_token": self.account.csrf_token
        }
        headers = {
            "accept": "*/*",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest"
        }

        # ЛОГ: Начало запроса
        logger.debug(f"Runner: отправка запроса (msg_tag={self.__last_msg_event_tag})")
        
        response = self.account.method("post", "runner/", headers, payload, raise_not_200=True)
        
        # ЛОГ: Конец запроса
        logger.debug("Runner: ответ получен")
        
        json_response = response.json()
        return json_response

    def parse_updates(self, updates: dict) -> list:
        events = []
        if not updates.get("objects"):
            return events
            
        # ЛОГ: Начало парсинга
        logger.debug(f"Runner: получено объектов: {len(updates['objects'])}")

        for obj in sorted(updates["objects"], key=lambda x: x.get("type") == "orders_counters", reverse=True):
            if obj.get("type") == "chat_bookmarks":
                events.extend(self.parse_chat_updates(obj))
            elif obj.get("type") == "orders_counters":
                events.extend(self.parse_order_updates(obj))
            elif obj.get("type") == "c-p-u":
                bv = self.account.parse_buyer_viewing(obj)
                self.buyers_viewing[bv.buyer_id] = bv
        if self.__first_request:
            self.__first_request = False
        return events

    def parse_chat_updates(self, obj) -> list:
        events, lcmc_events = [], []
        self.__last_msg_event_tag = obj.get("tag")
        parser = BeautifulSoup(obj["data"]["html"], "lxml")
        chats = parser.find_all("a", {"class": "contact-item"})

        chats_to_fetch_history = {}
        for chat in chats:
            chat_id = int(chat.get("data-id", 0))
            if not chat_id:
                continue

            if not (last_msg_text_div := chat.find("div", {"class": "contact-item-message"})):
                continue

            last_msg_text = last_msg_text_div.text
            node_msg_id = int(chat.get('data-node-msg', 0))
            user_msg_id = int(chat.get('data-user-msg', 0))

            prev_node_msg_id, _, _ = self.runner_last_messages.get(chat_id, [-1, -1, None])
            if node_msg_id == prev_node_msg_id:
                continue

            by_bot = last_msg_text.startswith(self.account.bot_character)
            by_vertex = last_msg_text.startswith(self.account.old_bot_character)
            last_msg_text_cleaned = last_msg_text[1:] if by_bot or by_vertex else last_msg_text
            is_image = last_msg_text_cleaned in ("Изображение", "Зображення", "Image")
            last_msg_text_for_storage = None if is_image else last_msg_text_cleaned

            chat_with_div = chat.find("div", {"class": "media-user-name"})
            chat_with = chat_with_div.text if chat_with_div else f"ID: {chat_id}"
            unread = "unread" in chat.get("class", [])
            chat_obj = types.ChatShortcut(chat_id, chat_with, last_msg_text_cleaned, node_msg_id, user_msg_id, unread, str(chat))
            if not is_image:
                chat_obj.last_by_bot = by_bot
                chat_obj.last_by_vertex = by_vertex
            
            self.account.add_chats([chat_obj])
            self.runner_last_messages[chat_id] = [node_msg_id, user_msg_id, last_msg_text_for_storage]
            
            if self.__first_request:
                events.append(InitialChatEvent(self.__last_msg_event_tag, chat_obj))
                if self.make_msg_requests:
                    self.last_messages_ids[chat_id] = node_msg_id
                continue
            
            lcmc_event = LastChatMessageChangedEvent(self.__last_msg_event_tag, chat_obj)
            lcmc_events.append(lcmc_event)
            
            if self.make_msg_requests and node_msg_id > self.last_messages_ids.get(chat_id, -1):
                chats_to_fetch_history[chat_id] = {
                    "name": chat_obj.name,
                    "from_id": self.last_messages_ids.get(chat_id, -1),
                    "lcmc_event": lcmc_event
                }
                self.last_messages_ids[chat_id] = node_msg_id

        if lcmc_events:
            events.append(ChatsListChangedEvent(self.__last_msg_event_tag))
        
        if chats_to_fetch_history:
            # ЛОГ: Запрос истории чатов
            logger.debug(f"Runner: обнаружены новые сообщения в {len(chats_to_fetch_history)} чатах.")
            
            if self.make_buyer_viewing_requests:
                self.__interlocutor_ids.update({self.account.interlocutor_ids.get(cid) for cid in chats_to_fetch_history if cid in self.account.interlocutor_ids})

            chat_ids_to_fetch = list(chats_to_fetch_history.keys())
            while chat_ids_to_fetch:
                chat_pack_ids = chat_ids_to_fetch[:self.runner_len]
                del chat_ids_to_fetch[:self.runner_len]

                bv_pack = []
                while self.make_buyer_viewing_requests and len(chat_pack_ids) + len(bv_pack) < self.runner_len and self.__interlocutor_ids:
                    interlocutor_id = self.__interlocutor_ids.pop()
                    if interlocutor_id not in self.buyers_viewing:
                        bv_pack.append(interlocutor_id)

                chats_data_for_request = {cid: (chats_to_fetch_history[cid]["name"], chats_to_fetch_history[cid]["from_id"]) for cid in chat_pack_ids}
                new_msg_events_map = self.generate_new_message_events(chats_data_for_request, bv_pack)
                
                if self.make_buyer_viewing_requests:
                    for cid, msgs in new_msg_events_map.items():
                        if cid not in self.account.interlocutor_ids and msgs and msgs[0].message.interlocutor_id:
                            self.account.interlocutor_ids[cid] = msgs[0].message.interlocutor_id
                            self.__interlocutor_ids.add(msgs[0].message.interlocutor_id)
                
                for cid in chat_pack_ids:
                    events.append(chats_to_fetch_history[cid]["lcmc_event"])
                    if new_msg_events_map.get(cid):
                        events.extend(new_msg_events_map[cid])
        else:
            events.extend(lcmc_events)

        return events

    def generate_new_message_events(self, chats_data: dict, interlocutor_ids: list[int] | None = None) -> dict:
        attempts = 3
        chats_to_request = {cid: name for cid, (name, _) in chats_data.items()}
        
        while attempts:
            try:
                chats = self.account.get_chats_histories(chats_to_request, interlocutor_ids)
                break
            except exceptions.RequestFailedError as e:
                logger.error(e)
            except Exception:
                logger.error(f"Не удалось получить истории чатов {list(chats_data.keys())}.", exc_info=True)
            time.sleep(1)
            attempts -= 1
        else:
            logger.error(f"Не удалось получить истории чатов {list(chats_data.keys())}: превышено кол-во попыток.")
            return {}

        result = {}
        for cid, (chat_name, from_id) in chats_data.items():
            messages = chats.get(cid, [])
            if not messages:
                continue

            new_messages = [msg for msg in messages if msg.id > from_id]
            if not new_messages:
                continue

            self.by_bot_ids.setdefault(cid, [])
            for i in new_messages:
                if not i.by_bot and i.id in self.by_bot_ids[cid]:
                    i.by_bot = True

            stack = MessageEventsStack()
            events_for_stack = [NewMessageEvent(self.__last_msg_event_tag, msg, stack) for msg in new_messages]
            stack.add_events(events_for_stack)
            result[cid] = events_for_stack
            self.by_bot_ids[cid] = [i for i in self.by_bot_ids[cid] if i > new_messages[-1].id]
            
        return result


    def parse_order_updates(self, obj) -> list:
        events = []
        self.__last_order_event_tag = obj.get("tag")
        if not self.__first_request:
            events.append(OrdersListChangedEvent(self.__last_order_event_tag,
                                                 obj["data"]["buyer"], obj["data"]["seller"]))
        if not self.make_order_requests:
            return events

        # ЛОГ: Обновление заказов
        logger.debug("Runner: обновление списка заказов...")

        attempts = 3
        while attempts:
            try:
                orders_list = self.account.get_sales()
                break
            except exceptions.RequestFailedError as e:
                logger.error(e)
            except Exception:
                logger.error("Не удалось обновить список заказов.", exc_info=True)
            time.sleep(1)
            attempts -= 1
        else:
            logger.error("Не удалось обновить список продаж: превышено кол-во попыток.")
            return events

        saved_orders = {}
        for order in orders_list[1]:
            saved_orders[order.id] = order
            if order.id not in self.saved_orders:
                event_to_add = InitialOrderEvent if self.__first_request else NewOrderEvent
                events.append(event_to_add(self.__last_order_event_tag, order))
                if not self.__first_request and order.status == types.OrderStatuses.CLOSED:
                    events.append(OrderStatusChangedEvent(self.__last_order_event_tag, order))

            elif order.status != self.saved_orders[order.id].status:
                events.append(OrderStatusChangedEvent(self.__last_order_event_tag, order))
        self.saved_orders = saved_orders
        return events

    def update_last_message(self, chat_id: int, message_id: int, message_text: str | None):
        self.runner_last_messages[chat_id] = [message_id, message_id, message_text]
        self.last_messages_ids[chat_id] = message_id

    def mark_as_by_bot(self, chat_id: int, message_id: int):
        self.by_bot_ids.setdefault(chat_id, []).append(message_id)

    def listen(self, requests_delay: int | float = 6.0,
               ignore_exceptions: bool = True) -> Generator:
        """
        Основной цикл получения обновлений.
        """
        consecutive_errors = 0
        max_retries = 5
        events_to_process = []

        while True:
            # --- WATCHDOG UPDATE ---
            self.last_activity = time.time()
            # -----------------------

            # ИЗМЕНЕНИЕ: БЛОКИРОВКА ИЗ-ЗА ОТСУТСТВИЯ ПРОКСИ УБРАНА

            jitter = requests_delay * 0.2
            sleep_time = random.uniform(max(0.5, requests_delay - jitter), requests_delay + jitter)

            try:
                if self.make_buyer_viewing_requests:
                    self.__interlocutor_ids = {event.message.interlocutor_id for event in events_to_process
                                               if event.type == EventTypes.NEW_MESSAGE and event.message.interlocutor_id is not None}
                
                updates = self.get_updates()
                new_events = self.parse_updates(updates)
                events_to_process.extend(new_events)

                remaining_events = []
                for event in events_to_process:
                    if self.make_buyer_viewing_requests and event.type == EventTypes.NEW_MESSAGE and event.message.interlocutor_id is not None:
                        event.message.buyer_viewing = self.buyers_viewing.get(event.message.interlocutor_id)
                        if event.message.buyer_viewing is None:
                            remaining_events.append(event)
                            continue
                    yield event
                
                events_to_process = remaining_events
                self.buyers_viewing.clear()
                
                if consecutive_errors > 0:
                    logger.info("Соединение с FunPay восстановлено в раннере.")
                consecutive_errors = 0

            except exceptions.RequestFailedError as e:
                consecutive_errors += 1
                logger.error(f"{e.short_str()} ({consecutive_errors}/{max_retries})")
                
                if e.status_code == 0:
                    if consecutive_errors >= max_retries:
                        raise e 
                    time.sleep(5)
                    continue
                
                if not ignore_exceptions:
                    raise e
                time.sleep(sleep_time + random.uniform(2, 7))

            except requests.exceptions.RequestException as e:
                consecutive_errors += 1
                logger.error(f"Сетевая ошибка runner ({consecutive_errors}/{max_retries}): {e}")
                
                if consecutive_errors >= max_retries:
                    raise e
                
                time.sleep(sleep_time + random.uniform(2, 7))

            except Exception as e:
                consecutive_errors += 1
                logger.error("Произошла непредвиденная ошибка при получении событий.", exc_info=True)
                if not ignore_exceptions or consecutive_errors >= max_retries:
                    raise e
            
            # ЛОГ: Сон
            logger.debug(f"Runner: сон {sleep_time:.2f} сек.")
            time.sleep(sleep_time)

# END OF FILE FunPayCortex/FunPayAPI/updater/runner.py
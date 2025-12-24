# --- НАЧАЛО ФАЙЛА FunPayCortex/Utils/config_loader.py ---

"""
В данном модуле написаны функции для валидации конфигов.
"""
import configparser
from configparser import ConfigParser, SectionProxy
import codecs
import os
import logging

from Utils.exceptions import (ParamNotFoundError, EmptyValueError, ValueNotValidError, SectionNotFoundError,
                              ConfigParseError, ProductsFileNotFoundError, NoProductVarError,
                              SubCommandAlreadyExists, DuplicateSectionErrorWrapper)
from Utils.cortex_tools import hash_password

logger = logging.getLogger("FPC.config_loader")


def check_param(param_name: str, section: SectionProxy, valid_values: list[str | None] | None = None,
                raise_if_not_exists: bool = True) -> str | None:
    """
    Проверяет, существует ли в переданной секции указанный параметр и если да, валидно ли его значение.
    """
    if param_name not in list(section.keys()):
        if raise_if_not_exists:
            raise ParamNotFoundError(param_name)
        return None

    value = section[param_name].strip()

    # Если значение пустое ("", оно не может быть None)
    if not value:
        if valid_values and None in valid_values:
            return value
        raise EmptyValueError(param_name)

    if valid_values and valid_values != [None] and value not in valid_values:
        raise ValueNotValidError(param_name, value, valid_values)
    return value


def create_config_obj(config_path: str) -> ConfigParser:
    """
    Создает объект конфига с нужными настройками.
    """
    config = ConfigParser(delimiters=(":",), interpolation=None)
    config.optionxform = str
    config.read_file(codecs.open(config_path, "r", "utf8"))
    return config


def load_main_config(config_path: str):
    """
    Парсит и проверяет на правильность основной конфиг.
    """
    config = create_config_obj(config_path)
    values = {
        "FunPay": {
            "golden_key": "any+empty",
            "user_agent": "any+empty",
            "autoRaise": ["0", "1"],
            "autoResponse": ["0", "1"],
            "autoDelivery": ["0", "1"],
            "multiDelivery": ["0", "1"],
            "autoRestore": ["0", "1"],
            "autoDisable": ["0", "1"],
            "oldMsgGetMode": ["0", "1"],
            "keepSentMessagesUnread": ["0", "1"],
            # Оставляем только ru для FunPay локали
            "locale": ["ru"]
        },

        "Telegram": {
            "enabled": ["0", "1"],
            "token": "any+empty",
            "secretKeyHash": "any",
            "blockLogin": ["0", "1"]
        },

        "CortexHosting": {
            "url": "any+empty",
            "token": "any+empty"
        },

        "Manager": {
            "registration_key": "any+empty"
        },

        "BlockList": {
            "blockDelivery": ["0", "1"],
            "blockResponse": ["0", "1"],
            "blockNewMessageNotification": ["0", "1"],
            "blockNewOrderNotification": ["0", "1"],
            "blockCommandNotification": ["0", "1"]
        },

        "NewMessageView": {
            "includeMyMessages": ["0", "1"],
            "includeFPMessages": ["0", "1"],
            "includeBotMessages": ["0", "1"],
            "notifyOnlyMyMessages": ["0", "1"],
            "notifyOnlyFPMessages": ["0", "1"],
            "notifyOnlyBotMessages": ["0", "1"],
            "showImageName": ["0", "1"]
        },

        "Greetings": {
            "ignoreSystemMessages": ["0", "1"],
            "sendGreetings": ["0", "1"],
            "greetingsText": "any",
            "greetingsCooldown": "any"
        },

        "OrderConfirm": {
            "watermark": ["0", "1"],
            "sendReply": ["0", "1"],
            "replyText": "any"
        },

        "ReviewReply": {
            "star1Reply": ["0", "1"],
            "star2Reply": ["0", "1"],
            "star3Reply": ["0", "1"],
            "star4Reply": ["0", "1"],
            "star5Reply": ["0", "1"],
            "star1ReplyText": "any+empty",
            "star2ReplyText": "any+empty",
            "star3ReplyText": "any+empty",
            "star4ReplyText": "any+empty",
            "star5ReplyText": "any+empty",
        },

        "Proxy": {
            "enable": ["0", "1"],
            "ip": "any+empty",
            "port": "any+empty",
            "login": "any+empty",
            "password": "any+empty",
            "check": ["0", "1"]
        },

        "Other": {
            "watermark": "any+empty",
            "requestsDelay": [str(i) for i in range(1, 101)],
            # Оставляем только ru для языка интерфейса
            "language": ["ru"]
        },
        
        "Statistics": {
            "enabled": ["0", "1"],
            "analysis_period": "any",
            "report_interval": "any"
        },

        "ManagerPermissions": {
            "autoResponse": ["0", "1"],
            "autoDelivery": ["0", "1"],
            "templates": ["0", "1"],
            "greetings": ["0", "1"],
            "orderConfirm": ["0", "1"],
            "reviewReply": ["0", "1"],
            "plugins": ["0", "1"],
            "proxy": ["0", "1"],
            "statistics": ["0", "1"]
        }
    }

    # Установка дефолтного водяного знака, если секции нет
    # ИЗМЕНЕНИЕ: Устанавливаем пустую строку по умолчанию вместо текста
    if "Other" not in config or "watermark" not in config["Other"]:
        if "Other" not in config:
            config.add_section("Other")
        config.set("Other", "watermark", "")
        with open(config_path, "w", encoding="utf-8") as f:
            config.write(f)

    # Добавление секций по умолчанию для обратной совместимости
    if "ManagerPermissions" not in config:
        config.add_section("ManagerPermissions")
        for perm in values["ManagerPermissions"]:
            config.set("ManagerPermissions", perm, "0")
        with open(config_path, "w", encoding="utf-8") as f:
            config.write(f)

    if "CortexHosting" not in config:
        config.add_section("CortexHosting")
        config.set("CortexHosting", "url", "")
        config.set("CortexHosting", "token", "")
        with open(config_path, "w", encoding="utf-8") as f:
            config.write(f)


    for section_name in values:
        if section_name not in config.sections():
            if section_name == "Manager":
                config.add_section("Manager")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "Statistics":
                config.add_section("Statistics")
                config.set("Statistics", "enabled", "1")
                config.set("Statistics", "analysis_period", "30")
                config.set("Statistics", "report_interval", "0")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            else:
                raise ConfigParseError(config_path, section_name, SectionNotFoundError())

        # UPDATE секция для совместимости
        if section_name == "Greetings" and "cacheInitChats" in config[section_name]:
            config.remove_option(section_name, "cacheInitChats")
            with open(config_path, "w", encoding="utf-8") as f:
                config.write(f)

        for param_name in values[section_name]:
            # Логика обновления старых конфигов
            if section_name == "FunPay" and param_name == "oldMsgGetMode" and param_name not in config[section_name]:
                config.set("FunPay", "oldMsgGetMode", "0")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "Manager" and param_name == "registration_key" and param_name not in config[section_name]:
                config.set("Manager", "registration_key", "")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "Greetings" and param_name == "ignoreSystemMessages" and param_name not in config[section_name]:
                config.set("Greetings", "ignoreSystemMessages", "0")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "Other" and param_name == "language" and param_name not in config[section_name]:
                config.set("Other", "language", "ru")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            
            # ПРИНУДИТЕЛЬНЫЙ СБРОС ЯЗЫКА НА RU
            # Если в конфиге стоит "en" или "uk", меняем на "ru"
            elif section_name == "Other" and param_name == "language":
                if config[section_name][param_name] != "ru":
                    config.set("Other", "language", "ru")
                    with open(config_path, "w", encoding="utf-8") as f:
                        config.write(f)
            # То же самое для локали FunPay
            elif section_name == "FunPay" and param_name == "locale":
                if param_name not in config[section_name] or config[section_name][param_name] != "ru":
                    config.set("FunPay", "locale", "ru")
                    with open(config_path, "w", encoding="utf-8") as f:
                        config.write(f)

            elif section_name == "Greetings" and param_name == "greetingsCooldown" and param_name not in config[section_name]:
                config.set("Greetings", "greetingsCooldown", "2")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "OrderConfirm" and param_name == "watermark" and param_name not in config[section_name]:
                config.set("OrderConfirm", "watermark", "1")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "FunPay" and param_name == "keepSentMessagesUnread" and param_name not in config[section_name]:
                config.set("FunPay", "keepSentMessagesUnread", "0")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "NewMessageView" and param_name == "showImageName" and param_name not in config[section_name]:
                config.set("NewMessageView", "showImageName", "1")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "Telegram" and param_name == "blockLogin" and param_name not in config[section_name]:
                config.set("Telegram", "blockLogin", "0")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)
            elif section_name == "Telegram" and param_name == "secretKeyHash" and param_name not in config[section_name]:
                if "secretKey" in config[section_name]:
                    config.set(section_name, "secretKeyHash", hash_password(config[section_name]["secretKey"]))
                    config.remove_option(section_name, "secretKey")
                    with open(config_path, "w", encoding="utf-8") as f:
                        config.write(f)
                else:
                     pass
            elif section_name == "ManagerPermissions" and param_name == "statistics" and param_name not in config[section_name]:
                config.set(section_name, "statistics", "0")
                with open(config_path, "w", encoding="utf-8") as f:
                    config.write(f)

            try:
                if values[section_name][param_name] == "any":
                    check_param(param_name, config[section_name])
                elif values[section_name][param_name] == "any+empty":
                    check_param(param_name, config[section_name], valid_values=[None])
                else:
                    check_param(param_name, config[section_name], valid_values=values[section_name][param_name])
            except (ParamNotFoundError, EmptyValueError, ValueNotValidError) as e:
                raise ConfigParseError(config_path, section_name, e)

    return config


def load_auto_response_config(config_path: str):
    """
    Парсит и проверяет на правильность конфиг команд.
    При ошибке возвращает пустой конфиг.
    """
    try:
        config = create_config_obj(config_path)
        command_sets = []
        for command in config.sections():
            try:
                check_param("response", config[command])
                check_param("telegramNotification", config[command], valid_values=["0", "1"], raise_if_not_exists=False)
                check_param("notificationText", config[command], raise_if_not_exists=False)
            except (ParamNotFoundError, EmptyValueError, ValueNotValidError) as e:
                raise ConfigParseError(config_path, command, e)

            if "|" in command:
                command_sets.append(command)

        for command_set in command_sets:
            commands = command_set.split("|")
            parameters = config[command_set]

            for new_command in commands:
                new_command = new_command.strip()
                if not new_command:
                    continue
                if new_command in config.sections():
                    raise ConfigParseError(config_path, command_set, SubCommandAlreadyExists(new_command))
                config.add_section(new_command)
                for param_name in parameters:
                    config.set(new_command, param_name, parameters[param_name])
        return config
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось прочитать файл auto_response.cfg. Ошибка: {e}")
        logger.warning("Модуль 'Автоответчик' будет работать с пустой конфигурацией. Пожалуйста, исправьте файл или настройте команды заново через Telegram-бота.")
        empty_config = ConfigParser(delimiters=(":",), interpolation=None)
        empty_config.optionxform = str
        return empty_config


def load_raw_auto_response_config(config_path: str):
    """
    Загружает исходный конфиг автоответчика.
    При ошибке возвращает пустой конфиг.
    """
    try:
        return create_config_obj(config_path)
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось прочитать RAW-файл auto_response.cfg. Ошибка: {e}")
        logger.warning("Модуль 'Автоответчик' будет работать с пустой конфигурацией. Пожалуйста, исправьте файл или настройте команды заново через Telegram-бота.")
        empty_config = ConfigParser(delimiters=(":",), interpolation=None)
        empty_config.optionxform = str
        return empty_config


def load_auto_delivery_config(config_path: str):
    """
    Парсит и проверяет на правильность конфиг автовыдачи.
    При ошибке возвращает пустой конфиг.
    """
    try:
        config = create_config_obj(config_path)
        for lot_title in config.sections():
            try:
                lot_response = check_param("response", config[lot_title])
                products_file_name = check_param("productsFileName", config[lot_title], raise_if_not_exists=False)
                check_param("disable", config[lot_title], valid_values=["0", "1"], raise_if_not_exists=False)
                check_param("disableAutoRestore", config[lot_title], valid_values=["0", "1"], raise_if_not_exists=False)
                check_param("disableAutoDisable", config[lot_title], valid_values=["0", "1"], raise_if_not_exists=False)
                check_param("disableAutoDelivery", config[lot_title], valid_values=["0", "1"], raise_if_not_exists=False)
                if products_file_name is None:
                    continue
            except (ParamNotFoundError, EmptyValueError, ValueNotValidError) as e:
                raise ConfigParseError(config_path, lot_title, e)

            if not os.path.exists(f"storage/products/{products_file_name}"):
                raise ConfigParseError(config_path, lot_title,
                                       ProductsFileNotFoundError(f"storage/products/{products_file_name}"))

            if "$product" not in lot_response:
                raise ConfigParseError(config_path, lot_title, NoProductVarError())
        return config
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось прочитать файл auto_delivery.cfg. Ошибка: {e}")
        logger.warning("Модуль 'Автовыдача' будет работать с пустой конфигурацией. Пожалуйста, исправьте файл или настройте автовыдачу заново через Telegram-бота.")
        empty_config = ConfigParser(delimiters=(":",), interpolation=None)
        empty_config.optionxform = str
        return empty_config

# END OF FILE FunPayCortex/Utils/config_loader.py
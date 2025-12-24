"""
В данном модуле написаны форматтеры для логгера.
"""
from colorama import Fore, Back, Style
import logging.handlers
import logging
import re
import os

# ИЗМЕНЕНИЕ: Импорт redis для Pub/Sub
try:
    import redis
except ImportError:
    redis = None


LOG_COLORS = {
        logging.DEBUG: Fore.BLACK + Style.BRIGHT,
        logging.INFO: Fore.GREEN,
        logging.WARN: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Back.RED
}

CLI_LOG_FORMAT = f"{Fore.BLACK + Style.BRIGHT}[%(asctime)s]{Style.RESET_ALL}"\
                 f"{Fore.CYAN}>{Style.RESET_ALL} $RESET%(levelname).1s: %(message)s{Style.RESET_ALL}"
CLI_TIME_FORMAT = "%d-%m-%Y %H:%M:%S"

FILE_LOG_FORMAT = "[%(asctime)s][%(filename)s][%(lineno)d]> %(levelname).1s: %(message)s"
FILE_TIME_FORMAT = "%d.%m.%y %H:%M:%S"
CLEAR_RE = re.compile(r"(\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))|(\n)|(\r)")


def add_colors(text: str) -> str:
    """
    Заменяет ключевые слова на коды цветов.
    """
    colors = {
        "$YELLOW": Fore.YELLOW,
        "$CYAN": Fore.CYAN,
        "$MAGENTA": Fore.MAGENTA,
        "$BLUE": Fore.BLUE,
        "$GREEN": Fore.GREEN,
        "$BLACK": Fore.BLACK,
        "$WHITE": Fore.WHITE,

        "$B_YELLOW": Back.YELLOW,
        "$B_CYAN": Back.CYAN,
        "$B_MAGENTA": Back.MAGENTA,
        "$B_BLUE": Back.BLUE,
        "$B_GREEN": Back.GREEN,
        "$B_BLACK": Back.BLACK,
        "$B_WHITE": Back.WHITE,
    }
    for c in colors:
        if c in text:
            text = text.replace(c, colors[c])
    return text


class CLILoggerFormatter(logging.Formatter):
    """
    Форматтер для вывода логов в консоль.
    """
    def format(self, record: logging.LogRecord) -> str:
        record_copy = logging.makeLogRecord(record.__dict__)
        message = record_copy.getMessage()
        message = add_colors(message)
        message = message.replace("$RESET", LOG_COLORS.get(record_copy.levelno, ''))
        record_copy.msg = message
        record_copy.args = ()
        log_format = CLI_LOG_FORMAT.replace("$RESET", Style.RESET_ALL + LOG_COLORS.get(record_copy.levelno, ''))
        formatter = logging.Formatter(log_format, CLI_TIME_FORMAT)
        return formatter.format(record_copy)


class FileLoggerFormatter(logging.Formatter):
    """
    Форматтер для сохранения логов в файл.
    """
    def format(self, record: logging.LogRecord) -> str:
        record_copy = logging.makeLogRecord(record.__dict__)
        message = record_copy.getMessage()
        record_copy.msg = CLEAR_RE.sub("", message)
        record_copy.args = ()
        formatter = logging.Formatter(FILE_LOG_FORMAT, FILE_TIME_FORMAT)
        return formatter.format(record_copy)


# ИЗМЕНЕНИЕ: Новый класс для отправки логов в Redis Pub/Sub
class RedisPubSubHandler(logging.Handler):
    def __init__(self, host, port, channel):
        super().__init__()
        self.channel = channel
        try:
            self.redis_client = redis.Redis(host=host, port=port, socket_connect_timeout=1)
        except Exception:
            self.redis_client = None

    def emit(self, record):
        if not self.redis_client:
            return
        try:
            # Формируем чистое сообщение, как для файла
            record_copy = logging.makeLogRecord(record.__dict__)
            message = record_copy.getMessage()
            clean_message = CLEAR_RE.sub("", message)
            
            # Добавляем метку времени для красоты (опционально)
            formatted_msg = f"[{self.formatTime(record, '%H:%M:%S')}] {record.levelname}: {clean_message}"
            
            # Публикуем в канал (fire and forget)
            self.redis_client.publish(self.channel, formatted_msg)
        except Exception:
            pass


LOGGER_CONFIG = {
    "version": 1,
    "handlers": {
        "file_handler": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "file_formatter",
            "filename": "logs/log.log",
            "maxBytes": 20 * 1024 * 1024,
            "backupCount": 25,
            "encoding": "utf-8"
        },

        "cli_handler": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "cli_formatter"
        }
    },

    "formatters": {
        "file_formatter": {
            "()": "Utils.logger.FileLoggerFormatter"
        },

        "cli_formatter": {
            "()": "Utils.logger.CLILoggerFormatter"
        }
    },

    "loggers": {
        "main": {
            "handlers": ["cli_handler", "file_handler"],
            "level": "DEBUG"
        },
        "FunPayAPI": {
            "handlers": ["cli_handler", "file_handler"],
            "level": "DEBUG"
        },
        "FPC": {
            "handlers": ["cli_handler", "file_handler"],
            "level": "DEBUG"
        },
        "TGBot": {
            "handlers": ["cli_handler", "file_handler"],
            "level": "DEBUG"
        },
        "TeleBot": {
            "handlers": ["file_handler"],
            "level": "ERROR",
            "propagate": "False"
        }
    }
}
import time
import psutil
import Utils.cortex_tools
import Utils.config_loader as cfg_loader
from first_setup import first_setup
from colorama import Fore, Style
from Utils.logger import LOGGER_CONFIG
import logging.config
import colorama
import sys
import os
import io
import signal
import fcntl
from cortex import Cortex
import Utils.exceptions as excs
from locales.localizer import Localizer
import configparser
import requests
import json
import types
import telebot
import random

sys.dont_write_bytecode = True

lock_file_handle = None

def acquire_lock(base_path: str):
    global lock_file_handle
    lock_path = os.path.join(base_path, "storage/cache/process.lock")
    
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    except Exception:
        pass

    try:
        lock_file_handle = open(lock_path, 'w')
        fcntl.flock(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        lock_file_handle.write(str(os.getpid()))
        lock_file_handle.flush()
        
        print(f"{Fore.GREEN}--- [LOCK] Блокировка процесса успешно захвачена. Дубликатов нет. ---{Style.RESET_ALL}", flush=True)
    except IOError:
        print(f"{Fore.RED}========================================================{Style.RESET_ALL}")
        print(f"{Fore.RED}   КРИТИЧЕСКАЯ ОШИБКА: КОНФЛИКТ ПРОЦЕССОВ (DOUBLE RUN){Style.RESET_ALL}")
        print(f"{Fore.RED}   Другая копия бота уже работает с этой папкой storage.{Style.RESET_ALL}")
        print(f"{Fore.RED}   Запуск отменен для предотвращения дублирования ответов.{Style.RESET_ALL}")
        print(f"{Fore.RED}========================================================{Style.RESET_ALL}", flush=True)
        sys.exit(1)

def ensure_single_instance_pid(base_path: str):
    pid_file = os.path.join(base_path, "storage/cache/pid.txt")
    current_pid = os.getpid()

    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                content = f.read().strip()
                old_pid = int(content) if content else None

            if old_pid and old_pid != current_pid and psutil.pid_exists(old_pid):
                if old_pid == 1:
                    print(f"{Fore.YELLOW}--- [WATCHDOG] Нашел старый PID: 1. Это системный процесс Docker. Пропускаю убийство. ---{Style.RESET_ALL}", flush=True)
                else:
                    print(f"{Fore.YELLOW}--- [WATCHDOG] Нашел старый процесс PID: {old_pid}. Убиваю... ---{Style.RESET_ALL}", flush=True)
                    try:
                        p = psutil.Process(old_pid)
                        p.terminate()
                        p.wait(timeout=3)
                    except:
                        try:
                            os.kill(old_pid, 9)
                        except: pass
        except:
            pass

    try:
        with open(pid_file, 'w') as f:
            f.write(str(current_pid))
    except: pass

logo = r"""
 ______________________________                __                 
\_   _____/\______   \_   ___ \  ____________/  |_  ____ ___  ___
 |    __)   |     ___/    \  \/ /  _ \_  __ \   __\/ __ \\  \/  /
 |     \    |    |   \     \___(  <_> )  | \/|  | \  ___/ >    < 
 \___  /    |____|    \______  /\____/|__|   |__|  \___  >__/\_ \
     \/                      \/                        \/      \/                                             
"""

VERSION = "2.0.3.5" 

Utils.cortex_tools.set_console_title(f"FunPay Cortex v{VERSION}")

# ПРИНУДИТЕЛЬНОЕ ОТКЛЮЧЕНИЕ РЕЖИМА ХОСТИНГА
IS_HOSTING_ENV = False
BASE_PATH = os.path.dirname(os.path.abspath(__file__))

if os.getenv('FPCORTEX_BASE_PATH') is None:
    os.chdir(BASE_PATH)

print(f"--- [INFO] Базовый путь для данных определен как: {BASE_PATH} ---", flush=True)

if sys.platform != "win32":
    acquire_lock(BASE_PATH)
ensure_single_instance_pid(BASE_PATH)

folders = ["configs", "logs", "storage", "storage/cache", "storage/products", "plugins"]
for i in folders:
    path_to_create = os.path.join(BASE_PATH, i)
    if not os.path.exists(path_to_create):
        os.makedirs(path_to_create, exist_ok=True)

main_cfg_path = os.path.join(BASE_PATH, "configs/_main.cfg")
ar_cfg_path = os.path.join(BASE_PATH, "configs/auto_response.cfg")
ad_cfg_path = os.path.join(BASE_PATH, "configs/auto_delivery.cfg")

colorama.init()

LOGGER_CONFIG['handlers']['file_handler']['filename'] = os.path.join(BASE_PATH, 'logs/log.log')
logging.config.dictConfig(LOGGER_CONFIG)

root_logger = logging.getLogger()
for handler in root_logger.handlers:
    if isinstance(handler, logging.StreamHandler):
        class FlushFilter(logging.Filter):
            def filter(self, record):
                handler.flush()
                return True
        handler.addFilter(FlushFilter())

logger = logging.getLogger("main")
logger.debug("------------------------------------------------------------------")

print(f"{Style.RESET_ALL}{Fore.CYAN}{logo}{Style.RESET_ALL}\n")
print(f"{Fore.RED}{Style.BRIGHT}v{VERSION}{Style.RESET_ALL}\n")
print(f"{Fore.MAGENTA}{Style.BRIGHT}Автор: {Fore.BLUE}{Style.BRIGHT}@beedge{Style.RESET_ALL}")

if not os.path.exists(main_cfg_path):
    # Так как IS_HOSTING_ENV всегда False, сработает только эта ветка
    logger.info("Основной конфиг не найден, запускаю первичную настройку...")
    first_setup()
    sys.exit()

if sys.platform == "linux" and os.getenv('FPCORTEX_IS_RUNNING_AS_SERVICE', '0') == '1':
    import getpass
    service_name = "FunPayCortex"
    run_dir = f"/run/{service_name}"
    user_run_dir = f"{run_dir}/{getpass.getuser()}"
    pid_file_path = f"{user_run_dir}/{service_name}.pid"

    if not os.path.exists(run_dir):
        os.makedirs(run_dir, mode=0o755)
    if not os.path.exists(user_run_dir):
         os.makedirs(user_run_dir, mode=0o755)

    try:
        pid = str(os.getpid())
        with open(pid_file_path, "w") as pidFile:
             pidFile.write(pid)
        logger.info(f"$GREENPID файл службы создан: {pid_file_path}, PID: {pid}")
    except Exception as e:
         logger.error(f"Не удалось создать PID файл службы {pid_file_path}: {e}")

def sigterm_handler(_signo, _stack_frame):
    logger.info("Получен сигнал SIGTERM (остановка контейнера). Завершаем работу...")
    if 'cortex_instance' in globals() and cortex_instance:
        cortex_instance.stop() 
    sys.exit(0)

signal.signal(signal.SIGTERM, sigterm_handler)
signal.signal(signal.SIGINT, sigterm_handler)

try:
    pre_main_cfg = cfg_loader.load_main_config(main_cfg_path)
    
    # Блок проверки переменных окружения для хостинга удален
    
    if pre_main_cfg["Proxy"]["ip"] and pre_main_cfg["Proxy"]["port"]:
         logger.info("Данные прокси обнаружены в конфиге.")
    
    raw_ar_cfg_obj = cfg_loader.load_raw_auto_response_config(ar_cfg_path)
    ar_config_failed = not raw_ar_cfg_obj.sections() and os.path.exists(ar_cfg_path) and os.path.getsize(ar_cfg_path) > 0

    ad_cfg_obj = cfg_loader.load_auto_delivery_config(ad_cfg_path)
    ad_config_failed = not ad_cfg_obj.sections() and os.path.exists(ad_cfg_path) and os.path.getsize(ad_cfg_path) > 0

    localizer = Localizer(pre_main_cfg["Other"]["language"])
    _ = localizer.translate

    cortex_instance = Cortex(pre_main_cfg, raw_ar_cfg_obj, VERSION, BASE_PATH, IS_HOSTING_ENV)
    cortex_instance.AR_CFG_LOAD_ERROR = ar_config_failed
    cortex_instance.AD_CFG_LOAD_ERROR = ad_config_failed

    # Блок переопределения методов сохранения конфига (Monkey Patching) удален

    cortex_instance.init()
    
    cortex_instance.executor.submit(cortex_instance.run)

    if cortex_instance.telegram:
        logger.info("Запуск Telegram Bot Polling (Main Thread)...")
        try:
            cortex_instance.telegram.bot.infinity_polling(
                logger_level=logging.WARNING,
                timeout=60,
                long_polling_timeout=30,
                allowed_updates=["message", "callback_query"]
            )
        except Exception as e:
            logger.critical(f"Telegram Polling Critical Error: {e}")
    else:
        logger.info("Telegram-бот отключен. Основной процесс переходит в режим ожидания.")
        while True:
            time.sleep(3600)

except excs.ConfigParseError as e:
    logger.error(e)
    logger.error("Завершаю программу...")
    time.sleep(5)
    sys.exit(1)
except UnicodeDecodeError:
    logger.error("Произошла ошибка при расшифровке UTF-8. Убедитесь, что кодировка файла — UTF-8, "
                 "а формат конца строк — LF.")
    logger.error("Завершаю программу...")
    time.sleep(5)
    sys.exit(1)
except Exception:
    logger.critical("При работе Кортекса произошла необработанная ошибка.")
    logger.warning("TRACEBACK", exc_info=True)
    logger.critical("Завершаю программу...")
    if 'cortex_instance' in locals() and cortex_instance:
        cortex_instance.executor.shutdown(wait=False, cancel_futures=True)
    time.sleep(5)
    sys.exit(1)
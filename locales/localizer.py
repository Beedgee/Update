# START OF FILE FunPayCortex/locales/localizer.py

from typing import Literal
from locales import ru
import logging

logger = logging.getLogger("localizer")


class Localizer:
    def __new__(cls, curr_lang: str | None = None):
        if not hasattr(cls, "instance"):
            cls.instance = super(Localizer, cls).__new__(cls)
            cls.instance.languages = {
                "ru": ru
            }
            cls.instance.current_language = "ru"
        return cls.instance

    def _get_translation(self, variable_name: str, language: str):
        lang_module = self.languages.get(language)
        # Если язык не найден (например, старый конфиг просит 'en'), используем ru
        if not lang_module:
            lang_module = self.languages.get("ru")
            
        if lang_module and hasattr(lang_module, variable_name):
            return getattr(lang_module, variable_name)
        return None

    def translate(self, variable_name: str, *args, **kwargs):
        """
        Возвращает форматированный локализированный текст (Всегда русский).
        """
        # Игнорируем переданный язык, всегда используем ru
        kwargs.pop('language', None)
        
        text = self._get_translation(variable_name, "ru")
        
        # Если в русском нет, вернуть имя переменной
        if text is None:
            text = variable_name

        try:
            return text.format(*args, **kwargs)
        except (IndexError, KeyError) as e:
            logger.debug(f"Ошибка форматирования для переменной '{variable_name}' с текстом '{text}' и аргументами {args}, {kwargs}: {e}", exc_info=True)
            return text


    def add_translation(self, uuid: str, variable_name: str, value: str, language: Literal["uk", "ru", "en"]):
        """Позволяет добавить перевод фраз из плагина (только для ru)."""
        if language == "ru":
            setattr(self.languages["ru"], f"{uuid}_{variable_name}", value)

    def plugin_translate(self, uuid: str, variable_name: str, *args, **kwargs):
        """Позволяет получить перевод фраз из плагина."""
        prefixed_variable_name = f"{uuid}_{variable_name}"
        
        translation = self.translate(prefixed_variable_name, *args, **kwargs)
        
        if translation == prefixed_variable_name:
            return self.translate(variable_name, *args, **kwargs)
        
        return translation
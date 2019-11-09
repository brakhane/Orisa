import gettext
import logging
import re

from contextvars import ContextVar

from curious.commands.manager import CommandsManager
from curious.core.event import EventContext
from curious.dataclasses.message import Message

from .utils import run_sync

logger = logging.getLogger(__name__)


DEFAULT_LOCALE = "en"

LOCALES = [
    "cs",
    "de",
    "es",
    "fi",
    "fr",
    "it",
    "nb_NO",
    "nl",
    "pl",
    "pt_BR",
    "pt_PT",
    "ru",
]

CurrentLocale: ContextVar[str] = ContextVar("CurrentLocale", default=DEFAULT_LOCALE)

_REGIONAL_A_ORD = ord("\N{REGIONAL INDICATOR SYMBOL LETTER A}")

FLAG_TO_LOCALE = {
    ''.join(chr(ord(ch) - ord('A') + _REGIONAL_A_ORD) for ch in locale[-2:].upper()): locale
    for locale in LOCALES
}
FLAG_TO_LOCALE["🇬🇧"] = "en"

TRANSLATIONS = {
    locale: gettext.translation("bot", localedir="orisa/locale", languages=[locale])
    for locale in LOCALES
}

class MultiString(str):
    """fluent inspired string that can take multiple conditions.

    It can be a normal string, or, if it starts with << a special string:

    <<key1>> text1
    text1
    text1
    <<*key2>> text2
    text2
    <<key3>> text3

    This will make "text2\ntext2" the default (because of the *), but it can be used like
    a dictionary, so in a format string, one could use "foo[key1]" to get "text1\text1\text1"
    """
    
    def __new__(cls, val):
        if val.startswith("<<"):
            value_map = {}
            for key, text in re.findall(r"^<<([*\w]+)>> (.*?)$", val, re.MULTILINE | re.DOTALL):
                if key.startswith("*"):
                    default = text
                    key = key[1:]
                value_map[key] = text
        else:
            return super().__new__(cls, val)

        inst = super().__new__(cls, default)
        inst.value_map = value_map
        return inst

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.value_map[key]
        else:
            return super().__getitem__(key)


class I18NCommandsManager(CommandsManager):
    async def handle_commands(self, ctx: EventContext, message: Message):
        guild_id = message.guild_id
        try:
            orisa = self.plugins["Orisa"]
        except KeyError:
            logger.debug("Not initialized yet, ignoring command")
            return
        # guild_config is a defaultdict, so we can just lookup, even if guild_id is None
        locale = orisa.guild_config[guild_id].locale

        if not locale:
            locale = orisa._welcome_language.get(guild_id, None)

        # update locale for user, or get locale from user if we have no locale
        async with orisa.database.session() as session:
            user = await orisa.database.user_by_discord_id(session, message.author_id)
            if user:
                if locale:
                    if user.locale != locale:
                        user.locale = locale
                        await run_sync(session.commit)
                elif guild_id is None:
                    # only change language in private messages
                    locale = user.locale

        CurrentLocale.set(locale or DEFAULT_LOCALE)
        return await super().handle_commands(ctx, message)

def N_(x):
    "No-op to mark strings that need to be translated, but not at this exact spot"
    return x

def NP_(sing, plural):
    return sing

def _(msg):
    locale = CurrentLocale.get()
    return get_translation(locale, msg)

def get_translation(locale, msg):
    if locale and locale != DEFAULT_LOCALE:
        return MultiString(TRANSLATIONS[locale].gettext(msg))
    else:
        return MultiString(msg)

def ngettext(singular, plural, n):
    locale = CurrentLocale.get()
    if locale and locale != DEFAULT_LOCALE:
        return MultiString(TRANSLATIONS[locale].ngettext(singular, plural, n))
    else:
        return MultiString(singular if n==1 else plural)

def locale_by_flag(flag):
    return FLAG_TO_LOCALE.get(flag, None)

def get_all_locales():
    return LOCALES + [DEFAULT_LOCALE]

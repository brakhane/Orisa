import gettext
import logging

from contextvars import ContextVar

from curious.commands.manager import CommandsManager
from curious.core.event import EventContext
from curious.dataclasses.message import Message
from trio.to_thread import run_sync

logger = logging.getLogger(__name__)


DEFAULT_LOCALE = "en"

LOCALES = [
    "cs",
    "de",
    "es",
    "fi",
    "fr",
    "it",
    "nl",
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

class I18NCommandsManager(CommandsManager):
    async def handle_commands(self, ctx: EventContext, message: Message):
        guild_id = message.guild_id
        try:
            orisa = self.plugins["Orisa"]
        except KeyError:
            logger.debug("Not initialized yet, ignoring command", exc_info=True)
            return
        # guild_config is a defaultdict, so we can just lookup, even if guild_id is None
        locale = orisa.guild_config[guild_id].locale

        # update locale for user, or get locale from user if we have no locale
        async with orisa.database.session() as session:
            user = await orisa.database.user_by_discord_id(session, message.author_id)
            if user:
                if locale:
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

def _(msg):
    locale = CurrentLocale.get()
    return get_translation(locale, msg)

def get_translation(locale, msg):
    if locale and locale != DEFAULT_LOCALE:
        return TRANSLATIONS[locale].gettext(msg)
    else:
        return msg

def ngettext(singular, plural, n):
    locale = CurrentLocale.get()
    if locale and locale != DEFAULT_LOCALE:
        return TRANSLATIONS[locale].ngettext(singular, plural, n)
    else:
        return singular if n==0 else plural

def locale_by_flag(flag):
    return FLAG_TO_LOCALE.get(flag, None)

def get_all_locales():
    return LOCALES + [DEFAULT_LOCALE]
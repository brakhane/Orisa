import gettext

from contextvars import ContextVar

from curious.commands.manager import CommandsManager
from curious.core.event import EventContext
from curious.dataclasses.message import Message


CurrentLocale: ContextVar[str] = ContextVar("CurrentLocale", default="es")

LOCALES = [
    "de",
    "es",
    "nl",
    "pt_BR",
    "pt_PT",
]

TRANSLATIONS = {
    locale: gettext.translation("bot", localedir="orisa/locale", languages=[locale])
    for locale in LOCALES
}



class I18NCommandsManager(CommandsManager):
    async def handle_commands(self, ctx: EventContext, message: Message):
        CurrentLocale.set("de")
        return await super().handle_commands(ctx, message)

def N_(x):
    "No-op to mark strings that need to be translated, but not at this exact spot"
    return x

def _(msg):
    locale = CurrentLocale.get()
    if locale and locale != 'en':
        return TRANSLATIONS[locale].gettext(msg)
    else:
        return msg

def ngettext(singular, plural, n):
    locale = CurrentLocale.get()
    if locale and locale != 'en':
        return TRANSLATIONS[locale].ngettext(singular, plural, n)
    else:
        return singular if n==0 else plural


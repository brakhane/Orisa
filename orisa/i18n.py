from contextvars import ContextVar

from curious.commands.manager import CommandsManager
from curious.core.event import EventContext
from curious.dataclasses.message import Message


Language: ContextVar[str] = ContextVar("Language", default="?")

class I18NCommandsManager(CommandsManager):
    async def handle_commands(self, ctx: EventContext, message: Message):
        Language.set(f"{message.channel}")
        return await super().handle_commands(ctx, message)

def N_(x):
    "No-op to mark strings that need to be translated, but not at this exact spot"
    return x

def _(msg):
    return Language.get() + "---" + msg


import logging
import traceback
import yaml


import multio
import trio

import raven
from curious.commands.manager import CommandsManager
from curious.dataclasses.presence import Game, GameType, Status

from . import web
from .config import SENTRY_DSN, BOT_TOKEN, GLADOS_TOKEN, MASHERY_API_KEY
from .models import Database
from .orisa import Orisa, OrisaClient
from .wow import Wow


multio.init("trio")

with open("logging.yaml") as logfile:
    logging.config.dictConfig(yaml.safe_load(logfile))

logger = logging.getLogger(__name__)

if SENTRY_DSN:
    logger.info("USING SENTRY")
    raven_client = raven.Client(
        dsn=SENTRY_DSN, release=raven.fetch_git_sha(os.path.dirname(__file__))
    )

    @client.event("command_error")
    async def command_error(ev_ctx, ctx, err):
        exc_info = (type(err), err, err.__traceback__)
        raven_client.captureException(exc_info)
        fmtted = "".join(traceback.format_exception(*exc_info))
        logger.error(f"Error in command!\n{fmtted}")


else:
    raven_client = None
    logger.info("NOT USING SENTRY")


client = OrisaClient(BOT_TOKEN)

database = Database()

manager = CommandsManager.with_client(client, command_prefix="!")


@client.event("ready")
async def ready(ctx):
    logger.debug(f"Guilds are {ctx.bot.guilds}")
    await manager.load_plugin(Orisa, database, raven_client)

    msg = "!ow help"
    if MASHERY_API_KEY:
        await manager.load_plugin(Wow, database)
        msg += " | !wow help"
    await ctx.bot.change_status(game=Game(name=msg, type=GameType.LISTENING_TO))
    logger.info("Ready")


client.run()

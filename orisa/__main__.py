# Orisa, a simple Discord bot with good intentions
# Copyright (C) 2018, 2019 Dennis Brakhane
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, version 3 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import logging
import os
import traceback
import yaml


import multio
import trio
from dataclasses import dataclass

import raven
from curious.dataclasses.presence import Game, GameType, Status
from curious.commands.exc import ConversionFailedError
from curious.commands.utils import prefix_check_factory

from . import web
from .config import SENTRY_DSN, BOT_TOKEN, GLADOS_TOKEN, MASHERY_API_KEY, DEVELOPMENT
from .i18n import I18NCommandsManager
from .models import Database
from .orisa import Orisa, OrisaClient


multio.init("trio")

with open("logging.yaml") as logfile:
    logging.config.dictConfig(yaml.safe_load(logfile))

logger = logging.getLogger("orisa.main")

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

command_prefix="!" if not DEVELOPMENT else ","
curious_message_check = prefix_check_factory(command_prefix)

@dataclass
class FakeMessage:
    content: str

async def my_message_check(bot, message):
    orig_msg = msg = message.content.strip()
    mention = f"<@{bot.application_info.client_id}>"
    if msg.startswith(mention):
        msg = msg.replace(mention, "").replace(f"{command_prefix}ow", "").strip()
        msg = f"{command_prefix}ow {msg}"
        logger.debug(f"Converted [{orig_msg}] to [{msg}]")
    return await curious_message_check(bot, FakeMessage(msg))
    

manager = I18NCommandsManager.with_client(
    client, message_check=my_message_check
)

already_loaded = False


@client.event("ready")
async def ready(ctx):
    global already_loaded

    if already_loaded:
        logger.info("Ignoring second call to ready")
    else:
        already_loaded = True
        await manager.load_plugin(Orisa, database, raven_client)

    logger.debug(f"I'm in {len(ctx.bot.guilds)} guilds, shard id is {ctx.shard_id}")

    msg = "@Orisa help" if not DEVELOPMENT else "@Orisa Test help"
    await ctx.bot.change_status(game=Game(name=msg, type=GameType.LISTENING_TO))

    class Logger:
        def before_task_step(self, task):
            logger.debug(f">>> task step {task.name}")

        def task_exited(self, task):
            logger.debug(f"<<< task end {task.name}")

    # trio.hazmat.add_instrument(Logger())

@client.event("command_error")
async def command_error(ev_ctx, ctx, err):
    if isinstance(err, ConversionFailedError):
        await ctx.channel.messages.send(str(err))
    else:
        fmtted = ''.join(traceback.format_exception(type(err), err, err.__traceback__))
        logger.error(f"Error in command!\n{fmtted}")

client.run(autoshard=False)

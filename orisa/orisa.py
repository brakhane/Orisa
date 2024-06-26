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
from collections import defaultdict
from contextlib import contextmanager, nullcontext, suppress
from contextvars import ContextVar
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from itertools import groupby
import logging
import logging.config
from operator import attrgetter
import random
import re
from string import Template
import tempfile
import time
import urllib.parse
import warnings

import arrow
import cachetools
from curious import event
from curious.commands.conditions import author_has_roles
from curious.commands.context import Context
from curious.commands.decorators import command, condition
from curious.commands.exc import ConversionFailedError
from curious.commands.plugin import Plugin
from curious.core.client import Client
from curious.core.event import EventContext
from curious.core.httpclient import HTTPClient
from curious.dataclasses.channel import ChannelType
from curious.dataclasses.embed import Embed
from curious.dataclasses.guild import Guild
from curious.dataclasses.member import Member
from curious.dataclasses.presence import Game, Status
from curious.exc import Forbidden, HierarchyError, NotFound, PermissionsError
import dateutil.parser as date_parser
from fuzzywuzzy import fuzz, process
import hypercorn.config
import hypercorn.trio
from itsdangerous.url_safe import URLSafeTimedSerializer
import matplotlib
import matplotlib.pyplot as plt
import multio
import numpy as np
from oauthlib.oauth2 import WebApplicationClient
import pandas as pd
from pandas.plotting import register_matplotlib_converters
import raven
import seaborn as sns
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import desc, func
import tabulate
import trio
from trio.to_thread import run_sync
from typing_extensions import Literal
import unicodedata2 as unicodedata

from . import i18n, web
from .config import (
    CHANNEL_NAMES,
    GLADOS_TOKEN,
    GuildConfig,
    OAUTH_BLIZZARD_CLIENT_ID,
    OAUTH_DISCORD_CLIENT_ID,
    OAUTH_REDIRECT_HOST,
    OAUTH_REDIRECT_PATH,
    PRIVACY_POLICY_PATH,
    RANK_EMOJIS,
    ROLE_EMOJIS,
    SIGNING_SECRET,
    WEB_APP_PATH,
)
from .exceptions import (
    BlizzardError,
    InvalidBattleTag,
    InvalidFormat,
    NicknameTooLong,
    UnableToFindSR,
)
from .i18n import CurrentLocale, N_, _, locale_by_flag, ngettext
from .models import (
    BattleTag,
    Gamertag,
    GuildConfigJson,
    Handle,
    HighscoreCron,
    OnlineID,
    Role,
    SR,
    User,
    WelcomeMessage,
)
from .utils import (
    TDS,
    get_sr,
    reply,
    resolve_handle_or_index,
    run_sync,
    send_long,
    sort_secondaries,
    sr_to_rank,
)

matplotlib.use("Agg")  # noqa


logger = logging.getLogger("orisa")


OAUTH_SERIALIZER = URLSafeTimedSerializer(SIGNING_SECRET)

SUPPORT_DISCORD = "https://discord.gg/ZKzBEDF"
VOTE_LINK = "https://discordbots.org/bot/445905377712930817/vote"
DONATE_LINK = "https://ko-fi.com/R5R2PC36"
TRANSLATE_LINK = "https://hosted.weblate.org/engage/orisa/"

RANKS = (
    # Translators: 2 letter code for "Bronze" rank
    N_("Br"),
    # Translators: 2 letter code for "Silver" rank
    N_("Si"),
    # Translators: 2 letter code for "Gold" rank
    N_("Go"),
    # Translators: 2 letter code for "Platinum" rank
    N_("Pt"),
    # Translators: 2 letter code for "Diamond" rank
    N_("Dm"),
    # Translators: 2 letter code for "Master" rank
    N_("Ma"),
    # Translators: 2 letter code for "Grandmaster" rank
    N_("GM"),
    # Translators: 2 letter code for "Champion" rank
    N_("CH"),
    
)
FULL_RANKS = (
    # Translators: SR rank
    N_("Bronze"),
    # Translators: SR rank
    N_("Silver"),
    # Translators: SR rank
    N_("Gold"),
    # Translators: SR rank
    N_("Platinum"),
    # Translators: SR rank
    N_("Diamond"),
    # Translators: SR rank
    N_("Master"),
    # Translators: SR rank
    N_("Grandmaster"),
    # Translators: SR rank
    N_("Champion"),
)

ROLE_NAMES = [
    # Translators: Role
    N_("Tank"),
    # Translators: Role
    N_("Damage"),
    # Translators: Role
    N_("Support"),
]

COLORS = (
    0xCD7E32,  # Bronze
    0xC0C0C0,  # Silver
    0xFFD700,  # Gold
    0xE5E4E2,  # Platinum
    0xA2BFD3,  # Diamond
    0xF9CA61,  # Master
    0xF1D592,  # Grand Master
    0x9F41E2,  # Champion
)


PROFILER = __import__("cProfile").Profile()
PROFILER.disable()

# Conditions


def correct_channel(ctx):
    return (
        any(
            ctx.channel.id == guild.listen_channel_id
            for guild in Orisa._instance.guild_config.values()
        )
        or ctx.channel.private
    )


def only_owner(ctx):
    try:
        return (
            ctx.author.id == ctx.bot.application_info.owner.id and ctx.channel.private
        )
    except AttributeError:
        # application_info is None
        return False


def only_owner_all_channels(ctx):
    try:
        return ctx.author.id == ctx.bot.application_info.owner.id
    except AttributeError:
        # application_info is None
        return False


def rank_fmt(sr, short=False):
    rank = sr_to_rank(sr)
    div = 5 - (sr // 100 % 5)
    return f"{_(RANKS[rank])}{div}" if short else f"{_(FULL_RANKS[rank])} {div}"

@dataclass
class ChannelRenameLimit:
    lock: trio.Lock
    reset_time: float
    remaining: int


# Main Orisa code
class Orisa(Plugin):

    SYMBOL_DPS = "\N{CROSSED SWORDS}"
    SYMBOL_TANK = "\N{SHIELD}"
    SYMBOL_SUPPORT = "\N{HEAVY GREEK CROSS}"

    # dirty hack needed for correct_channel condition
    _instance = None

    def __init__(self, client, database, raven_client):
        super().__init__(client)
        Orisa._instance = self
        self.database = database
        self.dialogues = {}
        self.web_send_ch, self.web_recv_ch = trio.open_memory_channel(5)
        self.raven_client = raven_client
        self.sync_cache = cachetools.TTLCache(maxsize=1000, ttl=30)
        self.stopped_playing_cache = cachetools.TTLCache(maxsize=1000, ttl=10)

        self.guild_config = defaultdict(GuildConfig.default)

        self._new_channel_name = {}
        self._channel_rename_limit = cachetools.LRUCache(maxsize=1000)

        self._welcome_language = cachetools.LRUCache(maxsize=500)

        # Translators: sent by Orisa when she joins a new server
        self._welcome_text = N_(
            "*Greetings*! I am excited to be here :smiley:\n"
            "To get started, create a new role named `Orisa Admin` (only the name is important, it doesn't need any special permissions) and add yourself "
            "and everybody that should be allowed to configure me.\n"
            "Then, write `@Orisa config` in this channel and I will send you a link to configure me via DM.\n"
            "*I will ignore all commands except `@Orisa help` and `@Orisa config` until I'm configured for this Discord!*"
        )

        self._welcome_embed_title = N_(":thinking: Need help?")
        self._welcome_embed_desc = N_("Join the [Support Discord]({SUPPORT_DISCORD})!")
        self._welcome_private_message_info = N_(
            "\n\n*Somebody (hopefully you) invited me to your server {guild_name}, but I couldn't find a "
            "text channel I am allowed to send messages to, so I have to message you directly*"
        )

    async def load(self):

        async with self.database.session() as session:
            for config in await run_sync(
                session.query(GuildConfigJson)
                .filter(GuildConfigJson.id.in_(self.client.guilds.keys()))
                .all
            ):
                self.guild_config[config.id] = data = GuildConfig.from_json2(
                    config.config
                )

        logger.warn("TEMPORARILY NOT SENDING MESSAGES TO GUILDS!")
        # await self.spawn(self._message_new_guilds)

        await self.spawn(self._sync_all_handles_task)

        logger.info("spawning cron")
        await self.spawn(self._cron_task)

        await self.spawn(self._web_server)

        await self.spawn(self._oauth_result_listener)

    # admin commands

    @command()
    @condition(only_owner, bypass_owner=False)
    async def qqqq(self, ctx):
            await reply(ctx, str(await get_sr(BattleTag())))

    @command()
    @condition(only_owner)
    async def farmcheck(self, ctx):
        await reply(ctx, "checking")
        farm = []
        for guild in self.client.guilds.values():
            humans, bots = [], []
            for member in guild.members.values():
                (bots if member.user.bot else humans).append(member)
            if 3 < len(bots) > len(humans):
                farm.append((guild, len(bots), len(humans)))
        await reply(ctx, "done")
        farm.sort(key=lambda x: x[1])
        await send_long(
            ctx.channel.messages.send,
            "\n".join(
                f"{guild.name} ({guild.id}) with {nb} bots and {nh} humans"
                for guild, nb, nh in farm
            ),
        )

    @command()
    @condition(only_owner, bypass_owner=False)
    async def startp(self, ctx):
        PROFILER.enable()
        await reply(ctx, "starting profiling")

    @command()
    @condition(only_owner, bypass_owner=False)
    async def stopp(self, ctx):
        PROFILER.disable()
        PROFILER.dump_stats("/tmp/orisaprof")
        await reply(ctx, "stopped profiling")

    @command()
    @condition(only_owner, bypass_owner=False)
    async def shutdown(self, ctx, safety: str = None):
        if safety != "Orisa":
            await reply(
                ctx,
                "If you want me to shut down, you need to issue `!shutdown Orisa` exactly as shown",
            )
        logger.critical("***** GOT EMERGENCY SHUTDOWN COMMAND FROM OWNER *****")
        try:
            await reply(ctx, "Shutting down…")
        except:
            pass
        try:
            await self.client.kill()
        except:
            pass
        raise SystemExit(42)

    @command()
    @condition(only_owner, bypass_owner=False)
    async def restart(self, ctx):
        logger.critical("***** GOT RESTART COMMAND FROM OWNER *****")
        try:
            await reply(ctx, "Restarting…")
        except:
            pass
        try:
            await self.client.kill()
        except:
            pass
        raise SystemExit(0)

    @command()
    @condition(only_owner, bypass_owner=False)
    async def createallchannels(self, ctx):
        logger.info("creating all channels")

        for gi in self.guild_config.copy().values():
            for vc in gi.managed_voice_categories:
                await self._adjust_voice_channels(
                    self.client.find_channel(vc.category_id), create_all_channels=True
                )

    @command()
    @condition(only_owner, bypass_owner=False)
    async def adjustallchannels(self, ctx):
        for gi in self.guild_config.copy().values():
            for vc in gi.managed_voice_categories:
                await self._adjust_voice_channels(
                    self.client.find_channel(vc.category_id)
                )

    @command()
    @condition(only_owner, bypass_owner=False)
    async def messageallusers(self, ctx, *, message: str):
        async with self.database.session() as s:
            users = await run_sync(s.query(User).all)
            for user in users:
                try:
                    logger.debug(f"Sending message to {user.discord_id}")
                    u = await self.client.get_user(user.discord_id)
                    await u.send(message)
                except:
                    logger.exception(f"Could not send to {user.discord_id}")
            logger.debug("All messages sent")

    @command()
    @condition(only_owner, bypass_owner=False)
    async def messageallservers(self, ctx, *, message: str):
        for guild_config in self.guild_config.copy().values():
            try:
                logger.debug(f"Sending message to {guild_config}")
                ch = self.client.find_channel(guild_config.listen_channel_id)
                await ch.messages.send(message)
            except:
                logger.exception(f"Error while sending to {guild_config}")
        logger.debug("Done sending")

    @command()
    @condition(only_owner, bypass_owner=False)
    async def messageserverowners(self, ctx, *, message: str):
        for guild in self._configured_guilds():
            try:
                logger.info(
                    "working on guild %s with owner %s (%s)",
                    guild,
                    guild.owner,
                    guild.owner.name,
                )
                # await ctx.author.send(
                #     f"sending to {guild.owner.mention} ({guild.owner.name}) of {guild}"
                # )
                await guild.owner.send(message)
            except Exception:
                logger.exception("unable to send to owner of guild %s", guild)

    @command()
    @condition(only_owner, bypass_owner=False)
    async def post(self, ctx, channel_id: str, *, message: str):
        await self._post(ctx, channel_id, message, glados=False)

    @command()
    @condition(only_owner, bypass_owner=False)
    async def gpost(self, ctx, channel_id: str, *, message: str):
        await self._post(ctx, channel_id, message, glados=True)

    async def _post(self, ctx, channel_id: str, message: str, glados: bool):
        try:
            channel_id = CHANNEL_NAMES[channel_id]
        except KeyError:
            channel_id = int(channel_id)
        channel = self.client.find_channel(channel_id)
        with self.client.as_glados() if glados else nullcontext():
            logger.info(ctx.message.embeds)
            logger.info(ctx.message.attachments)
            try:
                embed = ctx.message.embeds[0]
            except IndexError:
                embed = None
            if ctx.message.attachments:
                attachment = ctx.message.attachments[0]

                data = await attachment.download()
                msg = await channel.messages.upload(
                    data,
                    filename=attachment.filename,
                    message_content=message,
                    message_embed=embed,
                )
            else:
                msg = await channel.messages.send(content=message, embed=embed)
        await ctx.channel.messages.send(f"created {msg.id}")

    @command()
    @condition(only_owner, bypass_owner=False)
    async def gdelete(self, ctx, channel_id: str, message_id: int = None):
        with self.client.as_glados():
            await self.delete(ctx, channel_id, message_id)

    @command()
    @condition(only_owner, bypass_owner=False)
    async def delete(self, ctx, channel_id: str, message_id: int = None):
        match = re.match(
            r"https://discord.com/channels/[0-9]+/([0-9]+)/([0-9]+)", channel_id
        )
        if match:
            channel_id = int(match.group(1))
            message_id = int(match.group(2))

        try:
            channel_id = CHANNEL_NAMES[channel_id]
        except KeyError:
            channel_id = int(channel_id)
        # low level access, because getting a message requires MESSAGE_HISTORY permission
        await self.client.http.delete_message(channel_id, message_id)
        await ctx.channel.messages.send("deleted")

    @command()
    @condition(only_owner)
    async def hs(self, ctx, guild_id: int, style: str = "fancy_grid"):

        logger.info("Triggered top_players %s on %d", style, guild_id)  

        await self._top_players([guild_id], style, update_cron=False)

    @command()
    @condition(only_owner)
    async def updatenicks(self, ctx):
        async with self.database.session() as session:
            for user in await run_sync(session.query(User).all):
                try:
                    await self._update_nick(user)
                except Exception:
                    if self.raven_client:
                        self.raven_client.captureException()
                    logger.exception("something went wrong during updatenicks")
            await ctx.channel.messages.send("Done")

    @command()
    @condition(only_owner, bypass_owner=False)
    async def cleanup(self, ctx, *, doit: str = None):
        member_ids = [
            id for guild in self.client.guilds.values() for id in guild.members.keys()
        ]
        guild_ids = self.client.guilds.keys()
        async with self.database.session() as session:
            registered_ids = [
                x[0] for x in await run_sync(session.query(User.discord_id).all)
            ]
            stale_ids = set(registered_ids) - set(member_ids)
            ids = "\n".join(f"<@{id}>" for id in stale_ids)
            await send_long(
                ctx.channel.messages.send,
                f"there are {len(stale_ids)} stale entries: {ids}",
            )

            registered_guilds = set(self.guild_config.keys())
            stale_guild_configs = set(registered_guilds) - set(guild_ids)
            ids = "\n".join(f"{id}" for id in stale_guild_configs)
            await send_long(
                ctx.channel.messages.send,
                f"there are {len(stale_guild_configs)} stale guild configs: {ids}",
            )

            if doit == "confirm":
                for id in stale_ids:
                    user = await self.database.user_by_discord_id(session, id)
                    if not user:
                        await ctx.channel.messages.send(f"user {id} not found in DB???")
                    else:
                        await run_sync(session.delete, user)
                        logger.info(f"deleted guild config {id}")
                for id in stale_guild_configs:
                    gc = session.query(GuildConfigJson).filter_by(id=id).one_or_none()
                    if not gc:
                        await ctx.channel.messages.send(
                            f"guild config {id} not found in DB???"
                        )
                    else:
                        await run_sync(session.delete, gc)
                        del self.guild_config[id]
                        logger.info(f"deleted guild config {id}")

                await send_long(
                    ctx.channel.messages.send,
                    f"Deleted {len(stale_ids)} members and {len(stale_guild_configs)} guild configs",
                )
                await run_sync(session.commit)
            elif stale_ids:
                await ctx.channel.messages.send("issue `!cleanup confirm` to delete.")

    @command()
    @condition(only_owner, bypass_owner=False)
    async def fixdiscordbug(self, ctx, guild_id: int, category_id: int, prefix: str):
        logger.info(f"fixdiscordbug {guild_id} {category_id} {prefix}")
        guild = self.client.guilds[guild_id]
        for chan in list(guild.channels.values()):
            if (
                not chan.parent
                or chan.type != ChannelType.VOICE
                or chan.parent.id != category_id
            ):
                continue
            if chan.name.startswith(prefix):
                logger.info(f"deleting channel {chan}")
                await chan.delete()

    @command()
    @condition(correct_channel)
    async def ping(self, ctx):
        await reply(ctx, "pong")

    # easter egg
    @command()
    @condition(correct_channel)
    async def owo(self, ctx, *, ignored: str = None):
        await reply(ctx, "uwu")

    # ow commands

    @command()
    @condition(correct_channel)
    async def ow(self, ctx, *, member: Member = None):
        def format_sr(handle):
            sr = handle.sr
            if not sr or not any(sr) or handle.last_update < datetime(2023, 2, 1):
                return "—"

            def single_sr(symbol, sr):
                if sr:
                    return (
                        symbol + RANK_EMOJIS[sr_to_rank(sr)] + str(5-(sr//100 % 5))
                        if RANK_EMOJIS
                        else symbol + str(sr)
                    )
                else:
                    return ""

            return " | ".join(
                single_sr(ROLE_EMOJIS[ix], val) for ix, val in enumerate(sr) if val
            )

        def escape_handle(handle):
            return re.sub(r"([_*~])", r"\\\1", handle)

        member_given = member is not None
        if not member_given:
            member = ctx.author

        content = embed = None
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, member.id)
            if user:
                embed = Embed(colour=0x659DBD)  # will be overwritten later if SR is set

                # Translators: Short for Discord Nickname
                embed.add_field(name=_("Nick"), value=member.name, inline=False)

                primary, *secondary = user.handles

                sr_value = f"**{format_sr(primary)}**\n"
                sr_value += "\n".join(format_sr(tag) for tag in secondary)

                num_handles = len(user.handles)
                multiple_handles = num_handles > 1
                handle_types = set(handle.type for handle in user.handles)
                multiple_handle_types = len(handle_types) > 1

                if multiple_handle_types:

                    def fmt(handle):
                        return f"{escape_handle(handle.handle)} ({handle.blizzard_url_type.upper()})"

                else:

                    def fmt(handle):
                        return escape_handle(handle.handle)

                handle_value = f"**{fmt(primary)}**\n"
                handle_value += "\n".join(fmt(handle) for handle in secondary)

                if multiple_handle_types:
                    # Translators: When a user has BattleTags and Gamertags registered, this is shown instead of "BattleTags"
                    handle_name = _("Tags")
                else:
                    handle_name = ngettext(
                        user.handles[0].desc,
                        user.handles[0].desc + "s",
                        len(user.handles),
                    )

                embed.add_field(name=handle_name, value=handle_value)

                # Hacky workaround for Discord limitation
                while len(sr_value) > 1024:
                    sr_value = sr_value.rsplit("\n", 1)[0] + "…"

                if any(handle.sr for handle in user.handles):
                    embed.add_field(
                        name=ngettext("SR", "SRs", num_handles), value=sr_value
                    )

                if primary.sr is not None:
                    embed.colour = COLORS[
                        sr_to_rank(
                            max(
                                x or 0
                                for x in [
                                    primary.sr.tank,
                                    primary.sr.damage,
                                    primary.sr.support,
                                ]
                            )
                        )
                    ]

                if user.roles:
                    # Translators: The roles a user has set with setroles (Main Tank, Damage, etc.)
                    embed.add_field(
                        name=_("Roles"), inline=False, value=user.roles.format(ctx)
                    )

                text_links = []
                if primary.web_profile_uuid:
                    text_links.append((
                        _("Overwatch profile"),
                        f'https://overwatch.blizzard.com/en-us/career/{primary.web_profile_uuid}/',
                    ))
                text_links.extend([
                    (_("Upvote Orisa"), VOTE_LINK),
                    (_("Orisa Support Server"), SUPPORT_DISCORD),
                    (_("Help Translate Orisa"), TRANSLATE_LINK),
                    (_("Donate `{HEART}`").format(HEART="❤️"), DONATE_LINK),
                ])

                embed.add_field(
                    # Translators: Weblinks
                    name=_("Links"),
                    inline=False,
                    value=(
                        " | ".join(
                            f"[{text}]({link})"
                            for text, link in text_links
                        )
                    ),
                )

                if primary.last_update:
                    locale = CurrentLocale.get()
                    if locale == "zh_Hans":
                        locale = "zh_CN"
                    when = arrow.get(primary.last_update).humanize(locale=locale)
                    if multiple_handles:
                        footer_text = _(
                            "The SR of the primary {type} was last updated {when}."
                        ).format(type=_(user.handles[0].desc), when=when)
                    else:
                        footer_text = _("The SR was last updated {when}.").format(
                            when=when
                        )
                else:
                    footer_text = ""

                num_psn = sum(handle.type == "online_id" for handle in user.handles)

                if num_psn == 1:
                    footer_text += _(
                        "\nOrisa can neither confirm nor refute that the PSN Online ID actually belongs to this account."
                    )
                elif num_psn > 1:
                    footer_text += _(
                        "\nOrisa can neither confirm nor refute that the PSN Online IDs actually belong to this account."
                    )

                if member == ctx.author and member_given:
                    footer_text += _(
                        "\nBTW, you do not need to specify your nickname if you want your own BattleTag; just @Orisa is enough."
                    )
                embed.set_footer(text=footer_text)
            else:
                # Translators: "Do you need a hug" should be replaced by the corresponding Orisa voice line in game.
                content = _(
                    "{member_name} not found in database! *Do you need a hug?*"
                ).format(member_name=member.name)
                if member == ctx.author:
                    embed = Embed(
                        # Translators: A headline for a tip for the user
                        title=_("Tip"),
                        description=_(
                            "Use `@Orisa register` to register, or `@Orisa help` for more info."
                        ),
                    )
        await ctx.channel.messages.send(content=content, embed=embed)

    @ow.subcommand()
    @condition(correct_channel)
    async def get(self, ctx, *, member: Member = None):
        r = await self.ow(ctx, member=member)
        return r

    @ow.subcommand()
    @condition(correct_channel)
    async def about(self, ctx):
        embed = Embed(
            title=_("About Me"),
            description=(
                # Translators: feel free to add "and the translation for this language was done by name"
                _(
                    "I am an open source Discord bot to help manage Overwatch Discord communities.\n"
                    "I'm written and maintained by Dennis Brakhane (Joghurt#2732 on Discord) and licensed under the "
                    "[GNU Affero General Public License 3.0+]({AGPL_LINK}); "
                    "[development happens on GitHub]({GH_LINK})"
                ).format(
                    AGPL_LINK="https://www.gnu.org/licenses/agpl-3.0.en.html",
                    GH_LINK="https://github.com/brakhane/Orisa",
                )
            ),
        )
        embed.add_field(
            name=_("Invite me to your own Discord"),
            inline=False,
            value=(
                _(
                    "To invite me to your server, simply [click here]({LINK}), I will post a message with more "
                    "information in a channel after I have joined your server"
                ).format(LINK="https://orisa.rocks/invite")
            ),
        )
        embed.add_field(
            name=_("Join the official Orisa Discord"),
            inline=False,
            value=(
                _(
                    "If you use me in your Discord server, or generally have suggestions, [join the official Orisa Discord]({SUPPORT_DISCORD}). Updates and new features "
                    "will be discussed and announced there."
                ).format(SUPPORT_DISCORD=SUPPORT_DISCORD)
            ),
        )
        embed.add_field(
            name=_("Show your love :heart:"),
            inline=False,
            value=(
                _(
                    "If you find me useful, [buy my maintainer a cup of coffee]({DONATE_LINK})."
                ).format(DONATE_LINK=DONATE_LINK)
            ),
        )
        await ctx.author.send(content=None, embed=embed)
        if not ctx.channel.private:
            await reply(ctx, _("I've sent you a DM."))

    @ow.subcommand()
    async def config(self, ctx, guild_id: int = None):
        is_owner = ctx.author == ctx.bot.application_info.owner
        if ctx.channel.private and not is_owner:
            await ctx.channel.messages.send(
                content=_(
                    "The config command must be issued from a channel of the server you want to configure. "
                    "Don't worry, I will send you the config instructions as a DM, so others can't configure me just by watching you sending this command."
                ),
                embed=Embed(
                    # Translators: A tip/information for a user
                    title=_("Tip"),
                    description=_(
                        "`@Orisa config` works in *any* channel (that I'm allowed to read messages in, of course), so you can also use an admin-only channel."
                    ),
                ),
            )
            return

        if not is_owner and not any(
            role.name.lower() == "orisa admin" for role in ctx.author.roles
        ):
            help_embed = Embed(
                # Translators: :thinking: must remain as is, it's an emoji
                title=_(":thinking: Need help?"),
                description=_("Join the [Support Discord]({SUPPORT_DISCORD})!").format(
                    SUPPORT_DISCORD=SUPPORT_DISCORD
                ),
            )
            await reply(
                ctx,
                # Translators: "Orisa Admin" must not be translated; additionally explaining what the string "Orisa Admin" means is ok
                _(
                    "This command can only be used by members with the `Orisa Admin` role! Only the name of the role is important, it doesn't need any permissions."
                ),
            )
            try:
                await ctx.channel.messages.send(content=None, embed=help_embed)
            except Exception:
                logger.exception("unable to send help embed")
            logger.info(
                f"user {ctx.author} tried to issue ow config without being in Orisa Admin"
            )
            return

        if is_owner and guild_id is not None:
            token = web.create_token(guild_id)
        else:
            token = web.create_token(ctx.guild.id)

        embed = Embed(
            title=_("Click here to configure me!"), url=f"{WEB_APP_PATH}config/{token}"
        )
        embed.add_field(
            # Translators: :thinking: is an emoji code
            name=_(":thinking: Need help?"),
            value=_("Join the [Support Discord]({SUPPORT_DISCORD})!").format(
                SUPPORT_DISCORD=SUPPORT_DISCORD
            ),
            inline=False,
        )
        embed.set_footer(text=_("This link will be valid for 30 minutes."))
        try:
            await ctx.author.send(content=None, embed=embed)
            await reply(ctx, _("I've sent you a DM."))
        except Forbidden:
            await reply(
                ctx,
                _(
                    "I tried to send you a DM with the link, but you disallow DM from server members. Please allow that and retry. I can't post the link here because "
                    "everybody who knows that link will be able to configure me."
                ),
            )

    @ow.subcommand()
    @condition(correct_channel)
    async def register(self, ctx, type: str = "pc", *, online_id: str = None):
        user_id = ctx.message.author_id

        if "#" in type:
            await reply(
                ctx,
                _(
                    "{type} looks like a BattleTag and not like PC/Xbox, assuming you meant `@Orisa register pc`…"
                ).format(type=type),
            )
            type = "pc"

        type = type.lower()

        if type == "pc":
            client = WebApplicationClient(OAUTH_BLIZZARD_CLIENT_ID)
            oauth_url = "https://eu.battle.net/oauth/authorize"
            scope = []
            description = _(
                "To complete your registration, I need your permission to ask Blizzard for your BattleTag. Please click "
                "the link above and give me permission to access your data. I only need this permission once, you can remove it "
                "later in your BattleNet account."
            )
        elif type == "xbox":
            client = WebApplicationClient(OAUTH_DISCORD_CLIENT_ID)
            oauth_url = "https://discord.com/oauth2/authorize"
            scope = ["connections"]
            description = _(
                "To complete your registration, I need your permission to ask Discord for your Gamertag. Please click "
                "the link above and give me permission to access your data. Make sure you have linked your Xbox account to Discord."
            )
        elif type in ["psn", "ps"]:
            if not online_id:
                await reply(
                    ctx,
                    _(
                        "When registering a PSN account, you need to give your Online ID, like `@Orisa register psn My-Cool-ID_12345`."
                    ),
                )
                return
            await self._handle_registration(user_id, "psn", online_id)
            if not ctx.channel.private:
                await reply(ctx, _("I've sent you a DM."))
            return
        else:
            await reply(
                ctx,
                _(
                    'Invalid registration type "{type}". Use `@Orisa register` or `@Orisa register pc` for PC; `@Orisa register xbox` for Xbox, or `@Orisa register psn My-Online-Id_1234` for PlayStation.'
                ).format(type=_(type)),
            )
            return

        state = OAUTH_SERIALIZER.dumps((type, user_id))
        url, headers, body = client.prepare_authorization_request(
            oauth_url,
            scope=scope,
            redirect_url=f"{OAUTH_REDIRECT_HOST}{OAUTH_REDIRECT_PATH}",
            state=state,
        )
        embed = Embed(
            url=url,
            # Translators: type will be PC, XBOX or PSN
            title=_("Click here to register your {type} account!").format(
                type=type.upper()
            ),
            description=description,
        )
        if type == "pc":
            embed.add_field(
                # Translators: :information_source: is an emoji
                name=_(":information_source: Protip"),
                value=_(
                    "If you want to register a secondary/smurf BattleTag, you can open the link in a private/incognito tab (try right clicking the link) and enter the "
                    "account data for that account instead."
                ),
                inline=False,
            )
            embed.add_field(
                # Translators: :video_game: is an emoji
                name=_(":video_game: Not on PC?"),
                value=_(
                    "If you have an XBL account, use `@Orisa register xbox`. For PSN, use `@Orisa register psn Your_Online-ID`"
                ),
                inline=False,
            )
        embed.set_footer(
            # Translators: The translation should mention that the privacy policy is currently only available in English
            text=_(
                "By registering, you agree to Orisa's Privacy Policy; you can read it by entering @Orisa privacy."
            )
        )

        try:
            await ctx.author.send(content=None, embed=embed)
        except Forbidden:
            await reply(
                ctx,
                # Translators: Check how Discord translates "Allow direct messages from server members" in your local language and use the same term
                _(
                    "I'm not allowed to send you a DM. Please right click on the Discord server, "
                    'select "Privacy Settings", and enable "Allow direct messages from server members." Then try again.'
                ),
            )
        else:
            if not ctx.channel.private:
                await reply(ctx, _("I've sent you a DM with instructions."))

    @ow.subcommand()
    @condition(correct_channel)
    async def unregister(self, ctx, handle_or_index: str):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(
                    ctx, _("You are not registered, there's nothing for me to do.")
                )
                return

            try:
                index = resolve_handle_or_index(user, handle_or_index)
            except ValueError as e:
                await reply(ctx, e.args[0])
                return
            if index == 0:
                await reply(
                    ctx,
                    _(
                        "You cannot unregister your primary handle. Use `@Orisa setprimary` to set a different primary first, or "
                        "use `@Orisa forgetme` to delete all your data."
                    ),
                )
                return

            removed = user.handles.pop(index)
            removed.current_sr_id = None
            handle = removed.handle
            await run_sync(session.commit)
            await reply(ctx, _("Removed **{handle}**!").format(handle=handle))
            await self._update_nick_after_secondary_change(ctx, user)

    async def _update_nick_after_secondary_change(self, ctx, user):
        try:
            await self._update_nick(user, force=True)
        except HierarchyError:
            pass
        except NicknameTooLong as e:
            await reply(
                ctx,
                _(
                    'However, your new nickname "{nickname}" is now longer than 32 characters, which Discord doesn\'t allow. '
                    "Please choose a different format, or shorten your nickname and do a `@Orisa forceupdate` afterwards."
                ).format(nickname=e.nickname),
            )
        except Exception:
            await reply(
                ctx,
                _(
                    "However, there was an error updating your nickname. I will try that again later."
                ),
            )
        with suppress(HierarchyError):
            await self._update_nick(user)

    @ow.subcommand()
    @condition(correct_channel)
    async def setprimary(self, ctx, handle_or_index: str = None):
        if handle_or_index is None:
            await reply(
                ctx,
                _(
                    "`setprimary` requires the first few letters of the handle you want to make your primary as a parameter, e.g. `@Orisa setprimary foo`"
                ),
            )
            return
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(
                    ctx, _("You are not registered. Use `@Orisa register` first.")
                )
                return
            try:
                index = resolve_handle_or_index(user, handle_or_index)
            except ValueError as e:
                await reply(ctx, e.args[0])
                return
            if index == 0:
                await reply(
                    ctx,
                    # Translators: handle will be the BattleTag/Gamertag the user tried to register, type will be BattleTag or GamerTag
                    _(
                        '"{handle}" already is your primary {type}. *Going back to sleep!*'
                    ).format(
                        handle=user.handles[0].handle, type=_(user.handles[0].desc)
                    ),
                )
                return

            p, s = user.handles[0], user.handles[index]
            p.position = index
            s.position = 0
            await run_sync(session.commit)

            for i, t in enumerate(sorted(user.handles[1:], key=attrgetter("handle"))):
                t.position = i + 1

            await run_sync(session.commit)

            await reply(
                ctx,
                # Translators: handle will be the battletag/gamertag the user registered, type will be BattleTag or GamerTag
                _("Done. Your primary {type} is now **{handle}**.").format(
                    handle=user.handles[0].handle, type=user.handles[0].desc
                ),
            )
            await self._update_nick_after_secondary_change(ctx, user)

    @ow.subcommand()
    @condition(correct_channel)
    async def format(self, ctx, *, format: str):
        if "]" in format:
            await reply(ctx, _("format string may not contain square brackets!"))
            return
        if "$" not in format:
            # Translators: keep the $ to remind the user that placeholders start with a $ sign
            await reply(ctx, _("format string must contain at least one $placeholder!"))
            return
        if not format:
            await reply(ctx, _("format string missing!"))
            return

        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, _("you must register first!"))
                return
            else:
                user.format = format
                try:
                    new_nick = await self._update_nick(user, force=True)
                except InvalidFormat as e:
                    await reply(
                        ctx,
                        _('Invalid format string: unknown placeholder "{key}"!').format(
                            key=e.key
                        ),
                    )
                    await run_sync(session.rollback)
                except NicknameTooLong as e:
                    logger.info(f"Cannot set nickname {e.nickname}, it's too long")
                    await reply(
                        ctx,
                        _(
                            "Sorry, using this format would make your nickname `{nickname}` be longer than 32 characters ({len} to be exact).\n"
                            "Please choose a shorter format or shorten your nickname!"
                        ).format(nickname=e.nickname, len=len(e.nickname)),
                    )
                    await run_sync(session.rollback)
                else:
                    # Translators: A list of random silly titles that will be shown in the confirmation message when a user changed his nickname format.
                    # Most of them were found on the Internet, for example
                    # "Eternal Bosom of Hot Love" is one of Kim Jong-Il's official titles.
                    # One title per line, you can replace it with different titles, the number of
                    # titles can be different than the english one, but must contain at least one entry.
                    # Keep the titles funny and not insulting! Nobody wants to be called an asshole when he used ow format.
                    # You can also leave the list empty; in that case, the English original will be used.
                    titles = _(
                        """\
Smarties Expert
Bread Scientist
Eternal Bosom of Hot Love
Sith Lord of Security
Namer of Clouds
Scourge of Beer Cans
Muse of Jeff Kaplan
Shredded Cheese Authority
Pork Rind Expert
Dinosaur Supervisor
Galactic Viceroy of C9
Earl of Bacon
Dean of Pizza
Duke of Tacos
Retail Jedi"""
                    ).split("\n")
                    # reset if SR should not be shown normally
                    await self._update_nick(user)
                    await reply(
                        ctx,
                        # Translators: Unlike other messages, keep this message overly formal and archaic sounding to keep a funny contrast to the silly title that will be "given" to the user.
                        # So, unlike in all the other messages, if your language has a concept of "formal" vs "familiar" you, use the formal you here.
                        # {title} is taken from the list of random titles
                        _(
                            'Done. Henceforth, thou shall be knownst as "`{new_nick}`, {title}".'
                        ).format(new_nick=new_nick, title=random.choice(titles)),
                    )
            await run_sync(session.commit)

    @ow.subcommand(aliases=("alwayshowsr",))
    @condition(correct_channel)
    async def alwaysshowsr(self, ctx, param: str = "on"):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, _("you are not registered!"))
                return
            new_setting = param != "off"
            user.always_show_sr = new_setting
            await self._update_nick(user)
            await run_sync(session.commit)

        msg = "Done. "
        if new_setting:
            msg += _(
                "Your nick will be updated even when you are not in an OW voice channel. Use `@Orisa alwaysshowsr off` to turn it off again."
            )
        else:
            msg += _(
                "Your nick will only be updated when you are in an OW voice channel. Use `@Orisa alwaysshowsr on` to always update your nick."
            )
        await reply(ctx, msg)

    @ow.subcommand()
    @condition(correct_channel, bypass_owner=False)
    async def forceupdate(self, ctx, discord_id=None):
        async with self.database.session() as session:
            if (
                discord_id is None
                or ctx.author.id != self.client.application_info.owner.id
            ):
                logger.info(f"{ctx.author.id} used forceupdate")
                discord_id = ctx.author.id
            else:
                logger.info(
                    f"{ctx.author.id} (owner) used forceupdate with discord_id {discord_id}"
                )
            user = await self.database.user_by_discord_id(session, discord_id)
            if not user:
                await reply(
                    ctx, _("You are not registered! Do `@Orisa register` first.")
                )
            else:
                fault = False
                async with ctx.channel.typing:
                    for handle in user.handles:
                        try:
                            await self._sync_handle(session, handle)
                        except InvalidBattleTag:
                            await reply(
                                ctx,
                                _(
                                    "Blizzard says your {type} {handle} does not exist. Did you change it? Use `@Orisa register` to update it.".format(
                                        type=handle.desc, handle=handle.handle
                                    )
                                ),
                            )
                            fault = True
                        except Exception:
                            if self.raven_client:
                                self.raven_client.captureException()
                            logger.exception(f"exception while syncing {handle}")
                            fault = True

                if fault:
                    await reply(
                        ctx,
                        _(
                            "There were some problems updating your SR! Try again later."
                        ),
                    )
                else:
                    await reply(
                        ctx,
                        _(
                            "OK, I have updated your data. Your ranks are now {sr}. "
                            "If that is not correct, you need to log out of Overwatch once and try again; your "
                            "profile also needs to be public for me to track your ranks."
                        ).format(sr=TDS(*[rank_fmt(s) if s else None for s in user.handles[0].sr])),
                    )
            await run_sync(session.commit)

    @ow.subcommand()
    async def forgetme(self, ctx):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if user:
                logger.info(f"{ctx.author.name} ({ctx.author.id}) requested removal")
                user_id = user.discord_id
                try:
                    for guild in self._configured_guilds():
                        try:
                            nn = str(guild.members[user_id].name)
                        except KeyError:
                            continue
                        new_nn = re.sub(r"\s*\[.*?\]", "", nn, count=1).strip()
                        try:
                            await guild.members[user_id].nickname.set(new_nn)
                        except HierarchyError:
                            pass
                except Exception:
                    logger.exception("Some problems while resetting nicks")
                session.delete(user)
                await reply(
                    ctx,
                    _("OK, deleted {name} from database").format(name=ctx.author.name),
                )
                await run_sync(session.commit)
            else:
                await reply(
                    ctx,
                    _(
                        "you are not registered anyway, so there's nothing for me to forget…"
                    ),
                )

    @ow.subcommand()
    @condition(correct_channel)
    async def setrole(self, ctx, *, roles_str: str = None):
        "Alias for setroles"
        return await self.setroles(ctx, roles_str=roles_str)

    @ow.subcommand()
    @condition(correct_channel)
    async def setroles(self, ctx, *, roles_str: str = None):
        names = {
            "d": Role.DPS,
            "m": Role.MAIN_TANK,
            "o": Role.OFF_TANK,
            "s": Role.SUPPORT,
        }

        roles = Role.NONE
        if roles_str is None:
            await reply(
                ctx,
                # Translators: the identifiers m o d s must not be translated
                _(
                    "Missing roles identifier. Valid role identifiers are: `m` (Main Tank), `o` (Off Tank), `d` (Damage), `s` (Support). "
                    "They can be combined, e.g. `ds` would mean Damage + Support."
                ),
            )
            return

        for role in roles_str.replace(" ", "").lower():
            try:
                roles |= names[role]
            except KeyError:
                await reply(
                    ctx,
                    _(
                        "Unknown role identifier '{role}'. Valid role identifiers are: `m` (Main Tank), `o` (Off Tank), "
                        "`d` (Damage), `s` (Support). They can be combined, e.g. `ds` would mean Damage + Support."
                    ).format(role=role),
                )
                return

        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(
                    ctx, _("You are not registered! Do `@Orisa register` first.")
                )
                return
            user.roles = roles
            await run_sync(session.commit)
            await reply(
                ctx,
                _("Done. Your roles are now **{roles}**").format(
                    roles=roles.format(ctx)
                ),
            )

    @ow.subcommand()
    async def help(self, ctx):
        if not ctx.channel.private:
            if (
                ctx.channel.guild_id not in self.guild_config
                or self.guild_config[ctx.channel.guild_id] == GuildConfig.default()
            ):
                await reply(
                    ctx,
                    # Translators: Orisa Admin must not be translated
                    _(
                        "I'm not configured yet! Somebody with the role `Orisa Admin` needs to issue `@Orisa config` to configure me first!"
                    ),
                )
                try:
                    await ctx.channel.messages.send(
                        content=None,
                        embed=Embed(
                            title=_(":thinking: Need help?"),
                            description=_(
                                "Join the [Support Discord]({SUPPORT_DISCORD})!"
                            ).format(SUPPORT_DISCORD=SUPPORT_DISCORD),
                        ),
                    )
                except Exception:
                    logger.exception("Unable to send help embed")

                return
        forbidden = False
        for embed in self._create_help(ctx):
            try:
                await ctx.author.send(content=None, embed=embed)
            except Forbidden:
                forbidden = True
                break

        if forbidden:
            await reply(
                ctx,
                _(
                    "I tried to send you a DM with help, but you don't allow DM from server members. "
                    "I can't post it here, because it's rather long. Please allow DMs and try again."
                ),
            )
        else:
            try:
                await ctx.author.send(
                    content=None,
                    embed=Embed(
                        title=_(":thinking: Need help?"),
                        description=_(
                            "Join the [Support Discord]({SUPPORT_DISCORD})!"
                        ).format(SUPPORT_DISCORD=SUPPORT_DISCORD),
                    ),
                )
            except Exception:
                logger.exception("Unable to send help embed")

            if not ctx.channel.private:
                await reply(ctx, _("I've sent you a DM with instructions."))

    def _create_help(self, ctx):

        channel_id = None
        try:
            g_conf = self.guild_config[ctx.channel.guild_id]
        except KeyError:
            pass
        else:
            if g_conf != GuildConfig.default():
                channel_id = g_conf.listen_channel_id

        if not channel_id:
            for guild in self._configured_guilds():
                if ctx.author.id in guild.members:
                    channel_id = self.guild_config[guild.id].listen_channel_id
                    break

        embed = Embed(
            title=_("Orisa's purpose"),
            # Translators: <@!> and <#> are discord codes and must be kept
            description=(
                _(
                    "When joining a QP or Comp channel, you need to know the BattleTag of a channel member, or they need "
                    "yours to add you. In competitive channels it also helps to know which SR the channel members have. "
                    "To avoid having to ask for this information again and again when joining a channel, this bot was created. "
                    "When you register with your BattleTag, your nick will automatically be updated to show your "
                    "current SR and it will be kept up to date. You can also ask for other member's BattleTag, or request "
                    "your own so others can easily add you in OW.\n"
                    "It will also send a short message to the chat when you ranked up.\n"
                    "*Like Overwatch's Orisa, this bot is quite young and still new at this. Report issues to <@!{OWNER}>*\n"
                    "\n**The commands only work in the <#{channel_id}> channel or by sending me a DM**\n"
                    "If you are new to Orisa, you are probably looking for `@Orisa register` or `@Orisa register xbox`\n"
                    "If you want to use Orisa on your own server or help developing it, enter `@Orisa about`\n"
                    "Parameters in [square brackets] are optional."
                ).format(
                    OWNER=self.client.application_info.owner.id, channel_id=channel_id
                )
            ),
        )
        embed.add_field(
            name="@Orisa [nick]",
            # Translators: help text for @Orisa <some nickname>
            value=(
                _(
                    "Shows the BattleTag for the given nickname, or your BattleTag "
                    "if no nickname is given. `nick` can contain spaces. A fuzzy search for the nickname is performed.\n"
                    "*Examples:*\n"
                    "`@Orisa` will show your BattleTag\n"
                    '`@Orisa the chosen one` will show the BattleTag of "tHE ChOSeN ONe"\n'
                    '`@Orisa orisa` will show the BattleTag of "SG | Orisa", "Orisa", or "Orisad"\n'
                    '`@Orisa oirsa` and `@Orisa ori` will probably also show the BattleTag of "Orisa"'
                )
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa about",
            value=_(
                "Shows information about Orisa, and how you can add her to your own Discord server, or help supporting her."
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa alwaysshowsr [on/off]",
            value=_(
                "On some servers, Orisa will only show your SR or rank in your nick when you are in an OW voice channel. If you want your nick to always show your SR or rank, "
                "set this to on.\n"
                "*Example:*\n"
                "`@Orisa alwaysshowsr on`"
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa config",
            # Translators: don't translate "Orisa Admin"
            value=_(
                'This command can only be used by members with the "Orisa Admin" role and allows them to configure Orisa for the specific Discord server.'
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa dumpsr",
            # Translators: help for @Orisa dumpsr
            value=_("Download your SR history as an Excel spreadsheet"),
            inline=False,
        )
        embed.add_field(
            name="@Orisa forceupdate",
            # Translators: help @Orisa forceupdate
            value=_(
                "Immediately checks your account data and updates your nick accordingly.\n"
                "*Checks and updates are done automatically, use this command only if "
                "you want your nick to be up to date immediately!*"
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa forgetme",
            # Translators: help @Orisa forgetme
            value=_(
                "All your BattleTags will be removed from the database and your nick "
                "will not be updated anymore. You can re-register at any time."
            ),
            inline=False,
        )

        embed.add_field(
            name="@Orisa format *format*",
            # Translators: help @Orisa format. $placeholder can be translated, as can ${placeholder}
            value=_(
                "Lets you specify how your SR or rank is displayed. It will always be shown in [square\u00a0brackets] appended to your name.\n"
                "In the *format*, you can specify placeholders with `$placeholder` or `${placeholder}`."
            ),
            inline=False,
        )
        embed.add_field(
            name=_("★ *ow format placeholders*"),
            # Translators: $fullsr, $rank, etc. cannot be translated
            value=_(
                "*The following placeholders are defined:*\n"
                "`$sr`\nthe first two digits of your SR for all 3 roles in order Tank, Damage, Support; if you have secondary accounts, an asterisk (\*) is added at the end. A question mark is added if an old SR is shown\n\n"
                "`$fullsr`\nLike `$sr` but all 4 digits are shown\n\n"
                "`$rank`\nyour rank in shortened form for all 3 roles in order Tank, Damage, Support; asterisk and question marks work like in `$sr`\n\n"
                "`$tank`, `$damage`, `$support`\nYour full SR for the respective role followed by its symbol. Asterisk and question mark have the same meaning like in `$sr`. "
                "For technical reasons the symbols for the respective roles are `{SYMBOL_TANK}`, `{SYMBOL_DPS}`, `{SYMBOL_SUPPORT}`\n\n"
                "`$tankrank`, `$damagerank`, `$supportrank`\nlike above, but the rank is shown instead.\n\n"
                "`$shorttank`, `$shorttankrank` etc.\nshow only 2 digits/letters of the respective SR/rank.\n\n"
                "`$dps`, `$dpsrank`, `$shortdps`, `$shortdpsrank` \nAlias for `$damage`, `$damagerank` etc."
            ).format(
                SYMBOL_TANK=self.SYMBOL_TANK,
                SYMBOL_DPS=self.SYMBOL_DPS,
                SYMBOL_SUPPORT=self.SYMBOL_SUPPORT,
            ),
            inline=False,
        )
        embed.add_field(
            name=_("★ *ow format examples*"),
            value=_(
                "`@Orisa format hello $sr` will result in `[hello 12-34-45]`.\n"
                "`@Orisa format Potato/$fullrank` in `[Potato/Bronze-Gold-Diamond]`.\n"
                "`@Orisa format $damage $support` in `[{SYMBOL_DPS}1234 {SYMBOL_SUPPORT}2345]`.\n"
                "`@Orisa format $shortdamage` in `[{SYMBOL_DPS}12]`.\n"
                "*By default, the format is `$sr`*"
            ).format(SYMBOL_DPS=self.SYMBOL_DPS, SYMBOL_SUPPORT=self.SYMBOL_SUPPORT),
            inline=False,
        )

        embeds = [embed]
        # Translators: headline of second help page
        embed = Embed(title=_("help cont'd"))
        embeds.append(embed)

        embed.add_field(
            name="@Orisa get nick",
            value=(
                _(
                    "Same as `@Orisa [nick]`, (only) useful when the nick is the same as a command.\n"
                    "*Example:*\n"
                    '`@Orisa get register` will search for the nick "register".'
                )
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa register [pc/xbox/psn]",
            value=_(
                "Create a link to your BattleNet or Gamertag account, or adds a secondary BattleTag to your account. "
                "Your OW account will be checked periodically and your nick will be "
                "automatically updated to show your SR or rank (see the *format* command for more info). "
                "`@Orisa register` and `@Orisa register pc` will register a PC account, `@Orisa register xbox` will register an XBL account. "
                "If you register an XBL account, you have to link it to your Discord beforehand. "
                "For PSN accounts, you have to give your Online ID as part of the command, like `@Orisa register psn Your_Online-ID`."
            ),
            inline=False,
        )
        embed.add_field(name="@Orisa privacy", value=_("Show Orisa's Privacy Policy"))
        embed.add_field(
            name="@Orisa setprimary *battletag*",
            value=_(
                "Makes the given secondary BattleTag your primary BattleTag. Your primary BattleTag is the one you are currently using: its SR is shown in your nick\n"
                "The search is performed fuzzy and case-insensitve, so you normally only need to give the first (few) letters.\n"
                "The given BattleTag must already be registered as one of your BattleTags.\n"
                "*Example:*\n"
                "`@Orisa setprimary jjonak`"
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa setprimary *index*",
            value=_(
                "Like `@Orisa setprimary battletag`, but uses numbers, 1 is your first secondary, 2 your seconds etc. The order is shown by `@Orisa` (alphabetical)\n"
                "Normally, you should not need to use this alternate form, it's available in case Orisa gets confused on what BattleTag you mean (which shouldn't happen).\n"
                "*Example:*\n"
                "`@Orisa setprimary 1`"
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa setroles *roles*",
            # Translators: the role codes d, m, o, s cannot be translated
            value=_(
                "Sets the role you can/want to play. It will be shown in `@Orisa` and will also be used to update the number of roles "
                "in voice channels you join.\n"
                '*roles* is a single "word" consisting of one or more of the following identifiers (both upper and lower case work):\n'
                "`d` for DPS, `m` for Main Tank, `o` for Off Tank, `s` for Support\n"
                "*Examples:*\n"
                "`@Orisa setroles d`: you only play DPS.\n"
                "`@Orisa setroles so`: you play Support and Off Tanks.\n"
                "`@Orisa setroles dmos`: you are a true Flex and play everything."
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa srgraph [from_date]",
            value=_(
                "*This command is in beta and can change at any time; it might also have bugs, report them please*\n"
                "Shows a graph of your SR. If from_date (as DD.MM.YY or YYYY-MM-DD) is given, the graph starts at that date, otherwise it starts "
                "as early as Orisa has data."
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa usersrgraph *username* [from_date]",
            value=_(
                '*This command can only be used by users with the "Orisa Admin" role!*\n'
                "Like srgraph, but shows the graph for the given user."
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa unregister *battletag*",
            value=_(
                "If you have secondary BattleTags, you can remove the given BattleTag from the list. The search is performed fuzzy, so "
                "you normally only have to specify the first few letters of the BattleTag to remove.\n"
                "You cannot remove your primary BattleTag, you have to choose a different primary BattleTag first.\n"
                "*Example:*\n"
                "`@Orisa unregister foo`"
            ),
            inline=False,
        )
        embed.add_field(
            name="@Orisa unregister *index*",
            value=_(
                "Like `unregister battletag`, but removes the battletag by number. Your first secondary is 1, your second 2, etc.\n"
                "The order is shown by the `@Orisa` command (it's alphabetical).\n"
                "Normally, you should not need to use this alternate form, it's available in case Orisa gets confused on what BattleTag you mean (which shouldn't happen)\n"
                "*Example:*\n"
                "`@Orisa unregister 1`"
            ),
            inline=False,
        )

        return embeds

    @ow.subcommand()
    @condition(correct_channel)
    async def srgraph(self, ctx, date: str = None):
        async with ctx.channel.typing:
            async with self.database.session() as session:
                user = await self.database.user_by_discord_id(session, ctx.author.id)
                if not user:
                    await reply(
                        ctx, _("You are not registered. Do `@Orisa register` first!")
                    )
                    return
                else:
                    await self._srgraph(ctx, user, ctx.author.name, date)

    @ow.subcommand()
    @author_has_roles("Orisa Admin")
    async def usersrgraph(self, ctx, member: Member, date: str = None):
        async with ctx.channel.typing:
            async with self.database.session() as session:
                user = await self.database.user_by_discord_id(session, member.id)
                if not user:
                    await reply(
                        ctx,
                        _("{member_name} is not registered!").format(
                            member_name=member.name
                        ),
                    )
                    return
                else:
                    await self._srgraph(ctx, user, member.name, date)

    @ow.subcommand()
    async def privacy(self, ctx):
        with open(PRIVACY_POLICY_PATH) as f:
            text = f.read()
        text = text.replace("OWNER_ID", f"<@!{self.client.application_info.owner.id}>")
        await send_long(ctx.author.send, text)
        if not ctx.channel.private:
            # Translators: privacy policy is currently only availabe in English
            await reply(ctx, _("I DM'ed you the privacy policy."))

    @ow.subcommand()
    async def dumpsr(self, ctx):
        async with ctx.channel.typing:
            async with self.database.session() as session:
                user = await self.database.user_by_discord_id(session, ctx.author.id)
                if not user:
                    await reply(ctx, _("You are not registered."))
                    return

                with tempfile.NamedTemporaryFile(suffix=".xls") as tmp:
                    filename = tmp.name
                    with pd.ExcelWriter(filename, engine="openpyxl") as xls_wr:
                        for handle in user.handles:
                            df = pd.DataFrame.from_records(
                                [
                                    (sr.timestamp, sr.tank, sr.damage, sr.support)
                                    for sr in handle.sr_history
                                ],
                                columns=[
                                    _("Timestamp"),
                                    _("Tank"),
                                    _("Damage"),
                                    _("Support"),
                                ],
                            )
                            df.to_excel(xls_wr, sheet_name=handle.handle, index=False)
                            xls_wr.sheets[handle.handle].column_dimensions[
                                "A"
                            ].width = 25

                    tmp.file.seek(0)
                    data = tmp.file.read()
                try:
                    if ctx.channel.private:
                        chan = ctx.channel
                    else:
                        chan = await ctx.author.user.open_private_channel()
                    await chan.messages.upload(
                        data,
                        # Translators: file name of the sr history excel file to download
                        filename=_("sr-history.xls"),
                        message_content=_(
                            "Here is your SR history of all your accounts as an Excel spreadsheet."
                        ),
                    )
                except Forbidden:
                    # Translators: check how Discord translated "Allow DM from server members"
                    await reply(
                        ctx,
                        _(
                            "I'm not allowed to send you a DM, please make sure that you enabled \"Allow DM from server members\" in the server's privacy settings!"
                        ),
                    )
                if not ctx.channel.private:
                    await reply(ctx, "I've sent you a DM.")

    async def _srgraph(self, ctx, user, name, date: str = None):
        sns.set_theme(font="Lato")

        handle = user.handles[0]

        data = [(sr.timestamp, *sr.values) for sr in handle.sr_history]

        if not data:
            await ctx.channel.messages.send(
                _("There is no data yet for {handle}, try again later").format(
                    handle=handle.handle
                )
            )
            return

        data = pd.DataFrame.from_records(
            reversed(data),
            columns=["timestamp", _("Tank"), _("Damage"), _("Support")],
            index="timestamp",
        )

        for row in [_("Tank"), _("Damage"), _("Support")]:
            if data[row].isnull().all():
                data.drop(row, axis=1, inplace=True)

        if len(data.columns) == 0:
            await reply(ctx, _("I have no SR for your account stored yet."))
            return

        if date:
            try:
                date = date_parser.isoparse(date)
            except ValueError:
                try:
                    date = date_parser.parse(
                        date, parserinfo=date_parser.parserinfo(dayfirst=True)
                    )
                except ValueError:
                    await reply(
                        ctx,
                        _(
                            "I don't know what date {date} is supposed to mean. Please use "
                            "the format DD.MM.YY or YYYY-MM-DD!"
                        ).format(date=date),
                    )
                    return

            data = data[data.index >= date]

        fig, ax = plt.subplots()

        ax.xaxis_date()

        sns.lineplot(data=data, ax=ax, drawstyle="steps-post", dashes=True)

        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y-%m-%d"))
        ax.yaxis.set_major_locator(
            matplotlib.ticker.MaxNLocator(
                nbins="auto", steps=[1, 1.25, 2.5, 5], integer=True
            )
        )
        fig.autofmt_xdate()

        plt.xlabel("Date")
        plt.ylabel("SR")

        image = BytesIO()
        plt.savefig(format="png", fname=image, transparent=False)
        image.seek(0)
        embed = Embed(
            title=_("SR History For {name}").format(name=name),
            description=_("Here is your SR history starting from {date}").format(
                # Translators: used instead of a date when user requested a SR history from the beginning (which is the usual case)
                date=_("when you registered")
                if not date
                else arrow.get(date).isoformat()[:10]
            ),
        )
        embed.set_image(image_url="attachment://graph.png")
        try:
            await ctx.channel.messages.upload(
                image, filename="graph.png", message_embed=embed
            )
        except PermissionsError as e:
            if e.permission_required == "attach_files":
                # we assume this message came from a guild channel, if not, there's nothing we can do anyway
                if ctx.channel.private:
                    await reply(ctx, _("Sorry, I'm not allowed to send you files…"))
                else:
                    chan = await ctx.author.user.open_private_channel()
                    await chan.messages.upload(
                        image, filename="graph.png", message_embed=embed
                    )
                await reply(
                    ctx,
                    _(
                        "I'm not allowed to upload images in this channel, so I've sent you a DM instead."
                    ),
                )

    @command()
    async def help(self, ctx):
        """NOP to turn off the curious built-in help command"""
        pass

    # Events
    @event("member_update")
    async def _member_update(self, ctx, old_member: Member, new_member: Member):
        def plays_overwatch(m):
            try:
                return m.game.name == "Overwatch 2"
            except AttributeError:
                return False

        async def wait_and_fire(ids_to_sync):
            logger.debug(
                f"sleeping for 20s before syncing after OW close of {new_member.name}"
            )
            await trio.sleep(20)
            await self._sync_handles(ids_to_sync)
            logger.debug(f"done syncing tags for {new_member.name} after OW close")

        if plays_overwatch(old_member) and (not plays_overwatch(new_member)):
            uid = new_member.user.id
            if uid in self.stopped_playing_cache:
                logger.debug("Already handled %s, nothing to do", new_member.name)
                return
            else:
                self.stopped_playing_cache[uid] = True

            async with self.database.session() as session:
                user = await self.database.user_by_discord_id(
                    session, new_member.user.id
                )
                if not user:
                    logger.debug(
                        "%s stopped playing OW but is not registered, nothing to do.",
                        new_member.name,
                    )
                    return

                ids_to_sync = [t.id for t in user.handles]
                logger.info(
                    f"{new_member.name} stopped playing OW and has {len(ids_to_sync)} BattleTags that need to be checked"
                )

            await self.spawn(wait_and_fire, ids_to_sync)

    @event("voice_state_update")
    async def _voice_state_update(self, ctx, member, old_voice_state, new_voice_state):
        parent = None
        if old_voice_state and old_voice_state.channel:
            parent = old_voice_state.channel.parent
            if parent:

                async def task():
                    try:
                        await self._adjust_voice_channels(parent)
                    except Exception:
                        logger.warn(
                            f"Can't adjust voice channel for parent {parent}",
                            exc_info=True,
                        )

                await self.spawn(task)

        if new_voice_state and new_voice_state.channel:
            if new_voice_state.channel.parent != parent:
                if new_voice_state.channel.parent:

                    async def task():
                        try:
                            await self._adjust_voice_channels(
                                new_voice_state.channel.parent
                            )
                        except Exception:
                            if new_voice_state.channel:
                                logger.warn(
                                    f"Can't adjust voice channel for new state parent {new_voice_state.channel.parent}",
                                    exc_info=True,
                                )
                            else:
                                logger.warn(
                                    f"Can't adjust voice channel for new state (channel is none) {new_voice_state}",
                                    exc_info=True,
                                )

                    await self.spawn(task)

        CurrentLocale.set(self.guild_config[member.guild_id].locale)
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, member.id)
            if user:
                formatted = self._format_nick(user)
                try:
                    await self._update_nick_for_member(member, formatted)
                except Exception:
                    logger.warn(
                        "Unable to update nick for member %s", member, exc_info=True
                    )

    @event("message_create")
    async def _message_create(self, ctx, msg):
        # logger.debug(f"got message {msg.author} {msg.channel} {msg.content} {msg.snowflake_timestamp}")
        if msg.content.startswith("!ow"):
            logger.info(
                f"{msg.author.name} ({msg.author.id}) in {msg.channel} issued {msg.content}"
            )
        if msg.content.startswith("!"):
            return

    @event("guild_leave")
    async def _guild_leave(self, ctx, guild):
        logger.info(
            "I was removed from guild %s, I'm now in %d guilds",
            guild,
            len(self.client.guilds),
        )
        async with self.database.session() as session:
            gc = session.query(GuildConfigJson).filter_by(id=guild.id).one_or_none()
            if gc:
                logger.info("That guild was configured")
                session.delete(gc)
            cron = session.query(HighscoreCron).filter_by(id=guild.id).one_or_none()
            if cron:
                logger.info("That guild had a cron configured")
                session.delete(cron)
            with suppress(KeyError):
                del self.guild_config[guild.id]
            await run_sync(session.commit)

    @event("guild_member_remove")
    async def _guild_member_remove(self, ctx: Context, member: Member):
        logger.debug(
            f"Member {member.name}({member.id}) left the guild ({member.guild})"
        )
        if member.id == ctx.bot.user.id:
            # seems we got the remove_member event instead of the member_leave event?
            logger.info("Seems like I was kicked from guild %s", member.guild)
            await self._guild_leave(ctx, member.guild)
            return
        else:
            async with self.database.session() as session:
                user = await self.database.user_by_discord_id(session, member.id)
                if user:
                    in_other_guild = False
                    for guild in self.client.guilds.values():
                        if guild.id != member.guild.id and member.id in guild.members:
                            in_other_guild = True
                            logger.debug(f"{member.name} is still in guild {guild.id}")
                            break
                    if not in_other_guild:
                        logger.info(
                            f"deleting {user} from database because {member.name} left the guild and has no other guilds"
                        )
                        session.delete(user)
                        await run_sync(session.commit)

    @event("gateway_dispatch_received")
    async def _gw_dispatch_received(
        self, event_ctx: EventContext, event: str, data: dict
    ):
        if event.startswith("MESSAGE_REACTION_"):
            if "user_id" in data and int(data["user_id"]) == event_ctx.bot.user.id:
                return
            mid = int(data["message_id"])
            async with self.database.session() as session:
                wm_info = await self.database.get_welcome_message(session, mid)
                if not wm_info:
                    return
                session.expunge(wm_info)

            locale = locale_by_flag(data["emoji"]["name"]) or "en"
            CurrentLocale.set(locale)
            guild_id = int(data.get("guild_id", 0)) or None

            if guild_id:
                self._welcome_language[guild_id] = locale

            text = _(self._welcome_text)
            if wm_info.is_private_message:
                text += _(self._welcome_private_message_info).format(
                    guild_name=wm_info.guild_name
                )

            await self.client.http.edit_message(int(data["channel_id"]), mid, text)

            embed_id = wm_info.need_help_embed_id
            if embed_id:
                await self.client.http.edit_message(
                    int(data["channel_id"]),
                    embed_id,
                    embed={
                        "title": _(self._welcome_embed_title),
                        "description": _(self._welcome_embed_desc).format(
                            SUPPORT_DISCORD=SUPPORT_DISCORD
                        ),
                    },
                )

    @event("guild_join")
    async def _guild_joined(self, ctx: Context, guild: Guild):
        logger.info("Joined guild %r", guild)
        await self._handle_new_guild(guild)

    @event("guild_streamed")
    async def _guild_streamed(self, ctx, guild):
        logger.info("Streamed guild %r", guild)
        if guild.id not in self.guild_config:
            await self._handle_new_guild(guild)

    async def _handle_new_guild(self, guild):
        logger.info(
            r"We have a new guild %s, I'm now in %d guilds \o/",
            guild,
            len(self.client.guilds),
        )
        self.guild_config[guild.id] = GuildConfig.default()

        # try to find a channel to post the first hello message to
        channels = sorted(guild.channels.values(), key=attrgetter("position"))

        # if there is a welcome channel, try that first
        logger.debug("system channel is %r", guild.system_channel)
        if guild.system_channel:
            channels = [guild.system_channel] + list(channels)
        for channel in channels:
            if (
                channel.type == ChannelType.TEXT
                # when read_messages is false, no messages can be sent even if send_messages is true
                and channel.effective_permissions(guild.me).send_messages
                and channel.effective_permissions(guild.me).read_messages
            ):
                logger.debug("found hello channel %s", channel)
                async with self.database.session() as session:
                    try:
                        # no need to translate here, as we will provide reactions to translate for this one
                        message = await channel.messages.send(self._welcome_text)
                        logger.debug("message successfully sent")
                    except Exception:
                        logger.exception(
                            "Got exception when trying to send to channel %s, checking another one",
                            channel,
                        )
                        continue
                    else:
                        # found one
                        wm_info = WelcomeMessage(id=message.id)
                        try:
                            embed = await channel.messages.send(
                                content=None,
                                embed=Embed(
                                    title=self._welcome_embed_title,
                                    description=self._welcome_embed_desc.format(
                                        SUPPORT_DISCORD=SUPPORT_DISCORD
                                    ),
                                ),
                            )
                        except Exception:
                            logger.exception("Unable to send support embed")
                        else:
                            wm_info.need_help_embed_id = embed.id

                        for flag, locale in i18n.FLAG_TO_LOCALE.items():
                            if (
                                locale == "en"
                                or i18n.get_translation(locale, self._welcome_text)
                                != self._welcome_text
                            ):
                                try:
                                    await message.react(flag)
                                except Exception:
                                    logger.debug(
                                        "Cannot react to message", exc_info=True
                                    )

                        session.add(wm_info)
                        await run_sync(session.commit)

                        break
        else:
            #            logger.debug(
            #                'no valid "hello" channel found. Falling back to DM to owner for %s',
            #                guild,
            #            )
            logger.debug(
                'no valid "hello" channel found. NOT sending DM to owner of %s', guild
            )

    #            async with self.database.session() as session:
    #                try:
    #                    message = await guild.owner.send(
    #                        self._welcome_text
    #                        + self._welcome_private_message_info.format(
    #                            guild_name=guild.name
    #                        )
    #                    )
    #                except Exception:
    #                    logger.exception("Unable to send e-mail to owner, oh well…")
    #                else:
    #                    wm_info = WelcomeMessage(
    #                        id=message.id, is_private_message=True, guild_name=guild.name
    #                    )
    #                    session.add(wm_info)
    #                    try:
    #                        embed = await guild.owner.send(
    #                            content=None,
    #                            embed=Embed(
    #                                title=self._welcome_embed_title,
    #                                description=self._welcome_embed_desc.format(
    #                                    SUPPORT_DISCORD=SUPPORT_DISCORD
    #                                ),
    #                            ),
    #                        )
    #                    except Exception:
    #                        logger.exception("Unable to send support embed")
    #                    else:
    #                        wm_info.need_help_embed_id = embed.id
    #
    #                    for flag, locale in i18n.FLAG_TO_LOCALE.items():
    #                        if (
    #                            locale == "en"
    #                            or i18n.get_translation(locale, self._welcome_text)
    #                            != self._welcome_text
    #                        ):
    #                            try:
    #                                await message.react(flag)
    #                            except Exception:
    #                                logger.debug("Cannot react to message", exc_info=True)
    #                                break
    #
    #                    await run_sync(session.commit)

    # Util

    async def _adjust_voice_channels(
        self, parent, *, create_all_channels=False, adjust_user_limits=False
    ):
        guild = parent.guild
        if not guild:
            logger.debug(f"channel {parent} doesn't belong to a guild")
            return

        for cat in self.guild_config[guild.id].managed_voice_categories:
            if cat.category_id == parent.id:
                prefix_map = {prefix.name.strip(): prefix for prefix in cat.prefixes}
                break
        else:
            # logger.debug("channel is not managed")
            return

        logger.debug("adjusting parent %s", parent)

        def chan_name_no_sr(chan):
            return re.sub(r" \[.*?\]$", "", chan.name)

        def prefixkey(chan):
            return chan_name_no_sr(chan).rsplit("#", 1)[0].strip()

        def numberkey(chan):
            try:
                return int(chan_name_no_sr(chan).rsplit("#", 1)[1])
            except (TypeError, ValueError):
                logger.exception("Invalid numeric value")
                return 255

        async def delete_channel(chan):
            nonlocal made_changes

            id = chan.id
            logger.debug("deleting channel %s", chan)
            async with self.client.events.wait_for_manager(
                "channel_delete", lambda chan: chan.id == id
            ):
                try:
                    await chan.delete()
                except NotFound:
                    logger.warn(
                        "tried to delete a channel that Discord says does not exist, removing it from cache!",
                        exc_info=True,
                    )
                    chan.guild._channels.pop(chan.id, None)
            made_changes = True

        async def add_a_channel():
            nonlocal made_changes, chans, cat, guild

            name = f"{prefix.strip()} #{len(chans)+1}"
            logger.debug("creating a new channel %s", name)

            limit = prefix_map[prefix].limit

            async with self.client.events.wait_for_manager(
                "channel_create", lambda chan: chan.name == name
            ):
                await guild.channels.create(
                    type_=ChannelType.VOICE, name=name, parent=parent, user_limit=limit
                )

            made_changes = True

        def is_managed(chan):
            return bool(re.search(r" #\d+( \[.+?\])?\s*$", chan.name))

        sorted_channels = sorted(
            filter(is_managed, parent.children), key=attrgetter("name")
        )

        grouped = list(
            (prefix, list(sorted(group, key=numberkey)))
            for prefix, group in groupby(sorted_channels, key=prefixkey)
        )

        made_changes = False

        found_prefixes = frozenset(prefix for prefix, _ in grouped)

        for wanted_prefix in prefix_map.keys():
            if wanted_prefix not in found_prefixes:
                grouped.append((wanted_prefix, []))

        for prefix, chans in grouped:
            logger.debug("working on prefix %s, chans %s", prefix, chans)
            if prefix not in prefix_map.keys():
                logger.debug("%s is not in prefixes", prefix)
                if cat.remove_unknown:
                    for chan in chans:
                        # deleting a used channel is not cool
                        # sometimes, voice_members contains [None], it's empty
                        # then, so use any...
                        if not any(member for member in chan.voice_members):
                            await delete_channel(chan)
                continue
            # logger.debug("voicemembers %s", [chan.voice_members for chan in chans])
            empty_channels = [
                chan
                for chan in chans
                if not any(member for member in chan.voice_members)
            ]
            logger.debug("empty channels %s", empty_channels)

            if create_all_channels:
                while len(chans) < cat.channel_limit and len(parent.children) < 50:
                    await add_a_channel()
                    chans.append("dummy")  # value doesn't matter

            elif not empty_channels:
                if len(chans) < cat.channel_limit and len(parent.children) < 50:
                    await add_a_channel()

            elif len(empty_channels) == 1:
                # how we want it
                continue

            else:
                # more than one empty channel, delete the ones with the highest numbers
                for chan in empty_channels[1:]:
                    await delete_channel(chan)

        if True or made_changes:
            managed_channels = []
            unmanaged_channels = []

            # parent.children should be updated by now to contain newly created channels and without deleted ones

            for chan in (
                chan for chan in parent.children if chan.type == ChannelType.VOICE
            ):
                if is_managed(chan) and prefixkey(chan) in prefix_map.keys():
                    managed_channels.append(chan)
                else:
                    unmanaged_channels.append(chan)

            managed_group = {}
            for prefix, group in groupby(
                sorted(managed_channels, key=prefixkey), key=prefixkey
            ):
                managed_group[prefix] = sorted(list(group), key=numberkey)

            final_list = []

            async def channel_suffix(session, chan):
                srs = await self.database.get_srs(
                    session, [member.id for member in chan.voice_members if member]
                )

                combined = np.array([sr.values for sr in srs], dtype=np.float)

                if not any(x is not None for x in combined):
                    return ""

                # hide useless warning in case we take the mean of an empty slice
                with warnings.catch_warnings():

                    tds_filtered_mean = [
                        0
                        if np.all(np.isnan(x))
                        else np.nanmean(x[np.abs(x - np.nanmean(x)) <= 750])
                        for x in combined.T
                    ]

                def val(x):
                    return (
                        "xx" if np.isnan(x) else "⊘" if x == 0 else f"{int(x//100):02}"
                    )

                return f" [{'-'.join(val(x) for x in tds_filtered_mean)}]"

            for prefix, prefix_info in prefix_map.items():
                chans = managed_group[prefix]
                # rename channels if necessary
                async with self.database.session() as session:
                    for i, chan in enumerate(chans):
                        if cat.show_sr_in_nicks:
                            new_name = (
                                f"{prefix} #{i+1}{await channel_suffix(session, chan)}"
                            )
                        else:
                            new_name = f"{prefix} #{i+1}"

                        try:
                            await self._rename_channel(chan, new_name)
                            if adjust_user_limits:
                                limit = prefix_info.limit
                                await chan.edit(user_limit=limit)
                        except NotFound:
                            logger.warn(
                                "Tried to change a channel that Discord says does not exist, removing it from cache!",
                                exc_info=True,
                            )
                            chan.guild._channels.pop(chan.id, None)

                final_list.extend(chans)

            unmanaged_set = frozenset()
            if cat.managed_position == "top":
                start_pos = 0
                final_list.extend(
                    sorted(unmanaged_channels, key=attrgetter("position"))
                )
                unmanaged_set = frozenset(unmanaged_channels)
            else:
                start_pos = (
                    max(chan.position for chan in unmanaged_channels) + 1
                    if unmanaged_channels
                    else 1
                )

            pos = start_pos - 1
            for chan in final_list:
                pos += 1
                if pos < 100 and chan in unmanaged_set:
                    pos = 100
                if chan.position != pos:
                    try:
                        try:
                            await chan.edit(position=pos)
                        except:
                            logger.error(
                                "cannot edit channel %s, effective permissions %s",
                                chan,
                                chan.effective_permissions(guild.me),
                            )
                            raise
                        await trio.sleep(0.5)  #  FIXME: temporary hack
                    except NotFound:
                        logger.warn(
                            "Tried to change a channel that Discord says does not exist, removing from cache!",
                            exc_info=True,
                        )
                        chan.guild._channels.pop(chan.id, None)

    def _format_nick(self, user):
        primary = user.handles[0]

        if primary.sr:
            all_sr = primary.sr
        else:
            all_sr = TDS(None, None, None)

        if any(x is None for x in all_sr):
            # normally, we only save different values for SR, so if there is
            # a non null value, it should be the second or third, but just
            # to be sure, check the first 10...
            # negative value means it's an old one
            for old_sr in primary.sr_history[:10]:
                if old_sr.timestamp < datetime(2023, 1, 1):
                    break
                if old_sr.values:
                    all_sr = TDS(
                        *[av or (ov and -ov) for av, ov in zip(all_sr, old_sr.values)]
                    )
                if all(x is not None for x in all_sr):
                    break

        has_secondaries = len(user.handles) > 1

        def val_str(val, short=False):
            if val is None:
                return "⊘"
            elif val < 0:
                return f"{rank_fmt(-val, short=short)}?"
            else:
                return rank_fmt(val, short=short)

        def val_rank(val, short=False):
            if val is None:
                return "⊘"
            elif val < 0:
                return (RANKS if short else FULL_RANKS)[sr_to_rank(-val)] + "?"
            else:
                return (RANKS if short else FULL_RANKS)[sr_to_rank(val)]

        sr_str = "-".join(val_str(x, short=True) for x in all_sr)
        rank_str = "-".join(val_rank(x, short=True) for x in all_sr)
        full_sr_str = "-".join(val_str(x) for x in all_sr)
        full_rank_str = "-".join(val_rank(x) for x in all_sr)

        if has_secondaries:
            sec_mark = "*"
        else:
            sec_mark = ""

        t = Template(user.format)
        try:
            return (
                t.substitute(
                    sr=sr_str,
                    fullsr=full_sr_str,
                    rank=rank_str,
                    fullrank=full_rank_str,
                    dps=self.SYMBOL_DPS + val_str(all_sr.damage),
                    shortdps=self.SYMBOL_DPS + val_str(all_sr.damage, short=True),
                    dpsrank=self.SYMBOL_DPS + val_rank(all_sr.damage),
                    shortdpsrank=self.SYMBOL_DPS + val_rank(all_sr.damage, short=True),
                    damage=self.SYMBOL_DPS + val_str(all_sr.damage),
                    shortdamage=self.SYMBOL_DPS + val_str(all_sr.damage, short=True),
                    damagerank=self.SYMBOL_DPS + val_rank(all_sr.damage),
                    shortdamagerank=self.SYMBOL_DPS
                    + val_rank(all_sr.damage, short=True),
                    tank=self.SYMBOL_TANK + val_str(all_sr.tank),
                    shorttank=self.SYMBOL_TANK + val_str(all_sr.tank, short=True),
                    tankrank=self.SYMBOL_TANK + val_rank(all_sr.tank),
                    shorttankrank=self.SYMBOL_TANK + val_rank(all_sr.tank, short=True),
                    support=self.SYMBOL_SUPPORT + val_str(all_sr.support),
                    shortsupport=self.SYMBOL_SUPPORT
                    + val_str(all_sr.support, short=True),
                    supportrank=self.SYMBOL_SUPPORT + val_rank(all_sr.support),
                    shortsupportrank=self.SYMBOL_SUPPORT
                    + val_rank(all_sr.support, short=True),
                )
                + sec_mark
            )
        except KeyError as e:
            raise InvalidFormat(e.args[0]) from e

    async def _rename_channel(self, channel, new_name):
        """
        Discord only allows 2 renames within 10 minutes (per channel), so we have to enforce that
        limit somehow
        """
        # logger.debug("got a request to rename channel %s to %s", channel, new_name)

        self._new_channel_name[channel.id] = new_name

        async def perform_rename():
            # 10 minutes + 2 seconds safety margin
            reset_interval = 602
            try:
                try:
                    limit = self._channel_rename_limit[channel.id]
                except KeyError:
                    limit = ChannelRenameLimit(
                        lock=trio.Lock(), reset_time=None, remaining=2
                    )
                    self._channel_rename_limit[channel.id] = limit

                # logger.debug("Trying to acquire lock for channel %s", channel)
                async with limit.lock:
                    # logger.debug("Lock for channel %s acquired", channel)
                    if not limit.remaining:
                        to_sleep = limit.reset_time - time.time()
                        if to_sleep >= 0:
                            logger.debug(
                                "Rate limit for channel %s reached, sleeping %f s",
                                channel,
                                to_sleep,
                            )
                            await trio.sleep(to_sleep)

                        # reset limits
                        limit.reset_time = None
                        limit.remaining = 2

                    new_name = self._new_channel_name.get(channel.id)

                    if not new_name:
                        # logger.debug("no new name for channel %s, assuming it has already been renamed", channel)
                        return

                    # channel object/name might have changed in the meantime, so acquire it again

                    up_to_date_channel = channel.guild.channels.get(channel.id)
                    if not up_to_date_channel:
                        # logger.debug("Channel %s not found in channels list, assuming it has been deleted by now", channel)
                        pass
                    elif up_to_date_channel.name == new_name:
                        # logger.debug("no need to rename channel %s to %s, as it already has the correct name", up_to_date_channel, new_name)
                        pass
                    else:
                        logger.debug(
                            "renaming channel %s to %s", up_to_date_channel, new_name
                        )
                        try:
                            await up_to_date_channel.edit(name=new_name)
                        except NotFound:
                            logger.warn(
                                "Tried to change a channel that Discord says does not exist, removing from cache!",
                                exc_info=True,
                            )
                            channel.guild._channels.pop(channel.id, None)
                        if limit.reset_time is None:
                            limit.reset_time = time.time() + reset_interval
                        limit.remaining -= 1

                    del self._new_channel_name[channel.id]
            except Exception:
                logger.exception("Unhandled exception in perform_rename")

        await self.spawn(perform_rename)

    async def _update_nick(self, user, *, force=False, raise_hierachy_error=False):
        user_id = user.discord_id
        exception = new_nn = None

        for guild in self._configured_guilds():
            try:
                member = guild.members[user_id]
            except KeyError:
                continue
            try:
                CurrentLocale.set(self.guild_config[guild.id].locale)
                formatted = self._format_nick(user)
                new_nn = await self._update_nick_for_member(
                    member,
                    formatted,
                    user,
                    force=force,
                    raise_hierachy_error=raise_hierachy_error,
                )
            except Exception as e:
                exception = e
                continue

        if exception:
            raise exception

        return new_nn

    async def _update_nick_for_member(
        self,
        member,
        formatted: str,
        user=None,
        *,
        force=False,
        raise_hierachy_error=False,
    ):
        nn = str(member.name)

        if force or await self._show_sr_in_nick(member, user):
            if re.search(r"\[.*?\]", str(nn)):
                new_nn = re.sub(r"\[.*?\]", f"[{formatted}]", nn)
            else:
                new_nn = f"{nn} [{formatted}]"
        else:
            if re.search(r"\[.*?\]", str(nn)):
                new_nn = re.sub(r"\[.*?\]", "", nn)
            else:
                new_nn = nn

        if len(new_nn) > 32:
            raise NicknameTooLong(new_nn)

        if nn != new_nn:
            logger.debug("New nick for %s is %s", nn, new_nn)
            try:
                await member.nickname.set(new_nn)
            except (HierarchyError, PermissionsError):
                logger.info(
                    "Cannot update nick %s to %s due to insufficient permissions",
                    nn,
                    new_nn,
                )
                if raise_hierachy_error:
                    raise
            except Exception:
                logger.warn("error while setting nick", exc_info=True)
                raise

        return new_nn

    async def _show_sr_in_nick(self, member, user):
        if self.guild_config[member.guild_id].show_sr_in_nicks_by_default:
            return True

        if not user:
            async with self.database.session() as session:
                user = await self.database.user_by_discord_id(session, member.id)

        if user.always_show_sr:
            return True

        if member.voice:
            logger.debug("user %s is currently in voice", member)
            gi = self.guild_config[member.guild.id]
            logger.debug(
                "user is in %s with parent %s",
                member.voice.channel,
                member.voice.channel.parent,
            )
            for vc in gi.managed_voice_categories:
                if vc.category_id == member.voice.channel.parent.id:
                    logger.debug("that parent is managed")
                    return vc.show_sr_in_nicks

        return False

    async def _send_congrats(self, handle, role_idx, sr, rank, image):
        user = handle.user

        for guild in self._configured_guilds():
            try:
                if user.discord_id not in guild.members:
                    continue
                CurrentLocale.set(self.guild_config[guild.id].locale)
                embed = Embed(
                    # Translators: Used when somebody reached a new rank. Replace with the localized voiceline that Orisa uses
                    title=_("Supercharged and on fire!"),
                    description=_(
                        "**{name}** just reached **{sr} SR** as **{role}** and advanced to **{rank}**. Congratulations!"
                    ).format(
                        name=str(guild.members[user.discord_id].name),
                        sr=sr,
                        role=_(ROLE_NAMES[role_idx]),
                        rank=_(FULL_RANKS[rank]),
                    ),
                    colour=COLORS[rank],
                )

                embed.set_thumbnail(url=image)
                embed.set_footer(text=f"{handle.desc} {handle.handle}")

                await self.client.find_channel(
                    self.guild_config[guild.id].congrats_channel_id
                ).messages.send(
                    # Translators: <@!> is discord markup and needs to be preserved
                    content=_("Let's hear it for <@!{discord_id}>!").format(
                        discord_id=user.discord_id
                    ),
                    embed=embed,
                )
            except Exception:
                logger.exception(f"Cannot send congrats for guild {guild}")

    async def _top_players(self, guild_ids, style="fancy_grid", update_cron=True):
        def prev_sr(tag):
            for sr in tag.sr_history[:30]:
                prev_sr = sr
                if sr.timestamp < datetime.now() - timedelta(days=1):
                    break
            return prev_sr

        async with self.database.session() as session:

            handles = {
                (type_class, role): await run_sync(
                    session.query(type_class)
                    .options(joinedload(type_class.user))
                    .join(type_class.current_sr)
                    .order_by(desc(role))
                    .filter(role != None)
                    .filter(type_class.position == 0)
                    .filter(type_class.current_sr.has(SR.timestamp >= datetime(2023, 1, 1)))
                    .all
                )
                for role in [SR.tank, SR.damage, SR.support]
                #for type_class in [BattleTag, Gamertag, OnlineID]
                for type_class in [BattleTag]
            }

            def create_h_a_p():

                return [
                    (c, t, handle, prev_sr(handle))
                    # for c in [BattleTag, Gamertag, OnlineID]
                    for c in [BattleTag]
                    for t in [SR.tank, SR.damage, SR.support]
                    for handle in handles[c, t]
                ]

            handles_and_prev = await run_sync(create_h_a_p)

            top_per_guild = {}

            guilds = [
                guild for guild in self.client.guilds.values() if guild.id in guild_ids
            ]

            for type_class, type, handle, prev_sr in handles_and_prev:
                for guild in guilds:
                    try:
                        member = guild.members[handle.user.discord_id]
                    except KeyError:
                        # logger.debug(f"member {handle.user.discord_id} not found for highscore, downloading")
                        # try:
                        #     member = await self.client.download_guild_member(guild.id, handle.user.discord_id)
                        # except Exception:
                        #     logger.warn(f"unable to download member {handle.user.discord_id}, ignoring")
                        #     continue
                        # if member:
                        #     guild._members[handle.user.discord_id] = member
                        # else:
                        #     continue
                        continue

                    top_per_guild.setdefault(guild.id, {}).setdefault(
                        (type_class, type.key), []
                    ).append((member, handle, getattr(prev_sr, type.key)))

            def member_name(member):
                name = str(member.name)
                name = re.sub(r"\[.*?\]", "", name)
                name = re.sub(r"\{.*?\}", "", name)
                name = re.sub(r"\s{2,}", " ", name)

                return "".join(
                    ch if ord(ch) < 256 or unicodedata.category(ch)[0] != "S" else ""
                    for ch in name
                )

            for guild_id, role_tops in top_per_guild.items():
                logger.debug(f"Processing guild {guild_id} for top_players")
                CurrentLocale.set(self.guild_config[guild_id].locale)
                for type_role, tops in role_tops.items():
                    type_class, role = type_role

                    # FIXME: wrong if there is a tie
                    prev_top_tags = [
                        top[1]
                        for top in sorted(tops, key=lambda x: x[2] or 0, reverse=True)
                    ]

                    def prev_str(pos, tag, prev_sr):
                        if not prev_sr:
                            return "  (——)"

                        old_pos = prev_top_tags.index(tag) + 1
                        if pos == old_pos:
                            sym = " "
                        elif pos > old_pos:
                            sym = "↓"
                        else:
                            sym = "↑"

                        return f"{sym} ({old_pos:2})"

                    def delta_fmt(curr, prev):
                        if not curr or not prev or curr == prev:
                            return ""
                        else:
                            return f"{(curr-prev)//100:+2}"


                    table_prev_sr = None
                    data = []
                    for ix, (member, handle, prev_sr) in enumerate(tops):
                        if getattr(handle.sr, role) != table_prev_sr:
                            pos = ix + 1
                        sr = getattr(handle.sr, role)
                        table_prev_sr = sr
                        data.append(
                            (
                                pos,
                                prev_str(ix + 1, handle, prev_sr),
                                member_name(member),
                                member.id,
                                rank_fmt(sr),
                                delta_fmt(sr, prev_sr),
                            )
                        )

                    headers = [
                        # Translators: header for highscore table: position (keep it short)
                        _("#"),
                        # Translators: header for highscore table: previous position (keep it short)
                        _("prev"),
                        # Translators: header for highscore table: member name
                        _("Member"),
                        # Translators: header for highscore table: member discord id
                        _("Member ID"),
                        # Translators: header for highscore table: Rank
                        _("{role} Rank").format(role=_(role.capitalize())),
                        # Translators: header for highscore table: Division difference
                        _("ΔDiv"),
                    ]
                    csv_file = StringIO()
                    csv_writer = csv.writer(csv_file)
                    csv_writer.writerow(headers)
                    csv_writer.writerows(data)

                    csv_file = BytesIO(csv_file.getvalue().encode("utf-8"))
                    csv_file.seek(0)

                    def no_id(x):
                        return x[:3] + x[4:]

                    tabulate.PRESERVE_WHITESPACE = True
                    table_lines = tabulate.tabulate(
                        (no_id(e) for e in data), headers=no_id(headers), tablefmt=style
                    ).split("\n")

                    # fancy_grid inserts a ├─────┼───────┤ after every line, let's get rid of it
                    if style == "fancy_grid":
                        table_lines = [
                            line for line in table_lines if not line.startswith("├")
                        ]

                    # Split table into submessages, because a short gap is visible after each message
                    # we want it to be in "nice" multiples

                    ix = 0
                    lines = 20

                    try:
                        logger.debug("trying to send highscore to %i…", guild_id)
                        chan = self.client.find_channel(
                            self.guild_config[guild_id].listen_channel_id
                        )
                        if not chan:
                            logger.debug("no channel found")
                            continue
                        logger.debug("found channel %s", chan)
                        send = chan.messages.send
                        # send = self.client.application_info.owner.send
                        await send(
                            _(
                                "Hello! Here are the current SRs for **{role}** on {platform}. If a member has more than one "
                                "{handle_type}, only the primary {handle_type} is considered. Players with "
                                "private profiles, or those that didn't do their placements this season yet "
                                "are not shown."
                            ).format(
                                role=_(role.capitalize()),
                                platform=type_class.blizzard_url_type.upper(),
                                handle_type=_(type_class.desc),
                            )
                        )
                        while ix < len(table_lines):
                            # prefer splits at every "step" entry, but if it turns out too long, send a shorter message
                            step = lines if ix else lines + 3
                            await send_long(
                                send,
                                "```"
                                + ("\n".join(table_lines[ix : ix + step]) + "```"),
                            )
                            ix += step

                        # await chan.messages.upload(
                        #    csv_file,
                        #    filename=f"ranking_{role}_{type_class.blizzard_url_type.upper()}_{arrow.now().isoformat()[:10]}.csv",
                        # )
                        # logger.debug("upload done")
                    except Exception:
                        logger.exception(
                            "unable to send top players to guild %i", guild_id
                        )

                    # wait a bit before sending the next batch to avoid running into
                    # rate limiting and sending data twice due to "timeouts"
                    logger.debug("sleeping for 5s")
                    await trio.sleep(5)
                    logger.debug("done sleeping")
                # one guild done

    async def _message_new_guilds(self):
        for guild_id, guild in self.client.guilds.copy().items():
            if guild_id not in self.guild_config:
                await self._handle_new_guild(guild)

    async def _sync_handle(self, session, handle):
        try:
            srs, images = await get_sr(handle)
        except UnableToFindSR:
            logger.debug(f"No SR for {handle}, oh well…")
            srs = TDS(None, None, None)
            images = [None] * 3
        except Exception:
            handle.error_count += 1
            # we need to update the last_update pseudo-column
            handle.update_sr(handle.sr)
            if self.raven_client:
                self.raven_client.captureException()
            logger.exception(f"Got exception while requesting {handle.handle}")
            raise
        handle.error_count = 0
        handle.update_sr(srs)
        await self._handle_new_sr(session, handle, srs, images)

    async def _handle_new_sr(self, session, handle, srs, images):
        try:
            await self._update_nick(handle.user)
        except HierarchyError:
            # not much we can do, just ignore
            pass
        except NicknameTooLong as e:
            if (
                handle.user.last_problematic_nickname_warning is None
                or handle.user.last_problematic_nickname_warning
                < datetime.utcnow() - timedelta(days=7)
            ):
                handle.user.last_problematic_nickname_warning = datetime.utcnow()
                msg = _(
                    "*To avoid spamming you, I will only send out this warning once per week*\n"
                )
                msg += _(
                    "Hi! I just tried to update your nickname, but the result '{nick}' would be longer than 32 characters."
                ).format(nick=e.nickname)
                if handle.user.format == "$sr":
                    msg += _("\nPlease shorten your nickname.")
                else:
                    msg += _(
                        "\nTry to use the $sr format (you can type `@Orisa format $sr` into this DM channel), or shorten your nickname."
                    )
                msg += _(
                    "\nYour nickname cannot be updated until this is done. I'm sorry for the inconvenience."
                )
                discord_user = await self.client.get_user(handle.user.discord_id)
                await discord_user.send(msg)

            # we can still do the rest, no need to return here

        for role_ix, rank, sr, type_to_check, image in zip(
            range(3), handle.rank, srs, [SR.tank, SR.damage, SR.support], images
        ):

            if rank is not None:
                # get highest SR, but exclude current_sr
                await run_sync(session.commit)
                prev_highest_sr_value = (
                    session.query(func.max(type_to_check))
                    .join(SR.handle)
                    .filter(
                        SR.id != handle.current_sr_id,
                        Handle.user_id == handle.user_id,
                        Handle.type == handle.type,
                    )
                )

                prev_highest_sr = (
                    session.query(SR)
                    .join(SR.handle)
                    .filter(
                        type_to_check == prev_highest_sr_value,
                        Handle.user_id == handle.user_id,
                        Handle.type == handle.type,
                    )
                    .order_by(desc(SR.timestamp))
                    .first()
                )

                logger.debug(f"prev_sr {role_ix} {prev_highest_sr} {rank}")
                if prev_highest_sr and rank > sr_to_rank(
                    prev_highest_sr.values[role_ix]
                ):
                    logger.debug(
                        f"handle {handle} role {role_ix} old SR {prev_highest_sr}, new rank {rank}, sending congrats…"
                    )
                    await self._send_congrats(handle, role_ix, sr, rank, image)

    async def _sync_handles_from_channel(self, channel):
        first = True
        async with channel:
            async for handle_id in channel:
                if handle_id in self.sync_cache:
                    logger.debug("Already updated, not doing it again")
                    continue
                else:
                    self.sync_cache[handle_id] = True  # any value really
                if not first:
                    delay = 5 + random.random() * 10
                    logger.debug(f"rate limiting: sleeping for {delay:3.02}s")
                    await trio.sleep(delay)
                else:
                    first = False
                async with self.database.session() as session:
                    try:
                        handle = await self.database.handle_by_id(session, handle_id)
                        if handle:
                            await self._sync_handle(session, handle)
                        else:
                            logger.warn(
                                f"No handle for id {handle_id} found, probably deleted"
                            )
                        await run_sync(session.commit)
                    except Exception:
                        if handle:
                            logger.warn(
                                f"exception while syncing {handle} for {handle.user.discord_id}",
                                exc_info=True,
                            )
                        else:
                            logger.warn(
                                "Exception while getting handle for sync", exc_info=True
                            )
                    finally:
                        try:
                            await run_sync(session.commit)
                        except Exception:
                            logger.exception("cannot sync session")

    async def _sync_check(self):
        async with self.database.session() as session:
            ids_to_sync = await self.database.get_handles_to_be_synced(session)
        if ids_to_sync:
            logger.info(f"{len(ids_to_sync)} handles need to be synced")
            await self._sync_handles(ids_to_sync)
        else:
            logger.debug("No tags need to be synced")

    async def _sync_handles(self, ids_to_sync):
        send_ch, receive_ch = trio.open_memory_channel(len(ids_to_sync))

        async with send_ch:
            for tag_id in ids_to_sync:
                await send_ch.send(tag_id)

        async with trio.open_nursery() as nursery:
            async with receive_ch:
                for _ in range(min(len(ids_to_sync), 5)):
                    nursery.start_soon(
                        self._sync_handles_from_channel, receive_ch.clone()
                    )
        logger.info("done syncing")

    async def _sync_all_handles_task(self):
        logger.debug("started waiting…")
        await trio.sleep(10)
        while True:
            try:
                await self._sync_check()
            except Exception as e:
                logger.exception(f"something went wrong during _sync_check")
            await trio.sleep(5 * 60)

    async def _cron_task(self):
        "poor man's cron"

        while True:
            try:
                logger.debug("checking Cron…")
                async with self.database.session() as s:
                    to_process = await run_sync(
                        s.query(SR)
                        .filter(SR.processed == False)
                        .order_by(SR.timestamp.desc())
                        .all
                    )

                    logger.debug("to_process %s", to_process)

                    seen_handle_ids = set()

                    for sr in to_process:
                        logger.debug("working on %s", sr)
                        if sr.handle_id not in seen_handle_ids:
                            handle = sr.handle
                            logger.debug("new %s", handle)

                            ranks = "Bronze Silver Gold Platinum Diamond Master GM".split()
                            logger.debug("%d", sr_to_rank(sr.values.support))
                            images = [
                                f"https://orisa.rocks/web/standalone-{ranks[sr_to_rank(x)]}.png" if x else None
                                for x in sr.values
                            ]

                            await self._handle_new_sr(
                                s,
                                handle,
                                sr.values,
                                images
                            )
                            seen_handle_ids.add(sr.handle_id)
                        else:
                            logger.debug("already processed handle for %s", sr)
                        sr.processed = True
                    s.commit()

                async with self.database.session() as s:

                    now = datetime.utcnow()
                    to_run = await run_sync(
                        s.query(HighscoreCron).filter(HighscoreCron.next_run <= now).limit(10).all
                    )

                    logger.debug("to_run %s", to_run)

                    for hc in to_run:
                        hc.last_run = now
                        n = hc.next_run
                        n = now.replace(
                            hour=n.hour, minute=n.minute, second=n.second, microsecond=0
                        ) + timedelta(days=1)
                        hc.next_run = n
                    await run_sync(s.commit)

                    guild_ids = [h.id for h in to_run]

                if guild_ids:
                    logger.debug("running highscores…")
                    await self._top_players(guild_ids)
                    logger.debug("done running highscores")
            except Exception:
                logger.exception("Error during cron")
            await trio.sleep(1 * 60)

    async def _web_server(self):
        config = hypercorn.config.Config()
        config.access_logger = config.error_logger = logger
        config.bind = "127.0.0.1:9999"

        web.send_ch = self.web_send_ch
        web.client = self.client
        web.orisa = self

        logger.info("Starting web server")
        while True:
            try:
                await hypercorn.trio.serve(web.app, config)
            except Exception:
                logger.exception("hypercorn crashed!")
            logger.error("hypercorn serve stopped, restarting in 10s…")
            await trio.sleep(10)

    async def _oauth_result_listener(self):
        async with self.web_recv_ch as recv_ch:
            async for uid, type, data in recv_ch:
                logger.debug(
                    f"got OAuth response data {data} of type {type} for UID {uid}"
                )
                try:
                    with trio.move_on_after(60):
                        await self._handle_registration(uid, type, data)
                except Exception:
                    logger.error(
                        "Something went wrong when working with data %s",
                        data,
                        exc_info=True,
                    )

    async def _handle_registration(
        self, user_id, type: Literal["pc", "xbox", "psn"], data
    ):
        handles_to_check = []
        async with self.database.session() as session:
            user_obj = await self.client.get_user(user_id)
            user_channel = await user_obj.open_private_channel()

            if type == "pc":
                blizzard_id, battle_tag = data["id"], data.get("battletag")

                if battle_tag is None:
                    await user_channel.messages.send(
                        _(
                            "I'm sorry, it seems like you don't have a BattleTag. Use `@Orisa register xbox` to register an Xbox account."
                        )
                    )
                    return

                handles = [BattleTag(blizzard_id=blizzard_id, battle_tag=battle_tag, web_profile_uuid=None)]

            elif type == "xbox":
                handles = [
                    Gamertag(xbl_id=datum["id"], gamertag=datum["name"])
                    for datum in data
                    if datum["type"] == "xbox"
                ]

                if not handles:
                    await user_channel.messages.send(
                        _(
                            "I couldn't find a Xbox account linked to your Discord. Please link your Xbox account to Discord and try again. "
                            "Unfortunately, I cannot ask Xbox Live for the info."
                        )
                    )
                    return
            elif type == "psn":
                handles = [OnlineID(online_id=data.replace("\\", ""))]

            user = await self.database.user_by_discord_id(session, user_id)

            if user is None:
                user = User(discord_id=user_id, handles=handles, format="$sr")
                session.add(user)
                handles_to_check = handles

                extra_text = ""
                for guild in self._configured_guilds():
                    if user_id in guild.members:
                        extra_text = (
                            self.guild_config[guild.id].extra_register_text or ""
                        )
                        break
                first, *others = handles
                if others:
                    # Translators: type will be BattleTag or GamerTag, and it must be transformed into plural
                    desc = _(
                        "OK. People can now ask me for your {type}s **{handles}**, and I will keep track of your SR."
                    ).format(
                        type=_(first.desc), handles=", ".join(h.handle for h in handles)
                    )
                else:
                    desc = _(
                        "OK. People can now ask me for your {type} **{handle}**, and I will keep track of your SR."
                    ).format(type=_(first.desc), handle=first.handle)
                embed = Embed(
                    color=0x6DB76D, title=_("Registration successful"), description=desc
                )
                embed.add_field(
                    name=_(":information_source: Pro Tips"),
                    value=_(
                        "On some servers, I will only update your nick if you join a OW voice channel. If you want your nick to always show your SR, "
                        "use the `@Orisa alwaysshowsr` command. If you want me to show your rank instead of your SR, use `@Orisa format $rank`.\n"
                        "If you have more than one account, simply issue `@Orisa register` again.\n"
                    ),
                    inline=False,
                )
                if extra_text:
                    embed.add_field(
                        name=_(
                            ":envelope: A message from the *{guild_name}* staff"
                        ).format(guild_name=guild.name),
                        value=extra_text,
                        inline=False,
                    )
            else:
                logger.debug(f"user {user} already has handles {user.handles}")
                for new_handle in handles:
                    existing_handle = None
                    for handle in user.handles:
                        if handle.external_id == new_handle.external_id:
                            existing_handle = handle
                            logger.debug(
                                f"found existing handle {handle}, names are {existing_handle.handle} and {new_handle.handle}"
                            )
                            break
                    if existing_handle and existing_handle.handle != new_handle.handle:
                        embed = Embed(
                            color=0x6DB76D,
                            # Translators: type is battletag or gamertag
                            title=_("{type} updated").format(
                                type=_(existing_handle.desc)
                            ),
                            description=_(
                                "It seems like your {type} changed from *{old_handle}* to *{new_handle}*. I have updated my database."
                            ).format(
                                type=_(existing_handle.desc),
                                old_handle=existing_handle.handle,
                                new_handle=new_handle.handle,
                            ),
                        )
                        existing_handle.handle = new_handle.handle
                        existing_handle.web_profile_uuid = None
                        handles_to_check.append(existing_handle)
                        logger.debug(
                            f"handle name changed. handles_to_check is now {handles_to_check}"
                        )
                    elif existing_handle:
                        embed = Embed(
                            # Translators: type is translated GamerTag or BattleTag
                            title=_("{type} already registered").format(
                                type=_(existing_handle.desc)
                            ),
                            color=0x6F0808,
                            description=_(
                                "You already registered the {type} *{handle}*, so there's nothing for me to do. *Sleep mode reactivated.*\n"
                            ).format(
                                type=_(existing_handle.desc),
                                handle=existing_handle.handle,
                            ),
                        )
                        if type == "pc":
                            embed.add_field(
                                name=_(":information_source: Tip"),
                                value=_(
                                    "Open the URL in a private/incognito tab next time, so you can enter the credentials of the account you want."
                                ),
                                inline=False,
                            )
                        await user_obj.send(content=None, embed=embed)
                        return
                    else:
                        user.handles.append(new_handle)
                        handles_to_check.append(new_handle)
                        embed = Embed(
                            color=0x6DB76D,
                            # Translators: type is GamerTag/BattleTag
                            title=_("{type} added").format(type=_(new_handle.desc)),
                            # Translators: {new_type}s is plural. type is BattleTag/GamerTag
                            description=_(
                                "OK. I've added **{new_handle}** to the list of your {new_type}s. **Your primary {primary_type} remains {primary_handle}**. "
                                "To change your primary tag, use `@Orisa setprimary`, see help for more details."
                            ).format(
                                new_handle=new_handle.handle,
                                new_type=_(new_handle.desc),
                                primary_type=_(user.handles[0].desc),
                                primary_handle=user.handles[0].handle,
                            ),
                        )

            for handle in handles_to_check:
                try:
                    # Translators: Used during registration while Orisa checks the BattleTag/GamerTag. {type} is BattleTag/GamerTag, {tag} is the tag (Foo#2345)
                    check_msg_obj = await user_channel.messages.send(
                        _("Checking your {type} {tag}…").format(
                            type=_(handle.desc), tag=handle.handle
                        )
                    )
                    async with user_channel.typing:
                        srs, images = await get_sr(handle)
                except InvalidBattleTag as e:
                    logger.exception(f"Got invalid {handle.desc} for {handle.handle}")
                    await user_channel.messages.send(
                        _(
                            # Translators: {type} is "BattleTag", {handle} is the tag (Foo#2345), {message} is some untranslated English error message
                            "Invalid {type}: {message}… Blizzard claims that the {type} {handle} has no OW account. "
                            "Play a QP or arcade game, close OW and try again, sometimes this helps."
                        ).format(
                            type=_(handle.desc), handle=handle.handle, message=e.message
                        )
                    )
                    return
                except BlizzardError as e:
                    await user_channel.messages.send(
                        # Translators: e is some (English) error message
                        _(
                            "Sorry, but it seems like Blizzard's site has some problems currently ({e}), please try again later!"
                        ).format(e=e)
                    )
                    raise
                except UnableToFindSR:
                    embed.add_field(
                        # Translators: :warning: is an emoji code
                        name=_(":warning: No SR"),
                        value=_(
                            "You don't have an SR though, your profile needs to be public for SR tracking to work… I still saved your {type}."
                        ).format(type=_(handle.desc)),
                    )
                    srs = TDS(None, None, None)
                finally:
                    try:
                        await check_msg_obj.delete()
                    except Exception:
                        logger.exception("Unable to delete check message")

                handle.update_sr(srs)

            sort_secondaries(user)

            await run_sync(session.commit)

            try:
                await self._update_nick(user, force=True, raise_hierachy_error=True)
            except NicknameTooLong as e:
                embed.add_field(
                    # Translators: :warning: is emoji code
                    name=_(":warning: Nickname too long!"),
                    value=_(
                        "Adding your SR to your nickname as '{nickname}', would make it {len} characters, which is longer than Discord's maximum of 32."
                        "Please shorten it to 28 characters or less. I will regularly try to update it."
                    ).format(nickname=e.nickname, len=len(e.nickname)),
                    inline=False,
                )
            except HierarchyError as e:
                embed.add_field(
                    name=_(":warning: Cannot update nickname"),
                    value=_(
                        'I do not have sufficient permissions to update your nickname. The owner needs to move the "Orisa" role higher, '
                        "so that is higher than your highest role. If you are the owner of this server, there is no way for me to update your nickname, sorry!"
                    ),
                    inline=False,
                )
            except Exception as e:
                logger.warn(f"unable to update nick for user {user}", exc_info=True)
                embed.add_field(
                    name=_(":warning: Cannot update nickname"),
                    value=(
                        _(
                            "Right now I couldn't update your nickname, I will try that again later. "
                            "People will still be able to ask for your {type}, though."
                        ).format(type=_(user.handles[0].desc))
                    ),
                    inline=False,
                )
            finally:
                with suppress(Exception):
                    await self._update_nick(user)

            embed.add_field(
                name=_(":thumbsup: Vote for me on Discord Bot List"),
                value=_(
                    "If you find me useful, consider voting for me [by clicking here]({VOTE_LINK})!"
                ).format(VOTE_LINK=VOTE_LINK),
                inline=False,
            )

            embed.add_field(
                name=_(":heart: Say thanks by buying a coffee"),
                value=_(
                    "Want to say thanks to the guy who wrote and maintains me? Why not [buy him a coffee?]({DONATE_LINK})"
                ).format(DONATE_LINK=DONATE_LINK),
                inline=False,
            )

            await user_channel.messages.send(content=None, embed=embed)

    def _configured_guilds(self):
        return [
            guild
            for guild in self.client.guilds.values()
            if guild.id in self.guild_config
        ]


def fuzzy_nick_match(ann, ctx: Context, name: str):
    def strip_tags(name):
        return re.sub(r"^(\w*\s?\|)?([^[{]*)((\[|\{).*)?", r"\2", str(name)).strip()

    name = name.strip()

    member = member_id = None
    if ctx.guild:
        guilds = [ctx.guild]
    else:
        raise ConversionFailedError(
            ctx,
            name,
            Member,
            _(
                'This command must be issued from the Orisa channel in the Discord server if you give a name as argument, so I know where to look. Omit the name argument if you mean "myself"; that works even in DMs.'
            ),
        )
        # logger.debug("collecting guilds...")
        # guilds = [
        #    guild for guild in ctx.bot.guilds.values() if ctx.author.id in guild.members
        # ]
        # logger.debug("done collecting guilds")

    if name.startswith("<@") and name.endswith(">"):
        id = name[2:-1]
        if id[0] == "!":  # strip nicknames
            id = id[1:]
        try:
            member_id = int(id)
        except ValueError:
            raise ConversionFailedError(ctx, name, Member, "Invalid member ID")
    else:

        def scorer(s1, s2, force_ascii=True, full_process=True):
            if s1.lower() == s2.lower():
                return 200
            else:
                score = fuzz.WRatio(s1, s2, force_ascii, full_process)
                if s2.startswith(s1):
                    score *= 2
                return score

        logger.debug("collecting names")
        all_names = {
            id: strip_tags(mem.name)
            for guild in guilds
            for id, mem in guild.members.items()
        }
        # logger.debug(f"all_names {list(all_names.values())}")
        logger.debug("names collected, getting candidates")
        candidates = process.extractBests(name, all_names, scorer=scorer)
        logger.debug(f"candidates are {candidates}")
        if candidates:
            member_name, score, member_id = candidates[0]

    if member_id is not None:
        for guild in guilds:
            member = guild.members.get(member_id)
            if member:
                break

    if member is None:
        raise ConversionFailedError(
            ctx, name, Member, "Cannot find any member with that name"
        )
    else:
        return member


Context.add_converter(Member, fuzzy_nick_match)

multio.init("trio")
register_matplotlib_converters()

GLaDOS: ContextVar[bool] = ContextVar("GLaDOS", default=False)


class OrisaClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__GLaDOS_http = HTTPClient(GLADOS_TOKEN, bot=True)

    @contextmanager
    def as_glados(self):
        token = GLaDOS.set(True)
        try:
            yield
        finally:
            GLaDOS.reset(token)

    def _http_get(self):
        return self.__GLaDOS_http if GLaDOS.get() else self.__http

    def _http_set(self, http):
        self.__http = http

    http = property(_http_get, _http_set)

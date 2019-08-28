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
import logging.config

import csv
import functools
import math
import re
import random
import os
import tempfile
import traceback
import unicodedata
import urllib.parse
import warnings

from contextlib import contextmanager, nullcontext, suppress
from contextvars import ContextVar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import groupby, count
from io import BytesIO, StringIO
from operator import attrgetter, itemgetter
from string import Template
from typing import Optional

import asks
import cachetools
import dateutil.parser as date_parser
import hypercorn.config
import hypercorn.trio
import html5lib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import multio
import numpy as np
import pandas as pd
import pendulum
import raven
import seaborn as sns
import tabulate
import trio
import yaml

from curious import event
from curious.commands.context import Context
from curious.commands.conditions import author_has_roles
from curious.commands.decorators import command, condition
from curious.commands.exc import ConversionFailedError
from curious.commands.plugin import Plugin
from curious.core.client import Client
from curious.core.httpclient import HTTPClient
from curious.exc import Forbidden, HierarchyError, NotFound
from curious.dataclasses.channel import ChannelType
from curious.dataclasses.embed import Embed
from curious.dataclasses.guild import Guild
from curious.dataclasses.member import Member
from curious.dataclasses.presence import Game, Status
from fuzzywuzzy import process, fuzz
from lxml import html
from oauthlib.oauth2 import WebApplicationClient
from pandas.plotting import register_matplotlib_converters
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import func, desc, and_
from trio.to_thread import run_sync
from itsdangerous.url_safe import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature
from wcwidth import wcswidth

from .config import (
    GuildConfig,
    CHANNEL_NAMES,
    GLADOS_TOKEN,
    MASHERY_API_KEY,
    SENTRY_DSN,
    SIGNING_SECRET,
    OAUTH_BLIZZARD_CLIENT_ID,
    OAUTH_DISCORD_CLIENT_ID,
    OAUTH_REDIRECT_HOST,
    OAUTH_REDIRECT_PATH,
    PRIVACY_POLICY_PATH,
    RANK_EMOJIS,
    ROLE_EMOJIS,
    WEB_APP_PATH,
)
from .models import Cron, User, BattleTag, Gamertag, SR, Role, GuildConfigJson
from .exceptions import (
    BlizzardError,
    InvalidBattleTag,
    UnableToFindSR,
    NicknameTooLong,
    InvalidFormat,
)
from .utils import (
    get_sr,
    sort_secondaries,
    send_long,
    reply,
    resolve_handle_or_index,
    sr_to_rank,
    TDS,
)
from . import web


logger = logging.getLogger("orisa")


OAUTH_SERIALIZER = URLSafeTimedSerializer(SIGNING_SECRET)

SUPPORT_DISCORD="https://discord.gg/tsNxvFh"
VOTE_LINK="https://discordbots.org/bot/445905377712930817/vote"
DONATE_LINK="https://ko-fi.com/R5R2PC36"

RANKS = ("Br", "Si", "Go", "Pt", "Dm", "Ma", "GM")
FULL_RANKS = ("Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master", "Grandmaster")

ROLE_NAMES = 'Tank Damage Support'.split()

COLORS = (
    0xCD7E32,  # Bronze
    0xC0C0C0,  # Silver
    0xFFD700,  # Gold
    0xE5E4E2,  # Platinum
    0xA2BFD3,  # Diamond
    0xF9CA61,  # Master
    0xF1D592,  # Grand Master
)

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


# Main Orisa code
class Orisa(Plugin):

    SYMBOL_DPS = "\N{CROSSED SWORDS}"
    SYMBOL_TANK = "\N{SHIELD}"
    SYMBOL_SUPPORT = (
        "\N{VERY HEAVY GREEK CROSS}"
    )
    SYMBOL_FLEX = (
        "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}"
    )

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

    async def load(self):

        logger.debug("Loading config")
        async with self.database.session() as session:
            for config in await run_sync(session.query(GuildConfigJson).filter(
                GuildConfigJson.id.in_(self.client.guilds.keys())
            ).all):
                self.guild_config[config.id] = data = GuildConfig.from_json2(
                    config.config
                )
                logger.debug("Configured %d as %s", config.id, data)

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
    async def shutdown(self, ctx, safety: str = None):
        if safety != "Orisa":
            await reply(
                ctx,
                "If you want me to shut down, you need to issue `!ow shutdown Orisa` exactly as shown",
            )
        logger.critical("***** GOT EMERGENCY SHUTDOWN COMMAND FROM OWNER *****")
        try:
            await reply(ctx, "Shutting down...")
        except:
            pass
        try:
            await self.client.kill()
        except:
            pass
        raise SystemExit(42)

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
                    logger.exception(f"Error while sending to {user.discord_id}")
            logger.debug("Done sending")

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
        for guild in ctx.bot.guilds.values():
            try:
                logger.info("working on guild %s with owner %s (%s)", guild, guild.owner, guild.owner.name)
                await ctx.author.send(f"sending to {guild.owner.mention} ({guild.owner.name}) of {guild}")
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
                msg = await channel.messages.upload(data, filename=attachment.filename, message_content=message, message_embed=embed)
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
            r"https://discordapp.com/channels/[0-9]+/([0-9]+)/([0-9]+)", channel_id
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
    async def hs(self, ctx, kind: str, type_str = "pc", style: str = "fancy_grid"):

        prev_date = datetime.utcnow() - timedelta(days=1)

        logger.info("Triggered top_players %s %s", kind, type_str)

        async with self.database.session() as session:
            t = BattleTag if type_str == "pc" else Gamertag
            await self._top_players(session, prev_date, t, kind, style)

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
        async with self.database.session() as session:
            registered_ids = [x[0] for x in await run_sync(session.query(User.discord_id).all)]
            stale_ids = set(registered_ids) - set(member_ids)
            ids = "\n".join(f"<@{id}>" for id in stale_ids)
            await send_long(
                ctx.channel.messages.send, 
                f"there are {len(stale_ids)} stale entries: {ids}"
            )
            if doit == "confirm":
                for id in stale_ids:
                    user = await self.database.user_by_discord_id(session, id)
                    if not user:
                        await ctx.channel.messages.send(f"{id} not found in DB???")
                    else:
                        await run_sync(session.delete, user)
                        logger.info(f"deleted {id}")
                await send_long(ctx.channel.messages.send, f"Deleted {len(stale_ids)} entries")
                await run_sync(session.commit)
            elif stale_ids:
                await ctx.channel.messages.send("issue `!cleanup confirm` to delete.")

    @command()
    @condition(correct_channel)
    async def ping(self, ctx):
        await reply(ctx, "pong")

    # ow commands

    @command()
    @condition(correct_channel)
    async def ow(self, ctx, *, member: Member = None):
        def format_sr(handle):
            sr = handle.sr
            if not sr or not any(sr):
                return "—"

            def single_sr(symbol, sr):
                if sr:
                    return symbol + str(sr) + RANK_EMOJIS[sr_to_rank(sr)] if RANK_EMOJIS else symbol + str(sr)
                else:
                    return ""
            
            return " | ".join(single_sr(ROLE_EMOJIS[ix], val) for ix, val in enumerate(sr) if val)

        member_given = member is not None
        if not member_given:
            member = ctx.author

        content = embed = None
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, member.id)
            if user:
                embed = Embed(colour=0x659DBD)  # will be overwritten later if SR is set
                embed.add_field(name="Nick", value=member.name, inline=False)

                primary, *secondary = user.handles

                sr_value = f"**{format_sr(primary)}**\n"
                sr_value += "\n".join(format_sr(tag) for tag in secondary)

                multiple_handles = len(user.handles) > 1
                multiple_handle_types = len(set(handle.type for handle in user.handles)) > 1

                if multiple_handle_types:
                    def fmt(handle):
                        return f"{handle.handle} ({handle.blizzard_url_type.upper()})"
                else:
                    def fmt(handle):
                        return handle.handle

                handle_value = f"**{fmt(primary)}**\n"
                handle_value += "\n".join(fmt(handle) for handle in secondary)

                if multiple_handles:
                    if multiple_handle_types:
                        handle_name = "Handles"
                    else:
                        handle_name = f"{user.handles[0].desc}s"
                else:
                    handle_name = user.handles[0].desc

                embed.add_field(
                    name=handle_name, value=handle_value
                )
                if any(handle.sr for handle in user.handles):
                    embed.add_field(
                        name="SRs" if multiple_handles else "SR", value=sr_value
                    )

                if primary.sr is not None:
                    embed.colour = COLORS[sr_to_rank(np.nanmean(np.array([primary.sr.tank, primary.sr.damage, primary.sr.support], dtype=float)))]

                if user.roles:
                    embed.add_field(name="Roles", value=user.roles.format())

                embed.add_field(
                    name="Links",
                    inline=False,
                    value=(
                        f'[Overwatch profile](https://playoverwatch.com/en-us/career/{primary.blizzard_url_type}/{urllib.parse.quote(primary.handle.replace("#", "-"))}) | '
                        f'[Upvote Orisa]({VOTE_LINK}) | [Orisa Support Server]({SUPPORT_DISCORD}) | [Donate `❤️`]({DONATE_LINK})'
                    )
                )

                if primary.last_update:
                    if multiple_handles:
                        footer_text = f"The SR of the primary {user.handles[0].desc} was last updated {pendulum.instance(primary.last_update).diff_for_humans()}."
                    else:
                        footer_text = f"The SR was last updated {pendulum.instance(primary.last_update).diff_for_humans()}."
                else:
                    footer_text = ""

                if member == ctx.author and member_given:
                    footer_text += "\nBTW, you do not need to specify your nickname if you want your own BattleTag; just !ow is enough"
                embed.set_footer(text=footer_text)
            else:
                content = f"{member.name} not found in database! *Do you need a hug?*"
                if member == ctx.author:
                    embed = Embed(
                        title="Hint",
                        description="use `!ow register` to register, or `!ow help` for more info",
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
            title="About Me",
            description=(
                "I am an open source Discord bot to help manage Overwatch Discord communities.\n"
                "I'm written and maintained by Dennis Brakhane (Joghurt#2732 on Discord) and licensed under the "
                "[GNU Affero General Public License 3.0](https://www.gnu.org/licenses/agpl-3.0.en.html); the "
                "[development is done on Github](https://github.com/brakhane/Orisa)"
            ),
        )
        embed.add_field(
            name="Invite me to your own Discord",
            value=(
                "To invite me to your server, simply [click here](https://orisa.rocks/invite), I will post a message with more information in a channel after I have joined your server"
            ),
        )
        embed.add_field(
            name="Join the official Orisa Discord",
            value=(
                f"If you use me in your Discord server, or generally have suggestions, [join the official Orisa Discord]({SUPPORT_DISCORD}). Updates and new features "
                "will be discussed and announced there"
            ),
        )
        embed.add_field(
            name="Show your love :heart:",
            value=(
                f"If you find me useful, [buy my maintainer a cup of coffee]({DONATE_LINK})."
            )
        )
        await ctx.author.send(content=None, embed=embed)
        if not ctx.channel.private:
            await reply(ctx, "I've sent you a DM")

    @ow.subcommand()
    async def config(self, ctx, guild_id: int = None):
        is_owner = ctx.author == ctx.bot.application_info.owner
        if ctx.channel.private and not is_owner:
            await ctx.channel.messages.send(
                content="The config command must be issued from a channel of the server you want to configure. "
                "Don't worry, I will send you the config instructions as a DM, so others can't configure me just by watching you sending this command.",
                embed=Embed(
                    title="Tip",
                    description="`!ow config` works in *any* channel (that I'm allowed to read messages in, of course), so you can also use an admin only channel",
                ),
            )
            return

        if not is_owner and not any(
            role.name.lower() == "orisa admin" for role in ctx.author.roles
        ):
            help_embed=Embed(
                title=":thinking: Need help?",
                description=f"Join the [Support Discord]({SUPPORT_DISCORD})"
            )
            await reply(
                ctx,
                "This command can only be used by members with the `Orisa Admin` role (only the name of the role is important, it doesn't need any permissions)"
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
            title="Click here to configure me", url=f"{WEB_APP_PATH}config/{token}"
        )
        embed.add_field(
            name=":thinking: Need help?",
            value=f"Join the [Support Discord]({SUPPORT_DISCORD})"
        )
        embed.set_footer(text="This link will be valid for 30 minutes")
        try:
            await ctx.author.send(content=None, embed=embed)
            await reply(ctx, "I sent you a DM")
        except Forbidden:
            await reply(ctx,
            "I tried to send you a DM with the link, but you disallow DM from server members. Please allow that and retry. (I can't post the link here because "
            "everybody who knows that link will be able to configure me for the next 30 minutes)")


    @ow.subcommand()
    @condition(correct_channel)
    async def register(self, ctx, *, type: str = "pc"):
        user_id = ctx.message.author_id

        if "#" in type:
            await reply(ctx, f"{type} looks like a BattleTag and not like pc/xbox, assuming you meant just `!ow register`...")
            type = "pc"

        if type == "pc":
            client = WebApplicationClient(OAUTH_BLIZZARD_CLIENT_ID)
            oauth_url = "https://eu.battle.net/oauth/authorize"
            scope = []
            description=(
                "To complete your registration, I need your permission to ask Blizzard for your BattleTag. Please click "
                "the link above and give me permission to access your data. I only need this permission once, you can remove it "
                "later in your BattleNet account."
            )
        elif type == "xbox":
            client = WebApplicationClient(OAUTH_DISCORD_CLIENT_ID)
            oauth_url = "https://discordapp.com/oauth2/authorize"
            scope = ["connections"]
            description=(
                "To complete your registration, I need your permission to ask Discord for your Gamertag. Please click "
                "the link above and give me permission to access your data. Make sure you have linked your Xbox account to Discord."
            )
        else:
            await reply(ctx, f'Invalid registration type "{type}". Use `!ow register` or `!ow register pc` for PC; `!ow register xbox` for XBOX. PlayStation is not supported yet.')
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
            title=f"Click here to register your {type.upper()} account",
            description=description
        )
        if type == "pc":
            embed.add_field(
                name=":information_source: Protip",
                value="If you want to register a secondary/smurf BattleTag, you can open the link in a private/incognito tab (try right clicking the link) and enter the "
                "account data for that account instead.",
            )
            embed.add_field(
                name=":video_game: Not on PC?",
                value="If you have an XBL account, use `!ow register xbox`. PSN accounts are currently not supported, but will be in the future."
            )
        embed.set_footer(
            text="By registering, you agree to Orisa's Privacy Policy; you can read it by entering !ow privacy"
        )

        try:
            await ctx.author.send(content=None, embed=embed)
        except Forbidden:
            await reply(ctx, 'I\'m not allowed to send you a DM. Please right click on the Discord server, select Privacy Settings, and enable "Allow direct messages from server members." Then try again.')
        else:
            if not ctx.channel.private:
                await reply(ctx, "I sent you a DM with instructions.")

    @ow.subcommand()
    @condition(correct_channel)
    async def unregister(self, ctx, handle_or_index: str):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(
                    ctx, "You are not registered, there's nothing for me to do."
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
                    "You cannot unregister your primary handle. Use `!ow setprimary` to set a different primary first, or "
                    "use `!ow forgetme` to delete all your data.",
                )
                return

            removed = user.handles.pop(index)
            handle = removed.handle
            await run_sync(session.commit)
            await reply(ctx, f"Removed **{handle}**")
            await self._update_nick_after_secondary_change(ctx, user)

    async def _update_nick_after_secondary_change(self, ctx, user):
        try:
            await self._update_nick(user, force=True)
        except HierarchyError:
            pass
        except NicknameTooLong as e:
            await reply(
                ctx,
                f'However, your new nickname "{e.nickname}" is now longer than 32 characters, which Discord doesn\'t allow. '
                "Please choose a different format, or shorten your nickname and do a `!ow forceupdate` afterwards.",
            )
        except:
            await reply(
                ctx,
                "However, there was an error updating your nickname. I will try that again later.",
            )
        with suppress(HierarchyError):
            await self._update_nick(user)

    @ow.subcommand()
    @condition(correct_channel)
    async def setprimary(self, ctx, handle_or_index: str):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "You are not registered. Use `!ow register` first.")
                return
            try:
                index = resolve_handle_or_index(user, handle_or_index)
            except ValueError as e:
                await reply(ctx, e.args[0])
                return
            if index == 0:
                await reply(
                    ctx,
                    f'"{user.handles[0].handle}" already is your primary {user.handles[0].desc}. *Going back to sleep*',
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
                f"Done. Your primary {user.handles[0].desc} is now **{user.handles[0].handle}**.",
            )
            await self._update_nick_after_secondary_change(ctx, user)

    @ow.subcommand()
    @condition(correct_channel)
    async def format(self, ctx, *, format: str):
        if "]" in format:
            await reply(ctx, "format string may not contain square brackets")
            return
        if "$" not in format:
            await reply(ctx, "format string must contain at least one $placeholder")
            return
        if not format:
            await reply(ctx, "format string missing")
            return

        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "you must register first")
                return
            else:
                user.format = format
                try:
                    new_nick = await self._update_nick(user, force=True)
                except InvalidFormat as e:
                    await reply(
                        ctx, f'Invalid format string: unknown placeholder "{e.key}"'
                    )
                    await run_sync(session.rollback)
                except NicknameTooLong as e:
                    await reply(
                        ctx,
                        f"Sorry, using this format would make your nickname be longer than 32 characters ({len(e.nickname)} to be exact).\n"
                        f"Please choose a shorter format or shorten your nickname",
                    )
                    await run_sync(session.rollback)
                else:
                    titles = [
                        "Smarties Expert",
                        "Bread Scientist",
                        "Eternal Bosom of Hot Love",
                        "Sith Lord of Security",
                        "Namer of Clouds",
                        "Scourge of Beer Cans",
                        "Muse of Jeff Kaplan",
                        "Shredded Cheese Authority",
                        "MILF Commander",
                        "Cunning Linguist",
                        "Pork Rind Expert",
                        "Dinosaur Supervisor",
                        "Galactic Viceroy of C9",
                        "Earl of Bacon",
                        "Dean of Pizza",
                        "Duke of Tacos",
                        "Retail Jedi",
                        "Pornography Historian",
                    ]
                    # reset if SR should not be shown normally
                    await self._update_nick(user)
                    await reply(
                        ctx,
                        f'Done. Henceforth, ye shall be knownst as "`{new_nick}`, {random.choice(titles)}."',
                    )
            await run_sync(session.commit)

    @ow.subcommand(aliases=("alwayshowsr",))
    @condition(correct_channel)
    async def alwaysshowsr(self, ctx, param: str = "on"):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "you are not registered")
                return
            new_setting = param != "off"
            user.always_show_sr = new_setting
            await self._update_nick(user)
            await run_sync(session.commit)

        msg = "Done. "
        if new_setting:
            msg += "Your nick will be updated even when you are not in an OW voice channel. Use `!ow alwaysshowsr off` to turn it off again"
        else:
            msg += "Your nick will only be updated when you are in an OW voice channel. Use `!ow alwaysshowsr on` to always update your nick"
        await reply(ctx, msg)

    @ow.subcommand()
    @condition(correct_channel, bypass_owner=False)
    async def forceupdate(self, ctx):
        async with self.database.session() as session:
            logger.info(f"{ctx.author.id} used forceupdate")
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "you are not registered")
            else:
                fault = False
                async with ctx.channel.typing:
                    for handle in user.handles:
                        try:
                            await self._sync_handle(session, handle)
                        except Exception as e:
                            if self.raven_client:
                                self.raven_client.captureException()
                            logger.exception(f"exception while syncing {handle}")
                            fault = True

                if fault:
                    await reply(
                        ctx,
                        "There were some problems updating your SR. Try again later.",
                    )
                else:
                    await reply(
                        ctx,
                        f"OK, I have updated your data. Your (primary) SR is now {user.handles[0].sr}. "
                        "If that is not correct, you need to log out of Overwatch once and try again; your "
                        "profile also needs to be public for me to track your SR.",
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
                    for guild in self.client.guilds.values():
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
                await reply(ctx, f"OK, deleted {ctx.author.name} from database")
                await run_sync(session.commit)
            else:
                await reply(
                    ctx,
                    "you are not registered anyway, so there's nothing for me to forget...",
                )

    @ow.subcommand()
    @condition(correct_channel)
    async def findplayers(self, ctx, diff_or_min_sr: int = None, max_sr: int = None):
        await self._findplayers(ctx, diff_or_min_sr, max_sr, findall=False)

    @ow.subcommand()
    @condition(correct_channel)
    async def findallplayers(self, ctx, diff_or_min_sr: int = None, max_sr: int = None):
        await self._findplayers(ctx, diff_or_min_sr, max_sr, findall=True)

    @ow.subcommand()
    @condition(correct_channel)
    async def setrole(self, ctx, *, roles_str: str=None):
        "Alias for setroles"
        return await self.setroles(ctx, roles_str=roles_str)

    @ow.subcommand()
    @condition(correct_channel)
    async def setroles(self, ctx, *, roles_str: str=None):
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
                "Missing roles identifier. Valid role identifiers are: `m` (Main Tank), `o` (Off Tank), `d` (Damage), `s` (Support). They can be combined, eg. `ds` would mean Damage + Support."
            )
            return

        for role in roles_str.replace(" ", "").lower():
            try:
                roles |= names[role]
            except KeyError:
                await reply(
                    ctx,
                    f"Unknown role identifier '{role}'. Valid role identifiers are: `m` (Main Tank), `o` (Off Tank), `d` (Damage), `s` (Support). They can be combined, eg. `ds` would mean Damage + Support.",
                )
                return

        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "You are not registered! Do `!ow register` first.")
                return
            user.roles = roles
            await run_sync(session.commit)
            await reply(ctx, f"Done. Your roles are now **{roles.format()}**.")

    async def _findplayers(
        self, ctx, diff_or_min_sr: int = None, max_sr: int = None, *, findall
    ):
        await reply(ctx, "Sorry, findplayers doesn't work with role based SR yet. Try later.")
        return
        logger.info(
            f"{ctx.author.id} issued findplayers {diff_or_min_sr} {max_sr} {findall}"
        )

        async with self.database.session() as session:
            asker = await self.database.user_by_discord_id(session, ctx.author.id)
            if not asker:
                await reply(ctx, "you are not registered")
                return

            if max_sr is None:
                # we are looking around the askers SR
                sr_diff = diff_or_min_sr

                if sr_diff is not None:
                    if sr_diff <= 0:
                        await reply(ctx, "SR difference must be positive")
                        return

                    if sr_diff > 5000:
                        await reply(
                            ctx, "You just had to try ridiculous values, didn't you?"
                        )
                        return

                base_sr = asker.handles[0].sr
                if not base_sr:
                    await reply(
                        ctx,
                        "You primary {asker.handles[0].desc} has no SR, please give a SR range you want to search for instead",
                    )
                    return

                if sr_diff is None:
                    sr_diff = 1000 if base_sr < 3500 else 500

                min_sr, max_sr = base_sr - sr_diff, base_sr + sr_diff

                type_msg = f"within {sr_diff} of {base_sr} SR"

            else:
                # we are looking at a range
                min_sr = diff_or_min_sr

                if not (
                    (500 <= min_sr <= 5000)
                    and (500 <= max_sr <= 5000)
                    and (min_sr <= max_sr)
                ):
                    await reply(
                        ctx,
                        "min and max must be between 500 and 5000, and min must not be larger than max.",
                    )
                    return

                type_msg = f"between {min_sr} and {max_sr} SR"

            candidates = (
                session.query(BattleTag)
                .join(BattleTag.current_sr)
                .options(joinedload(BattleTag.user))
                .filter(SR.value.between(min_sr, max_sr))
                .all()
            )

            users = set(c.user for c in candidates)

            cmap = {u.discord_id: u for u in users}

            online = []
            offline = []

            for guild in self.client.guilds.values():

                if ctx.author.id not in guild.members:
                    continue

                for member in guild.members.values():
                    if member.user.id == ctx.author.id or member.user.id not in cmap:
                        continue
                    if member.status == Status.OFFLINE:
                        offline.append(member)
                    else:
                        online.append(member)

            def format_member(member):
                nonlocal cmap
                markup = "~~" if member.status == Status.DND else ""

                if member.status == Status.IDLE:
                    hint = "(idle)"
                elif member.status == Status.DND:
                    hint = "(DND)"
                else:
                    hint = ""

                return f"{markup}{str(member.name)}\u00a0{member.mention}{markup}\u00a0{hint}\n"

            msg = ""

            if not online:
                msg += f"There are no players currently online {type_msg}\n\n"
            else:
                msg += f"**The following players are currently online and {type_msg}:**\n\n"
                msg += "\n".join(format_member(m) for m in online)
                msg += "\n"

            if findall:

                if not offline:
                    if online:
                        msg += "There are no offline players within that range."
                    else:
                        msg += "There are also no offline players within that range. :("
                else:
                    msg += "**The following players are within that range, but currently offline:**\n\n"
                    msg += "\n".join(format_member(m) for m in offline)

            else:
                if offline:
                    msg += f"\nThere are also {len(offline)} offline players within that range. Use the `findallplayers` "
                    msg += "command to show them as well."

            await send_long(ctx.author.send, msg)
            if not ctx.channel.private:
                await reply(ctx, "I sent you a DM with the results.")

    @ow.subcommand()
    async def help(self, ctx):
        if not ctx.channel.private:
            if (
                ctx.channel.guild_id not in self.guild_config
                or self.guild_config[ctx.channel.guild_id] == GuildConfig.default()
            ):
                await reply(
                    ctx,
                    "I'm not configured yet! Somebody with the role `Orisa Admin` needs to issue `!ow config` to configure me first!",
                )
                try:
                    await ctx.channel.messages.send(content=None, embed=Embed(
                        title=":thinking: Need help?",
                        description=f"Join the [Support Discord]({SUPPORT_DISCORD})"
                    ))
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
                "I tried to send you a DM with help, but you don't allow DM from server members. "
                "I can't post it here, because it's rather long. Please allow DMs and try again.",
            )
        elif not ctx.channel.private:
            await reply(ctx, "I sent you a DM with instructions.")

    def _create_help(self, ctx):
        channel_id = None

        for guild in self.client.guilds.values():
            if ctx.author.id in guild.members:
                channel_id = self.guild_config[guild.id].listen_channel_id
                break

        embed = Embed(
            title="Orisa's purpose",
            description=(
                "When joining a QP or Comp channel, you need to know the BattleTag of a channel member, or they need "
                "yours to add you. In competitive channels it also helps to know which SR the channel members have. "
                "To avoid having to ask for this information again and again when joining a channel, this bot was created. "
                "When you register with your BattleTag, your nick will automatically be updated to show your "
                "current SR and it will be kept up to date. You can also ask for other member's BattleTag, or request "
                "your own so others can easily add you in OW.\n"
                "It will also send a short message to the chat when you ranked up.\n"
                f"*Like Overwatch's Orisa, this bot is quite young and still new at this. Report issues to <@!{self.client.application_info.owner.id}>*\n"
                f"\n**The commands only work in the <#{channel_id}> channel or by sending me a DM**\n"
                "If you are new to Orisa, you are probably looking for `!ow register` or `!ow register xbox`\n"
                "If you want to use Orisa on your own server or help developing it, enter `!ow about`\n"
                "Parameters in [square brackets] are optional."
            ),
        )
        embed.add_field(
            name="!ow [nick]",
            value=(
                "Shows the BattleTag for the given nickname, or your BattleTag "
                "if no nickname is given. `nick` can contain spaces. A fuzzy search for the nickname is performed.\n"
                "*Examples:*\n"
                "`!ow` will show your BattleTag\n"
                '`!ow the chosen one` will show the BattleTag of "tHE ChOSeN ONe"\n'
                '`!ow orisa` will show the BattleTag of "SG | Orisa", "Orisa", or "Orisad"\n'
                '`!ow oirsa` and `!ow ori` will probably also show the BattleTag of "Orisa"'
            ),
        )
        embed.add_field(
            name="!ow about",
            value="Shows information about Orisa, and how you can add her to your own Discord server, or help supporting her",
        )
        embed.add_field(
            name="!ow alwaysshowsr [on/off]",
            value="On some servers, Orisa will only show your SR or rank in your nick when you are in an OW voice channel. If you want your nick to always show your SR or rank, "
            "set this to on.\n"
            "*Example:*\n"
            "`!ow alwaysshowsr on`",
        )
        embed.add_field(
            name="!ow config",
            value='This command can only be used by members with the "Orisa Admin" role and allows them to configure Orisa for the specific Discord server',
        )
        embed.add_field(
            name="!ow dumpsr",
            value="Download your SR history as an Excel sheet"
        )
        embed.add_field(
            name="!ow findplayers [max diff] *or* !ow findplayers min max",
            value="*This command is still in beta and may change at any time!*\n"
            "This command is intended to find partners for your Competitive team and shows you all registered and online users within the specified range.\n"
            "If `max diff` is not given, the maximum range that allows you to queue with them is used, so 1000 below 3500 SR, and 500 otherwise. "
            "If `max diff` is given, it is used instead. `findplayers` then searches for all online players that around that range of your own SR.\n"
            "Alternatively, you can give two parameters, `!ow findplayers min max`. In this mode, `findplayers` will search for all online players that are between "
            "min and max.\n"
            "Note that `findplayers` will take all registered BattleTags of players into account, not just their primary.\n"
            "*Examples:*\n"
            "`!ow findplayers`: finds all players that you could start a competitive queue with\n"
            "`!ow findplayers 123`: finds all players that are within 123 SR of your SR\n"
            "`!ow findplayers 1500 2300`: finds all players between 1500 and 2300 SR\n",
        )
        embed.add_field(
            name="!ow findallplayers [max diff] *or* !ow findplayers min max",
            value="Same as `findplayers`, but also includes offline players",
        )
        embed.add_field(
            name="!ow forceupdate",
            value="Immediately checks your account data and updates your nick accordingly.\n"
            "*Checks and updates are done automatically, use this command only if "
            "you want your nick to be up to date immediately!*",
        )
        embed.add_field(
            name="!ow forgetme",
            value="All your BattleTags will be removed from the database and your nick "
            "will not be updated anymore. You can re-register at any time.",
        )

        embed.add_field(
            name="!ow format *format*",
            value="Lets you specify how your SR or rank is displayed. It will always be shown in [square\u00a0brackets] appended to your name.\n"
            "In the *format*, you can specify placeholders with `$placeholder` or `${placeholder}`."
        )
        embed.add_field(
            name="\N{BLACK STAR} *ow format placeholders*",
            value="*The following placeholders are defined:*\n"
            "`$sr`\nthe first two digits of your SR for all 3 roles in order Tank, Damage, Support; if you have secondary accounts, an asterisk (\*) is added at the end. A question mark is added if an old SR is shown\n\n"
            "`$fullsr`\nLike `$sr` but all 4 digits are shown\n\n"
            "`$rank`\nyour rank in shortened form for all 3 roles in order Tank, Damage, Support; asterisk and question marks work like in `$sr`\n\n"
            "`$tank`, `$damage`, `$support`\nYour full SR for the respective role followed by its symbol. Asterisk and question mark have the same meaning like in `$sr`. "
            f"For technical reasons the symbols for the respective roles are `{self.SYMBOL_TANK}`, `{self.SYMBOL_DPS}`, `{self.SYMBOL_SUPPORT}`\n\n"
            "`$tankrank`, `$damagerank`, `$supportrank`\nlike above, but the rank is shown instead.\n\n"
            "`$dps`, `$dpsrank`\nAlias for `$damage` and `$damagerank`, respectively"
        )
        embed.add_field(
            name="\N{BLACK STAR} *ow format examples*",
            value=
            "`!ow format hello $sr` will result in `[hello 12-34-45]`\n"
            "`!ow format Potato/$fullrank` in `[Potato/Bronze-Gold-Diamond]`.\n"
            f"`!ow format $damage $support` in `[1234{self.SYMBOL_DPS} 2345{self.SYMBOL_SUPPORT}]`\n"
            "*By default, the format is `$sr`*",
        )

        embeds = [embed]
        embed = Embed(title="help cont'd")
        embeds.append(embed)

        embed.add_field(
            name="!ow get nick",
            value=(
                "Same as `!ow [nick]`, (only) useful when the nick is the same as a command.\n"
                "*Example:*\n"
                '`!ow get register` will search for the nick "register"'
            ),
        )
        embed.add_field(
            name="!ow register [pc/xbox]",
            value="Create a link to your BattleNet or Gamertag account, or adds a secondary BattleTag to your account. "
            "Your OW account will be checked periodically and your nick will be "
            "automatically updated to show your SR or rank (see the *format* command for more info). "
            "`!ow register` and `!ow register pc` will register a PC account, `!ow register xbox` will register an XBL account. "
            "If you register an XBL account, you have to link it to your Discord beforehand. PSN accounts are not supported yet.",
        )
        embed.add_field(name="!ow privacy", value="Show Orisa's Privacy Policy")
        embed.add_field(
            name="!ow setprimary *battletag*",
            value="Makes the given secondary BattleTag your primary BattleTag. Your primary BattleTag is the one you are currently using, the its SR is shown in your nick\n"
            "Unlike `register`, the search is performed fuzzy and case-insensitve, so you normally only need to give the first (few) letters.\n"
            "The given BattleTag must already be registered as one of your BattleTags.\n"
            "*Example:*\n"
            "`!ow setprimary jjonak`",
        )
        embed.add_field(
            name="!ow setprimary *index*",
            value="Like `!ow setprimary battletag`, but uses numbers, 1 is your first secondary, 2 your seconds etc. The order is shown by `!ow` (alphabetical)\n"
            "Normally, you should not need to use this alternate form, it's available in case Orisa gets confused on what BattleTag you mean (which shouldn't happen)\n"
            "*Example:*\n"
            "`!ow setprimary 1`",
        )
        embed.add_field(
            name="!ow setroles *roles*",
            value="Sets the role you can/want to play. It will be shown in `!ow` and will also be used to update the number of roles "
            "in voice channels you join.\n"
            '*roles* is a single "word" consisting of one or more of the following identifiers (both upper and lower case work):\n'
            "`d` for DPS, `m` for Main Tank, `o` for Off Tank, `s` for Support\n"
            "*Examples:*\n"
            "`!ow setroles d`: you only play DPS\n"
            "`!ow setroles so`: you play Support and Off Tanks\n"
            "`!ow setroles dmos`: you are a true Flex and play everything.",
        )
        embed.add_field(
            name="!ow srgraph [from_date]",
            value="*This command is in beta and can change at any time; it might also have bugs, report them please*\n"
            "Shows a graph of your SR. If from_date (as DD.MM.YY or YYYY-MM-DD) is given, the graph starts at that date, otherwise it starts "
            "as early as Orisa has data.",
        )
        embed.add_field(
            name="!ow usersrgraph *username* [from_date]",
            value="*This command can only be used by users with the Orisa Admin role!*\n"
            "Like srgraph, but shows the graph for the given user"
        )
        embed.add_field(
            name="!ow unregister *battletag*",
            value="If you have secondary BattleTags, you can remove the given BattleTag from the list. Unlike register, the search is performed fuzzy, so "
            "you normally only have to specify the first few letters of the BattleTag to remove.\n"
            "You cannot remove your primary BattleTag, you have to choose a different primary BattleTag first.\n"
            "*Example:*\n"
            "`!ow unregister foo`",
        )
        embed.add_field(
            name="!ow unregister *index*",
            value="Like `unregister battletag`, but removes the battletag by number. Your first secondary is 1, your second 2, etc.\n"
            "The order is shown by the `!ow` command (it's alphabetical).\n"
            "Normally, you should not need to use this alternate form, it's available in case Orisa gets confused on what BattleTag you mean (which shouldn't happen)\n"
            "*Example:*\n"
            "`!ow unregister 1`",
        )

        return embeds

    @ow.subcommand()
    @condition(correct_channel)
    async def srgraph(self, ctx, date: str = None):

        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "You are not registered. Do `!ow register` first.")
                return
            else:
                await self._srgraph(ctx, user, ctx.author.name, date)

    @ow.subcommand()
    @author_has_roles("Orisa Admin")
    async def usersrgraph(self, ctx, member: Member, date: str = None):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, member.id)
            if not user:
                await reply(ctx, f"{member.name} not registered")
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
            await reply(ctx, "I sent you the privacy policy as DM.")

    @ow.subcommand()
    async def dumpsr(self, ctx):
        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "You are not registered.")
                return

            with tempfile.NamedTemporaryFile(suffix=".xls") as tmp:
                filename=tmp.name
                with pd.ExcelWriter(filename, engine="openpyxl") as xls_wr:
                    for handle in user.handles:
                        df = pd.DataFrame.from_records(
                            [(sr.timestamp, sr.tank, sr. damage, sr.support) for sr in handle.sr_history], 
                            columns=["Timestamp", "Tank", "Damage", "Support"],
                        )
                        df.to_excel(xls_wr, sheet_name=handle.handle, index=False)
                        xls_wr.sheets[handle.handle].column_dimensions['A'].width = 25

                tmp.file.seek(0)
                data = tmp.file.read()
            try:
                if ctx.channel.private:
                    chan = ctx.channel
                else:
                    chan = await ctx.author.user.open_private_channel()
                await chan.messages.upload(
                    data, filename="sr-history.xls", message_content="Here is your SR history of all your accounts as an Excel sheet."
                )
            except Forbidden:
                await reply(ctx, "I'm not allowed to send you a DM, please make sure that you enabled \"Allow DM from server members\" in the server's privacy settings")
            if not ctx.channel.private:
                await reply(ctx, "I sent you a DM")
        

    async def _srgraph(self, ctx, user, name, date: str = None):
        sns.set()

        handle = user.handles[0]

        data = [(sr.timestamp, *sr.values) for sr in handle.sr_history]

        if not data:
            await ctx.channel.messages.send(
                f"There is no data yet for {handle.handle}, try again later"
            )
            return

        data = pd.DataFrame.from_records(reversed(data), columns=["timestamp", "Tank", "Damage", "Support"], index="timestamp")

        for row in ["Tank", "Damage", "Support"]:
            if data[row].isnull().all():
                data.drop(row, axis=1, inplace=True)

        if len(data.columns) == 0:
            await reply(ctx, "I have no SR for your account stored yet.")
            return

        if date:
            try:
                date = date_parser.parse(
                    date, parserinfo=date_parser.parserinfo(dayfirst=True)
                )
            except ValueError:
                await reply(
                    ctx,
                    f"I don't know what date {date} is supposed to mean. Please use "
                    "the format DD.MM.YY or YYYY-MM-DD",
                )

            data = data[data.index >= date]

        fig, ax = plt.subplots()

        ax.xaxis_date()

        sns.lineplot(data=data, ax=ax, drawstyle="steps-post", dashes=True)

        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d.%m.%y"))
        fig.autofmt_xdate()

        plt.xlabel("Date")
        plt.ylabel("SR")

        image = BytesIO()
        plt.savefig(format="png", fname=image, transparent=False)
        image.seek(0)
        embed = Embed(
            title=f"SR History For {name}",
            description=f"Here is your SR history starting from "
            f"{'when you registered' if not date else pendulum.instance(date).to_formatted_date_string()}."
        )
        embed.set_image(image_url="attachment://graph.png")
        await ctx.channel.messages.upload(
            image, filename="graph.png", message_embed=embed
        )

    # Events
    @event("member_update")
    async def _member_update(self, ctx, old_member: Member, new_member: Member):
        def plays_overwatch(m):
            try:
                return m.game.name == "Overwatch"
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
                logger.debug("Already handled %s, ignoring", new_member.name)
                return
            else:
                self.stopped_playing_cache[uid] = True

            async with self.database.session() as session:
                user = await self.database.user_by_discord_id(session, new_member.user.id)
                if not user:
                    logger.debug(
                        "%s stopped playing OW but is not registered, nothing to do.", new_member.name
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
        if old_voice_state:
            parent = old_voice_state.channel.parent
            if parent:
                try:
                    await self._adjust_voice_channels(parent)
                except Exception:
                    logger.exception(f"Can't adjust voice channel for parent {parent}")

        if new_voice_state:
            if new_voice_state.channel.parent != parent:
                if new_voice_state.channel.parent:
                    try:
                        await self._adjust_voice_channels(new_voice_state.channel.parent)
                    except Exception:
                        logger.exception(f"Can't adjust voice channel for new state parent {new_voice_state.channel.parent}")

        async with self.database.session() as session:
            user = await self.database.user_by_discord_id(session, member.id)
            if user:
                formatted = self._format_nick(user)
                try:
                    await self._update_nick_for_member(member, formatted)
                except Exception:
                    logger.exception("Unable to update nick for member %s", member)

    @event("message_create")
    async def _message_create(self, ctx, msg):
        # logger.debug(f"got message {msg.author} {msg.channel} {msg.content} {msg.snowflake_timestamp}")
        if msg.content.startswith("!ow"):
            logger.info(
                f"{msg.author.name} in {msg.channel} issued {msg.content}"
            )
        if msg.content.startswith("!"):
            return


    @event("guild_leave")
    async def _guild_leave(self, ctx, guild):
        logger.info("I was removed from guild %s, I'm now in %d guilds", guild, len(self.client.guilds))
        async with self.database.session() as session:
            gc = (
                session.query(GuildConfigJson)
                .filter_by(id=guild.id)
                .one_or_none()
            )
            if gc:
                logger.info("That guild was configured")
                session.delete(gc)
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
        logger.info("We have a new guild %s, I'm now on %d guilds \o/", guild, len(self.client.guilds))
        self.guild_config[guild.id] = GuildConfig.default()

        msg = (
            "*Greetings*! I am excited to be here :smiley:\n"
            "To get started, create a new role named `Orisa Admin` (only the name is important, it doesn't need any special permissions) and add yourself "
            "and everybody that should be allowed to configure me.\n"
            "Then, write `!ow config` in this channel and I will send you a link to configure me via DM.\n"
            "*I will ignore all commands except `!ow help` and `!ow config` until I'm configured for this Discord!*"
        )

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
                try:
                    await channel.messages.send(msg)
                    logger.debug("message successfully sent")
                except Exception:
                    logger.exception(
                        "Got exception when trying to send to channel %s, checking another one",
                        channel
                    )
                    continue
                else:
                    # found one
                    try:
                        await channel.messages.send(content=None, embed=Embed(
                            title=":thinking: Need help?",
                            description=f"Join the [Support Discord]({SUPPORT_DISCORD})"))
                    except Exception:
                        logger.exception("Unable to send support embed")

                    break
        else:
            logger.debug(
                "no valid hello channel found. Falling back to DM to owner for %s",
                guild,
            )
            try:
                await guild.owner.send(
                    msg
                    + f"\n\n*Somebody (hopefully you) invited me to your server {guild.name}, but I couldn't find a "
                    f"text channel I am allowed to send messages to, so I have to message you directly*"
                )
            except Exception:
                logger.exception("Unable to send mail to owner, oh well...")
            try:
                await guild.owner.send(content=None, embed=Embed(
                    title=":thinking: Need help?",
                    description=f"Join the [Support Discord]({SUPPORT_DISCORD})"))
            except Exception:
                logger.exception("Unable to send support embed")


    # Util

    async def _adjust_voice_channels(
        self, parent, *, create_all_channels=False, adjust_user_limits=False
    ):
        logger.debug("adjusting parent %s", parent)
        guild = parent.guild
        if not guild:
            logger.debug("channel doesn't belong to a guild")
            return

        for cat in self.guild_config[guild.id].managed_voice_categories:
            if cat.category_id == parent.id:
                prefix_map = {prefix.name: prefix for prefix in cat.prefixes}
                break
        else:
            logger.debug("channel is not managed")
            return

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
                await chan.delete()
            made_changes = True

        async def add_a_channel():
            nonlocal made_changes, chans, cat, guild

            name = f"{prefix} #{len(chans)+1}"
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

        voice_channels = [
            chan for chan in parent.children if chan.type == ChannelType.VOICE
        ]

        sorted_channels = sorted(
            filter(is_managed, parent.children),
            key=attrgetter("name"),
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
            logger.debug("voicemembers %s", [chan.voice_members for chan in chans])
            empty_channels = [chan for chan in chans if not any(member for member in chan.voice_members)]
            logger.debug("empty channels %s", empty_channels)

            if create_all_channels:
                while len(chans) < cat.channel_limit:
                    await add_a_channel()
                    chans.append("dummy")  # value doesn't matter

            elif not empty_channels:
                if len(chans) < cat.channel_limit:
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
                        0 if np.all(np.isnan(x)) else np.nanmean(x[np.abs(x - np.nanmean(x)) <= 750])
                        for x in combined.T
                    ]
                
                def val(x):
                    return "xx" if np.isnan(x) else "??" if x == 0 else f"{int(x//100):02}"

                return f" [{'-'.join(val(x) for x in tds_filtered_mean)}]"

            for prefix, prefix_info in prefix_map.items():
                chans = managed_group[prefix]
                # rename channels if necessary
                async with self.database.session() as session:
                    for i, chan in enumerate(chans):
                        if cat.show_sr_in_nicks:
                            new_name = f"{prefix} #{i+1}{await channel_suffix(session, chan)}"
                        else:
                            new_name = f"{prefix} #{i+1}"

                        if new_name != chan.name:
                            await chan.edit(name=new_name)
                        if adjust_user_limits:
                            limit = prefix_info.limit
                            await chan.edit(user_limit=limit)

                final_list.extend(chans)

            start_pos = (
                max(chan.position for chan in unmanaged_channels) + 1
                if unmanaged_channels
                else 1
            )

            for i, chan in enumerate(final_list):
                pos = start_pos + i
                if chan.position != pos:
                    await chan.edit(position=pos)

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
                if old_sr.values:
                    all_sr = TDS(*[av or (ov and -ov) for av, ov in zip(all_sr, old_sr.values)])
                if all(x is not None for x in all_sr):
                    break

        has_secondaries = len(user.handles) > 1

        def val_str(val, short=False):
            if val is None:
                return "⊘"
            elif val<0:
                return f"{int(-val//100):02}?" if short else f"{-val:04}?"
            else:
                return f"{int(val//100,):02}" if short else f"{val:04}"

        def val_rank(val, short=False):
            if val is None:
                return "∅"
            elif val<0:
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
            return t.substitute(
                sr=sr_str,
                fullsr = full_sr_str,
                rank=rank_str,
                fullrank=full_rank_str,
                dps=self.SYMBOL_DPS + val_str(all_sr.damage),
                dpsrank=self.SYMBOL_DPS + val_rank(all_sr.damage) ,
                damage=self.SYMBOL_DPS + val_str(all_sr.damage),
                damagerank=self.SYMBOL_DPS + val_rank(all_sr.damage),
                tank=self.SYMBOL_TANK + val_str(all_sr.tank),
                tankrank=self.SYMBOL_TANK + val_rank(all_sr.tank),
                support=self.SYMBOL_SUPPORT + val_str(all_sr.support),
                supportrank=self.SYMBOL_SUPPORT + val_rank(all_sr.support),
            ) + sec_mark
        except KeyError as e:
            raise InvalidFormat(e.args[0]) from e


    async def _update_nick(self, user, *, force=False, raise_hierachy_error=False):
        user_id = user.discord_id
        exception = new_nn = None

        for guild in self.client.guilds.values():
            try:
                member = guild.members[user_id]
            except KeyError:
                continue
            try:
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

        logger.debug("New nick for %s is %s", nn, new_nn)

        if nn != new_nn:
            try:
                await member.nickname.set(new_nn)
            except HierarchyError:
                logger.info(
                    "Cannot update nick %s to %s due to not enough permissions",
                    nn,
                    new_nn,
                )
                if raise_hierachy_error:
                    raise
            except Exception as e:
                logger.exception("error while setting nick", exc_info=True)
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
        for guild in self.client.guilds.values():
            try:
                if user.discord_id not in guild.members:
                    continue
                embed = Embed(
                    title=f"For your own safety, get behind the barrier!",
                    description=f"**{str(guild.members[user.discord_id].name)}** just reached **{sr} SR** as **{ROLE_NAMES[role_idx]}** and advanced to **{FULL_RANKS[rank]}**. Congratulations!",
                    colour=COLORS[rank],
                )

                embed.set_thumbnail(url=image)
                embed.set_footer(text=f"{handle.desc} {handle.handle}")

                await self.client.find_channel(
                    self.guild_config[guild.id].congrats_channel_id
                ).messages.send(
                    content=f"Let's hear it for <@!{user.discord_id}>!", embed=embed
                )
            except Exception:
                logger.exception(f"Cannot send congrats for guild {guild}")


    async def _top_players(self, session, prev_date, type_class, sr_kind: str, style="fancy_grid"):
        def get_kind(obj):
            return getattr(obj, sr_kind)

        def prev_sr(tag):
            for sr in tag.sr_history[:30]:
                prev_sr = sr
                if sr.timestamp < prev_date:
                    break
            return prev_sr


        handles = (
            session.query(type_class)
            .options(joinedload(type_class.user))
            .join(type_class.current_sr)
            .order_by(desc(get_kind(SR)))
            .filter(get_kind(SR) != None)
            .filter(BattleTag.position==0)
            .all()
        )

        handles_and_prev = [(handle, prev_sr(handle)) for handle in handles]

        top_per_guild = {}

        guilds = [guild for guild in self.client.guilds.values() if self.guild_config[guild.id].post_highscores]

        for handle, prev_sr in handles_and_prev:
            found = False

            for guild in guilds:
                try:
                    member = guild.members[handle.user.discord_id]
                except KeyError:
                    continue

                top_per_guild.setdefault(guild.id, []).append(
                    (member, handle, get_kind(prev_sr))
                )
                found = True

            @dataclass
            class dummy:
                name: str

            if not found:
                logger.warning(
                    "User %i not found in any of the guilds", handle.user.discord_id
                )

        def member_name(member):
            name = str(member.name)
            name = re.sub(r"\[.*?\]", "", name)
            name = re.sub(r"\{.*?\}", "", name)
            name = re.sub(r"\s{2,}", " ", name)

            return "".join(
                ch if ord(ch) < 256 or unicodedata.category(ch)[0] != "S" else ""
                for ch in name
            )

        for guild_id, tops in top_per_guild.items():
            logger.debug(f"Processing guild {guild_id} for top_players")

            # FIXME: wrong if there is a tie
            prev_top_tags = [
                top[1] for top in sorted(tops, key=lambda x: x[2] or 0, reverse=True)
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
                    return f"{curr-prev:+4}"

            table_prev_sr = None
            data = []
            for ix, (member, handle, prev_sr) in enumerate(tops):
                if get_kind(handle.sr) != table_prev_sr:
                    pos = ix + 1
                sr = get_kind(handle.sr)
                table_prev_sr = sr
                data.append(
                    (
                        pos,
                        prev_str(ix + 1, handle, prev_sr),
                        member_name(member),
                        member.id,
                        sr,
                        delta_fmt(sr, prev_sr),
                    )
                )

            logger.debug("creating table...")
            headers = ["#", "prev", "Member", "Member ID", f"{sr_kind.capitalize()} SR", "ΔSR"]
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
                table_lines = [line for line in table_lines if not line.startswith("├")]


            # Split table into submessages, because a short gap is visible after each message
            # we want it to be in "nice" multiples

            ix = 0
            lines = 20

            try:
                logger.debug("trying to send highscore to %i", guild_id)
                chan = self.client.find_channel(
                    self.guild_config[guild_id].listen_channel_id
                )
                logger.debug("found channel %s", chan)
                send = chan.messages.send
                # send = self.client.application_info.owner.send
                await send(
                    f"Hello! Here are the current SRs for **{sr_kind.capitalize()}** on {type_class.blizzard_url_type.upper()} . If a member has more than one "
                    f"{type_class.desc}, only the primary {type_class.desc} is considered. Players with "
                    "private profiles, or those that didn't do their placements this season yet "
                    "are not shown."
                )
                logger.debug("sent message")
                while ix < len(table_lines):
                    # prefer splits at every "step" entry, but if it turns out too long, send a shorter message
                    step = lines if ix else lines + 3
                    logger.debug("sending long...")
                    await send_long(send, "```" + ("\n".join(table_lines[ix : ix + step]) + "```"))
                    logger.debug("sending long done")
                    ix += step

                logger.debug("trying to upload")
                await chan.messages.upload(
                    csv_file,
                    filename=f"ranking_{sr_kind}_{type_class.blizzard_url_type.upper()}_{pendulum.now().to_iso8601_string()[:10]}.csv",
                )
                logger.debug("upload done")
            except Exception:
                logger.exception("unable to send top players to guild %i", guild_id)

            # wait a bit before sending the next batch to avoid running into
            # rate limiting and sending data twice due to "timeouts"
            logger.debug("sleeping for 5s")
            await trio.sleep(5)
            logger.debug("done sleeping")

    async def _message_new_guilds(self):
        for guild_id, guild in self.client.guilds.copy().items():
            if guild_id not in self.guild_config:
                await self._handle_new_guild(guild)

    async def _sync_handle(self, session, handle):
        try:
            srs, images = await get_sr(handle)
        except UnableToFindSR:
            logger.debug(f"No SR for {handle}, oh well...")
            srs = TDS(None, None, None)
            images = [None]*3
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
            if handle.user.last_problematic_nickname_warning is None or handle.user.last_problematic_nickname_warning < datetime.utcnow() - timedelta(
                days=7
            ):
                handle.user.last_problematic_nickname_warning = datetime.utcnow()
                msg = "*To avoid spamming you, I will only send out this warning once per week*\n"
                msg += f"Hi! I just tried to update your nickname, but the result '{e.nickname}' would be longer than 32 characters."
                if handle.user.format == "$sr":
                    msg += "\nPlease shorten your nickname."
                else:
                    msg += "\nTry to use the $sr format (you can type `!ow format $sr` into this DM channel), or shorten your nickname."
                msg += "\nYour nickname cannot be updated until this is done. I'm sorry for the inconvenience."
                discord_user = await self.client.get_user(handle.user.discord_id)
                await discord_user.send(msg)

            # we can still do the rest, no need to return here

        for role_ix, rank, sr, type_to_check, image in zip(range(3), handle.rank, srs, [SR.tank, SR.damage, SR.support], images):

            if rank is not None:
                # get highest SR, but exclude current_sr
                await run_sync(session.commit)
                prev_highest_sr_value = session.query(func.max(type_to_check)).filter(
                    SR.handle == handle, SR.id != handle.current_sr_id
                )
                prev_highest_sr = (
                    session.query(SR)
                    .filter(type_to_check == prev_highest_sr_value)
                    .order_by(desc(SR.timestamp))
                    .first()
                )

                logger.debug(f"prev_sr {role_ix} {prev_highest_sr} {rank}")
                if prev_highest_sr and rank > sr_to_rank(prev_highest_sr.values[role_ix]):
                    logger.debug(
                        f"handle {handle} role {role_ix} old SR {prev_highest_sr}, new rank {rank}, sending congrats..."
                    )
                    await self._send_congrats(handle, role_ix, sr, rank, image)

    async def _sync_handles_from_channel(self, channel):
        first = True
        async with channel:
            async for handle_id in channel:
                logger.debug("got %s from channel %r", handle_id, channel)
                if handle_id in self.sync_cache:
                    logger.debug("Already updated, not doing it again")
                    continue
                else:
                    self.sync_cache[handle_id] = True  # any value really
                if not first:
                    delay = 1 + random.random() * 5
                    logger.debug(f"rate limiting: sleeping for {delay:4.02}s")
                    await trio.sleep(delay)
                else:
                    first = False
                async with self.database.session() as session:
                    try:
                        handle = await self.database.handle_by_id(session, handle_id)
                        if handle:
                            await self._sync_handle(session, handle)
                        else:
                            logger.warn(f"No handle for id {handle_id} found, probably deleted")
                        await run_sync(session.commit)
                    except Exception:
                        if handle:
                            logger.exception(
                                f"exception while syncing {handle} for {handle.user.discord_id}"
                            )
                        else:
                            logger.exception("Exception while getting handle for sync")
                    finally:
                        await run_sync(session.commit)
            
        logger.debug("channel %r closed, done", channel)

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
        logger.debug("preparing to sync handles: %s into channel %r", ids_to_sync, send_ch)

        async with send_ch:
            for tag_id in ids_to_sync:
                await send_ch.send(tag_id)

        async with trio.open_nursery() as nursery:
            async with receive_ch:
                for _ in range(min(len(ids_to_sync), 5)):
                    nursery.start_soon(self._sync_handles_from_channel, receive_ch.clone())
        logger.info("done syncing")

    async def _sync_all_handles_task(self):
        logger.debug("started waiting...")
        await trio.sleep(10)
        while True:
            try:
                logger.debug("running sync check")
                await self._sync_check()
            except Exception as e:
                logger.exception(f"something went wrong during _sync_check")
            logger.debug("sleeping for 60s before running sync check again")
            await trio.sleep(60)

    async def _cron_task(self):
        "poor man's cron, hardcode all the things"

        while True:
            try:
                logger.debug("checking cron...")
                do_run = False
                async with self.database.session() as s:
                    try:
                        hs = await run_sync(s.query(Cron).filter_by(id="highscore").one)
                    except NoResultFound:
                        hs = Cron(id="highscore", last_run=datetime.utcnow())
                        s.add(hs)
                    next_run = datetime.today().replace(
                        hour=9, minute=0, second=0, microsecond=0
                    )
                    logger.debug(
                        "next_run %s, now %s, last_run %s",
                        next_run,
                        datetime.utcnow(),
                        hs.last_run,
                    )
                    if next_run < datetime.utcnow() and hs.last_run < next_run:
                        do_run = True
                        hs.last_run = datetime.utcnow()
                    await run_sync(s.commit) # might have just added the entry, so just always commit
                    
                if do_run:
                    logger.debug("running highscore...")
                    await self._cron_run_highscore()
                    logger.debug("done running hiscore")
            except Exception:
                logger.exception("Error during cron")
            await trio.sleep(1 * 60)

    async def _cron_run_highscore(self):
        prev_date = datetime.utcnow() - timedelta(days=1)

        async with self.database.session() as session:
            for type in [BattleTag, Gamertag]:
                for kind in "tank damage support".split():
                    await self._top_players(session, prev_date, type, kind)

    async def _web_server(self):
        config = hypercorn.config.Config()
        config.access_logger = config.error_logger = logger

        web.send_ch = self.web_send_ch
        web.client = self.client
        web.orisa = self

        logger.info("Starting web server")
        while True:
            try:
                await hypercorn.trio.serve(web.app, config)
            except Exception:
                logger.exception("hypercorn crashed!")
            logger.error("hypercorn serve stopped, restarting in 10s...")
            await trio.sleep(10)

    async def _oauth_result_listener(self):
        async with self.web_recv_ch as recv_ch:
            async for uid, type, data in recv_ch:
                logger.debug(f"got OAuth response data {data} of type {type} for uid {uid}")
                try:
                    with trio.move_on_after(60):
                        await self._handle_registration(uid, type, data)
                except Exception:
                    logger.error(
                        "Something went wrong when working with data %s", data, exc_info=True
                    )

    async def _handle_registration(self, user_id, type, data):

        handles_to_check = []
        async with self.database.session() as session:
            user_obj = await self.client.get_user(user_id)
            user_channel = await user_obj.open_private_channel()

            if type == "pc":
                blizzard_id, battle_tag = data["id"], data.get("battletag")

                if battle_tag is None:
                    await user_channel.messages.send(
                        "I'm sorry, it seems like you don't have a BattleTag. Use `!ow register xbox` to register an XBOX account."
                    )
                    return

                handles = [
                    BattleTag(blizzard_id=blizzard_id, battle_tag=battle_tag)
                ]

            elif type == "xbox":
                handles = [
                    Gamertag(xbl_id=datum["id"], gamertag=datum["name"])
                    for datum in data if datum["type"] == "xbox"
                ]

                if not handles:
                    await user_channel.messages.send(
                        "I couldn't find a XBox account linked to your Discord. Please link your XBox account to Discord and try again. (Unfortunately, I cannot ask XBL directly for the information)"
                    )
                    return

            user = await self.database.user_by_discord_id(session, user_id)

            if user is None:
                user = User(discord_id=user_id, handles=handles, format="$sr")
                session.add(user)
                handles_to_check = handles

                extra_text = ""
                for guild in self.client.guilds.values():
                    if user_id in guild.members:
                        extra_text = (
                            self.guild_config[guild.id].extra_register_text or ""
                        )
                        break
                first, *others = handles
                if others:
                    desc = f"OK. People can now ask me for your {first.desc}s **{', '.join(h.handle for h in handles)}**, and I will keep track of your SR."
                else:
                    desc = f"OK. People can now ask me for your {first.desc} **{first.handle}**, and I will keep track of your SR."
                embed = Embed(
                    color=0x6DB76D,
                    title="Registration successful",
                    description=desc,
                )
                embed.add_field(
                    name=":information_source: Pro Tips",
                    value="On some servers, I will only update your nick if you join a OW voice channel. If you want your nick to always show your SR, "
                    "use the `!ow alwaysshowsr` command. If you want me to show your rank instead of your SR, use `!ow format $rank`.\n"
                    "If you have more than one account, simply issue `!ow register` again.\n",
                )
                if extra_text:
                    embed.add_field(
                        name=f":envelope: A message from the *{guild.name}* staff",
                        value=extra_text,
                    )
            else:
                for new_handle in handles:
                    existing_handle = None
                    for handle in user.handles:
                        if handle.external_id == new_handle.external_id:
                            existing_handle = handle
                            break
                    if existing_handle and existing_handle.handle != new_handle.handle:
                        embed = Embed(
                            color=0x6DB76D,
                            title=f"{existing_handle.desc} updated",
                            description=f"It seems like your {existing_handle.desc} changed from *{existing_handle.handle}* to *{new_handle.handle}*. I have updated my database.",
                        )
                        existing_handle.handle = new_handle.handle
                        handles_to_check.append(existing_handle)
                    elif existing_handle:
                        embed = Embed(
                            title=f"{existing_handle.desc} already registered",
                            color=0x6F0808,
                            description=f"You already registered the {existing_handle.desc} *{existing_handle.handle}*, so there's nothing for me to do. *Sleep mode reactivated.*\n",
                        )
                        if type == "pc":
                            embed.add_field(
                                name=":information_source: Tip",
                                value="Open the URL in a private/incognito tab next time, so you can enter the credentials of the account you want.",
                            )
                        await user_obj.send(content=None, embed=embed)
                        return
                    else:
                        user.handles.append(new_handle)
                        handles_to_check.append(new_handle)
                        embed = Embed(
                            color=0x6DB76D,
                            title=f"{new_handle.desc} added",
                            description=f"OK. I've added **{new_handle.handle}** to the list of your {new_handle.desc}s. **Your primary {user.handles[0].desc} remains {user.handles[0].handle}**. "
                            f"To change your primary tag, use `!ow setprimary`, see help for more details.",
                        )

            for handle in handles_to_check:
                try:
                    check_msg_obj = await user_channel.messages.send(f"Checking your {handle.desc} {handle.handle}…")
                    async with user_channel.typing:
                        srs, images = await get_sr(handle)
                except InvalidBattleTag as e:
                    logger.exception(f"Got invalid {handle.desc} for {handle.handle}")
                    await user_channel.messages.send(
                        f"Invalid {handle.desc}: {e.message}...Blizzard claims that the {handle.desc} {handle.handle} has no OW account. "
                        "Play a QP or arcade game, close OW and try again, sometimes this helps."
                    )
                    return
                except BlizzardError as e:
                    await user_channel.messages.send(
                        f"Sorry, but it seems like Blizzard's site has some problems currently ({e}), please try again later"
                    )
                    raise
                except UnableToFindSR:
                    embed.add_field(
                        name=":warning: No SR",
                        value=f"You don't have an SR though, your profile needs to be public for SR tracking to work... I still saved your {handle.desc}.",
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
                    name=":warning: Nickname too long!",
                    value=f"Adding your SR to your nickname would result in '{e.nickname}' and with {len(e.nickname)} characters, be longer than Discord's maximum of 32."
                    f"Please shorten your nick to be no longer than 28 characters. I will regularly try to update it.",
                )
            except HierarchyError as e:
                embed.add_field(
                    name=":warning: Cannot update nickname",
                    value='I do not have enough permissions to update your nickname. The owner needs to move the "Orisa" role higher '
                    "so that is higher than your highest role. If you are the owner of this server, there is no way for me to update your nickname, sorry.",
                )
            except Exception as e:
                logger.exception(f"unable to update nick for user {user}")
                embed.add_field(
                    name=":warning: Cannot update nickname",
                    value=(
                        "Right now I couldn't update your nickname, I will try that again later. "
                        f"People will still be able to ask for your {user.handles[0].desc}, though."
                    ),
                )
            finally:
                with suppress(Exception):
                    await self._update_nick(user)

            embed.add_field(
                name=":thumbsup: Vote for me on Discord Bot List",
                value=f"If you find me useful, consider voting for me [by clicking here]({VOTE_LINK})",
            )

            embed.add_field(
                name=":heart: Say thanks by buying a coffee",
                value=f"Want to say thanks to the guy who wrote and maintains me? Why not [buy him a coffee?]({DONATE_LINK})"
            )

            await user_channel.messages.send(content=None, embed=embed)


def fuzzy_nick_match(ann, ctx: Context, name: str):
    def strip_tags(name):
        return re.sub(r"^(.*?\|)?([^[{]*)((\[|\{).*)?", r"\2", str(name)).strip()

    member = member_id = None
    if ctx.guild:
        guilds = [ctx.guild]
    else:
        guilds = [
            guild for guild in ctx.bot.guilds.values() if ctx.author.id in guild.members
        ]

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

        candidates = process.extractBests(
            name,
            {
                id: strip_tags(mem.name)
                for guild in guilds
                for id, mem in guild.members.items()
            },
            scorer=scorer,
        )
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
            ctx, name, Member, "Cannot find member with that name"
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

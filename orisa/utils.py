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
import re

from operator import attrgetter

import asks
import trio

from cachetools.func import TTLCache
from fuzzywuzzy import process
from lxml import html

from .exceptions import (
    BlizzardError,
    InvalidBattleTag,
    UnableToFindSR,
    NicknameTooLong,
    InvalidFormat,
)
from .models import Role

logger = logging.getLogger(__name__)

SR_CACHE = TTLCache(maxsize=1000, ttl=30)
SR_LOCKS = TTLCache(
    maxsize=1000, ttl=60
)  # if a request should be hanging for 60s, just try another


async def get_sr(handle):
    try:
        lock = SR_LOCKS[handle.handle]
    except KeyError:
        lock = trio.Lock()
        SR_LOCKS[handle.handle] = lock

    await lock.acquire()
    try:
        try:
            res = SR_CACHE[handle.handle]
            logger.info(f"got SR for {handle} from cache")
            return res
        except KeyError:
            pass

        url = f'https://playoverwatch.com/en-us/career/{handle.blizzard_url_type}/{handle.handle.replace("#", "-")}'
        logger.debug("requesting %s", url)
        try:
            result = await asks.get(
                url,
                headers={
                    "User-Agent": "Orisa/1.0 (+https://github.com/brakhane/Orisa)"
                },
                connection_timeout=60,
                timeout=60,
            )
        except asks.errors.RequestTimeout:
            raise BlizzardError("Timeout")
        except Exception as e:
            raise BlizzardError("Something went wrong", e)
        if result.status_code != 200:
            raise BlizzardError(f"got status code {result.status_code} from Blizz")

        document = html.fromstring(result.content)
        srs = document.xpath('//div[@class="competitive-rank"]/div/text()')
        rank_image_elems = document.xpath('//div[@class="competitive-rank"]/img/@src')
        if not srs:
            if "Profile Not Found" in result.text:
                raise InvalidBattleTag(f"No profile with {handle.desc} {handle.handle} found")
            raise UnableToFindSR()
        sr = int(srs[0])
        if rank_image_elems:
            rank_image = str(rank_image_elems[0])
        else:
            rank_image = None

        res = SR_CACHE[handle.handle] = (sr, rank_image)
        return res
    finally:
        lock.release()


def sort_secondaries(user):
    user.handles[1:] = list(sorted(user.handles[1:], key=attrgetter("handle")))
    user.handles.reorder()


async def send_long(send_func, msg):
    "Splits a long message >2000 into smaller chunks"

    if len(msg) <= 2000:
        await send_func(msg)
        return
    else:
        lines = msg.split("\n")

        part = ""
        for line in lines:
            if len(part) + len(line) > 2000:
                await send_func(part)
                part = ""
            part += line + "\n"

        if part:
            await send_func(part)


async def reply(ctx, msg):
    return await ctx.channel.messages.send(f"<@!{ctx.author.id}> {msg}")


def resolve_handle_or_index(user, handle_or_index):
    try:
        index = int(handle_or_index)
    except ValueError:
        try:
            handle, score, index = process.extractOne(
                handle_or_index,
                {h.position: h.handle for h in user.handles},
                score_cutoff=50,
            )
        except (ValueError, TypeError):
            raise ValueError(
                f'The handle "{handle_or_index}" is not registered for your account '
                "(I even did a fuzzy search), use `!ow register` first."
            )
    else:
        if index >= len(user.handles):
            raise ValueError("You don't even have that many secondary BattleTags")
    return index


def format_roles(roles):
    names = {
        Role.DPS: "Damage",
        Role.MAIN_TANK: "Main Tank",
        Role.OFF_TANK: "Off Tank",
        Role.SUPPORT: "Support",
    }
    return ", ".join(names[r] for r in Role if r and r in roles)

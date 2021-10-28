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
import atexit
import logging
import logging.config
import logging.handlers
import queue

from bisect import bisect
from collections import namedtuple
from operator import attrgetter
from typing import List

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
from .config import DATABASE_URI

logger = logging.getLogger(__name__)

if DATABASE_URI.startswith("sqlite://"):
    logger.warn(
        """\
*** Using SQLite with dummy run_sync. This setup does have performance and concurrency problems. 
*** You will run into problems if multiple users send commands to Orisa at the same time, or during SR sync.
*** ONLY USE THIS SETUP DURING DEVELOPMENT OR WITH VERY LIMITED USERS!
*** PostgreSQL is highly recommended for production!"""
    )

    async def run_sync(method, *args, **kwargs):
        """Dummy run_sync that doesn't start a thread and just executes the sync call in the calling thread.
        Necessary for SQLite in combination with SQLAlchemy"""
        return method(*args, **kwargs)


else:
    from trio.to_thread import run_sync


class TDS(namedtuple("TDS", "tank damage support")):
    def __str__(self):
        return f"{self.tank}-{self.damage}-{self.support}"


SR_CACHE = TTLCache(maxsize=1000, ttl=30)
SR_LOCKS = TTLCache(
    maxsize=1000, ttl=60
)  # if a request should be hanging for 60s, just try another


_SESSION = asks.Session(
    headers={"User-Agent": "Orisa/1.1 (+https://github.com/brakhane/Orisa)"},
    connections=10,
)


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
            result = await _SESSION.get(url, connection_timeout=60, timeout=60)
        except asks.errors.RequestTimeout:
            raise BlizzardError("Timeout")
        except Exception as e:
            raise BlizzardError("Something went wrong", e)
        if result.status_code != 200:
            raise BlizzardError(f"got status code {result.status_code} from Blizz")

        document = html.fromstring(result.content)
        await trio.sleep(0)

        role_divs = document.xpath(
            '(//div[@class="competitive-rank"])[1]/div[@class="competitive-rank-role"]'
        )

        rank_images = [
            r.xpath('descendant::img[@class="competitive-rank-tier-icon"]/@src')
            for r in role_divs
        ]
        role_descs = [
            r.xpath(
                'descendant::div[contains(@class, "competitive-rank-tier-tooltip")]/@data-ow-tooltip-text'
            )
            for r in role_divs
        ]
        srs = [
            r.xpath('descendant::div[@class="competitive-rank-level"]/text()')
            for r in role_divs
        ]

        if not any(srs):
            if "Profile Not Found" in result.text:
                raise InvalidBattleTag(
                    f"No profile with {handle.desc} {handle.handle} found"
                )
            raise UnableToFindSR()

        combined = {
            desc[0].split()[0]: (sr[0], rank_image[0])
            for desc, sr, rank_image in zip(role_descs, srs, rank_images)
        }

        sr_list = [
            int(combined[n][0]) if n in combined else None
            for n in "Tank Damage Support".split()
        ]
        img_list = [
            combined[n][1] if n in combined else None
            for n in "Tank Damage Support".split()
        ]

        res = SR_CACHE[handle.handle] = (TDS(*sr_list), TDS(*img_list))

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
    if (
        ctx.message
        and ctx.guild
        and ctx.guild.me
        and ctx.channel.effective_permissions(ctx.guild.me).read_message_history
    ):
        return await ctx.channel.messages.send(msg, in_reply_to=ctx.message.id)
    else:
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


RANK_CUTOFF = (1500, 2000, 2500, 3000, 3500, 4000)


def sr_to_rank(sr):
    # there is no 0 SR, so if sr is false-ish, it's None
    return sr and bisect(RANK_CUTOFF, sr)


class QueueHandler(logging.handlers.QueueHandler):
    def __init__(self, handlers):
        q = queue.Queue(-1)
        # don't exactly know why it's necessary, but I don't care anymore
        handlers = [handlers[i] for i in range(len(handlers))]

        super().__init__(q)
        
        listener = logging.handlers.QueueListener(
            q, *handlers, respect_handler_level=True
        )
        listener.start()
        atexit.register(listener.stop)

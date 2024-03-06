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
import re
import urllib.parse

from bisect import bisect
from collections import namedtuple
from operator import attrgetter
from typing import TYPE_CHECKING, Optional

import asks
import trio
from cachetools.func import TTLCache
from fuzzywuzzy import process
from lxml import html

from curious.exc import ErrorCode, HTTPException

from .config import DATABASE_URI
from .exceptions import (
    BlizzardError,
    InvalidBattleTag,
    InvalidFormat,
    NicknameTooLong,
    UnableToFindSR,
)

if TYPE_CHECKING:
    from .models import Handle


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

async def get_web_profile_uuid(btag: str) -> Optional[str]:
    return "c251a785fe23c8ffba|4ed031481f8ec8b79a9ed70f6ff8f08c"
    name, num = btag.split("#")
    try:
        logger.debug(f"Searching for {name}")
        resp = await _SESSION.get(f"https://overwatch.blizzard.com/en-us/search/account-by-name/{urllib.parse.quote(name)}/")
        logger.debug(f"result is {resp}")
        entries = resp.json()
        logger.debug("Got results %s", entries)
        for entry in entries:
            if entry["battleTag"] == btag:
                return entry["url"]
        return None
    except asks.errors.RequestTimeout:
        raise BlizzardError("Timeout")
    except Exception as e:
        raise BlizzardError("Something went wrong", e)


async def get_sr(handle: "Handle"):
    try:
        lock = SR_LOCKS[handle.handle]
    except KeyError:
        lock = trio.Lock()
        SR_LOCKS[handle.handle] = lock

    if not handle.blizzard_url_type == "pc":
        raise UnableToFindSR()

    await lock.acquire()
    try:
        try:
            res = SR_CACHE[handle.handle]
            logger.info(f"got SR for {handle} from cache")
            return res
        except KeyError:
            pass

        url = (
            f'https://overwatch.blizzard.com/en-us/career/{handle.web_profile_uuid}/'
        )

        logger.debug("requesting %s", url)
        try:
            result = await _SESSION.get(url, connection_timeout=60, timeout=60)
        except asks.errors.RequestTimeout:
            raise BlizzardError("Timeout")
        except Exception as e:
            raise BlizzardError("Something went wrong", e)

        if result.status_code != 200:
            if result.status_code == 404:
                raise InvalidBattleTag(f"No profile for {handle.handle} found")
            else:
                raise BlizzardError(f"got status code {result.status_code} from Blizz")

        document = html.fromstring(result.content)
        await trio.sleep(0)

        def has_class(class_: str) -> str:
            return f'contains(concat(" ", @class, " "), " {class_} ")'

        def extract_sr(
            role_imgs: list[html.HtmlElement], rank_imgs: list[html.HtmlElement], tier_imgs: list[html.HtmlElement]
        ) -> tuple[TDS, TDS]:
            srs = [None] * 3
            imgs = [None] * 3

            values = {
                "Bronze": 1000,
                "Silver": 1500,
                "Gold": 2000,
                "Platinum": 2500,
                "Diamond": 3000,
                "Master": 3500,
                "Grandmaster": 4000,
                "Ultimate": 4500,
            }

            for role, rank, tier in zip(role_imgs, rank_imgs, tier_imgs):
                if "tank" in role:
                    idx = 0
                elif "offense" in role:
                    idx = 1
                elif "support" in role:
                    idx = 2
                else:
                    raise ValueError(f"unknown role {role} in role image URL")

                rm = re.search(r"/Rank_(\w+)Tier-", rank)
                if not rm:
                    raise ValueError(f"cannot parse rank image {rank}")
                tm = re.search(r"/TierDivision_(\d)", tier)
                if not tm:
                    raise ValueError(f"cannot parse tier image {tier}")

                rankname = rm.group(1)
                division = int(tm.group(1))

                srs[idx] = values[rankname] + (5 - division) * 100
                imgs[idx] = rank

                logger.debug(f"rank {rankname} div {division} idx {idx} sr {srs[idx]} {imgs[idx]}")

            return (TDS(*srs), TDS(*imgs))

        rank_wrappers = document.xpath(
            f'//div[{has_class("Profile-playerSummary--rankImageWrapper")}]'
        )

        srs_per_class = [
            extract_sr(
                role_imgs=rw.xpath(
                    f'//div[{has_class("Profile-playerSummary--role")}]/img/@src'
                ),
                rank_imgs=rw.xpath(
                    f'//img[{has_class("Profile-playerSummary--rank")}][1]/@src'
                ),
                tier_imgs=rw.xpath(
                    f'//img[{has_class("Profile-playerSummary--rank")}][2]/@src'
                )
            )
            for rw in rank_wrappers
        ]

        if not any(any(srs) for srs in srs_per_class):
            raise UnableToFindSR()

        srs_img = srs_per_class[0]
        if not any(srs_img[0]):
            raise UnableToFindSR()

        res = SR_CACHE[handle.handle] = srs_img

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
        try:
            res = await ctx.channel.messages.send(msg, in_reply_to=ctx.message.id)
        except HTTPException as e:
            if e.error_code == ErrorCode.INVALID_FORM_BODY:
                logger.warn(
                    "Got invalid form body when replying, trying to send a reply without message reference"
                )
            # fallthrough
        else:
            return res

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
                "(I even did a fuzzy search), use `@Orisa register` first."
            )
    else:
        if index >= len(user.handles):
            raise ValueError("You don't even have that many secondary BattleTags")
    return index


RANK_CUTOFF = (1500, 2000, 2500, 3000, 3500, 4000, 4500)


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

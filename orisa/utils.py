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


async def get_sr(asks_session, battletag):
    try:
        lock = SR_LOCKS[battletag]
    except KeyError:
        lock = trio.Lock()
        SR_LOCKS[battletag] = lock

    await lock.acquire()
    try:
        if not re.match(r"\w+#[0-9]+", battletag):
            raise InvalidBattleTag(
                "Malformed BattleTag. BattleTags look like SomeName#1234: a name and a # sign followed by a number and contain no spaces. They are case-sensitive, too!"
            )

        try:
            res = SR_CACHE[battletag]
            logger.info(f"got SR for {battletag} from cache")
            return res
        except KeyError:
            pass

        url = f'https://playoverwatch.com/en-us/career/pc/{battletag.replace("#", "-")}'
        logger.info(f"requesting {url}")
        try:
            result = await asks_session.get(
                url,
                headers={
                    "User-Agent": "Orisa/1.0 (+https://github.com/brakhane/Orisa)"
                },
                connection_timeout=10,
                timeout=10,
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
                raise InvalidBattleTag(f"No profile with BattleTag {battletag} found")
            raise UnableToFindSR()
        sr = int(srs[0])
        if rank_image_elems:
            rank_image = str(rank_image_elems[0])
        else:
            rank_image = None

        res = SR_CACHE[battletag] = (sr, rank_image)
        return res
    finally:
        lock.release()


def sort_secondaries(user):
    user.battle_tags[1:] = list(sorted(user.battle_tags[1:], key=attrgetter("tag")))
    user.battle_tags.reorder()


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


def resolve_tag_or_index(user, tag_or_index):
    try:
        index = int(tag_or_index)
    except ValueError:
        try:
            tag, score, index = process.extractOne(
                tag_or_index,
                {t.position: t.tag for t in user.battle_tags},
                score_cutoff=50,
            )
        except (ValueError, TypeError):
            raise ValueError(
                f'The BattleTag "{tag_or_index}" is not registered for your account '
                "(I even did a fuzzy search), use `!ow register` first."
            )
    else:
        if index >= len(user.battle_tags):
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

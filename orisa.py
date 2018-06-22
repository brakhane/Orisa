# Orisa, a simple Discord bot with good intentions
# Copyright (C) 2018 Dennis Brakhane
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

import re
import random
from bisect import bisect
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import groupby
from operator import attrgetter, itemgetter
from string import Template
from typing import Optional

import asks
import html5lib
import multio
import pendulum
import trio
import yaml

from cachetools.func import TTLCache
from curious import event
from curious.commands.context import Context
from curious.commands.decorators import command, condition
from curious.commands.exc import ConversionFailedError
from curious.commands.manager import CommandsManager
from curious.commands.plugin import Plugin
from curious.core.client import Client
from curious.exc import HierarchyError
from curious.dataclasses.channel import ChannelType
from curious.dataclasses.embed import Embed
from curious.dataclasses.guild import Guild
from curious.dataclasses.member import Member
from curious.dataclasses.presence import Game, Status
from fuzzywuzzy import process, fuzz
from lxml import html

from config import BOT_TOKEN, CHANNEL_NAMES, GUILD_INFOS, MASHERY_API_KEY

from models import Database, User, BattleTag, Role, WowUser, WowRole


CHANNEL_IDS = frozenset(guild.listen_channel_id for guild in GUILD_INFOS.values())
WOW_CHANNEL_IDS = frozenset(guild.wow_listen_channel_id for guild in GUILD_INFOS.values())


with open('logging.yaml') as logfile:
    logging.config.dictConfig(yaml.safe_load(logfile))

logger = logging.getLogger("orisa")

class InvalidBattleTag(Exception):
    def __init__(self, message):
        self.message = message

class UnableToFindSR(Exception):
    pass

class NicknameTooLong(Exception):
    def __init__(self, nickname):
        self.nickname = nickname

class InvalidFormat(Exception):
    def __init__(self, key):
        self.key = key

RANK_CUTOFF = (1500, 2000, 2500, 3000, 3500, 4000)
RANKS = ('Bronze', 'Silver', 'Gold', 'Platinum', 'Diamond', 'Master', 'Grand Master')
COLORS = (
    0xcd7e32, # Bronze
    0xc0c0c0, # Silver
    0xffd700, # Gold
    0xe5e4e2, # Platinum
    0xa2bfd3, # Diamond
    0xf9ca61, # Master
    0xf1d592, # Grand Master
)

# Utilities

def get_rank(sr):
    return bisect(RANK_CUTOFF, sr) if sr is not None else None

SR_CACHE = TTLCache(maxsize=1000, ttl=30)
SR_LOCKS = TTLCache(maxsize=1000, ttl=60) # if a request should be hanging for 60s, just try another

async def get_sr_rank(battletag):
    try:
        lock = SR_LOCKS[battletag]
    except KeyError:
        lock = trio.Lock()
        SR_LOCKS[battletag] = lock

    await lock.acquire()
    try:
        if not re.match(r'\w+#[0-9]+', battletag):
            raise InvalidBattleTag('Malformed BattleTag. BattleTags look like SomeName#1234: a name and a # sign followed by a number and contain no spaces. They are case-sensitive, too!')

        try:
            res = SR_CACHE[battletag]
            logger.info(f'got SR for {battletag} from cache')
            return res
        except KeyError:
            pass

        url = f'https://playoverwatch.com/en-us/career/pc/{battletag.replace("#", "-")}'
        logger.info(f'requesting {url}')
        result = await asks.get(url)
        if result.status_code != 200:
            raise RuntimeError(f'got status code {result.status_code} from Blizz')

        document = html.fromstring(result.content)
        srs = document.xpath('//div[@class="competitive-rank"]/div/text()')
        rank_image_elems = document.xpath('//div[@class="competitive-rank"]/img/@src')
        if not srs:
            if 'Profile Not Found' in result.text:
                raise InvalidBattleTag(f"No profile with BattleTag {battletag} found. BattleTags are case-sensitive!")
            raise UnableToFindSR()
        sr = int(srs[0])
        if rank_image_elems:
            rank_image = str(rank_image_elems[0])
        else:
            rank_image = None

        res = SR_CACHE[battletag] = (sr, get_rank(sr), rank_image)
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
            tag, score, index = process.extractOne(tag_or_index, {t.position: t.tag for t in user.battle_tags}, score_cutoff=50)
        except (ValueError, TypeError):
            raise ValueError(f'The BattleTag "{tag_or_index}" is not registered for your account '
                              '(I even did a fuzzy search), use `!bt register` first.')
    else:
        if index >= len(user.battle_tags):
            raise ValueError("You don't even have that many secondary BattleTags")
    return index

async def set_channel_suffix(chan, suffix: str):
    name = chan.name

    if ':' in name:
        if suffix:
            new_name = re.sub(r':.*', f': {suffix}', name)
        else:
            new_name = re.sub(r':.*', '', name)
    else:
        if suffix:
            new_name = f'{name}: {suffix}'
        else:
            new_name = name

    if name != new_name:
        await chan.edit(name=new_name)

def format_roles(roles):
    names = {
        Role.DPS: "Damage",
        Role.MAIN_TANK: "Main Tank",
        Role.OFF_TANK: "Off Tank",
        Role.SUPPORT: "Support",
    }
    return ", ".join(names[r] for r in Role if r and r in roles)

# Conditions

def correct_channel(ctx):
    return ctx.channel.id in CHANNEL_IDS or ctx.channel.private

def correct_wow_channel(ctx):
    return ctx.channel.id in WOW_CHANNEL_IDS or ctx.channel.private

def only_owner(ctx):
    try:
        return ctx.author.id == ctx.application_info.owner.id and ctx.channel.private
    except AttributeError:
        # application_info is None
        return False

def only_owner_all_channels(ctx):
    try:
        return ctx.author.id == ctx.application_info.owner.id
    except AttributeError:
        # application_info is None
        return False


# Dataclasses

@dataclass
class Dialogue:
    min_timestamp: datetime
    last_message_id: int = None
    queue:trio.Queue = field(default_factory=lambda:trio.Queue(1))


# Main Orisa code
class Orisa(Plugin):

    SYMBOL_DPS = '\N{CROSSED SWORDS}'
    SYMBOL_TANK = '\N{SHIELD}' #\N{VARIATION SELECTOR-16}'
    SYMBOL_SUPPORT = '\N{HEAVY PLUS SIGN}'   #\N{VERY HEAVY GREEK CROSS}'
    SYMBOL_FLEX = '\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}' # '\N{FLEXED BICEPS}'   #'\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}'


    def __init__(self, client, database):
        super().__init__(client)
        self.database = database
        self.dialogues = {}


    async def load(self):
        await self.spawn(self._sync_all_tags_task)

    # admin commands

    @command()
    @condition(only_owner)
    async def shutdown(self, ctx):
        logger.critical("***** GOT EMERGENCY SHUTDOWN COMMAND FROM OWNER *****")
        await self.client.kill()
        raise SystemExit(42)


    @command()
    @condition(only_owner)
    async def messageall(self, ctx, *, message: str):
        s = self.database.Session()
        try:
            users = s.query(User).all()
            for user in users:
                try:
                    logger.debug(f"Sending messsage to {user.discord_id}")
                    u = await self.client.get_user(user.discord_id)
                    await u.send(message)
                except:
                    logger.exception(f"Error while sending to {user.discord_id}")
            logger.debug("Done sending")
        finally:
            s.close()


    @command()
    @condition(only_owner)
    async def post(self, ctx, channel_id: str, *, message:str):
        try:
            channel_id = CHANNEL_NAMES[channel_id]
        except KeyError:
            channel_id = int(channel_id)
        channel = self.client.find_channel(channel_id)
        msg = await channel.messages.send(message)
        await ctx.channel.messages.send(f"created {msg.id}")


    @command()
    @condition(only_owner)
    async def delete(self, ctx, channel_id: str, message_id: int):
        try:
            channel_id = CHANNEL_NAMES[channel_id]
        except KeyError:
            channel_id = int(channel_id)
        # low level access, because getting a message requires MESSAGE_HISTORY permission
        await self.client.http.delete_message(channel_id, message_id)
        await ctx.channel.messages.send("deleted")

#    @command()
#    @condition(only_owner)
#    async def updatehelp(self, ctx, channel_id: int, message_id: int):
#        await self.client.http.edit_message(channel_id, message_id, embed=self._create_help().to_dict())
#        await ctx.channel.messages.send("done")


    @command()
    @condition(only_owner)
    async def randomize(self, ctx):
        with self.database.session() as s:
            for tag in s.query(BattleTag).all():
                tag.last_update += timedelta(minutes=random.randint(0, 50))
            s.commit()
        await reply(ctx, "randomized last updates")



    @command()
    @condition(only_owner)
    async def d(self, ctx):
        """testing123"""
        rec = ctx.author.id
        chan = ctx.channel
        try:
            name = await self._prompt(chan, rec, "What is your name?")
            quest = await self._prompt(chan, rec, f"So {name}, what is your quest?")
            ans = await self._prompt(chan, rec, f"As someone whose quest is {quest}, you should know this: What is the capital of Assyria?")
            await ctx.channel.messages.send(f"{ans}...")
        except trio.TooSlowError as e:
            logger.exception("got timeout")
            await chan.messages.send("TIMEOUT!")


    @command()
    @condition(only_owner)
    async def updatenicks(self, ctx):
        session = self.database.Session()
        for user in session.query(User).all():
            try:
                await self._update_nick(user)
            except Exception:
                logger.exception("something went wrong during updatenicks")
        await ctx.channel.messages.send("Done")


    @command()
    @condition(only_owner)
    async def cleanup(self, ctx, *, doit: str = None):
        member_ids = [id for guild in self.client.guilds.values() for id in guild.members.keys()]
        session = self.database.Session()
        try:
            registered_ids = [x[0] for x in session.query(User.discord_id).all()]
            stale_ids = set(registered_ids) - set(member_ids)
            ids = ', '.join(f"<@{id}>" for id in stale_ids)
            await ctx.channel.messages.send(f"there are {len(stale_ids)} stale entries: {ids}")

        finally:
            session.close()


    @command()
    @condition(correct_channel)
    async def ping(self, ctx):
        await reply(ctx, "pong")

    # bt commands

    @command()
    @condition(correct_channel)
    async def bt(self, ctx, *, member: Member = None):

        def format_sr(sr):
            if not sr:
                return "—"
            return f"{sr} ({RANKS[get_rank(sr)]})"


        member_given = member is not None
        if not member_given:
            member = ctx.author

        session = self.database.Session()

        content = embed = None
        try:
            user = self.database.user_by_discord_id(session, member.id)
            if user:
                embed = Embed(colour=0x659dbd) # will be overwritten later if SR is set
                embed.add_field(name="Nick", value=member.name)

                primary, *secondary = user.battle_tags
                tag_value = f"**{primary.tag}**\n"
                tag_value += "\n".join(tag.tag for tag in secondary)

                sr_value = f"**{format_sr(primary.sr)}**\n"
                sr_value += "\n".join(format_sr(tag.sr) for tag in secondary)

                multiple_tags = len(user.battle_tags) > 1

                embed.add_field(name="BattleTags" if multiple_tags else "BattleTag", value=tag_value)
                if any(tag.sr for tag in user.battle_tags):
                    embed.add_field(name="SRs" if multiple_tags else "SR", value=sr_value)

                if primary.sr:
                    embed.colour = COLORS[get_rank(primary.sr)]

                if user.roles:
                    embed.add_field(name="Roles", value=format_roles(user.roles))

                if multiple_tags:
                    #footer_text = f"The SR of the BattleTags were last updated "
                    #footer_text += ", ".join(pendulum.instance(tag.last_update).diff_for_humans() for tag in user.battle_tags)
                    #footer_text += " respectively."
                    footer_text = f"The SR of the primary BattleTag was last updated {pendulum.instance(primary.last_update).diff_for_humans()}."
                else:
                    footer_text = f"The SR was last updated {pendulum.instance(primary.last_update).diff_for_humans()}."

                if member == ctx.author and member_given:
                    footer_text += "\nBTW, you do not need to specify your nickname if you want your own BattleTag; just !bt is enough"
                embed.set_footer(text=footer_text)
            else:
                content = f"{member.name} not found in database! *Do you need a hug?*"
                if member == ctx.author:
                    embed = Embed(
                                title="Hint",
                                description="use `!bt register BattleTag#1234` to register, or `!bt help` for more info"
                            )
        finally:
            session.close()
        await ctx.channel.messages.send(content=content, embed=embed)


    @bt.subcommand()
    @condition(correct_channel)
    async def get(self, ctx, *, member: Member = None):
        r = await self.bt(ctx, member=member)
        return r


    @bt.subcommand()
    @condition(correct_channel)
    async def register(self, ctx, battle_tag: str = None):
        if battle_tag is None:
            await reply(ctx, "missing BattleTag")
            return
        member_id = ctx.message.author_id
        session = self.database.Session()
        try:
            user = self.database.user_by_discord_id(session, member_id)
            resp = None
            if user is None:
                tag = BattleTag(tag=battle_tag)
                user = User(discord_id=member_id, battle_tags=[tag], format="$sr")
                session.add(user)

                channel_id = None
                for guild in self.client.guilds.values():
                    if member_id in guild.members:
                        channel_id = GUILD_INFOS[guild.id].listen_channel_id
                        break

                resp = ("OK. People can now ask me for your BattleTag, and I will update your nick whenever I notice that your SR changed.\n"
                        "Please also tell us the roles you play by using `!bt setroles xxx`, where xxx is one or more of the following letters: "
                        "`d`amage/DPS, `m`ain tank, `o`ff tank, `s`upport. So `!bt setroles ds` for example would say you play both DPS and support.\n"
                        "If you want, you can also join the Overwatch role by visiting <#458669204048969748>, this way, you will get "
                         "notified of shoutouts to @Overwatch")
            else:
                if any(tag.tag == battle_tag for tag in user.battle_tags):
                    await reply(ctx, "You already registered that BattleTag, so there's nothing for me to do. *Sleep mode reactivated.*")
                    return

                tag = BattleTag(tag=battle_tag)
                user.battle_tags.append(tag)
                resp = (f"OK. I've added {battle_tag} to the list of your BattleTags. Your primary BattleTag remains **{user.battle_tags[0].tag}**. "
                        f"To change your primary tag, use `!bt setprimary yourbattletag`, see help for more details.")

            try:
                async with ctx.channel.typing:
                    sr, rank, image = await get_sr_rank(battle_tag)
            except InvalidBattleTag as e:
                await reply(ctx, f"Invalid BattleTag: {e.message}")
                raise
            except UnableToFindSR:
                resp += "\nYou don't have an SR though, you probably need to finish your placement matches... I still saved your BattleTag."
                sr = None

            tag.last_update = datetime.utcnow()
            tag.sr = sr
            rank = get_rank(sr)
            if user.highest_rank is None:
                user.highest_rank = rank
            else:
                user.highest_rank = max([user.highest_rank, rank or 0])

            sort_secondaries(user)

            session.commit()

            try:
                await self._update_nick(user)
            except NicknameTooLong as e:
                resp += (f"\n**Adding your SR to your nickname would result in '{e.nickname}' and with {len(e.nickname)} characters, be longer than Discord's maximum of 32.** Please shorten your nick to be no longer than 28 characters. I will regularly try to update it.")

            except Exception as e:
                logger.exception(f"unable to update nick for user {user}")
                resp += ("\nHowever, right now I couldn't update your nickname, will try that again later. If you are a clan admin, "
                         "I simply cannot update your nickname ever, period. People will still be able to ask for your BattleTag, though.")
        finally:
            session.close()

        await reply(ctx, resp)



    @bt.subcommand()
    @condition(correct_channel)
    async def unregister(self, ctx, tag_or_index: str):
        session = self.database.Session()
        try:
            user = self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "You are not registered, there's nothing for me to do.")
                return

            try:
                index = resolve_tag_or_index(user, tag_or_index)
            except ValueError as e:
                await reply(ctx, e.args[0])
                return
            if index == 0:
                await reply(ctx,
                    "You cannot unregister your primary BattleTag. Use `!bt setprimary` to set a different primary first, or "
                    "use `!bt forgetme` to delete all your data.")
                return

            removed = user.battle_tags.pop(index)
            if removed.sr:
                if user.highest_rank == get_rank(removed.sr):
                    user.highest_rank = max(filter(lambda x: x is not None, (get_rank(tag.sr) for tag in user.battle_tags)), default=None)
            session.commit()
            await reply(ctx, f'Removed **{removed.tag}**')
            await self._update_nick_after_secondary_change(ctx, user)

        finally:
            session.close()


    async def _update_nick_after_secondary_change(self, ctx, user):
            try:
                await self._update_nick(user)
            except HierarchyError:
                pass
            except NicknameTooLong as e:
                await reply(ctx,
                f'However, your new nickname "{e.nickname}" is now longer than 32 characters, which Discord doesn\'t allow. '
                 'Please choose a different format, or shorten your nickname and do a `!bt forceupdate` afterwards.')
            except:
                await reply(ctx, "However, there was an error updating your nickname. I will try that again later.")


    @bt.subcommand()
    @condition(correct_channel)
    async def setprimary(self, ctx, tag_or_index: str):
        session = self.database.Session()
        try:
            user = self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "You are not registered.")
                return
            try:
                index = resolve_tag_or_index(user, tag_or_index)
            except ValueError as e:
                await reply(ctx, e.args[0])
                return
            if index == 0:
                await reply(ctx, f'"{user.battle_tags[0].tag}" already is your primary BattleTag. *Going back to sleep*')
                return

            p, s = user.battle_tags[0], user.battle_tags[index]
            p.position = index
            s.position = 0
            session.commit()

            for i, t in enumerate(sorted(user.battle_tags[1:], key=attrgetter("tag"))):
                t.position = i+1

            session.commit()

            await reply(ctx, f'Done. Your primary BattleTag is now **{user.battle_tags[0].tag}**.')
            await self._update_nick_after_secondary_change(ctx, user)

        finally:
            session.close()


    @bt.subcommand()
    @condition(correct_channel)
    async def format(self, ctx, *, format: str):
        if ']' in format:
            await reply(ctx, "format string may not contain square brackets")
            return
        if not re.search(r'\$((sr|rank)(?!\w))|(\{(sr|rank)(?!\w)})', format):
            await reply(ctx, "format string must contain at least a $sr or $rank")
            return
        if not format:
            await reply(ctx, "format string missing")
            return

        session = self.database.Session()

        try:
            user = self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "you must register first")
                return
            else:
                user.format = format
                try:
                    new_nick = await self._update_nick(user)
                except InvalidFormat as e:
                    await reply(ctx, f'Invalid format string: unknown placeholder "{e.key}"')
                    session.rollback()
                except NicknameTooLong as e:
                    await reply(ctx, f"Sorry, using this format would make your nickname be longer than 32 characters ({len(e.nickname)} to be exact).\n"
                                f"Please choose a shorter format or shorten your nickname")
                    session.rollback()
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

                    await reply(ctx, f'Done. Henceforth, ye shall be knownst as "{new_nick}, {random.choice(titles)}."')
        finally:
            session.commit()
            session.close()


    @bt.subcommand()
    @condition(correct_channel)
    async def forceupdate(self, ctx):
        session = self.database.Session()
        try:
            logger.info(f"{ctx.author.id} used forceupdate")
            user = self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "you are not registered")
            else:
                async with ctx.channel.typing:
                    for tag in user.battle_tags:
                        try:
                            await self._sync_tag(tag)
                        except Exception as e:
                            logger.exception(f'exception while syncing {tag}')
                await reply(ctx, f"OK, I have updated your data. Your (primary) SR is now {user.battle_tags[0].sr}. "
                                 "If that is not correct, you need to log out of Overwatch once and try again.")
        finally:
            session.commit()
            session.close()


    @bt.subcommand()
    async def forgetme(self, ctx):
        session = self.database.Session()
        try:
            user = self.database.user_by_discord_id(session, ctx.author.id)
            if user:
                logger.info(f"{ctx.author.name} ({ctx.author.id}) requested removal")
                user_id = user.discord_id
                try:
                    for guild in self.client.guilds.values():
                        try:
                            nn = str(guild.members[user_id].name)
                        except KeyError:
                            continue
                        new_nn = re.sub(r'\s*\[.*?\]', '', nn, count=1).strip()
                        try:
                            await guild.members[user_id].nickname.set(new_nn)
                        except HierarchyError:
                            pass
                except Exception:
                    logger.exception("Some problems while resetting nicks")
                session.delete(user)
                await reply(ctx, f"OK, deleted {ctx.author.name} from database")
                session.commit()
            else:
                await reply(ctx, "you are not registered anyway, so there's nothing for me to forget...")
        finally:
            session.close()


    @bt.subcommand()
    @condition(correct_channel)
    async def findplayers(self, ctx, diff_or_min_sr: int = None, max_sr: int = None):
        await self._findplayers(ctx, diff_or_min_sr, max_sr, findall=False)


    @bt.subcommand()
    @condition(correct_channel)
    async def findallplayers(self, ctx, diff_or_min_sr: int = None, max_sr: int = None):
        await self._findplayers(ctx, diff_or_min_sr, max_sr, findall=True)


    @bt.subcommand()
    @condition(correct_channel)
    async def newsr(self, ctx, arg1, arg2 = None):
        with self.database.session() as session:
            user = self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                raise reply(ctx, "You are not registered.")
                return

            if arg2 is None:
                sr_str = arg1
                tag = user.battle_tags[0]
            else:
                tag_str, sr_str = arg1, arg2

                try:
                    tag, score, index = process.extractOne(tag_str, {t.position: t.tag for t in user.battle_tags}, score_cutoff=50)
                except (ValueError, TypeError):
                    tag = None

                if not tag:
                    await reply(ctx, f"I have no idea which of your BattleTags you mean by '{tag_str}'")
                    return
            # check for fat fingering
            force = False
            if sr_str.strip().endswith("!"):
                force = True
                sr_str = sr_str[:-1]
            try:
                if sr_str.strip().lower() == "none":
                    sr = None
                else:
                    sr = int(sr_str)
            except ValueError:
                await reply(ctx, "I don't know about you, but '{sr_str}' doesn't look like a number to me")
                return

            if sr is not None:
                if not (500 <= sr <= 5000):
                    await reply(ctx, "SR must be between 500 and 5000")
                    return

                # check for fat finger
                if abs(tag.sr - sr) > 200 and not force:
                    await reply(ctx, f"Whoa! {sr} looks like a big change compared to your previous SR of {tag.sr}. To avoid typos, I will only update it if you are sure."
                                     f"So, if that is indeed correct, reissue this command with a ! added to the SR, like `!bt newsr 1234!`")
                    return

            tag.sr = sr

            rank = get_rank(sr)
            image = f"https://d1u1mce87gyfbn.cloudfront.net/game/rank-icons/season-2/rank-{rank+1}.png"

            await self._handle_new_sr(tag, sr, rank, image)
            session.commit()
            await reply(ctx, f"Done. The SR for *{tag.tag}* is now *{sr}*")


    @bt.subcommand()
    @condition(correct_channel)
    async def setrole(self, ctx, roles_str: str):
        "Alias for setroles"
        return await self.setroles(ctx, roles_str)


    @bt.subcommand()
    @condition(correct_channel)
    async def setroles(self, ctx, roles_str: str):
        names = {
            'd': Role.DPS,
            'm': Role.MAIN_TANK,
            'o': Role.OFF_TANK,
            's': Role.SUPPORT,
        }

        roles = Role.NONE

        for role in roles_str.lower():
            try:
                roles |= names[role]
            except KeyError:
                await reply(ctx, f"Unknown role identifier '{role}'. Valid role identifiers are: `d` (DPS), `m` (Main Tank), `o` (Off Tank), `s` (Support). They can be combined, eg. `ds` would mean DPS + Support.")
                return

        session = self.database.Session()
        try:
            user = self.database.user_by_discord_id(session, ctx.author.id)
            if not user:
                await reply(ctx, "You are not registered!")
                return
            user.roles = roles
            session.commit()
            await reply(ctx, f"Done. Your roles are now **{format_roles(roles)}**.")
        finally:
            session.close()


    async def _findplayers(self, ctx, diff_or_min_sr: int = None, max_sr: int = None, *, findall):
        logger.info(f"{ctx.author.id} issued findplayers {diff_or_min_sr} {max_sr} {findall}")

        session = self.database.Session()
        try:
            asker = self.database.user_by_discord_id(session, ctx.author.id)
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
                        await reply(ctx, "You just had to try ridiculous values, didn't you?")
                        return

                base_sr = asker.battle_tags[0].sr
                if not base_sr:
                    await reply(ctx, "You primary BattleTag has no SR, please give a SR range you want to search for instead")
                    return

                if sr_diff is None:
                    sr_diff = 1000 if base_sr < 3500 else 500

                min_sr, max_sr = base_sr - sr_diff, base_sr + sr_diff

                type_msg = f"within {sr_diff} of {base_sr} SR"

            else:
                # we are looking at a range
                min_sr = diff_or_min_sr

                if not ((500 <= min_sr <= 5000) and (500 <= max_sr <= 5000) and (min_sr <= max_sr)):
                    await reply(ctx, "min and max must be between 500 and 5000, and min must not be larger than max.")
                    return

                type_msg = f"between {min_sr} and {max_sr} SR"

            candidates = session.query(BattleTag).filter(BattleTag.sr.between(min_sr, max_sr)).all()

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

        finally:
            session.close()



    @bt.subcommand()
    async def help(self, ctx):
        for embed in self._create_help(ctx):
            await ctx.author.send(content=None, embed=embed)
        if not ctx.channel.private:
            await reply(ctx, "I sent you a DM with instructions.")


    def _create_help(self, ctx):
        channel_id = None

        for guild in self.client.guilds.values():
            if ctx.author.id in guild.members:
                channel_id = GUILD_INFOS[guild.id].listen_channel_id
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
                "If you are new to Orisa, you are probably looking for `!bt register`\n"

                ),
        )
        embed.add_field(
            name='!bt [nick]',
            value=('Shows the BattleTag for the given nickname, or your BattleTag '
                   'if no nickname is given. `nick` can contain spaces. A fuzzy search for the nickname is performed.\n'
                   '*Examples:*\n'
                   '`!bt` will show your BattleTag\n'
                   '`!bt the chosen one` will show the BattleTag of "tHE ChOSeN ONe"\n'
                   '`!bt orisa` will show the BattleTag of "SG | Orisa", "Orisa", or "Orisad"\n'
                   '`!bt oirsa` and `!bt ori` will probably also show the BattleTag of "Orisa"')
        )
        embed.add_field(
            name='!bt findplayers [max diff] *or* !bt findplayers min max',
            value='*This command is still in beta and may change at any time!*\n'
                  'This command is intended to find partners for your Competitive team and shows you all registered and online users within the specified range.\n'
                  'If `max diff` is not given, the maximum range that allows you to queue with them is used, so 1000 below 3500 SR, and 500 otherwise. '
                  'If `max diff` is given, it is used instead. `findplayers` then searches for all online players that around that range of your own SR.\n'
                  'Alternatively, you can give two parameters, `!bt findplayers min max`. In this mode, `findplayers` will search for all online players that are between '
                  'min and max.\n'
                  'Note that `findplayers` will take all registered BattleTags of players into account, not just their primary.\n'
                  '*Examples:*\n'
                  '`!bt findplayers`: finds all players that you could start a competitive queue with\n'
                  '`!bt findplayers 123`: finds all players that are within 123 SR of your SR\n'
                  '`!bt findplayers 1500 2300`: finds all players between 1500 and 2300 SR\n'
        )
        embed.add_field(
            name='!bt findallplayers [max diff] *or* !bt findplayers min max',
            value='Same as `findplayers`, but also includes offline players'
        )
        embed.add_field(
            name='!bt forceupdate',
            value='Immediately checks your account data and updates your nick accordingly.\n'
                  '*Checks and updates are done automatically, use this command only if '
                  'you want your nick to be up to date immediately!*'
        )
        embed.add_field(
            name='!bt forgetme',
            value='All your BattleTags will be removed from the database and your nick '
                  'will not be updated anymore. You can re-register at any time.'
        )

        embed.add_field(
            name='!bt format *format*',
            value="Lets you specify how your SR or rank is displayed. It will always be shown in [square\u00a0brackets] appended to your name.\n"
                "In the *format*, you can specify placeholders with `$placeholder` or `${placeholder}`. The second form is useful when there are no spaces "
                "between the placeholder name and the text. For example, to get `[2000 SR]`, you *can* use just `$sr SR`, however, to get `[2000SR]`, you need "
                "to use `${sr}SR`, because `$srSR` would refer to a nonexistant placeholder `srSR`.\n"
                "Your format string needs to use at least either `$sr` or `$rank`.\n"
        )
        embed.add_field(
            name="\N{BLACK STAR} *bt format placeholders (prepend a $)*",
            value=
                "*The following placeholders are defined:*\n"
                f"`dps`, `tank`, `support`, `flex`\nSymbols for the respective roles: `{self.SYMBOL_DPS}`, `{self.SYMBOL_TANK}`, `{self.SYMBOL_SUPPORT}`, `{self.SYMBOL_FLEX}`\n\n"
                "`sr`\nyour SR; if you have secondary accounts, an asterisk (\*) is added at the end.\n\n"
                "`rank`\nyour Rank; if you have secondary accounts, an asterisk (\*) is added at the end.\n\n"
                "`secondary_sr`\nThe SR of your secondary account, if you have registered one.\nIf you have more than one secondary account (you really like to "
                "give Blizzard money, don't you), the first secondary account (sorted alphabetically) will be used; in that case, consider using `$sr_range` instead.\n\n"
                "`secondary_rank`\nLike `secondary_sr`, but shows the rank instead.\n\n"
                "`lowest_sr`, `highest_sr`\nthe lowest/highest SR of all your accounts, including your primary. Only useful if you have more than one secondary.\n\n"
                "`lowest_rank`, `highest_rank`\nthe same, just for rank.\n\n"
                "`sr_range`\nThe same as `${lowest_sr}–${highest_sr}`.\n\n"
                "`rank_range`\nDito, but for rank.\n"
        )
        embed.add_field(
            name="\N{BLACK STAR} *bt format examples*",
            value=
                '`!bt format test $sr SR` will result in [test 2345 SR]\n'
                '`!bt format Potato/$rank` in [Potato/Gold].\n'
                '`!bt format $sr (alt: $secondary_sr)` in [1234* (alt: 2345)]\n'
                '`!bt format $sr ($sr_range)` in [1234* (600-4200)]\n'
                '`!bt format $sr ($rank_range)` in [1234* (Bronze-Grand Master)]\n\n'
                '*By default, the format is `$sr`*'
        )

        embeds = [embed]
        embed = Embed(title="help cont'd")
        embeds.append(embed)

        embed.add_field(
            name='!bt get nick',
            value=('Same as `!bt [nick]`, (only) useful when the nick is the same as a command.\n'
                   '*Example:*\n'
                   '`!bt get register foo` will search for the nick "register foo"')
        )
        embed.add_field(
            name='!bt register BattleTag#1234',
            value='Registers your account with the given BattleTag, or adds a secondary BattleTag to your account. '
                'Your OW account will be checked periodically and your nick will be '
                'automatically updated to show your SR or rank (see the *format* command for more info). '
                '`register` will fail if the BattleTag is invalid. *BattleTags are case-sensitive!*'
        )
        embed.add_field(
            name='!bt unregister *battletag*',
            value='If you have secondary BattleTags, you can remove the given BattleTag from the list. Unlike register, the search is performed fuzzy, so '
                'you normally only have to specify the first few letters of the BattleTag to remove.\n'
                'You cannot remove your primary BattleTag, you have to choose a different primary BattleTag first.\n'
                '*Example:*\n'
                '`!bt unregister foo`'
        )
        embed.add_field(
            name='!bt unregister *index*',
            value='Like `unregister battletag`, but removes the battletag by number. Your first secondary is 1, your second 2, etc.\n'
                "The order is shown by the `!bt` command (it's alphabetical).\n"
                "Normally, you should not need to use this alternate form, it's available in case Orisa gets confused on what BattleTag you mean (which shouldn't happen)\n"
                '*Example:*\n'
                '`!bt unregister 1`'
        )
        embed.add_field(
            name='!bt setprimary *battletag*',
            value="Makes the given secondary BattleTag your primary BattleTag. Your primary BattleTag is the one you are currently using, the its SR is shown in your nick\n"
                'Unlike `register`, the search is performed fuzzy and case-insensitve, so you normally only need to give the first (few) letters.\n'
                'The given BattleTag must already be registered as one of your BattleTags.\n'
                '*Example:*\n'
                '`!bt setprimary jjonak`'
        )
        embed.add_field(
            name='!bt setprimary *index*',
            value="Like `!bt setprimary battletag`, but uses numbers, 1 is your first secondary, 2 your seconds etc. The order is shown by `!bt` (alphabetical)\n"
                "Normally, you should not need to use this alternate form, it's available in case Orisa gets confused on what BattleTag you mean (which shouldn't happen)\n"
                '*Example:*\n'
                '`!bt setprimary 1`'
        )
        embed.add_field(
            name='!bt setroles *roles*',
            value="Sets the role you can/want to play. It will be shown in `!bt` and will also be used to update the number of roles "
                  "in voice channels you join.\n"
                  '*roles* is a single "word" consisting of one or more of the following identifiers (both upper and lower case work):\n'
                  '`d` for DPS, `m` for Main Tank, `o` for Off Tank, `s` for Support\n'
                  '*Examples:*\n'
                  "`!bt setroles d`: you only play DPS\n"
                  "`!bt setroles so`: you play Support and Off Tanks\n"
                  "`!bt setroles dmos`: you are a true Flex and play everything."
        )


        return embeds


    # Events
    @event('member_update')
    async def _member_update(self, ctx, old_member: Member, new_member: Member):

        def plays_overwatch(m):
            try:
                return m.game.name == "Overwatch"
            except AttributeError:
                return False

        async def wait_and_fire(ids_to_sync):
            logger.debug(f"sleeping for 30s before syncing after OW close of {new_member.name}")
            await trio.sleep(30)
            await self._sync_tags(ids_to_sync)
            logger.debug(f"done syncing tags for {new_member.name} after OW close")

        if plays_overwatch(old_member) and (not plays_overwatch(new_member)):
            logger.debug(f"{new_member.name} stopped playing OW")

            session = self.database.Session()
            try:
                user = self.database.user_by_discord_id(session, new_member.user.id)
                if not user:
                    logger.debug(f"{new_member.name} is not registered, nothing to do.")
                    return

                ids_to_sync = [t.id for t in user.battle_tags]
                logger.info(f"{new_member.name} stopped playing OW and has {len(ids_to_sync)} BattleTags that need to be checked")
            finally:
                session.close()

            await self.spawn(wait_and_fire, ids_to_sync)


    @event('voice_state_update')
    async def _voice_state_update(self, ctx, member, old_voice_state, new_voice_state):
        parent = None
        if old_voice_state:
            parent = old_voice_state.channel.parent
            await self._adjust_voice_channels(parent)

        if new_voice_state:
            if new_voice_state.channel.parent != parent:
                await self._adjust_voice_channels(new_voice_state.channel.parent)


    @event('message_create')
    async def _message_create(self, ctx, msg):
        #logger.debug(f"got message {msg.author} {msg.channel} {msg.content} {msg.snowflake_timestamp}")
        if msg.content.startswith("!bt"):
            logger.info(f"{msg.author.name} in {msg.channel.type.name} issued {msg.content}")
        if msg.content.startswith("!"):
            return
        try:
            dialog = self.dialogues[(msg.channel.id, msg.author.id)]
            if msg.snowflake_timestamp >= dialog.min_timestamp:
                await dialog.queue.put(msg)
            else:
                logger.info(f"too young! {dialog.min_timestamp}")
        except KeyError:
            pass
        if msg.channel.private and re.match(r"^[0-9]{3,4}!?$", msg.content.strip()):
            # single number, special case for newsr
            await self.newsr(Context(msg, ctx), msg.content.strip())

    @event('guild_member_remove')
    async def _guild_member_remove(self, ctx: Context, member: Member):
        logger.debug(f"Member {member.name}({member.id}) left the guild ({member.guild})")
        with self.database.session() as session:
            user = database.user_by_discord_id(session, member.id)
            if user:
                in_other_guild = False
                for guild in client.guilds.values():
                    if guild.id != member.guild.id and member.id in guild.members:
                        in_other_guild = True
                        break
                if not in_other_guild:
                    logger.info(f"deleting {user} from database because {member.name} left the guild and has no other guilds")
                    session.delete(user)
                    session.commit()

    # Util

    async def _prompt(self, channel, recipient_id, msg, timeout=3):
        dialog = Dialogue(datetime.utcnow(), None)
        key = (channel.id, recipient_id)
        if key in self.dialogues:
            raise ValueError("a dialog is already in progress")
        self.dialogues[key] = dialog
        await channel.messages.send(msg)
        try:
            with trio.fail_after(timeout):
                result = await dialog.queue.get()
                return result
        finally:
            del self.dialogues[key]


    async def _adjust_voice_channels(self, parent):
        logger.debug("adjusting parent %s", parent)
        guild = parent.guild
        if not guild:
            logger.debug("channel doesn't belong to a guild")
            return

        for cat in GUILD_INFOS[guild.id].managed_voice_categories:
            if cat.category_id == parent.id:
                info = cat
                break
        else:
            logger.debug("channel is not managed")
            return

        def prefixkey(chan):
            return chan.name.rsplit('#', 1)[0].strip()

        def numberkey(chan):
            return int(chan.name.rsplit('#', 1)[1])

        sorted_channels = sorted(filter(lambda chan: '#' in chan.name, parent.children), key=attrgetter('name'))

        grouped = groupby(sorted_channels, key=prefixkey)

        made_changes = False

        for prefix, group in grouped:
            if prefix not in cat.prefixes:
                continue

            chans = sorted(group, key=numberkey)

            empty_channels = [chan for chan in chans if not chan.voice_members]

            if not empty_channels:
                if len(chans) < cat.channel_limit:
                    # add a new channel
                    name = f"{prefix} #{len(chans)+1}"
                    logger.debug("creating a new channel %s", name)

                    if isinstance(cat.prefixes, dict):
                        limit = cat.prefixes[prefix]
                    else:
                        limit = 0

                    async with self.client.events.wait_for_manager("channel_create", lambda chan:chan.name == name):
                        await guild.channels.create(type_=ChannelType.VOICE, name=name, parent=parent, user_limit=limit)

                    logger.debug("created a new channel %s", name)

                    made_changes = True

            elif len(empty_channels) == 1:
                # how we want it
                continue

            else:

                # more than one empty channel, delete the ones with the highest numbers
                for chan in empty_channels[1:]:

                    id = chan.id
                    logger.debug("deleting channel %s", chan)
                    async with self.client.events.wait_for_manager("channel_delete", lambda chan: chan.id == id):
                        await chan.delete()
                    made_changes = True

        if made_changes:
            managed_channels = []
            unmanaged_channels = []

            # parent.children should be updated by now to contain newly created channels and without deleted ones

            for chan in parent.children:
                if '#' in chan.name and chan.name.rsplit('#', 1)[0].strip() in cat.prefixes:
                    managed_channels.append(chan)
                else:
                    unmanaged_channels.append(chan)


            managed_group = {}
            for prefix, group in groupby(sorted(managed_channels, key=prefixkey), key=prefixkey):
                managed_group[prefix] = sorted(list(group), key=numberkey)

            final_list = unmanaged_channels.copy()

            for prefix in cat.prefixes:
                chans = managed_group[prefix]
                # rename channels if necessary
                for i, chan in enumerate(chans):
                    new_name = f"{prefix} #{i+1}"
                    if new_name != chan.name:
                        await chan.edit(name=new_name)

                final_list.extend(chans)

            for i, chan in enumerate(final_list):
                if chan.position != i:
                    await chan.edit(position=i)



    def _format_nick(self, user):
        primary = user.battle_tags[0]

        rankno = get_rank(primary.sr)
        rank = RANKS[rankno] if rankno is not None else "Unranked"
        sr = primary.sr or "noSR"

        try:
            secondary_sr = user.battle_tags[1].sr
        except IndexError:
            # no secondary accounts
            secondary_sr = None
        else:
            # secondary accounts, mark SR
            sr = f"{sr}*"
            rank = f"{rank}*"

        if secondary_sr is None:
            secondary_sr = "noSR"
            secondary_rank = "Unranked"
        else:
            secondary_rank = RANKS[get_rank(secondary_sr)]

        srs = list(sorted(t.sr or -1 for t in user.battle_tags))

        while srs and srs[0] == -1:
            srs.pop(0)

        if srs:
            lowest_sr, highest_sr = srs[0], srs[-1]
            lowest_rank, highest_rank = (RANKS[get_rank(sr)] for sr in (srs[0], srs[-1]))
        else:
            lowest_sr = highest_sr = "noSR"
            lowest_rank = highest_rank = "Unranked"

        t = Template(user.format)
        try:
            return t.substitute(
                sr=sr,
                rank=rank,
                lowest_sr=lowest_sr,
                highest_sr=highest_sr,
                sr_range=f"{lowest_sr}–{highest_sr}",
                rank_range=f"{lowest_rank}–{highest_rank}",
                secondary_sr=secondary_sr,
                secondary_rank=secondary_rank,
                dps=self.SYMBOL_DPS,
                tank=self.SYMBOL_TANK,
                support=self.SYMBOL_SUPPORT,
                flex=self.SYMBOL_FLEX,

            )
        except KeyError as e:
            raise InvalidFormat(e.args[0]) from e


    async def _update_nick(self, user):
        user_id = user.discord_id

        for guild in self.client.guilds.values():
            try:
                nn = str(guild.members[user_id].name)
            except KeyError:
                continue
            formatted = self._format_nick(user)
            if re.search(r'\[.*?\]', str(nn)):
                new_nn = re.sub(r'\[.*?\]', f'[{formatted}]', nn)
            else:
                new_nn = f'{nn} [{formatted}]'

            if len(new_nn) > 32:
                raise NicknameTooLong(new_nn)

            if str(nn) != new_nn:
                try:
                    await guild.members[user_id].nickname.set(new_nn)
                except Exception:
                    logger.exception("error while setting nick")

        return new_nn

    async def _send_congrats(self, user, rank, image):
        for guild in self.client.guilds.values():
            try:
                if user.discord_id not in guild.members:
                    continue
                embed = Embed(
                    title=f"For your own safety, get behind the barrier!",
                    description=f"**{str(guild.members[user.discord_id].name)}** just advanced to **{RANKS[rank]}**. Congratulations!",
                    colour=COLORS[rank],
                )

                embed.set_thumbnail(url=image)

                await self.client.find_channel(GUILD_INFOS[guild.id].congrats_channel_id).messages.send(content=f"Let's hear it for <@!{user.discord_id}>!", embed=embed)
            except Exception:
                logger.exception(f"Cannot send congrats for guild {guild}")

    async def _sync_tag(self, tag):

        try:
            sr, rank, image = await get_sr_rank(tag.tag)
        except UnableToFindSR:
            logger.debug(f"No SR for {tag.tag}, oh well...")
            sr = rank = image = None
        except Exception:
            tag.error_count += 1
            logger.exception(f"Got exception while requesting {tag.tag}")
            raise
        await self._handle_new_sr(tag, sr, rank, image)

    async def _handle_new_sr(self, tag, sr, rank, image):
        tag.last_update = datetime.utcnow()
        tag.error_count = 0
        tag.sr = sr
        try:
            await self._update_nick(tag.user)
        except HierarchyError:
            # not much we can do, just ignore
            pass
        except NicknameTooLong as e:
            if tag.user.last_problematic_nickname_warning is None or tag.user.last_problematic_nickname_warning < datetime.utcnow() - timedelta(days=7):
                tag.user.last_problematic_nickname_warning = datetime.utcnow()
                msg = "*To avoid spamming you, I will only send out this warning once per week*\n"
                msg += f"Hi! I just tried to update your nickname, but the result '{e.nickname}' would be longer than 32 characters."
                if tag.user.format == "%s":
                    msg += "\nPlease shorten your nickname."
                else:
                    msg += "\nTry to use the %s format (you can type `!bt format %s` into this DM channel, or shorten your nickname."
                msg += "\nYour nickname cannot be updated until this is done. I'm sorry for the inconvenience."
                discord_user = await self.client.get_user(tag.user.discord_id)
                await discord_user.send(msg)

            # we can still do the rest, no need to return here
        if rank is not None:
            user = tag.user
            if user.highest_rank is None:
                user.highest_rank = rank

            elif rank > user.highest_rank:
                logger.debug(f"user {user} old rank {user.highest_rank}, new rank {rank}, sending congrats...")
                await self._send_congrats(user, rank, image)
                user.highest_rank = rank


    async def _sync_tags_from_queue(self, queue):
        first = True
        while True:
            try:
                tag_id = queue.get_nowait()
            except trio.WouldBlock:
                return
            if not first:
                delay = random.random() * 5.
                logger.debug(f"rate limiting: sleeping for {delay:.02}s")
                await trio.sleep(delay)
            else:
                first = False
            session = self.database.Session()
            try:
                tag = self.database.tag_by_id(session, tag_id)
                await self._sync_tag(tag)
            except Exception:
                logger.exception(f'exception while syncing {tag.tag} for {tag.user.discord_id}')
            finally:
                session.commit()
                session.close()


    async def _sync_check(self):
        session = self.database.Session()
        try:
            ids_to_sync = self.database.get_tags_to_be_synced(session)
        finally:
            session.close()
        if ids_to_sync:
            logger.info(f"{len(ids_to_sync)} tags need to be synced")
            await self._sync_tags(ids_to_sync)
        else:
            logger.debug("No tags need to be synced")

    async def _sync_tags(self, ids_to_sync):
        queue = trio.Queue(len(ids_to_sync))
        for tag_id in ids_to_sync:
            await queue.put(tag_id)

        async with trio.open_nursery() as nursery:
            for _ in range(5):
                nursery.start_soon(self._sync_tags_from_queue, queue)
        logger.info("done syncing")

    async def _sync_all_tags_task(self):
        await trio.sleep(10)
        logger.debug("started waiting...")
        while True:
            try:
                await self._sync_check()
            except Exception as e:
                logger.exception(f"something went wrong during _sync_check")
            await trio.sleep(60)

def fuzzy_nick_match(ann, ctx: Context, name: str):
    def strip_tags(name):
        return re.sub(r'^(.*?\|)?([^[]*)(\[.*)?', r'\2', str(name)).strip()

    member = member_id = None
    if ctx.guild:
        guilds = [ctx.guild]
    else:
        guilds = [guild for guild in ctx.bot.guilds.values() if ctx.author.id in guild.members]

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

        candidates = process.extractBests(name, {id: strip_tags(mem.name) for guild in guilds for id, mem in guild.members.items()}, scorer=scorer)
        logger.debug(f"candidates are {candidates}")
        if candidates:
            member_name, score, member_id = candidates[0]


    if member_id is not None:
        for guild in guilds:
            member = guild.members.get(member_id)
            if member:
                break

    if member is None:
        raise ConversionFailedError(ctx, name, Member, 'Cannot find member with that name')
    else:
        return member


class InvalidCharacterName(RuntimeError):
    def __init__(self, realm: str, name: str):
        self.realm = realm
        self.name = name


class Wow(Plugin):
    """WoW specific functionality"""

    MASHERY_BASE = 'https://eu.api.battle.net/wow'

    SYMBOL_GM = '\N{CROWN}'
    SYMBOL_OFFICER = '\U0001F530'

    SYMBOL_PVP = '\N{CROSSED SWORDS}'

    SYMBOL_ROLES = {
        WowRole.TANK: '\N{SHIELD}',
        WowRole.HEALER: '\N{HELMET WITH WHITE CROSS}',
        WowRole.RANGED: '\N{BOW AND ARROW}',
        WowRole.MELEE: '\N{DAGGER KNIFE}',
    }

    def __init__(self, client, database):
        super().__init__(client)
        self.database = database
        self.gms = {}
        self.officers = {}


    async def load(self):
        for guild_id in self.client.guilds:
            if GUILD_INFOS[guild_id].wow_guild_name:
                await self._set_gms_and_officers(guild_id)

        await self.spawn(self._update_task)

    @command()
    @condition(correct_wow_channel)
    async def wow(self, ctx, *, cmd: str):
        await reply(ctx, f"unknown command **{cmd}**, see `!wow help`")

    @wow.subcommand()
    async def help(self, ctx):
        embed = Embed(title="WoW commands",
                      description=("Commands are sorted roughly in order of usefulness\n"
                                  f"Report issues to <@!{self.client.application_info.owner.id}>"))

        embed.add_field(
            name="!wow main *character_name* [realm]",
            value=("Registers (or changes) your character and will update your nick to show you ilvl. "
                   f"It auto detects whether the character is a GM (`{self.SYMBOL_GM}`) or Officer "
                   f"(`{self.SYMBOL_OFFICER}`) and will prepend that symbol to the ilvl.\n"
                   "Your ilvl will be updated periodically, and when Orisa notices you "
                   "stopped playing WoW (only works when using the Discord Desktop App).\n"
                   "*realm* is optional, if not given, defaults to the realm of the guild.\n"
                   "*Example:* `!wow main Orisa`\n"
                   "*Alternate form:* `!wow main character-realm`"))

        embed.add_field(
            name="!wow roles xxx",
            value=("Sets your PvE roles, those will be shown next to your ilvl. Roles are one "
                   "or more of the following:\n"
                   f"`m`elee (`{self.SYMBOL_ROLES[WowRole.MELEE]}`), `r`anged (`{self.SYMBOL_ROLES[WowRole.RANGED]}`), "
                   f"`t`ank (`{self.SYMBOL_ROLES[WowRole.TANK]}`), `h`ealer (`{self.SYMBOL_ROLES[WowRole.HEALER]}`)."
            ))

        embed.add_field(
            name="!wow pvp",
            value=("Switches your account to a PvP one. Instead of ilvl, it will show your "
                   f"RBG, and will add a `{self.SYMBOL_PVP}` symbol to distinguish it from "
                   "the ilvl. PvE roles will not be shown in this mode."))

        embed.add_field(
            name="!wow pve",
            value=("Switches back to PvE mode"))

        embed.add_field(
            name="!wow nopvp",
            value="Same as `!wow pve`")

        embed.add_field(
            name="!wow forceupdate",
            value=("Forces your ilvl/RBG to be checked and updated immediately. "
                   "Checks are done periodically (approximately every hour), you only "
                   "need to issue this command if you want your new levels to be shown "
                   "immediately."))

        embed.add_field(
            name="!wow forgetme",
            value="Resets your nick and removes you from the database")

        embed.add_field(
            name="!wow updateall",
            value=("Forces an immediate update of all guild data and guild members "
                   "(like every member issued a `forceupdate`). "
                   "Useful when the GM or Officers change.\n"
                   "*This is a priviledged command and can only be issued by members with "
                   "a specific Discord role (which is server specific).*"))

        await ctx.author.send(content=None, embed=embed)

        if not ctx.channel.private:
            await reply(ctx, "I sent you a DM with information.")


    @wow.subcommand()
    @condition(correct_wow_channel)
    async def main(self, ctx, name: str, *, realm: Optional[str] = None):
        guild = ctx.guild
        if not guild:
            await reply(ctx, "This command cannot be issued in DM")
            return

        if '-' in name and not realm:
            name, realm = name.strip().split('-')

        async with ctx.channel.typing:
            if not realm:
                realm = GUILD_INFOS[guild.id].wow_guild_realm
            try:

                ilvl_pvp = await self._get_profile_data(realm, name)
            except InvalidCharacterName:
                await reply(ctx, f"No character **{name}** exists in realm **{realm}**")
                return

            discord_id = ctx.author.id

            with self.database.session() as session:
                async with ctx.channel.typing:
                    user = self.database.wow_user_by_discord_id(session, discord_id)
                    ilvl, pvp = ilvl_pvp

                    if not user:
                        user = WowUser(discord_id=discord_id, character_name=name, realm=realm)
                        msg = (f"OK, I've registered the character **{name}** (ILvl {ilvl}, RBG {pvp}, realm {realm}) to your account. Next, please tell us what roles you play by issuing `!wow roles xxx`, where `xxx` "
                                "is one or more of: `t`ank, `m`elee, `r`anged, `h`ealer.\n"
                                "You can also use `!wow pvp` to switch to PvP mode.")
                        session.add(user)
                    else:
                        if (user.character_name, user.realm) == (name, realm):
                            await reply(ctx, f"That's already your main character. Use `!wow forceupdate` if you want to force an update")
                            return
                        user.character_name = name
                        user.realm = realm
                        msg = f"OK, I've updated your main character to **{name}** (ILvl {ilvl}, RBG {pvp}, realm {realm})"

                    session.commit()

                    await self._format_nick(user, ilvl_pvp)

        await reply(ctx, msg)

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def roles(self, ctx, roles: str):
        ROLE_MAP = {
            't': WowRole.TANK,
            'm': WowRole.MELEE,
            'r': WowRole.RANGED,
            'h': WowRole.HEALER,
        }

        discord_id = ctx.author.id

        with self.database.session() as session:
            user = self.database.wow_user_by_discord_id(session, discord_id)
            if not user:
                await reply(ctx, "you are not registered, use `!wow main` first")
                return

            roles_flag = WowRole.NONE
            for role in roles:
                try:
                    roles_flag |= ROLE_MAP[role.lower()]
                except KeyError:
                    await reply(ctx, f"Unknown role **{role}**. Valid roles are one or more of `t`ank, `m`elee, `r`anged, `h`ealer.")
                    return

            user.roles = roles_flag
            session.commit()
            await self._format_nick(user)

        await reply(ctx, "done")

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def pvp(self, ctx):
        await self._pvp(ctx, True)


    @wow.subcommand()
    @condition(correct_wow_channel)
    async def nopvp(self, ctx):
        await self._pvp(ctx, False)

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def pve(self, ctx):
        await self._pvp(ctx, False)


    async def _pvp(self, ctx, pvp):
        guild = ctx.guild
        if not guild:
            await reply(ctx, "This command cannot be issued in DM")
            return

        with self.database.session() as session:

            async with ctx.channel.typing:
                discord_id = ctx.author.id

                user = self.database.wow_user_by_discord_id(session, discord_id)
                if not user:
                    await reply(ctx, "You are not registered.")
                    return
                user.pvp = pvp
                session.commit()
                await self._format_nick(user)

        if pvp:
            msg = "Done. You can turn PvP off again with `!wow pve`"
        else:
            msg = "Done. You can turn PvP on again with `!wow pvp`"

        await reply(ctx, msg)

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def forceupdate(self, ctx):
        guild = ctx.guild
        if not guild:
            await reply(ctx, "This command cannot be issued in DM")
            return

        with self.database.session() as session:

            discord_id = ctx.author.id

            async with ctx.channel.typing:
                user = self.database.wow_user_by_discord_id(session, discord_id)
                if not user:
                    await reply(ctx, "you are not registered, use `!wow main` first")
                    return

                ilvl, rbg = await self._format_nick(user)

        await reply(ctx, f"Done. Your Item Level is now {ilvl}, and your RBG is {rbg}")

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def forgetme(self, ctx):
        with self.database.session() as session:
            discord_id = ctx.author.id

            user = self.database.wow_user_by_discord_id(session, discord_id)
            if not user:
                await reply(ctx, "You are not registered anyway. *Sleep mode reactivated*")
                return

            user_id = user.discord_id
            try:
                for guild in self.client.guilds.values():
                    try:
                        nn = str(guild.members[user_id].name)
                    except KeyError:
                        continue
                    new_nn = re.sub(r'\s*\{.*?\}', '', nn, count=1).strip()
                    try:
                        await guild.members[user_id].nickname.set(new_nn)
                    except HierarchyError:
                        pass
            except Exception:
                logger.exception("Some problems while resetting nicks")

            session.delete(user)

            session.commit()

        await reply(ctx, "OK, removed you from the database and stopped updating your nickname")


    @wow.subcommand()
    @condition(correct_wow_channel)
    async def updateall(self, ctx):
        guild = ctx.guild

        if not guild:
            await reply(ctx, "This command cannot be issued in DM")
            return

        needed_role = GUILD_INFOS[guild.id].wow_admin_role_name
        if not (ctx.author.id == ctx.bot.application_info.owner.id or any(role.name.lower() == needed_role.lower() for role in ctx.author.roles)):
            await reply(ctx, f"You need the **{needed_role}** role to issue this command")
            return

        async with ctx.channel.typing:
            await self._update_guild(guild)

        await reply(ctx, "Done")


    # Utils

    async def _update_task(self):
        logger.debug("Waiting 60s before starting WoW sync")
        await trio.sleep(60)
        while True:
            try:
                await self._update_all_the_things()
            except Exception:
                logger.exception("Error during WoW update")
            await trio.sleep(3600)

    async def _update_all_the_things(self):
        for guild_id, guild_info in GUILD_INFOS.items():
            if guild_info.wow_guild_name:
                await self._update_guild(self.client.guilds[guild_id])

    async def _update_guild(self, guild):
        await self._set_gms_and_officers(guild.id)
        with self.database.session() as session:
            for user_id in guild.members:
                user = self.database.wow_user_by_discord_id(session, user_id)
                if user:
                    try:
                        await self._format_nick(user)
                    except Exception:
                        logger.exception(f"unable to format nick for {user}")


    async def _set_gms_and_officers(self, guild_id):
        self.gms[guild_id], self.officers[guild_id] = await self._lookup_gm_and_officers(GUILD_INFOS[guild_id])

    async def _lookup_gm_and_officers(self, guild_info):
        res = await asks.get(f"{self.MASHERY_BASE}/guild/{guild_info.wow_guild_realm}/{guild_info.wow_guild_name}", params={"apikey": MASHERY_API_KEY, "fields": "members"})
        logger.debug(f"current quota: {res.headers.get('X-Plan-Quota-Current', '?')}/{res.headers.get('X-Plan-Quota-Allotted', '?')}")
        data = res.json()

        gms = set()
        officers = set()

        for member in data["members"]:
            if member["rank"] in guild_info.wow_gm_ranks:
                gms.add(member["character"]["name"])
            elif member["rank"] in guild_info.wow_officer_ranks:
                officers.add(member["character"]["name"])

        return gms, officers

    async def _get_profile_data(self, realm, character_name):
        logger.debug(f"requesting {realm}/{character_name}")
        res = await asks.get(f"{self.MASHERY_BASE}/character/{realm}/{character_name}", params={"apikey": MASHERY_API_KEY, "fields": "pvp, items"})

        logger.debug(f"current quota: {res.headers.get('X-Plan-Quota-Current', '?')}/{res.headers.get('X-Plan-Quota-Allotted', '?')}")
        if not res.status_code == 200:
            raise InvalidCharacterName(realm, character_name)

        data = res.json()

        rbg = ilvl = None

        with suppress(KeyError):
            rbg = data['pvp']['brackets']['ARENA_BRACKET_RBG']['rating']

        with suppress(KeyError):
            ilvl = data['items']['averageItemLevel']

        logger.debug(f"{realm}/{character_name} done")
        return ilvl, rbg


    async def _format_nick(self, user, ilvl_rbg = None):

        if ilvl_rbg is not None:
            ilvl, rbg = ilvl_rbg
        else:
            ilvl, rbg = await self._get_profile_data(user.realm, user.character_name)


        if user.pvp:
            format = f"{rbg}{self.SYMBOL_PVP}"
        else:
            format = f"{ilvl}"

            for role, sym in self.SYMBOL_ROLES.items():
                if role in user.roles:
                    format += sym

        for gid, guild in self.client.guilds.items():
            if user.discord_id in guild.members:
                nick = guild.members[user.discord_id].nickname

                nick_str = str(guild.members[user.discord_id].name)

                if user.character_name in self.gms[gid]:
                    prefix = self.SYMBOL_GM
                elif user.character_name in self.officers[gid]:
                    prefix = self.SYMBOL_OFFICER
                else:
                    prefix = ""


                if re.search(r"\{.*?\}", nick_str):
                    new_nick = re.sub(r"\{.*?\}", '{' + prefix + format + '}', nick_str, count=1)
                else:
                    new_nick = nick_str.strip() + ' {' + prefix + format + '}'

                try:
                    if new_nick != nick_str:
                        await nick.set(new_nick)
                except Exception:
                    logger.exception(f"unable to set nickname for {user} in {guild}")

        return ilvl, rbg

    # Events

    @event('member_update')
    async def _member_update(self, ctx, old_member: Member, new_member: Member):

        def plays_wow(m):
            try:
                return m.game.name == "World of Warcraft"
            except AttributeError:
                return False

        async def wait_and_fire(id_to_sync):
            logger.debug(f"sleeping for 30s before syncing after WoW close of {new_member.name}")
            await trio.sleep(30)
            with self.database.session() as session:
                user = self.database.wow_user_by_discord_id(session, id_to_sync)
                await self._format_nick(user)
            logger.debug(f"done updating nick for {new_member.name} after WoW close")

        if plays_wow(old_member) and (not plays_wow(new_member)):
            logger.debug(f"{new_member.name} stopped playing WoW")

            session = self.database.Session()
            try:
                user = self.database.wow_user_by_discord_id(session, new_member.user.id)
                if not user:
                    logger.debug(f"{new_member.name} is not registered, nothing to do.")
                    return

                logger.info(f"{new_member.name} stopped playing WoW and needs to be checked")
            finally:
                session.close()

            await self.spawn(wait_and_fire, new_member.user.id)


Context.add_converter(Member, fuzzy_nick_match)

multio.init('trio')

client = Client(BOT_TOKEN)

database = Database()

manager = CommandsManager.with_client(client, command_prefix="!")

@client.event('ready')
async def ready(ctx):
    logger.debug(f"Guilds are {ctx.bot.guilds}")
    await manager.load_plugin(Orisa, database)
    if MASHERY_API_KEY:
        await manager.load_plugin(Wow, database)
    await ctx.bot.change_status(game=Game(name='"!bt help" for help'))
    logger.info("Ready")

client.run()

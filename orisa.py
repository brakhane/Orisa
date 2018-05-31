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
from datetime import datetime
from itertools import groupby
from operator import attrgetter, itemgetter
from string import Template

import asks
import curio
import html5lib
import multio
import yaml
from curious.commands.context import Context
from curious.commands.decorators import command, condition
from curious.commands.exc import ConversionFailedError
from curious.commands.manager import CommandsManager
from curious.commands.plugin import Plugin
from curious.core.client import Client
from curious.exc import HierarchyError
from curious.dataclasses.embed import Embed
from curious.dataclasses.member import Member
from curious.dataclasses.presence import Game, Status
from fuzzywuzzy import process, fuzz
from lxml import html


from config import BOT_TOKEN, GUILD_ID, CHANNEL_ID, CONGRATS_CHANNEL_ID, OWNER_ID
from models import Database, User, BattleTag

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

async def get_sr_rank(battletag):
    if not re.match(r'\w+#[0-9]+', battletag):
        raise InvalidBattleTag('Malformed BattleTag. BattleTags look like SomeName#1234: a name and a # sign followed by a number and contain no spaces. They are case-sensitive, too!')

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
    return (sr, get_rank(sr), rank_image)

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
    return await ctx.channel.messages.send(f"{ctx.author.mention} {msg}")

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


# Conditions

def correct_guild(ctx):
    return ctx.guild.id == GUILD_ID

def correct_channel(ctx):
    return ctx.channel.id == CHANNEL_ID or ctx.channel.private

def only_owner(ctx):
    return ctx.author.id == OWNER_ID and ctx.channel.private

# Main Orisa code

class Orisa(Plugin):

    def __init__(self, client, database):
        super().__init__(client)
        self.database = database

    async def load(self):
        await self.spawn(self._sync_all_tags_task)


    # admin commands

    @command()
    @condition(only_owner)
    async def shutdown(self, ctx):
        logger.critical("GOT EMERGENCY SHUTDOWN COMMAND FROM OWNER")
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
                    logger.debug(f"Sending message to {user.discord_id}")
                    chan = await self.client.guilds[GUILD_ID].members[user.discord_id].user.open_private_channel()
                    await chan.messages.send(message)
                except:
                    logger.exception(f"Error while sending to {user.discord_id}")
            logger.debug("Done sending")
        finally:
            s.close()

    @command()
    @condition(only_owner)
    async def post(self, ctx, channel_id: int, *, message:str):
        channel = self.client.find_channel(channel_id)
        msg = await channel.messages.send(message)
        await ctx.channel.messages.send(f"created {msg.id}")

    @command()
    @condition(only_owner)
    async def delete(self, ctx, channel_id: int, message_id: int):
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
    async def cleanup(self, ctx, *, doit: str = None):
        member_ids = self.client.guilds[GUILD_ID].members.keys()
        session = self.database.Session()
        try:
            registered_ids = [x[0] for x in session.query(User.discord_id).all()]
            stale_ids = set(registered_ids) - set(member_ids)
            ids = ', '.join(f"<@{id}>" for id in stale_ids)
            await ctx.channel.messages.send(f"there are {len(stale_ids)} stale entries: {ids}")

        finally:
            session.close()

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
                if member == ctx.author and member_given:
                    embed.set_footer(text="BTW, you do not need to specify your nickname if you want your own BattleTag; just !bt is enough")
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
                resp = ("OK. People can now ask me for your BattleTag, and I will update your nick whenever I notice that your SR changed.\n"
                        "If you want, you can also join the Overwatch role by typing `.iam Overwatch` (mind the leading dot) in the overwatch-stats "
                        "channel, this way, you can get notified by shoutouts to @Overwatch\n")
            else:
                if any(tag.tag == battle_tag for tag in user.battle_tags):
                    await reply(ctx, "You already registered that BattleTag, so there's nothing for me to do. *Sleep mode reactivated.*")
                    return

                tag = BattleTag(tag=battle_tag)
                user.battle_tags.append(tag)
                resp = (f"OK. I've added {battle_tag} to the list of your BattleTags. Your primary BattleTag remains **{user.battle_tags[0].tag}**. "
                        f"To change your primary tag, use `!bt setprimary yourbattletag`, see help for more details.")
            await ctx.channel.send_typing() # show that we're working
            try:
                sr, rank, image = await get_sr_rank(battle_tag)
            except InvalidBattleTag as e:
                await reply(ctx, f"Invalid BattleTag: {e.message}")
                raise
            except UnableToFindSR:
                resp += "\nYou don't have an SR though, you probably need to finish your placement matches... I still saved your BattleTag."
                sr = None

            tag.last_update = datetime.now()
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
                 'Please choose a different format or shorten your nickname and do a `!bt forceupdate` afterwards.')
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
                await reply(ctx, "OK, I will update your data immediately. If your SR is not up to date, you need to log out of Overwatch once and try again.")
                for tag in user.battle_tags:
                    try:
                        await self._sync_tag(tag)
                    except Exception as e:
                        logger.exception(f'exception while syncing {tag}')
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

            guild = self.client.guilds[GUILD_ID]
            
            online = []
            offline = []

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
        for embed in self._create_help():
            await ctx.author.send(content=None, embed=embed)
        if not ctx.channel.private:
            await reply(ctx, "I sent you a DM with instructions.")


    def _create_help(self):
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
                f"*Like Overwatch's Orisa, this bot is quite young and still new at this. Report issues to <@!{OWNER_ID}>*\n"
                f"\n**The commands only work in the <#{CHANNEL_ID}> channel or by sending me a DM**"),
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
                  'If `max diff` is given, it is used instead. `findplayers` then search for all online players that around that range of your own SR.\n'
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
            name="\N{BLACK STAR} *bt format placeholders*",
            value=
                "*The following placeholders are defined:*\n"
                "`sr`\nyour SR; if you have secondary accounts, an asterisk (\*) is added at the end.\n\n"
                "`rank`\nyour Rank; if you have secondary accounts, an asterisk (\*) is added at the end.\n\n"
                "`secondary_sr`\nThe SR of your secondary account, if you have registered one. If you have more than one secondary account (you really like to "
                "give Blizzard money, don't you), the first secondary account (sorted alphabetically) will be used.\n\n"
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

        return embeds

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
            )
        except KeyError as e:
            raise InvalidFormat(e.args[0]) from e


    async def _update_nick(self, user):
        user_id = user.discord_id

        nn = str(self.client.guilds[GUILD_ID].members[user_id].name)
        formatted = self._format_nick(user)
        if re.search(r'\[.*?\]', str(nn)):
            new_nn = re.sub(r'\[.*?\]', f'[{formatted}]', nn)
        else:
            new_nn = f'{nn} [{formatted}]'
       
        if len(new_nn) > 32:
            raise NicknameTooLong(new_nn)

        if str(nn) != new_nn:
            await self.client.guilds[GUILD_ID].members[user_id].nickname.set(new_nn)

        return new_nn

    async def _send_congrats(self, user, rank, image):

        embed = Embed(
            title=f"For your own safety, get behind the barrier!",
            description=f"**{str(self.client.guilds[GUILD_ID].members[user.discord_id].name)}** just advanced to **{RANKS[rank]}**. Congratulations!",
            colour=COLORS[rank],
        )

        embed.set_thumbnail(url=image)

        await self.client.find_channel(CONGRATS_CHANNEL_ID).messages.send(embed=embed)

    async def _sync_tag(self, tag):

        try:
            sr, rank, image = await get_sr_rank(tag.tag)
            tag.last_update = datetime.now()
        except UnableToFindSR:
            logger.debug(f"No SR for {tag.tag}, oh well...")
            sr = rank = image = None
        except Exception:
            tag.error_count += 1
            logger.exception(f"Got exception while requesting {tag.tag}")
            raise

        tag.error_count = 0
        tag.sr = sr
        try:
            await self._update_nick(tag.user)
        except HierarchyError:
            # not much we can do, just ignore
            pass
        except NicknameTooLong as e:
            msg = f"Hi! I just tried to update your nickname, but the result '{e.nickname}' would be longer than 32 characters."
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


    async def _sync_tags_task(self, queue):
        first = True
        async for tag_id in queue:
            if not first:
                delay = random.random() * 5.
                logger.debug(f"rate limiting: sleeping for {delay}s")
                await curio.sleep(delay)
            else:
                first = False
            session = self.database.Session()
            try:
                tag = self.database.tag_by_id(session, tag_id)
                await self._sync_tag(tag)
            except Exception:
                logger.exception(f'exception while syncing {tag.tag} for {tag.user.discord_id}')
            finally:
                await queue.task_done()
                session.commit()
                session.close()            

    
    async def _sync_check(self):
        queue = curio.Queue()
        session = self.database.Session()
        try:
            ids_to_sync = self.database.get_tags_to_be_synced(session)
        finally:
            session.close()
        logger.info(f"{len(ids_to_sync)} tags need to be synced")
        if ids_to_sync:
            for tag_id in ids_to_sync:
                await queue.put(tag_id)
            async with curio.TaskGroup(name='sync tags') as g:
                for _ in range(5):
                    await g.spawn(self._sync_tags_task, queue)
                await queue.join()
                await g.cancel_remaining()
            logger.info("done syncing")

    async def _sync_all_tags_task(self):
        await curio.sleep(10)
        logger.debug("started waiting...")
        while True:
            try:
                await self._sync_check()
            except Exception as e:
                logger.exception(f"something went wrong during _sync_check")
            await curio.sleep(60)



def fuzzy_nick_match(ann, ctx: Context, name: str):
    def strip_tags(name):
        return re.sub(r'^(.*?\|)?([^[]*)(\[.*)?', r'\2', str(name)).strip()

    member = member_id = None
    guild = ctx.bot.guilds[GUILD_ID]
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

        candidates = process.extractBests(name, {id: strip_tags(mem.name) for id, mem in guild.members.items()}, scorer=scorer)
        logger.debug(f"candidates are {candidates}")
        if candidates:
            member_name, score, member_id = candidates[0]


    if member_id is not None:
        member = guild.members.get(member_id)

    if member is None:
        raise ConversionFailedError(ctx, name, Member, 'Cannot find member with that name')
    else:
        return member
      
Context.add_converter(Member, fuzzy_nick_match)


multio.init('curio')

client = Client(BOT_TOKEN)

database = Database()

async def check_guild(guild):
    if guild.id != GUILD_ID:
        logger.info("Unknown guild! leaving")
        if guild.system_channel:
            await guild.system_channel.messages.send(f"I'm not configured for this guild! Bye!")
        try:
            await guild.leave()
        except:
            logger.fatal("unknown guild, but cannot leave it...")
            raise SystemExit(1)

@client.event('guild_join')
async def guild_join(ctx, guild):
    await check_guild(guild)

@client.event('ready')
async def ready(ctx):
    for guild in ctx.bot.guilds.copy().values():
        await check_guild(guild)

    await manager.load_plugin(Orisa, database)
    await ctx.bot.change_status(game=Game(name='"!bt help" for help'))
    logger.info("Ready")

@client.event('guild_member_remove')
async def remove_member(ctx: Context, member: Member):
    logger.debug(f"Member {member.name}({member.id}) left the guild")
    session = database.Session()
    try:
        user = database.user_by_discord_id(session, member.id)
        if user:
            logger.info(f"deleting {user} from database")
            session.delete(user)
            session.commit()
    finally:
        session.close()



manager = CommandsManager.with_client(client, command_prefix="!")

client.run(with_monitor=True)

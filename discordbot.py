import logging
import re
import random
from bisect import bisect
from datetime import datetime, timedelta

import asks
import curio
import html5lib
import multio
from curious.commands.context import Context
from curious.commands.decorators import command, condition
from curious.commands.exc import ConversionFailedError
from curious.commands.manager import CommandsManager
from curious.commands.plugin import Plugin
from curious.core.client import Client
from curious.dataclasses.embed import Embed
from curious.dataclasses.member import Member
from curious.dataclasses.presence import Game
from fuzzywuzzy import process
from lxml import html

from config import BOT_TOKEN, GUILD_ID
from models import Database, User

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


class InvalidBattleTag(Exception):
    def __init__(self, message):
        self.message = message

RANK_CUTOFF = (1500, 2000, 2500, 3000, 3500, 4000)
RANKS = ('Bronze', 'Silver', 'Gold', 'Platinum', 'Diamond', 'Master', 'Grand Master')

def get_rank(sr):
    return RANKS[bisect(RANK_CUTOFF, sr)]

async def get_sr_rank(battletag):
    if not re.match(r'\w+#[0-9]+', battletag):
        raise InvalidBattleTag('Malformed BattleTag')

    url = f'https://playoverwatch.com/en-us/career/pc/{battletag.replace("#", "-")}'
    logging.info(f'requesting {url}')
    result = await asks.get(url)
    if result.status_code != 200:
        raise RuntimeError(f'got status code {result.status_code} from Blizz')

    document = html.fromstring(result.content)
    srs = document.xpath('//div[@class="competitive-rank"]/div/text()')
    rank_image_elems = document.xpath('//div[@class="competitive-rank"]/img/@src')
    if not srs:
        if 'Profile Not Found' in result.text:
            raise InvalidBattleTag(f"No profile with BattleTag {battletag} found. Battle tags are case-sensitive!")
        raise RuntimeError('Unable to find SR')
    sr = int(srs[0])
    if rank_image_elems:
        rank_image = str(rank_image_elems[0])
    else:
        rank_image = None
    return (sr, get_rank(sr), rank_image)


def correct_guild(ctx):
    return ctx.guild.id == GUILD_ID

class Orisa(Plugin):

    def __init__(self, client, database):
        super().__init__(client)
        self.database = database


    @command()
    async def get(self, ctx, bt: str):
        await ctx.channel.messages.send(f"requesting {bt}...")
        try:
            sr, rank, image = await get_sr_rank(bt)
        except InvalidBattleTag as e:
            await ctx.channel.messages.send(f'Invalid battle tag: {e.message}')
        except RuntimeError as e:
            await ctx.channel.messages.send(f'Sorry, something went wrong: {e.args[0]}')
        else:
            await ctx.channel.messages.send(f"{bt} has {sr} SR, that's {rank}. {image} {type(image)}")

            member = list(ctx.bot.guilds.values())[0].search_for_member(name='testxxyyzz')
            nnstr = str(member.nickname)
            if not nnstr:
                nnstr = member.name

            if re.search(r'\[.*\]', nnstr):
                new_name = re.sub(r'\[.*?\]', f'[{rank}]', nnstr)
            else:
                new_name = nnstr + f' [{rank}]'
            await member.nickname.set(new_name)

    @command()
    async def bt(self, ctx, member: Member = None):
        if member is None:
            member = ctx.author

        session = self.database.Session()
        try:
            user = self.database.by_discord_id(session, member.id)
            if user:
                msg = f"{member.name}'s BattleTag is **{user.battle_tag}**"
            else:
                msg = f"{member.name} not found in database! *Do you need a hug?*"
        finally:
            session.close()

        await ctx.channel.messages.send(msg)

    @bt.subcommand()
    async def register(self, ctx, battle_tag: str = None):
        if battle_tag is None:
            await ctx.channel.messages.send(f"{ctx.author.mention} missing battletag")
            return
        member_id = ctx.message.author_id
        session = self.database.Session()
        try:
            user = self.database.by_discord_id(session, member_id)
            resp = None
            if user is None:
                user = User(discord_id=member_id)
                resp = "I will now regularly update your nick."
            else:
                resp = "I've updated your battle tag"
            try:
                sr, rank, image = await get_sr_rank(battle_tag)
            except InvalidBattleTag as e:
                await ctx.channel.messages.send(f"{ctx.author.mention} Invalid battletag: {e.message}")
                raise
            else:
                user.battle_tag = battle_tag
                user.last_update = datetime.now()
                user.sr = sr
                user.format = "%s" 
                resp = f"${ctx.author.mention} {resp}"

        finally: 
            session.commit() # we always want to commit, because we have error_count
            session.close()
        
        await ctx.channel.messages.send(f"{ctx.author.mention} {resp}")

    @bt.subcommand()
    async def format(self, ctx, *, format: str):
        if ']' in format:
            await ctx.channel.messages.send(f"{ctx.author.mention}: format string may not contain square brackets")
            return
        if ('%s' not in format) and ('%r' not in format):
            await ctx.channel.messages.send(f"{ctx.author.mention}: format string must contain at least a %s or %r")
            return
        if not format:
            await ctx.channel.messages.send(f"{ctx.author.mention}: format string missing")
            return
        
        session = self.database.Session()
        
        try:
            user = self.database.by_discord_id(session, 0)#ctx.author.id)
            if not user:
                await ctx.channel.messages.send(f"{ctx.author.mention}: you must register first")
                return
            else:
                user.format = format
                session.commit()
                await self._update_nick(user)
        finally:
            session.close()
            

    @bt.subcommand()
    async def rank(self, ctx, rank: int):
        embed = Embed(
            title=f"For your own safety, get behind the barrier!",
            description=f"{ctx.author.mention} just advanced to {RANKS[rank-1]}. Congratulations!"

        )

        embed.set_thumbnail(url=f"https://d1u1mce87gyfbn.cloudfront.net/game/rank-icons/season-2/rank-{rank}.png")

        await ctx.channel.messages.send(embed=embed)

    @bt.subcommand()
    async def help(self, ctx):
        embed = Embed(
            title="Orisa's purpose",
            description=("When joining a QP or Comp channel, you need to know a battle tag of a channel member, or they need "
                         "yours to add it. In competitive channels it also helps to know which SR the channel members are. "
                         "To avoid having to ask this information again and again when joining a channel, this bot was created. "
                         "When you register with your battle tag, your nick will automatically be updated to show your "
                         "current SR and it will be kept up to date. You can also ask for other member's battle tag, or request "
                         "your own so others can easily add you in OW.\n"
                         "It will also send a short message to the chat when you ranked up.\n"
                         "*Like Overwatch's Orisa, this bot is quite young and still new at this. Report issues to Joghurt*"),
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
            name='!bt get nick', 
            value=('Same as `!bt [nick]`, (only) useful when the nick is the same as a command.\n'
                   '*Example:*\n'
                   '`!bt get register foo` will search for the nick "register foo"')
        )

        embed.add_field(
            name='!bt register BattleTag#1234', 
            value='Registers or updates your account with the given BattleTag. '
                  'Your OW account will be checked periodically and your nick will be '
                  'automatically updated to show your SR or rank (see the *format* command for more info). '
                  '`register` will fail if the BattleTag is invalid. *BattleTags are case-sensitive!*'
        )
        embed.add_field(
            name='!bt format *format*',
            value="Let's you specify how your SR or rank is displayed. It will always "
                  "be shown in [square\u00a0brackets] appended to your name. "
                  "In the *format*, `%s` will be replaced with your SR, and `%r` "
                  "will be replaced with your rank.\n"
                  '*Examples:*\n'
                  '`!bt format test %s SR` will result in [test 2345 SR]\n'
                  '`!bt format Potato/%r` in [Potato/Gold].\n'
                  '*Default: `%s`*'
        )
        embed.add_field(
            name='!bt force update', 
            value='Immediately checks your account data and updates your nick accordingly.\n'
                  '*Checks and updates are done automatically, use this command only if '
                  'you want your nick to be up to date immediately!*'
        )
        embed.add_field(
            name='!bt forget me', 
            value='Your BattleTag will be removed from the database and your nick '
                  'will not be updated anymore. You can re-register at any time.'
        )
        await ctx.author.send(content=None, embed=embed)
        if not ctx.channel.private:
            await ctx.channel.messages.send(f"{ctx.author.mention} I sent you a DM with instructions.")


    def _format_nick(self, format, sr):
        rank = get_rank(sr)
        return format.replace('%s', str(sr)).replace('%r', rank)

    async def _update_nick(self, user):
        nn = self.client.guilds[GUILD_ID].members[user.discord_id].name
        formatted = self._format_nick(user.format, user.sr)
        if re.search(r'\[.*?\]', str(nn)):
            new_nn = re.sub(r'\[.*?\]', f'[{formatted}]', nn)
        else:
            new_nn = f'{nn} [{formatted}]'
        
        if str(nn) != new_nn:
            await self.client.guilds[GUILD_ID].members[user.discord_id].nickname.set(new_nn)


    async def _sync_user(self, user):
        user.last_update = datetime.now()
        try:
            sr, rank, image = await get_sr_rank(user.battle_tag)
        except Exception as e:
            user.error_count += 1
            logging.error(f"Got exception while requesting {user.battle_tag}")
            raise
        else:
            user.error_count = 0
            user.sr = sr
            await self._update_nick(user)

    async def _sync_user_task(self, queue):
        first = True
        while not queue.empty():
            if not first:
                delay = random.random() * 5.
                logging.debug(f"rate limiting: sleeping for {delay}s")
                await curio.sleep(delay)
            else:
                first = False
            user_id = await queue.get()
            session = self.database.Session()
            try:
                user = self.database.by_id(session, user_id)
                await self._sync_user(user)
            except Exception:
                logging.error(f'exception while syncing {user.discord_id} {user.battle_tag}')
            finally:
                session.commit()
                session.close()            
            
            await queue.task_done()

    
    @command()
    async def task(self, ctx):
        queue = curio.Queue()
        session = self.database.Session()
        try:
            ids_to_sync = self.database.get_to_be_synced(session)
        finally:
            session.close()
        logging.info(f"{len(ids_to_sync)} users need to be synced")
        for user_id in ids_to_sync:
            await queue.put(user_id)
        async with curio.TaskGroup() as g:
            for _ in range(5):
                await g.spawn(self._sync_user_task, queue)




def fuzzy_nick_match(ann, ctx: Context, name: str):
    print(ctx, name)
    member = member_id = None
    if name.startswith("<@") and name.endswith(">"):
        id = name[2:-1]
        if id[0] == "!":  # strip nicknames
            id = id[1:]
        try:
            member_id = int(id)
        except ValueError:
            raise ConversionFailedError(ctx, name, Member, "Invalid member ID")
    else:
        try:
            member, score, member_id = process.extractOne(name, {id: str(mem.name) for id, mem in ctx.guild.members.items()}, score_cutoff=50)
        except TypeError: # extractOne returns None when nothing found
            pass

    if member_id is not None:
        member = ctx.guild.members.get(member_id)

    if member is None:
        raise ConversionFailedError(ctx, name, Member, 'Cannot find member with that name')
    else:
        return member
      
Context.add_converter(Member, fuzzy_nick_match)


multio.init('curio')

client = Client(BOT_TOKEN)

async def check_guild(guild):
    if guild.id != GUILD_ID:
        print(f"Unknown guild! leaving")
        if guild.system_channel:
            await guild.system_channel.messages.send(f"I'm not configured for this guild! Bye!")
        try:
            await guild.leave()
        except:
            logging.fatal("unknown guild, but cannot leave it...")
            raise SystemExit(1)

@client.event('guild_join')
async def guild_join(ctx, guild):
    await check_guild(guild)

@client.event('ready')
async def ready(ctx):
    for guild in ctx.bot.guilds.copy().values():
        await check_guild(guild)

    await manager.load_plugin(Orisa, Database())
    await ctx.bot.change_status(game=Game(name='"!bt help" for help'))
    print("ready")

@client.event('guild_member_remove')
async def remove_member(ctx: Context, member: Member):
    logging.debug(f"das war's dann wohl für {member.name} {member.id}")



manager = CommandsManager.with_client(client, command_prefix="!")

client.run()

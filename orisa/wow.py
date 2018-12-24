import logging
import re
from contextlib import suppress

import asks
import trio
from curious import event
from curious.commands.decorators import command, condition
from curious.commands.plugin import Plugin
from curious.dataclasses.embed import Embed
from curious.dataclasses.guild import Guild
from curious.dataclasses.member import Member
from curious.exc import Forbidden, HierarchyError
from fuzzywuzzy import process

from .config import GUILD_INFOS, MASHERY_API_KEY

from .exceptions import NicknameTooLong
from .utils import reply

from .models import WowUser, WowRole

logger = logging.getLogger(__name__)

WOW_CHANNEL_IDS = frozenset(
    guild.wow_listen_channel_id for guild in GUILD_INFOS.values()
)


def correct_wow_channel(ctx):
    return ctx.channel.id in WOW_CHANNEL_IDS or ctx.channel.private


class InvalidCharacterName(RuntimeError):
    def __init__(self, realm: str, name: str):
        self.realm = realm
        self.name = name


class Wow(Plugin):
    """WoW specific functionality"""

    MASHERY_BASE = "https://eu.api.battle.net/wow"

    SYMBOL_GM = "\N{CROWN}"
    SYMBOL_OFFICER = "\U0001F530"

    SYMBOL_PVP = "\N{CROSSED SWORDS}"

    SYMBOL_ROLES = {
        WowRole.TANK: "\N{SHIELD}",
        WowRole.HEALER: "\N{HELMET WITH WHITE CROSS}",
        WowRole.RANGED: "\N{BOW AND ARROW}",
        WowRole.MELEE: "\N{DAGGER KNIFE}",
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

        # await self.spawn(self._update_task)

    @command()
    @condition(correct_wow_channel)
    async def wow(self, ctx, *, member: Member = None):

        member_given = member is not None
        if not member_given:
            member = ctx.author

        with self.database.session() as s:
            user = self.database.wow_user_by_discord_id(s, member.id)
            if user:
                content = None
                embed = Embed()
                embed.add_field(name="Nick", value=member.name)
                embed.add_field(
                    name="Character and Realm",
                    value=f"**{user.character_name}-{user.realm}**",
                )
            else:
                content = f"{member.name} not found in database! *Do you need a hug?*"
                if member == ctx.author:
                    embed = Embed(
                        title="Hint",
                        description="use `!wow main character_name realm_name` to register, or `!wow help` for more info",
                    )
                else:
                    embed = None

        await ctx.channel.messages.send(content=content, embed=embed)

    @wow.subcommand()
    async def help(self, ctx):
        embed = Embed(
            title="WoW commands",
            description=(
                "Commands are sorted roughly in order of usefulness\n"
                f"Report issues to <@!{self.client.application_info.owner.id}>"
            ),
        )

        embed.add_field(
            name="!wow [member]",
            value=(
                "Shows the character and realm of the given member, or your own if no member is given.\n"
                "The search is performed fuzzy, so a few letters of the member name should suffice."
            ),
        )
        embed.add_field(
            name="!wow reverse character_name",
            value=(
                "Performs a fuzzy search in the database to find the *member* that plays the given character. "
                "The search is performed fuzzy and expects the format `character-realm`. But since it's fuzzy, "
                "you generally can omit the realm."
            ),
        )
        embed.add_field(
            name="!wow main *character_name* [realm]",
            value=(
                "Registers (or changes) your character and will update your nick to show you ilvl. "
                f"It auto detects whether the character is a GM (`{self.SYMBOL_GM}`) or Officer "
                f"(`{self.SYMBOL_OFFICER}`) and will prepend that symbol to the ilvl.\n"
                "Your ilvl will be updated periodically, and when Orisa notices you "
                "stopped playing WoW (only works when using the Discord Desktop App).\n"
                "*realm* is optional, if not given, defaults to the realm of the guild.\n"
                "*Example:* `!wow main Orisa`\n"
                "*Alternate form:* `!wow main character-realm`"
            ),
        )

        embed.add_field(
            name="!wow roles xxx",
            value=(
                "Sets your PvE roles, those will be shown next to your ilvl. Roles are one "
                "or more of the following:\n"
                f"`m`elee (`{self.SYMBOL_ROLES[WowRole.MELEE]}`), `r`anged (`{self.SYMBOL_ROLES[WowRole.RANGED]}`), "
                f"`t`ank (`{self.SYMBOL_ROLES[WowRole.TANK]}`), `h`ealer (`{self.SYMBOL_ROLES[WowRole.HEALER]}`)."
            ),
        )

        embed.add_field(
            name="!wow pvp",
            value=(
                "Switches your account to a PvP one. Instead of ilvl, it will show your "
                f"RBG, and will add a `{self.SYMBOL_PVP}` symbol to distinguish it from "
                "the ilvl. PvE roles will not be shown in this mode."
            ),
        )

        embed.add_field(name="!wow pve", value=("Switches back to PvE mode"))

        embed.add_field(name="!wow nopvp", value="Same as `!wow pve`")

        embed.add_field(
            name="!wow forceupdate",
            value=(
                "Forces your ilvl/RBG to be checked and updated immediately. "
                "Checks are done periodically (approximately every hour), you only "
                "need to issue this command if you want your new levels to be shown "
                "immediately."
            ),
        )

        embed.add_field(
            name="!wow forgetme",
            value="Resets your nick and removes you from the database",
        )

        embed.add_field(
            name="!wow updateall",
            value=(
                "Forces an immediate update of all guild data and guild members "
                "(like every member issued a `forceupdate`). "
                "Useful when the GM or Officers change.\n"
                "*This is a priviledged command and can only be issued by members with "
                "a specific Discord role (which is server specific).*"
            ),
        )

        try:
            await ctx.author.send(content=None, embed=embed)
        except Forbidden:
            await reply(
                ctx,
                "I tried to send you a DM with help, but you don't allow DM from server members. "
                "I can't post it here, because it's rather long. Please allow DMs and try again.",
            )
        else:
            if not ctx.channel.private:
                await reply(ctx, "I sent you a DM with information.")

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def main(self, ctx, *, name_and_realm: str):
        guild = ctx.guild
        if not guild:
            await reply(ctx, "This command cannot be issued in DM")
            return

        name_and_realm = name_and_realm.strip()
        if "-" in name_and_realm:
            name, realm = name_and_realm.split("-", 1)
        elif " " in name_and_realm:
            name, realm = name_and_realm.split(" ", 1)
        else:
            name = name_and_realm
            realm = GUILD_INFOS[guild.id].wow_guild_realm

        async with ctx.channel.typing:
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
                        user = WowUser(
                            discord_id=discord_id, character_name=name, realm=realm
                        )
                        msg = (
                            f"OK, I've registered the character **{name}** (ILvl {ilvl}, RBG {pvp}, realm {realm}) to your account. Next, please tell us what roles you play by issuing `!wow roles xxx`, where `xxx` "
                            "is one or more of: `t`ank, `m`elee, `r`anged, `h`ealer.\n"
                            "You can also use `!wow pvp` to switch to PvP mode."
                        )
                        session.add(user)
                    else:
                        if (user.character_name, user.realm) == (name, realm):
                            await reply(
                                ctx,
                                f"That's already your main character. Use `!wow forceupdate` if you want to force an update",
                            )
                            return
                        user.character_name = name
                        user.realm = realm
                        msg = f"OK, I've updated your main character to **{name}** (ILvl {ilvl}, RBG {pvp}, realm {realm})"

                    session.commit()

                    try:
                        await self._format_nick(user, ilvl_pvp, raise_on_long_name=True)
                    except NicknameTooLong:
                        await reply(
                            ctx,
                            "I cannot add the information to your nickname, as it would be longer than 32 characters. Please shorten your nickname and try again.",
                        )

        await reply(ctx, msg)

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def reverse(self, ctx, *, character_realm: str):
        guild = ctx.guild
        if not guild:
            await reply(ctx, "This command cannot be issued in DM")
            return

        with self.database.session() as session:
            async with ctx.channel.typing:
                users = (
                    session.query(WowUser)
                    .filter(WowUser.discord_id.in_(guild.members))
                    .all()
                )
                res = process.extractOne(
                    character_realm,
                    {
                        user.discord_id: f"{user.character_name}-{user.realm}"
                        for user in users
                    },
                    score_cutoff=50,
                )
                if res:
                    name, score, id = res
                    member = guild.members[id]
                    content = None
                    embed = Embed()
                    embed.add_field(name="Nick", value=member.name)
                    embed.add_field(name="Character and Realm", value=f"**{name}**")
                else:
                    content = "I can't find a character with that name in my database."
                    embed = None

        await ctx.channel.send(content=content, embed=embed)

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def roles(self, ctx, *, roles: str):
        ROLE_MAP = {
            "t": WowRole.TANK,
            "m": WowRole.MELEE,
            "r": WowRole.RANGED,
            "h": WowRole.HEALER,
        }

        discord_id = ctx.author.id
        roles = roles.replace(" ", "")

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
                    await reply(
                        ctx,
                        f"Unknown role **{role}**. Valid roles are one or more of `t`ank, `m`elee, `r`anged, `h`ealer.",
                    )
                    return

            user.roles = roles_flag
            session.commit()
            await self._format_nick(user)

        await reply(ctx, "done")

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def pvp(self, ctx):
        await self._pvp(ctx, True)

    @wow.subcommand(aliases=("pve",))
    @condition(correct_wow_channel)
    async def nopvp(self, ctx):
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
                await reply(
                    ctx, "You are not registered anyway. *Sleep mode reactivated*"
                )
                return

            user_id = user.discord_id
            try:
                for guild in self.client.guilds.values():
                    try:
                        nn = str(guild.members[user_id].name)
                    except KeyError:
                        continue
                    new_nn = re.sub(r"\s*\{.*?\}", "", nn, count=1).strip()
                    try:
                        await guild.members[user_id].nickname.set(new_nn)
                    except HierarchyError:
                        pass
            except Exception:
                logger.exception("Some problems while resetting nicks")

            session.delete(user)

            session.commit()

        await reply(
            ctx, "OK, removed you from the database and stopped updating your nickname"
        )

    @wow.subcommand()
    @condition(correct_wow_channel)
    async def updateall(self, ctx):
        guild = ctx.guild

        if not guild:
            await reply(ctx, "This command cannot be issued in DM")
            return

        needed_role = GUILD_INFOS[guild.id].wow_admin_role_name
        if not (
            ctx.author.id == ctx.bot.application_info.owner.id
            or any(
                role.name.lower() == needed_role.lower() for role in ctx.author.roles
            )
        ):
            await reply(
                ctx, f"You need the **{needed_role}** role to issue this command"
            )
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
        self.gms[guild_id], self.officers[
            guild_id
        ] = await self._lookup_gm_and_officers(GUILD_INFOS[guild_id])

    async def _lookup_gm_and_officers(self, guild_info):
        res = await asks.get(
            f"{self.MASHERY_BASE}/guild/{guild_info.wow_guild_realm}/{guild_info.wow_guild_name}",
            params={"apikey": MASHERY_API_KEY, "fields": "members"},
        )
        logger.debug(
            f"current quota: {res.headers.get('X-Plan-Quota-Current', '?')}/{res.headers.get('X-Plan-Quota-Allotted', '?')}"
        )
        data = res.json()

        gms = set()
        officers = set()

        for member in data["members"]:
            if member["rank"] in guild_info.wow_gm_ranks:
                gms.add(member["character"]["name"].lower())
            elif member["rank"] in guild_info.wow_officer_ranks:
                officers.add(member["character"]["name"].lower())

        return gms, officers

    async def _get_profile_data(self, realm, character_name):
        logger.debug(f"requesting {realm}/{character_name}")
        res = await asks.get(
            f"{self.MASHERY_BASE}/character/{realm}/{character_name}",
            params={"apikey": MASHERY_API_KEY, "fields": "pvp, items"},
        )

        logger.debug(
            f"current quota: {res.headers.get('X-Plan-Quota-Current', '?')}/{res.headers.get('X-Plan-Quota-Allotted', '?')}"
        )
        if not res.status_code == 200:
            raise InvalidCharacterName(realm, character_name)

        data = res.json()

        rbg = ilvl = None

        with suppress(KeyError):
            rbg = data["pvp"]["brackets"]["ARENA_BRACKET_RBG"]["rating"]

        with suppress(KeyError):
            ilvl = data["items"]["averageItemLevel"]

        logger.debug(f"{realm}/{character_name} done")
        return ilvl, rbg

    async def _format_nick(self, user, ilvl_rbg=None, *, raise_on_long_name=False):

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
                if user.character_name.lower() in self.gms.get(gid, set()):
                    prefix = self.SYMBOL_GM
                elif user.character_name.lower() in self.officers.get(gid, set()):
                    prefix = self.SYMBOL_OFFICER
                else:
                    prefix = ""

                if re.search(r"\{.*?\}", nick_str):
                    new_nick = re.sub(
                        r"\{.*?\}", "{" + prefix + format + "}", nick_str, count=1
                    )
                else:
                    new_nick = nick_str.strip() + " {" + prefix + format + "}"

                if new_nick != nick_str:
                    if len(new_nick) > 32:
                        if raise_on_long_name:
                            raise NicknameTooLong(new_nick)
                    else:
                        try:
                            await nick.set(new_nick)
                        except Exception:
                            logger.exception(
                                f"unable to set nickname for {user} in {guild}"
                            )

        return ilvl, rbg

    # Events

    @event("member_update")
    async def _member_update(self, ctx, old_member: Member, new_member: Member):
        def plays_wow(m):
            try:
                return m.game.name == "World of Warcraft"
            except AttributeError:
                return False

        async def wait_and_fire(id_to_sync):
            logger.debug(
                f"sleeping for 30s before syncing after WoW close of {new_member.name}"
            )
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

                logger.info(
                    f"{new_member.name} stopped playing WoW and needs to be checked"
                )
            finally:
                session.close()

            await self.spawn(wait_and_fire, new_member.user.id)

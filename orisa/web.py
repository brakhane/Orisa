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
import json
import logging
import re

from operator import attrgetter

import asks

from itsdangerous.url_safe import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature, SignatureExpired
from oauthlib.oauth2 import WebApplicationClient
from quart_trio import QuartTrio
from quart import Quart, request, render_template, jsonify, Response

from .config import (
    DEVELOPMENT,
    SIGNING_SECRET,
    OAUTH_BLIZZARD_CLIENT_ID,
    OAUTH_BLIZZARD_CLIENT_SECRET,
    OAUTH_DISCORD_CLIENT_ID,
    OAUTH_DISCORD_CLIENT_SECRET,
    OAUTH_REDIRECT_PATH,
    OAUTH_REDIRECT_HOST,
)
from .config_classes import GuildConfig
from .models import User, GuildConfigJson

logger = logging.getLogger(__name__)

serializer = URLSafeTimedSerializer(SIGNING_SECRET)


TOKEN_MAX_AGE = 1800

app = QuartTrio(__name__)

# HACK: these three are set by Orisa in orisa.py.
send_ch = None
client = None
orisa = None


app.debug = DEVELOPMENT


async def render_message(message, is_error=False):
    return await render_template(
        "message.html",
        message=message,
        classes="bg-danger text-white" if is_error else "bg-success text-white",
    )


def create_token(guild_id):
    return serializer.dumps({"g": guild_id})


from quart import request, jsonify

@app.route("/foo")
async def foo():
    from .models import League, Database


    with Database().session() as s:
        l = s.query(League).offset(1).first()
        return jsonify([{"name": x.Team.name, "points": x.points, "W": x.won, "L": x.lost} for x in l.standings(s)])



@app.route(OAUTH_REDIRECT_PATH + "fetch") #/<string:code>")
async def fetch():
    code = request.args.get('code')
    client = WebApplicationClient(OAUTH_DISCORD_CLIENT_ID)
    url, headers, body = client.prepare_token_request(
        "https://discordapp.com/api/oauth2/token",
        code=code,
        redirect_url="http://localhost:8000/fetch",
        client_secret=OAUTH_DISCORD_CLIENT_SECRET,
        scope=["email", "identify", "guilds"]
    )

    logger.debug(f"got data {(url, headers, body)}")

    resp = await asks.post(
        url,
        headers=headers,
        data=body,
    )

    client.parse_request_body_response(resp.text, scope=["email", "identify", "guilds"])

    logger.debug("token is %s, access token is %s, refresh token is %s", client.token, client.access_token, client.refresh_token)


    url, headers, body = client.add_token("https://discordapp.com/api/v6/users/@me")

    logger.debug((url, headers, body))

    me = (await asks.get(url, headers=headers)).json()


    url, headers, body = client.add_token("https://discordapp.com/api/v6/users/@me/guilds")

    logger.debug((url, headers, body))

    guilds = (await asks.get(url, headers=headers)).json()



    url, headers, body = client.prepare_token_revocation_request("https://discordapp.com/api/oauth2/token/revoke", client.access_token)

    logger.debug((url, headers, body))

    resp = await asks.post(url, headers=headers, data=body)

    logger.debug(f"revoke response is {resp}, {resp.text}")

    #url, headers, body = client.prepare_refresh_token_request("https://discordapp.com/api/oauth2/token", scope=["email", "identify", "guilds"], redirect_uri="http://localhost:8000/fetch", client_id=client.client_id, client_secret=OAUTH_DISCORD_CLIENT_SECRET)

    #logger.debug((url, headers, body))

    #resp = await asks.post(url, headers=headers, data=body)

    #logger.debug(f"refresh response is {resp}, {resp.text}")

    return jsonify({"guilds": guilds, "me": me})



@app.route(OAUTH_REDIRECT_PATH + "config_data/<string:token>")
async def channels(token):
    try:
        state = serializer.loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        return "token expired", 410
    except BadSignature:
        return "invalid token", 404

    guild_id = state["g"]

    guild_info = orisa.guild_config[guild_id]

    guild = client.guilds[guild_id]

    def conv(o):
        return {
            "id": str(o.id),
            "name": o.name,
            "type": o.type,
            "children": [conv(c) for c in o.children if c.type == 0],
        }

    channels = [
        conv(chan)
        for chan in sorted(
            (guild.channels.values()), key=lambda x: (x.type, x.position)
        )
        if not chan.parent
    ]

    roles = [
        role.name for role in sorted(guild.roles.values(), key=attrgetter("position"))
    ]

    return jsonify(
        {
            "channels": channels,
            "guild_name": guild.name,
            "guild_id": str(guild_id),
            "roles": roles,
            "top_role": guild.me.top_role.name,
            "guild_config": guild_info.to_js_json(),
        }
    )


def validate_config(guild, guild_config):
    errors = {}

    def missing_perms(permissions, required):
        def convert_name(name):
            return " ".join(part.capitalize() for part in name.split("_"))

        missing = [
            convert_name(perm) for perm in required if not getattr(permissions, perm)
        ]

        if missing:
            return f"Orisa is missing the following permissions: {', '.join(missing)}"
        else:
            return None

    chan = guild.channels.get(guild_config.listen_channel_id)
    if not chan or chan.type != 0:
        errors["listen_channel_id"] = "Please select a valid text channel"
    else:
        missing = missing_perms(
            chan.effective_permissions(guild.me),
            # we only need to check manage_nicknames once, so we do it here
            [
                "send_messages",
                "read_messages",
                "embed_links",
                "attach_files",
                "manage_nicknames",
            ],
        )
        if missing:
            errors["listen_channel_id"] = missing

    chan = guild.channels.get(guild_config.congrats_channel_id)
    if not chan or chan.type != 0:
        errors["congrats_channel_id"] = "Please select a valid text channel"
    else:
        missing = missing_perms(
            chan.effective_permissions(guild.me),
            ["send_messages", "read_messages", "embed_links", "attach_files"],
        )
        if missing:
            errors["congrats_channel_id"] = missing

    vce_list = []
    vce_list_has_errors = False

    for vc in guild_config.managed_voice_categories:
        vc_errors = {}

        chan = guild.channels.get(vc.category_id)
        if not chan or chan.type != 4:
            vc_errors["category_id"] = "Please select a valid category"
        else:
            missing = missing_perms(
                chan.effective_permissions(guild.me), ["manage_channels"]
            )
            if missing:
                vc_errors["category_id"] = missing

        if vc.channel_limit is None or not (0 <= vc.channel_limit <= 10):
            vc_errors["channel_limit"] = "Limit must be between 0 and 10"

        pe_list = []
        pe_list_has_errors = False
        names = set()
        for prefix in vc.prefixes:
            pref_errors = {}
            if not prefix.name:
                pref_errors["name"] = "A prefix is required"
            elif '#' in prefix.name:
                pref_errors["name"] = "The channel prefix must not contain a #"
            elif prefix.name.strip() in names:
                pref_errors["name"] = "This name is already used in this category"

            names.add(prefix.name.strip())

            if prefix.limit is None or not (0 <= prefix.limit <= 99):
                pref_errors["limit"] = "The limit must be between 0 and 99"

            pe_list.append(pref_errors)

            if pref_errors:
                pe_list_has_errors = True

        if pe_list_has_errors:
            vc_errors["prefixes"] = pe_list

        if vc_errors:
            vce_list_has_errors = True
        vce_list.append(vc_errors)

    if vce_list_has_errors:
        errors["managed_voice_categories"] = vce_list

    return errors


@app.route(OAUTH_REDIRECT_PATH + "guild_config/<int:guild_id>", methods=["PUT"])
async def save(guild_id):

    try:
        token = request.headers["authorization"].split(" ")[1]
    except (KeyError, IndexError):
        return "Authorization missing", 401, {"WWW-Authenticate": "Bearer"}

    try:
        serializer.loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        return "Token expired", 401, {"WWW-Authenticate": "Bearer"}
    except BadSignature:
        return "Invalid token", 401, {"WWW-Authenticate": "Bearer"}

    new_gi = GuildConfig.from_json2(await request.data)
    logger.debug(f"old info: {orisa.guild_config[guild_id]}")
    logger.debug(f"new info: {new_gi}")

    guild = client.guilds[guild_id]

    errors = validate_config(guild, new_gi)

    logger.debug(f"Errors {errors}")
    if errors:
        return jsonify(errors), 400

    orisa.guild_config[guild_id] = new_gi

    with orisa.database.session() as session:

        gc = session.query(GuildConfigJson).filter_by(id=guild_id).one_or_none()
        if not gc:
            gc = GuildConfigJson(id=guild_id)
            session.add(gc)

        new_config = json.dumps(new_gi.to_js_json())
        gc.config = new_config
        logger.info("New config for guild %d is %s", guild_id, new_config)
        session.commit()

    async def update():
        for vc in new_gi.managed_voice_categories:
            await orisa._adjust_voice_channels(
                client.find_channel(vc.category_id), adjust_user_limits=True
            )

        with orisa.database.session() as session:
            for user in (
                session.query(User)
                .filter(User.discord_id.in_(guild.members.keys()))
                .all()
            ):
                try:
                    await orisa._update_nick(user)
                except Exception:
                    logger.error("Exception during update", exc_info=True)

    await orisa.spawn(update)

    return "", 204


@app.route(OAUTH_REDIRECT_PATH)
async def handle_oauth():
    client = WebApplicationClient(OAUTH_BLIZZARD_CLIENT_ID)
    logger.debug(f"got OAuth auth URL {request.url}")

    # we are behind a proxy, and hypercorn doesn't support
    # proxy headers yet, so just fake https to avoid an exception
    request_url = request.url.replace("http:", "https:")

    if "error=access_denied" in request_url:
        return await render_message(
            "You didn't give me permission to access your BattleTag; registration cancelled.",
            is_error=True,
        )
    data = client.parse_request_uri_response(request_url)

    try:
        uid = serializer.loads(data["state"], max_age=600)
    except SignatureExpired:
        return await render_message(
            'The link has expired. Please request a new link with <p class="text-monospace">!ow register</p>',
            is_error=True,
        )
    except BadSignature:
        return await render_message(
            'The data I got back is invalid. Please request a new URL with <p class="text-monospace">!ow register</p>',
            is_error=True,
        )

    try:
        url, headers, body = client.prepare_token_request(
            "https://eu.battle.net/oauth/token",
            authorization_response=request_url,
            scope=[],
            redirect_url=f"{OAUTH_REDIRECT_HOST}{OAUTH_REDIRECT_PATH}",
            client_secret=OAUTH_BLIZZARD_CLIENT_SECRET,
        )

        logger.debug(f"got data {(url, headers, body)}")

        resp = await asks.post(
            url,
            headers=headers,
            data=body,
        )

        client.parse_request_body_response(resp.text, scope=[])

        logger.debug("token is %s", client.token)

        url, headers, body = client.add_token("https://eu.battle.net/oauth/userinfo")

        data = (await asks.get(url, headers=headers)).json()
    except Exception:
        logger.error(
            f"Something went wrong while getting OAuth data for {uid} {request_url}",
            exc_info=True,
        )
        return await render_message(
            'I\'m sorry. Something went wrong on my side. Try to reissue <p class="text-monospace">!ow register</p>',
            is_error=True,
        )
    await send_ch.send((uid, data))

    return await render_message("Thank you! I have sent you a DM.")


if DEVELOPMENT:

    @app.after_request
    async def add_cors(response):
        response.access_control.allow_origin = ["*"]
        response.access_control.allow_headers = ["authorization", "content-type"]
        response.access_control.allow_methods = ["GET", "POST", "PUT"]
        return response

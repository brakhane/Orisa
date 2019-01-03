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
    GUILD_INFOS,
    SIGNING_SECRET,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_REDIRECT_PATH,
    OAUTH_REDIRECT_HOST,
)
from .config_classes import GuildInfo
from .models import (User, GuildConfig)
logger = logging.getLogger(__name__)

serializer = URLSafeTimedSerializer(SIGNING_SECRET)


TOKEN_MAX_AGE = 1800

app = QuartTrio(__name__)

# HACK: these three are set by Orisa in orisa.py.
send_ch = None
client = None
orisa = None


app.debug = True


async def render_message(message, is_error=False):
    return await render_template(
        "message.html",
        message=message,
        classes="bg-danger text-white" if is_error else "bg-success text-white",
    )


def create_token(guild_id):
    return serializer.dumps({"g": guild_id})

@app.route(OAUTH_REDIRECT_PATH + "config_data/<string:token>")
async def channels(token):
    try:
        state = serializer.loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        return "token expired", 404
    except BadSignature:
        return "invalid token", 404

    guild_id = state["g"]

    guild_info = GUILD_INFOS[guild_id]

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
            (guild.channels.values()),
            key=lambda x: (x.type, x.position),
        )
        if not chan.parent
    ]

    return jsonify({
        "channels": channels,
        "guild_name": guild.name,
        "guild_id": str(guild_id),
        "guild_config": guild_info.to_js_json()
    })


def validate_config(guild, guild_config):
    errors = {}

    chan =  guild.channels.get(guild_config.congrats_channel_id)
    if not chan or chan.type != 0:
        errors["congrats_channel_id"] = "Please select a valid text channel"

    chan =  guild.channels.get(guild_config.listen_channel_id)
    if not chan or chan.type != 0:
        errors["listen_channel_id"] = "Please select a valid text channel"

    vce_list = []
    vce_list_has_errors = False

    for vc in guild_config.managed_voice_categories:
        vc_errors = {}

        chan =  guild.channels.get(vc.category_id)
        if not chan or chan.type != 4:
            vc_errors["category_id"] = "Please select a valid category"

        if vc.channel_limit is None or not (0 <= vc.channel_limit <= 10):
            vc_errors["channel_limit"] = "Limit must be between 0 and 10"

        pe_list = []
        pe_list_has_errors = False
        for prefix in vc.prefixes:
            pref_errors = {}
            if not prefix.name:
                pref_errors["name"] = "A prefix is required"
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
    #return {"extra_register_text": "ASDJHASKDJHASLKDJHASDKLJ"}



@app.route(OAUTH_REDIRECT_PATH + "guild_config/<int:guild_id>", methods=["PUT"])
async def save(guild_id):

    try:
        token = request.headers["authorization"].split(" ")[1]
    except (KeyError, IndexError):
        return "Authorization missing", 401, {'WWW-Authenticate': 'Bearer'}

    try:
        serializer.loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        return "Token expired", 401, {'WWW-Authenticate': 'Bearer'}
    except BadSignature:
        return "Invalid token", 401, {'WWW-Authenticate': 'Bearer'}


    new_gi = GuildInfo.from_json2(await request.data)
    logger.debug(f"old info: {GUILD_INFOS[guild_id]}")
    logger.debug(f"new info: {new_gi}")

    guild = client.guilds[guild_id]

    errors = validate_config(guild, new_gi)

    logger.debug(f"Errors {errors}")
    if errors:
        return jsonify(errors), 400

    GUILD_INFOS[guild_id] = new_gi

    with orisa.database.session() as session:

        gc = session.query(GuildConfig).filter_by(id=guild_id).one()
        new_config = json.dumps(new_gi.to_js_json())
        gc.config = new_config
        logger.info("New config for guild %d is %s", guild_id, new_config)
        session.commit()

    async def update():
        for vc in new_gi.managed_voice_categories:
            await orisa._adjust_voice_channels(client.find_channel(vc.category_id))

        with orisa.database.session() as session:
            for user in session.query(User).filter(User.discord_id.in_(guild.members.keys())).all():
                await orisa._update_nick(user)

    await orisa.spawn(update)

    return "", 204


@app.route(OAUTH_REDIRECT_PATH)
async def handle_oauth():
    client = WebApplicationClient(OAUTH_CLIENT_ID)
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
        )

        logger.debug(f"got data {(url, headers, body)}")

        # remove client_id and add scope, blizzard is a little bit picky...
        body = re.sub(r"client_id=.*?&", "scope=&", body)

        resp = await asks.post(
            url,
            headers=headers,
            auth=asks.BasicAuth((OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET)),
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

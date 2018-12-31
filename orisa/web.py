import logging
import re

import asks

from itsdangerous.url_safe import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature, SignatureExpired
from oauthlib.oauth2 import WebApplicationClient
from quart_trio import QuartTrio
from quart import request, render_template

from .config import (
    SIGNING_SECRET,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_REDIRECT_PATH,
    OAUTH_REDIRECT_HOST,
)


logger = logging.getLogger(__name__)

app = QuartTrio(__name__)

send_ch = None

app.debug = False


@app.route(OAUTH_REDIRECT_PATH)
async def handle_oauth():
    client = WebApplicationClient(OAUTH_CLIENT_ID)
    logger.debug(f"got OAuth auth URL {request.url}")

    # we are behind a proxy, and hypercorn doesn't support
    # proxy headers yet, so just fake https to avoid an exception
    request_url = request.url.replace("http:", "https:")

    if "error=access_denied" in request_url:
        return await render_template("message.html", message=
            "You didn't give me permission to access your BattleTag; registration cancelled."
        )
    data = client.parse_request_uri_response(request_url)

    s = URLSafeTimedSerializer(SIGNING_SECRET)

    try:
        uid = s.loads(data["state"], max_age=600)
    except SignatureExpired:
        return await render_template("message.html", message=
            "The link has expired. Please request a new link with <pre>!ow register</pre>"
        )
    except BadSignature:
        return await render_template("message.html", message=
            "The data I got back is invalid. Please request a new URL with <pre>!ow register</pre>"
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
        return await render_template("message.html", message=
            "I'm sorry. Something went wrong on my side. Try to reissue <pre>!ow register</pre>"
        )
    await send_ch.send((uid, data))

    return await render_template("message.html", message="Thank you! I have sent you a DM.")

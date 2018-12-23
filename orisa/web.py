import logging
import re

import asks

from itsdangerous.url_safe import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature, SignatureExpired
from oauthlib.oauth2 import WebApplicationClient
from quart_trio import QuartTrio
from quart import request

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

app.debug = True

@app.route(OAUTH_REDIRECT_PATH)
async def handle_oauth():
    client = WebApplicationClient(OAUTH_CLIENT_ID)
    logger.debug(f"got OAuth auth URL {request.url}")

    # we are behind a proxy, and hypercorn doesn't support
    # proxy headers yet, so just fake https to avoid an exception
    request_url = request.url.replace("http:", "https:")

    data = client.parse_request_uri_response(request_url)

    s = URLSafeTimedSerializer(SIGNING_SECRET)

    try:
        uid = s.loads(data['state'], max_age=600)
    except SignatureExpired:
        return "The data has expired. Please request a new URL with !ow register"
    except BadSignature:
        return "invalid data. Please request a new URL with !ow register"

    url, headers, body = client.prepare_token_request(
        'https://eu.battle.net/oauth/token',
        authorization_response=request_url,
        scope=[],
        redirect_url=f'{OAUTH_REDIRECT_HOST}{OAUTH_REDIRECT_PATH}'
    )

    logger.debug(f"got data {(url, headers, body)}")

    # remove client_id and add scope, blizzard is a little bit picky...
    body = re.sub(r"client_id=.*?&", "scope=&", body)

    resp = (await asks.post(url,
        headers=headers,
        auth=asks.BasicAuth((
            OAUTH_CLIENT_ID,
            OAUTH_CLIENT_SECRET)),
        data=body))

    logger.debug(resp.json())
    logger.debug(client.parse_request_body_response(resp.text, scope=[]))
    logger.debug(client.token)

    url, headers, body = client.add_token('https://eu.battle.net/oauth/userinfo')

    data = (await asks.get(url, headers=headers)).json()
    await send_ch.send((uid, data))

    msg = f"{uid} is {data}. You can now close this window, you should have a DM from Orisa"

    return msg

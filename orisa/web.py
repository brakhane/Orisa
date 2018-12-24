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

app.debug = False


def centered(text):
    return (
        """
<!doctype html>
<html>
  <head>
    <style>
      .center {
          height: 100vh;
          display: flex;
          justify-content: center;
          align-items: center;
      }
    </style>
  </head>
  <body>
    <div class="center">"""
        + text
        + """</div>
  </body>
</html>"""
    )


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
        uid = s.loads(data["state"], max_age=600)
    except SignatureExpired:
        return centered(
            "The link has expired. Please request a new link with <pre>!ow register</pre>"
        )
    except BadSignature:
        return centered(
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

        logger.debug(resp.json())
        logger.debug(client.parse_request_body_response(resp.text, scope=[]))
        logger.debug(client.token)

        url, headers, body = client.add_token("https://eu.battle.net/oauth/userinfo")

        data = (await asks.get(url, headers=headers)).json()
    except Exception:
        logger.error(
            f"Something went wrong while getting OAuth data for {uid} {request_url}",
            exc_info=True,
        )
        return centered(
            "I'm sorry. Something went wrong on my side. Try to reissue !ow register"
        )
    await send_ch.send((uid, data))

    return centered("Thank you! I have sent you a DM. You can now close this window.")

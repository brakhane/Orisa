import logging
import os
import tempfile
import time
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

import httpx
import trio
from hypercorn.config import Config
from hypercorn.trio import serve
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from pydantic import BaseModel, Field, HttpUrl, Json
from rich.pretty import pprint
from starlette.middleware.base import (BaseHTTPMiddleware,
                                       RequestResponseEndpoint)
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.responses import Response as StarletteResponse
from starlite import (NotAuthorizedException, Parameter, Request, Response,
                      Starlite, post)
from starlite.types import ASGIApp, Receive, Scope, Send
from contextlib import suppress

logger = logging.getLogger(__name__)

class SignatureCheck(BaseHTTPMiddleware):

    verify_key = VerifyKey(
        bytes.fromhex(
            "4b75f796994b235b727a28dc2d8d571d9840d85782ea4952de77d27fc448bcfd"
        )
    )

    async def dispatch(
        self, request: StarletteRequest, call_next: RequestResponseEndpoint
    ) -> StarletteResponse:
        #body = await request.body()
        #timestamp = request.headers.get("X-Signature-Timestamp")
        #ed25519 = request.headers.get("X-Signature-Ed25519")
        #if timestamp is None or ed25519 is None:
        #    return StarletteResponse('Missing signature', status_code=401)
        try:
            pass #self.verify_key.verify('{timestamp}{body}'.encode(), bytes.fromhex(ed25519))
        except BadSignatureError:
            return StarletteResponse('Invalid signature', status_code=401)
        else:
            return (await call_next(request))




Snowflake = Union[int, str]


class Interaction(BaseModel):
    id: Snowflake
    application_id: Snowflake
    guild_id: Optional[Snowflake]
    channel_id: Optional[Snowflake]
    member: Optional["Member"]
    user: Optional["User"]
    token: str
    version: Literal[1]
    #    message: Message
    app_permissions: Optional[str]
    locale: Optional[str]
    guild_locale: Optional[str]


class Member(BaseModel):
    user: Optional["User"]
    nick: Optional[str]

class User(BaseModel):
    id: Snowflake
    username: str
    discriminator: str

class PingInteraction(Interaction):
    type: Literal[1]


class CommandInteraction(Interaction):
    type: Literal[2]
    data: "CommandInteractionData"


class InteractionType(Enum):
    PING = 1
    APPLICATION_COMMAND = 2
    MESSAGE_COMPONENT = 3
    APPLICATION_COMMAND_AUTOCOMPLETE = 4
    MODAL_SUBMIT = 5


class CommandInteractionData(BaseModel):
    id: Snowflake
    name: str
    type: int
    resolved: Optional["Resolved"]
    options: Optional[list["CommandDataOption"]]
    guild_id: Optional[Snowflake]
    target_id: Optional[Snowflake]


class Resolved(BaseModel):
    attachments: Optional[dict[Snowflake, "Attachment"]]


class Attachment(BaseModel):
    id: Snowflake
    filename: str
    description: Optional[str]
    content_type: Optional[str]
    size: int
    url: HttpUrl
    proxy_url: HttpUrl
    height: Optional[int]
    width: Optional[int]
    ephermeral: Optional[bool]


class CommandDataOption(BaseModel):
    name: str
    type: int
    value: Optional[Union[str, int, float]]
    # options
    focused: Optional[bool]


IncomingInteraction = Annotated[
    Union[PingInteraction, CommandInteraction], Field(discriminator="type")
]


VERIFY_KEY = VerifyKey(
    bytes.fromhex(
        "4b75f796994b235b727a28dc2d8d571d9840d85782ea4952de77d27fc448bcfd"
    )
)

APPID = 445905377712930817

RATELIMIT_LOCK = trio.Lock()
RATELIMIT_REMAINING: int = 0
RATELIMIT_RESET: float = 0

async def process(ci: CommandInteraction):
    global RATELIMIT_REMAINING
    global RATELIMIT_RESET
    async with httpx.AsyncClient() as client:
        try:
            with tempfile.TemporaryFile(prefix="submit-") as tmpf:

                attachment = ci.data.resolved.attachments[int(ci.data.options[0].value)]



                async with client.stream(
                    "GET",
                    attachment.url
                ) as r:
                    async for d in r.aiter_bytes():
                        tmpf.write(d)

                await RATELIMIT_LOCK.acquire()

                holding_lock = True

                if RATELIMIT_REMAINING == 0:
                    to_wait = RATELIMIT_RESET - time.time()
                    print(f"Waiting for ratelimit {to_wait}s")
                    if to_wait >= 0:
                        await trio.sleep(to_wait)
                    else:
                        holding_lock = False
                        RATELIMIT_LOCK.release()

                tmpf.seek(0)

                resp = await client.post(
                    "https://discord.com/api/v10/channels/1028413925307465748/messages",
                    headers={
                        "Authorization": f"Bot {os.environ['BOT_TOKEN']}"
                    },
                    data={
                        "content": f"{ci.member.user.username}#{ci.member.user.discriminator} uploaded"
                    },
                    files={'files[0]': (attachment.filename, tmpf.read(), attachment.content_type)}
                )

                if not holding_lock:
                    await RATELIMIT_LOCK.acquire()

                rem = int(resp.headers['x-ratelimit-remaining'])
                res = float(resp.headers['x-ratelimit-reset'])
                if res > RATELIMIT_RESET:
                    RATELIMIT_RESET = res
                    RATELIMIT_REMAINING = rem
                elif rem < RATELIMIT_REMAINING:
                    RATELIMIT_REMAINING = rem

                RATELIMIT_LOCK.release()

            if resp.is_success:
                msg = "Screenshot received! Thank you for your compliance!"
            else:
                msg = f"Something went wrong, please try again later. (code {resp.status_code})"
            
            await client.patch(
                f"https://discord.com/api/v10/webhooks/{APPID}/{ci.token}/messages/@original",
                headers={
                    "Authorization": f"Bot {os.environ['BOT_TOKEN']}"
                },
                json={
                    "content": msg,
                    "flags": 64,
                }
            )
        except Exception:
            logger.exception("Something bad happened")
            with suppress(Exception):
                await client.patch(
                    f"https://discord.com/api/v10/webhooks/{APPID}/{ci.token}/messages/@original",
                    headers={
                        "Authorization": f"Bot {os.environ['BOT_TOKEN']}"
                    },
                        json={
                        "content": "Sorry, something unexpected happened (damn you, Sombra!) please try again later!",
                        "flags": 64,
                    }
                )

NURSERY: trio.Nursery

@post("/")
async def discord(
    data: IncomingInteraction,
    request: Request,
    ed25519: str=Parameter(header="X-Signature-Ed25519"),
    timestamp: str=Parameter(header="X-Signature-Timestamp"),
) -> dict[str, Any]|Response:
    pprint(type(data))
    pprint(data)
    body = (await request.body()).decode()
    try:
        VERIFY_KEY.verify(f'{timestamp}{body}'.encode(), bytes.fromhex(ed25519))
    except BadSignatureError:
        raise NotAuthorizedException("Invalid signature")


    if isinstance(data, PingInteraction):
        return {"type": 1}
    elif isinstance(data, CommandInteraction):
        NURSERY.start_soon(process, data)
        return {
            "type": 5,
            "data": {
                "flags": 64,
            }
        }
    else:
        return Response("unknown type", status_code=400, media_type="text/plain")


Member.update_forward_refs()
Interaction.update_forward_refs()
PingInteraction.update_forward_refs()
CommandInteraction.update_forward_refs()
CommandInteractionData.update_forward_refs()
Resolved.update_forward_refs()
Attachment.update_forward_refs()

app = Starlite(route_handlers=[discord], middleware=[SignatureCheck])

async def boot():
    global NURSERY
    hc = Config.from_mapping({
        'bind': '127.0.0.1:8000',
    })
    async with trio.open_nursery() as nursery:
        NURSERY = nursery
        nursery.start_soon(serve, app, hc)

if __name__ == "__main__":
    logging.basicConfig()
    trio.run(boot)
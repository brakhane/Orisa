from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, Field, HttpUrl, Json
from enum import Enum

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
    ephemeral: Optional[bool]


class CommandDataOption(BaseModel):
    name: str
    type: int
    value: Optional[Union[str, int, float]]
    # options
    focused: Optional[bool]


IncomingInteraction = Annotated[
    Union[PingInteraction, CommandInteraction], Field(discriminator="type")
]

Member.update_forward_refs()
Interaction.update_forward_refs()
PingInteraction.update_forward_refs()
CommandInteraction.update_forward_refs()
CommandInteractionData.update_forward_refs()
Resolved.update_forward_refs()
Attachment.update_forward_refs()

APPID = 445905377712930817

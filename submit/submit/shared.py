from enum import IntEnum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, HttpUrl, Json
from starlite.types import Message

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
    user: "User"  # only missing in MESSAGE_CREATE/MESSAGE_UPDATE
    nick: Optional[str]


class User(BaseModel):
    id: Snowflake
    username: str
    discriminator: str


class InteractionType(IntEnum):
    PING = 1
    APPLICATION_COMMAND = 2
    MESSAGE_COMPONENT = 3
    APPLICATION_COMMAND_AUTOCOMPLETE = 4
    MODAL_SUBMIT = 5


class PingInteraction(Interaction):
    type: Literal[InteractionType.PING]


class CommandInteraction(Interaction):
    type: Literal[InteractionType.APPLICATION_COMMAND]
    data: "CommandInteractionData"


class CommandInteractionData(BaseModel):
    id: Snowflake
    name: str
    type: int
    resolved: Optional["Resolved"]
    options: Optional[list["CommandDataOption"]]
    guild_id: Optional[Snowflake]
    target_id: Optional[Snowflake]


class MessageComponentInteraction(Interaction):
    type: Literal[InteractionType.MESSAGE_COMPONENT]
    data: "MessageComponentInteractionData"


class MessageComponentInteractionData(BaseModel):
    custom_id: str
    component_type: "ComponentType"
    values: Optional[list["SelectOption"]]


class ComponentType(IntEnum):
    ACTION_ROW = 1
    BUTTON = 2
    STRING_SELECT = 3
    TEXT_INPUT = 4
    USER_SELECT = 5
    ROLE_SELECT = 6
    MENTIONABLE_SELECT = 7
    CHANNEL_SELECT = 8


class SelectOption(BaseModel):
    label: str
    value: str
    description: Optional[str]
    # emoji
    default: Optional[bool]


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
    options: Optional[list["CommandDataOption"]]
    focused: Optional[bool]


IncomingInteraction = Annotated[
    Union[PingInteraction, CommandInteraction, MessageComponentInteraction],
    Field(discriminator="type"),
]

Member.update_forward_refs()
Interaction.update_forward_refs()
PingInteraction.update_forward_refs()
CommandInteraction.update_forward_refs()
CommandInteractionData.update_forward_refs()
Resolved.update_forward_refs()
Attachment.update_forward_refs()
MessageComponentInteraction.update_forward_refs()
MessageComponentInteractionData.update_forward_refs()

APPID = 445905377712930817

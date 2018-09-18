__all__ = ["GuildInfo", "VoiceCategoryInfo"]

from dataclasses import dataclass, field
from typing import List, Set, Optional, Union, Dict

@dataclass
class GuildInfo:
    congrats_channel_id: int
    listen_channel_id: int
    managed_voice_categories: List["VoiceCategoryInfo"]
    extra_register_text: str
    wow_admin_role_name: str
    wow_guild_realm: Optional[str]
    wow_guild_name: Optional[str]
    wow_gm_ranks: Set[int]
    wow_officer_ranks: Set[int]
    wow_listen_channel_id: int

@dataclass
class VoiceCategoryInfo:
    # the ID of the voice channel category
    category_id: int
    # the maximum amount of channels that should
    # be created per prefix
    channel_limit: int
    # should unknown managed channels be removed?
    # a channel is considered managed if
    # it is a child of the category and contains a #
    remove_unknown: bool
    # a list of prefix strings, or a dict
    # {"QP": 0, "Comp": 6} would mean that
    # Orisa should ensure that at least one empty
    # QP and Comp channel exists, up to channel_limit
    # Also, the created comp channels should only allow
    # 6 people
    prefixes: Union[List[str], Dict[str, int]]

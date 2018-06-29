__all__ = ["GuildInfo", "VoiceCategoryInfo"]

from dataclasses import dataclass, field
from typing import List, Set, Optional, Union, Dict

@dataclass
class GuildInfo:
    congrats_channel_id: int
    listen_channel_id: int
    managed_voice_categories: List["VoiceCategoryInfo"]
    wow_admin_role_name: str
    wow_guild_realm: Optional[str]
    wow_guild_name: Optional[str]
    wow_gm_ranks: Set[int]
    wow_officer_ranks: Set[int]
    wow_listen_channel_id: int

@dataclass
class VoiceCategoryInfo:
    category_id: int
    channel_limit: int
    prefixes: Union[List[str], Dict[str, int]]

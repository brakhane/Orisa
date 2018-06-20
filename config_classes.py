from dataclasses import dataclass, field
from typing import List, Set, Optional

__all__ = ["GuildInfo"]

@dataclass
class GuildInfo:
    congrats_channel_id: int
    listen_channel_id: int
    voice_channel_ids: List[int]
    wow_admin_role_name: str
    wow_guild_realm: Optional[str]
    wow_guild_name: Optional[str]
    wow_gm_ranks: Set[int]
    wow_officer_ranks: Set[int]
    wow_listen_channel_id: int

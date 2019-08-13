# Orisa, a simple Discord bot with good intentions
# Copyright (C) 2018, 2019 Dennis Brakhane
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, version 3 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from __future__ import annotations

__all__ = ["GuildConfig", "VoiceCategoryInfo", "PrefixConfig"]

import json
import typing

from dataclasses_json import dataclass_json
from dataclasses import dataclass, fields, is_dataclass, asdict
from typing import List, Set, Optional, Sequence, Union, Dict


@dataclass_json
@dataclass
class GuildConfig:
    show_sr_in_nicks_by_default: bool
    post_highscores: bool
    congrats_channel_id: int
    listen_channel_id: int
    managed_voice_categories: Sequence[VoiceCategoryInfo]
    extra_register_text: str

    @classmethod
    def default(cls):
        return cls(
            show_sr_in_nicks_by_default=True,
            post_highscores=True,
            congrats_channel_id=None,
            listen_channel_id=None,
            extra_register_text=None,
            managed_voice_categories=[],
        )

    def to_js_json(self):
        def id_to_str(data):
            def convert(key, value):
                if value is None:
                    return None
                if isinstance(value, dict):
                    return id_to_str(value)
                if isinstance(value, list):
                    return [id_to_str(item) for item in value]
                elif key.endswith("_id"):
                    return str(value)
                else:
                    return value

            return {k: convert(k, v) for k, v in data.items()}

        # reading the converted JSON into a dict, modifying it and then creating another JSON from that dict
        # is not the most efficient way to get it done, but the data is so small
        # that it isn't worth the effort optimizing it

        # to_json is added by @dataclass_json
        converted = id_to_str(json.loads(self.to_json()))
        return converted
        # return json.dumps(converted, separators=(",", ":"))

    @classmethod
    def from_json2(cls, json_str):
        def create_instance(cls, data):
            init = {}
            for name, type in typing.get_type_hints(cls).items():
                if hasattr(type, "__origin__") and issubclass(
                    type.__origin__, typing.Sequence
                ):
                    elem_type = type.__args__[0]
                    if is_dataclass(elem_type):
                        init[name] = [
                            create_instance(elem_type, init) for init in data[name]
                        ]
                    else:
                        init[name] = [elem_type(init) for init in data[name]]
                elif is_dataclass(type):
                    init[name] = type(**data[name])
                else:
                    try:
                        init[name] = None if data[name] is None else type(data[name])
                    except ValueError:
                        init[name] = None
            return cls(**init)

        return create_instance(cls, json.loads(json_str))


@dataclass_json
@dataclass
class PrefixConfig:
    name: str
    limit: int


@dataclass_json
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
    prefixes: Sequence[PrefixConfig]
    # Should a members nick be updated to show
    # the SR/rank when in this category,
    # even when change_nicks_by_default is False?
    show_sr_in_nicks: bool

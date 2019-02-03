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
class InvalidBattleTag(RuntimeError):
    def __init__(self, message):
        self.message = message


class BlizzardError(RuntimeError):
    pass


class UnableToFindSR(RuntimeError):
    pass


class NicknameTooLong(RuntimeError):
    def __init__(self, nickname):
        self.nickname = nickname


class InvalidFormat(RuntimeError):
    def __init__(self, key):
        self.key = key


class ValidationError(ValueError):
    def __init__(self, field, message):
        self.field = field
        self.message = message

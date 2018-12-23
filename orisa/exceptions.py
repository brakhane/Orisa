class InvalidBattleTag(Exception):
    def __init__(self, message):
        self.message = message

class BlizzardError(RuntimeError):
    pass

class UnableToFindSR(Exception):
    pass


class NicknameTooLong(Exception):
    def __init__(self, nickname):
        self.nickname = nickname


class InvalidFormat(Exception):
    def __init__(self, key):
        self.key = key

class InvalidCharacterName(RuntimeError):
    def __init__(self, realm: str, name: str):
        self.realm = realm
        self.name = name




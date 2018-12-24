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

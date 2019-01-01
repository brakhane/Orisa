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

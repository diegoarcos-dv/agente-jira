class VoiceCommandError(RuntimeError):
    """Base error safe to expose to the authenticated local user."""


class VoiceUnavailableError(VoiceCommandError):
    pass


class VoiceInputError(VoiceCommandError):
    pass


class VoiceTimeoutError(VoiceCommandError):
    pass


class VoiceTTSUnavailableError(VoiceCommandError):
    pass

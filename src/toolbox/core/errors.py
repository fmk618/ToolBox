class ToolboxError(Exception):
    pass


class UnknownFormatError(ToolboxError):
    pass


class NoConversionPathError(ToolboxError):
    pass


class EngineNotAvailableError(ToolboxError):
    pass


class ConversionFailedError(ToolboxError):
    pass

class ToolboxError(Exception):
    """Base class for business errors.

    `status_code` maps each subclass to the HTTP status returned by the
    global exception handler in `toolbox.api`.
    """

    status_code = 400


class UnknownFormatError(ToolboxError):
    status_code = 415


class NoConversionPathError(ToolboxError):
    status_code = 422


class EngineNotAvailableError(ToolboxError):
    status_code = 503


class ConversionFailedError(ToolboxError):
    status_code = 400


class MediaValidationError(ToolboxError):
    status_code = 422


class MediaUnavailableError(ToolboxError):
    status_code = 503


class MediaProcessingError(ToolboxError):
    status_code = 400

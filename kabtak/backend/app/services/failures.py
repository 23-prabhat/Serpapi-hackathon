"""Safe, stable processing failures exposed through persisted run state."""


class ProcessingError(RuntimeError):
    def __init__(
        self,
        code: str,
        public_message: str,
        *,
        retryable: bool,
        diagnostic: str | None = None,
    ) -> None:
        super().__init__(diagnostic or public_message)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable


class SourceUnavailableError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "SOURCE_UNAVAILABLE",
            "The source is temporarily unavailable. Try the check again later.",
            retryable=True,
            diagnostic=diagnostic,
        )


class IrrelevantSourceError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "SOURCE_SCOPE_MISMATCH",
            "The source did not establish a deadline for the requested programme cycle.",
            retryable=False,
            diagnostic=diagnostic,
        )


class UnsupportedSourceError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "UNSUPPORTED_SOURCE_FORMAT",
            "The source uses a format that Kabtak cannot safely process.",
            retryable=False,
            diagnostic=diagnostic,
        )


class UnsafeSourceURLError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "UNSAFE_SOURCE_URL",
            "This source link cannot be retrieved safely. Use a direct public publisher URL.",
            retryable=False,
            diagnostic=diagnostic,
        )


class UnsupportedPDFError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "UNSUPPORTED_PDF",
            "The PDF is scanned, encrypted, or could not be parsed safely.",
            retryable=False,
            diagnostic=diagnostic,
        )


class ParsingFailedError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "PARSING_FAILED",
            "The source could not be converted into reliable evidence blocks.",
            retryable=False,
            diagnostic=diagnostic,
        )


class InvalidExtractionError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "INVALID_EXTRACTION",
            "The extracted facts could not be validated against the preserved evidence.",
            retryable=True,
            diagnostic=diagnostic,
        )


class ExtractionUnavailableError(ProcessingError):
    def __init__(self, diagnostic: str | None = None) -> None:
        super().__init__(
            "EXTRACTION_UNAVAILABLE",
            "The extraction service is temporarily unavailable. Try the check again later.",
            retryable=True,
            diagnostic=diagnostic,
        )

"""Exception hierarchy. Every failure the CLI reports inherits from SubleaseError."""


class SubleaseError(Exception):
    """Base for every error this package raises deliberately."""


class ConfigError(SubleaseError):
    """The user's profile or environment is missing or invalid."""


class StoreError(SubleaseError):
    """The database could not be opened, migrated, or written."""


class SourceError(SubleaseError):
    """A platform source failed to fetch. Never fatal to a run."""


class ProviderError(SubleaseError):
    """An LLM provider was unreachable or returned unusable output."""

class ESGError(Exception):
    def __init__(self, msg: str, source: str = ""):
        super().__init__(f"[{source}] {msg}" if source else msg)
        self.source = source

class FeedFetchError(ESGError):
    """network or HTTP failure fetching a feed"""

class FeedParseError(ESGError):
    """feed returned nothing parseable"""

class BrowserError(ESGError):
    """playwright / chromium failed to load a page"""

class ClassifierError(ESGError):
    """model load or inference failure"""

class StorageError(ESGError):
    """database read/write failure"""

class ConfigError(ESGError):
    """missing env var or bad config"""

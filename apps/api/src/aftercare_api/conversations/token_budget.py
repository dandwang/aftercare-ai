"""Explicit local token accounting for the deterministic demo prompt."""

from functools import lru_cache
from importlib.metadata import version

import tiktoken


class ContextBudgetError(Exception):
    """Raised when the current input or required facts cannot fit the budget."""


class TokenMeter:
    def __init__(self, encoding_name: str):
        self.name = encoding_name
        self.version = version("tiktoken")
        self.encoding = tiktoken.get_encoding(encoding_name)

    def count(self, content: str) -> int:
        return len(self.encoding.encode(content, disallowed_special=()))

    def limit(self, content: str, budget: int) -> str:
        tokens = self.encoding.encode(content, disallowed_special=())
        prefix = self.encoding.decode_bytes(tokens[:budget]).decode("utf-8", errors="ignore")
        while self.count(prefix) > budget:
            prefix = prefix[:-1]
        return prefix


@lru_cache
def get_token_meter(encoding_name: str = "cl100k_base") -> TokenMeter:
    return TokenMeter(encoding_name)

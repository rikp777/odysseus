"""Shared billing provider contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Dict


ProviderFetch = Callable[[str], Dict[str, Any]]
ProviderNormalize = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class BillingProvider:
    id: str
    label: str
    short_label: str
    token_hint: str
    fetch: ProviderFetch
    normalize: ProviderNormalize

    def with_fetch(self, fetch: ProviderFetch) -> "BillingProvider":
        return replace(self, fetch=fetch)

    def with_normalize(self, normalize: ProviderNormalize) -> "BillingProvider":
        return replace(self, normalize=normalize)

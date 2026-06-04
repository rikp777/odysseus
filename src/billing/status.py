"""Monthly billing status orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, MutableMapping, Optional

from src.billing.common import decimal_or_zero, money, utc_now_iso
from src.billing.diagnostics import attach_billing_diagnostics


SettingsLoader = Callable[[], Dict[str, Any]]
AccountLoader = Callable[[Dict[str, Any]], list[Dict[str, Any]]]
ProviderNormalizer = Callable[[Any], str]
ProviderMeta = Callable[[str], Dict[str, str]]
SecretDecryptor = Callable[[str], str]
Fingerprint = Callable[[str], str]
PayloadFactory = Callable[..., Dict[str, Any]]
AccountSpendFetcher = Callable[..., Dict[str, Any]]
PrimarySpendSelector = Callable[..., Dict[str, Any]]


@dataclass
class BillingStatusService:
    """Builds the monthly billing status payload from settings and providers."""

    cache: MutableMapping[str, Any]
    load_settings: SettingsLoader
    billing_accounts: AccountLoader
    normalized_provider: ProviderNormalizer
    provider_meta: ProviderMeta
    decrypt_secret: SecretDecryptor
    token_fingerprint: Fingerprint
    empty_payload: PayloadFactory
    local_only_payload: PayloadFactory
    attach_local_usage: Callable[[Dict[str, Any]], Dict[str, Any]]
    fetch_account_spend: AccountSpendFetcher
    apply_primary_spend_source: PrimarySpendSelector
    clamp_refresh_seconds: Callable[[Any], int]

    def _with_diagnostics(self, payload: Dict[str, Any], *, cache_age_seconds: int = 0) -> Dict[str, Any]:
        return attach_billing_diagnostics(payload, cache_age_seconds=cache_age_seconds)

    def monthly_spend_status(
        self,
        *,
        refresh: bool = False,
        forced_provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        settings = self.load_settings()
        enabled = bool(settings.get("cloud_billing_enabled"))
        refresh_seconds = self.clamp_refresh_seconds(settings.get("cloud_billing_refresh_seconds"))
        warning_raw = str(settings.get("cloud_billing_monthly_warning_usd") or "").strip()
        warning = decimal_or_zero(warning_raw) if warning_raw else None
        warning_usd = money(warning) if warning is not None else None
        limit_raw = str(settings.get("cloud_billing_monthly_limit_usd") or "").strip()
        limit = decimal_or_zero(limit_raw) if limit_raw else None
        limit_usd = money(limit) if limit is not None else None
        accounts = self.billing_accounts(settings)
        if forced_provider:
            wanted = self.normalized_provider(forced_provider)
            accounts = [account for account in accounts if account["provider"] == wanted]

        visible_accounts = [account for account in accounts if account.get("enabled", True)]
        account_summaries = [
            {
                "account_id": account["id"],
                "account_label": account["label"],
                **self.provider_meta(account["provider"]),
                "enabled": bool(account.get("enabled", True)),
                "configured": bool(str(account.get("api_token") or "").strip()),
            }
            for account in accounts
        ]

        if not enabled:
            return self._with_diagnostics(self.attach_local_usage(self.empty_payload(
                enabled=False,
                configured=any(item["configured"] for item in account_summaries),
                warning_usd=warning_usd,
                limit_usd=limit_usd,
                refresh_seconds=refresh_seconds,
                status="disabled",
                error="Cloud billing display is disabled",
                accounts=account_summaries,
            )))

        if not visible_accounts:
            if not forced_provider and settings.get("cloud_billing_usage_ledger_enabled") is not False:
                return self._with_diagnostics(self.local_only_payload(
                    period="month",
                    warning_usd=warning_usd,
                    limit_usd=limit_usd,
                    refresh_seconds=refresh_seconds,
                ))
            return self._with_diagnostics(self.attach_local_usage(self.empty_payload(
                enabled=True,
                configured=False,
                warning_usd=warning_usd,
                limit_usd=limit_usd,
                refresh_seconds=refresh_seconds,
                status="missing_account",
                error="No enabled cloud billing accounts are configured",
                accounts=account_summaries,
            )))

        fingerprint_parts = [
            str(enabled),
            warning_usd or "",
            limit_usd or "",
            str(refresh_seconds),
            forced_provider or "",
        ]
        for account in visible_accounts:
            fingerprint_parts.extend([
                account["id"],
                account["provider"],
                account["label"],
                self.decrypt_secret(str(account.get("api_token") or "").strip()),
            ])
        fingerprint = self.token_fingerprint("\n".join(fingerprint_parts))
        now = time.time()
        if (
            not refresh
            and self.cache.get("fingerprint") == fingerprint
            and self.cache.get("payload")
            and float(self.cache.get("expires_at") or 0) > now
        ):
            expires_at = float(self.cache.get("expires_at") or 0)
            cached_at = max(0.0, expires_at - refresh_seconds)
            cache_age_seconds = max(0, int(now - cached_at)) if cached_at else 0
            payload = dict(self.cache["payload"])
            payload["accounts"] = [dict(item) for item in payload.get("accounts", [])]
            payload["cached"] = True
            self.attach_local_usage(payload)
            return self._with_diagnostics(self.apply_primary_spend_source(
                payload,
                settings=settings,
                warning=warning,
                limit=limit,
                forced_provider=forced_provider,
            ), cache_age_seconds=cache_age_seconds)

        account_results = [
            self.fetch_account_spend(
                account,
                warning=warning,
                warning_usd=warning_usd,
                refresh_seconds=refresh_seconds,
            )
            for account in visible_accounts
        ]
        account_total = sum(
            (
                decimal_or_zero(item.get("amount"))
                for item in account_results
                if item.get("ok") and item.get("amount_scope", "provider_account") == "provider_account"
            ),
            Decimal("0"),
        )
        configured = any(item.get("configured") for item in account_results)
        any_errors = any(not item.get("ok") for item in account_results)
        any_success = any(item.get("ok") for item in account_results)
        has_account_total = any(
            item.get("ok") and item.get("amount_scope", "provider_account") == "provider_account"
            for item in account_results
        )
        amount_scope = "provider_account" if has_account_total else "model_usage"

        if not configured:
            status = "missing_token"
            error = "No enabled cloud billing accounts have a billing token"
        elif any_errors and any_success:
            status = "partial_error"
            error = "One or more cloud billing providers could not be refreshed"
        elif any_errors:
            status = "provider_error"
            error = "Cloud billing providers could not be refreshed"
        else:
            status = "ok"
            error = ""

        provider_payload = {
            "ok": status == "ok",
            "enabled": True,
            "configured": configured,
            "status": status,
            "error": error,
            "currency": "USD",
            "amount": money(account_total) if any_success else None,
            "display": f"${money(account_total)}" if any_success else "",
            "amount_scope": amount_scope,
            "warning_usd": warning_usd,
            "limit_usd": limit_usd,
            "over_warning": bool(warning is not None and has_account_total and account_total >= warning),
            "over_limit": bool(limit is not None and has_account_total and account_total >= limit),
            "limit_check_blocked": bool(limit is not None and configured and not any_success),
            "refresh_seconds": refresh_seconds,
            "updated_at": utc_now_iso(),
            "cached": False,
            "provider": "multiple",
            "provider_label": "Cloud",
            "provider_short_label": (
                "ALL"
                if len(visible_accounts) > 1
                else (account_results[0].get("provider_short_label") if account_results else "ALL")
            ),
            "provider_token_hint": "Provider billing API token",
            "accounts": account_results,
        }
        payload = dict(provider_payload)
        payload["accounts"] = [dict(item) for item in account_results]
        self.attach_local_usage(payload)
        payload = self.apply_primary_spend_source(
            payload,
            settings=settings,
            warning=warning,
            limit=limit,
            forced_provider=forced_provider,
        )
        self.cache.update({
            "fingerprint": fingerprint,
            "expires_at": now + refresh_seconds,
            "payload": provider_payload,
        })
        return self._with_diagnostics(payload)

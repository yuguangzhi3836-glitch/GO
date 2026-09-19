from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

from sqlalchemy import select

from go_hotel.db.models import ProfileImportJobRow
from go_hotel.db.session import SessionLocal
from go_hotel.security.external_navigation import validate_external_navigation_url


def _utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ConsumerOtaComparisonService:
    """Build consumer-specific OTA choices without inventing member prices.

    An account link and a provider-hosted login deep link are discovery
    capabilities. Neither is price evidence. Only a fresh quote returned by an
    official adapter for this exact user and comparison basis is price-rankable.
    """

    MAX_QUOTE_AGE_SECONDS = 300
    PROVIDERS = {
        "CTRIP": {"label": "携程", "env": "GO_CTRIP_CONSUMER_DEEP_LINK", "schemes": {"ctrip", "trip"}, "domains": {"ctrip.com", "trip.com"}},
        "MEITUAN": {"label": "美团", "env": "GO_MEITUAN_CONSUMER_DEEP_LINK", "schemes": {"imeituan", "meituan"}, "domains": {"meituan.com"}},
        "FLIGGY": {"label": "飞猪", "env": "GO_FLIGGY_CONSUMER_DEEP_LINK", "schemes": {"fliggy"}, "domains": {"fliggy.com"}},
        "BOOKING": {"label": "Booking.com", "env": "GO_BOOKING_CONSUMER_DEEP_LINK", "schemes": {"booking"}, "domains": {"booking.com"}},
    }
    REQUIRED_DEEP_LINK_FIELDS = {"checkin", "checkout", "rooms", "adults", "children"}

    @staticmethod
    def _basis(search: dict) -> dict:
        basis = {
            "city_code": str(search.get("city_code") or "").upper(),
            "hotel_id": str(search.get("hotel_id") or ""),
            "check_in": str(search.get("check_in") or ""),
            "check_out": str(search.get("check_out") or ""),
            "rooms": search.get("rooms", 1),
            "adults": search.get("adults", 2),
            "children": search.get("children", 0),
            "currency": str(search.get("currency") or "CNY").upper(),
            "price_basis": "STAY_TOTAL",
            "tax_fee_basis": "INCLUDES_MANDATORY_TAXES_AND_FEES",
        }
        try:
            check_in = datetime.fromisoformat(basis["check_in"]).date()
            check_out = datetime.fromisoformat(basis["check_out"]).date()
            occupancy_valid = (
                type(basis["rooms"]) is int and basis["rooms"] > 0
                and type(basis["adults"]) is int and basis["adults"] > 0
                and type(basis["children"]) is int and basis["children"] >= 0
            )
            if not basis["city_code"] or check_out <= check_in or not occupancy_valid or len(basis["currency"]) != 3:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("INVALID_OTA_COMPARISON_BASIS")
        encoded = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return basis | {"fingerprint": hashlib.sha256(encoded).hexdigest()}

    @classmethod
    def _official_deep_link(cls, provider: str, template: str | None, params: dict) -> tuple[str | None, str]:
        if not template:
            return None, "NOT_CONFIGURED"
        if any("{" + field + "}" not in template for field in cls.REQUIRED_DEEP_LINK_FIELDS):
            return None, "SUPPRESSED_INCOMPLETE_SEARCH_BASIS"
        parsed = urlparse(template)
        spec = cls.PROVIDERS[provider]
        if parsed.scheme == "https":
            host = (parsed.hostname or "").lower()
            valid = any(host == domain or host.endswith("." + domain) for domain in spec["domains"])
        else:
            valid = parsed.scheme.lower() in spec["schemes"]
        if not valid:
            return None, "SUPPRESSED_UNVERIFIED_PROVIDER_DESTINATION"
        deep_link = template
        for key, value in params.items():
            deep_link = deep_link.replace("{" + key + "}", quote_plus(str(value)))
        try:
            deep_link = validate_external_navigation_url(deep_link, allowed_custom_schemes=spec["schemes"])
        except ValueError:
            return None, "SUPPRESSED_UNSAFE_PROVIDER_DESTINATION"
        return deep_link, "OFFICIAL_PROVIDER_DESTINATION"

    @staticmethod
    def _quote_reasons(provider: str, quote: dict, user_id: str, basis: dict, now: datetime) -> list[str]:
        reasons = []
        if quote.get("provider") != provider:
            reasons.append("PROVIDER_IDENTITY_MISMATCH")
        if quote.get("verification_source") != "OFFICIAL_PROVIDER_ADAPTER":
            reasons.append("OFFICIAL_ADAPTER_VERIFICATION_REQUIRED")
        if quote.get("verified_for_user_id") != user_id or quote.get("account_holder_authorized") is not True:
            reasons.append("CURRENT_CONSUMER_VERIFICATION_REQUIRED")
        if not quote.get("provider_quote_id"):
            reasons.append("PROVIDER_QUOTE_ID_REQUIRED")
        if not basis["hotel_id"] or not quote.get("hotel_id"):
            reasons.append("HOTEL_ID_REQUIRED_FOR_PRICE_COMPARISON")
        amount = quote.get("total_amount_minor")
        if type(amount) is not int or amount <= 0:
            reasons.append("VALID_TOTAL_AMOUNT_REQUIRED")
        quote_basis = {
            "city_code": str(quote.get("city_code") or "").upper(),
            "hotel_id": str(quote.get("hotel_id") or ""),
            "check_in": str(quote.get("check_in") or ""),
            "check_out": str(quote.get("check_out") or ""),
            "rooms": quote.get("rooms"),
            "adults": quote.get("adults"),
            "children": quote.get("children"),
            "currency": str(quote.get("currency") or "").upper(),
            "price_basis": quote.get("price_basis"),
            "tax_fee_basis": quote.get("tax_fee_basis"),
        }
        occupancy_types_valid = all(type(quote.get(key)) is int for key in ("rooms", "adults", "children"))
        if not occupancy_types_valid or quote_basis != {key: basis[key] for key in quote_basis}:
            reasons.append("COMPARISON_BASIS_MISMATCH")
        observed = _utc(quote.get("observed_at"))
        expires = _utc(quote.get("expires_at"))
        if observed is None:
            reasons.append("QUOTE_OBSERVED_AT_REQUIRED")
        elif (now - observed).total_seconds() > ConsumerOtaComparisonService.MAX_QUOTE_AGE_SECONDS:
            reasons.append("QUOTE_STALE")
        elif observed > now:
            reasons.append("QUOTE_OBSERVED_IN_FUTURE")
        if expires is None:
            reasons.append("QUOTE_EXPIRES_AT_REQUIRED")
        elif expires <= now:
            reasons.append("QUOTE_EXPIRED")
        return reasons

    def options(self, user_id: str, search: dict, provider_quotes: list[dict] | None = None, now: datetime | None = None):
        basis = self._basis(search)
        now = _utc(now) or datetime.now(timezone.utc)
        quotes = {str(q.get("provider") or "").upper(): q for q in (provider_quotes or [])}
        with SessionLocal() as session:
            jobs = session.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id == user_id)).all()
        linked = {str(row.source_provider or "").upper() for row in jobs if
            row.status == "PREVIEW_READY" and (row.metadata_json or {}).get("connection_intent")
            and (row.metadata_json or {}).get("account_holder_verified") is True
            and (row.metadata_json or {}).get("provider_account_subject_hash")}
        params = {
            "city": basis["city_code"], "checkin": basis["check_in"], "checkout": basis["check_out"],
            "hotel_id": basis["hotel_id"], "adults": basis["adults"], "children": basis["children"],
            "rooms": basis["rooms"], "currency": basis["currency"],
        }
        items = []
        for provider, spec in self.PROVIDERS.items():
            deep_link, deep_link_status = self._official_deep_link(provider, os.getenv(spec["env"]), params)
            quote = quotes.get(provider)
            reasons = self._quote_reasons(provider, quote, user_id, basis, now) if quote else ["NO_VERIFIED_QUOTE"]
            linked_account = provider in linked
            item = {
                "provider": provider,
                "provider_identity": {"provider_code": provider, "display_name": spec["label"], "booking_surface": "EXTERNAL_PROVIDER", "merchant_of_record": provider},
                "account_link_status": "LINKED" if linked_account else "NOT_LINKED",
                "account_holder_authorized": linked_account or not reasons,
                "deep_link": deep_link,
                "deep_link_status": deep_link_status,
                "login_session": "PROVIDER_APP_OR_SITE",
                "credentials_received_by_go": False,
                "eligible_for_price_comparison": not reasons,
                "member_price_status": "VERIFIED_PERSONAL_MEMBER_PRICE" if not reasons else ("QUOTE_SUPPRESSED" if quote else "VISIBLE_AFTER_PROVIDER_LOGIN"),
                "suppression_reasons": reasons,
                "verified_member_price": None,
                "price_disclosure": "FINAL_PRICE_REVALIDATED_BY_PROVIDER_AT_CHECKOUT",
            }
            if not reasons:
                expires = _utc(quote.get("expires_at"))
                item["verified_member_price"] = {
                    "provider_quote_id": quote["provider_quote_id"],
                    "total_amount_minor": quote["total_amount_minor"],
                    "currency": basis["currency"],
                    "member_tier": quote.get("member_tier"),
                    "observed_at": _utc(quote["observed_at"]).isoformat(),
                    "expires_at": expires.isoformat() if expires else None,
                    "comparison_basis_fingerprint": basis["fingerprint"],
                }
            items.append(item)
        return {
            "comparison_scope": "CURRENT_CONSUMER",
            "comparison_basis": basis,
            "misleading_price_prevention": {
                "rank_only_verified_fresh_same_basis_quotes": True,
                "login_only_deep_links_are_not_prices": True,
                "suppressed_quote_amounts_are_not_returned": True,
                "maximum_quote_age_seconds": self.MAX_QUOTE_AGE_SECONDS,
            },
            "providers": items,
        }


consumer_ota_comparison_service = ConsumerOtaComparisonService()

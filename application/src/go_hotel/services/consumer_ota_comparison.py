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

    @staticmethod
    def _product_comparison(quote: dict, basis: dict) -> tuple[dict | None, list[str]]:
        """Only adapter-normalized, complete terms define an equivalence group.

        Provider room/rate ids are provenance, never cross-provider identities.
        Unsupported extra terms fail closed rather than silently losing conditions.
        """
        terms = quote.get("product_terms")
        required = {"canonical_room_type_id", "room_mapping_source", "provider_room_id",
                    "provider_rate_plan_id", "meal", "cancellation", "payment_timing", "confirmation_mode", "included_benefits"}
        if not isinstance(terms, dict) or set(terms) != required:
            return None, ["COMPLETE_PRODUCT_TERMS_REQUIRED"]
        if terms["room_mapping_source"] != "GO_CANONICAL_VERIFIED" or any(
            not isinstance(terms[key], str) or not terms[key].strip()
            for key in ("canonical_room_type_id", "provider_room_id", "provider_rate_plan_id")
        ):
            return None, ["VERIFIED_ROOM_MAPPING_AND_RATE_PROVENANCE_REQUIRED"]
        if (terms["payment_timing"] not in ("PREPAY", "PAY_AT_PROPERTY")
            or terms["confirmation_mode"] not in ("INSTANT_CONFIRMED", "ON_REQUEST")
            or terms["included_benefits"] != []):
            return None, ["COMPLETE_PAYMENT_CONFIRMATION_AND_BENEFIT_TERMS_REQUIRED"]
        meal = terms["meal"]
        if (not isinstance(meal, dict) or set(meal) != {"code", "breakfast_per_room"}
            or meal["code"] not in ("ROOM_ONLY", "BREAKFAST")
            or type(meal["breakfast_per_room"]) is not int or meal["breakfast_per_room"] < 0
            or (meal["code"] == "ROOM_ONLY" and meal["breakfast_per_room"] != 0)
            or (meal["code"] != "ROOM_ONLY" and meal["breakfast_per_room"] == 0)):
            return None, ["COMPLETE_MEAL_TERMS_REQUIRED"]
        cancellation = terms["cancellation"]
        if not isinstance(cancellation, dict) or cancellation.get("policy_complete") is not True:
            return None, ["COMPLETE_CANCELLATION_TERMS_REQUIRED"]
        if cancellation == {"policy_complete": True, "policy_type": "NON_REFUNDABLE"}:
            normalized_cancellation = dict(cancellation)
        elif (set(cancellation) == {"policy_complete", "policy_type", "free_until", "penalty_after"}
              and cancellation["policy_type"] == "FREE_UNTIL"):
            deadline = cancellation["free_until"]
            # A local clock without a timezone cannot be compared as an instant.
            try:
                parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00")) if isinstance(deadline, str) else None
            except ValueError:
                parsed = None
            penalty = cancellation["penalty_after"]
            if (parsed is None or parsed.tzinfo is None or not isinstance(penalty, dict)
                or set(penalty) != {"type", "value"} or type(penalty["value"]) is not int
                or penalty["value"] < 0 or penalty["type"] not in ("FULL_STAY", "FIRST_NIGHT", "AMOUNT_MINOR", "PERCENT")
                or (penalty["type"] in ("FULL_STAY", "FIRST_NIGHT") and penalty["value"] != 1)
                or (penalty["type"] == "PERCENT" and penalty["value"] > 100)):
                return None, ["COMPLETE_CANCELLATION_TERMS_REQUIRED"]
            normalized_cancellation = cancellation | {"free_until": parsed.astimezone(timezone.utc).isoformat()}
        else:
            return None, ["UNSUPPORTED_CANCELLATION_TERMS"]
        identity = {"basis": basis["fingerprint"], "canonical_room_type_id": terms["canonical_room_type_id"],
                    "meal": meal, "cancellation": normalized_cancellation,
                    "payment_timing": terms["payment_timing"], "confirmation_mode": terms["confirmation_mode"],
                    "included_benefits": sorted(set(terms["included_benefits"]))}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {"group_id": fingerprint, "canonical_room_type_id": terms["canonical_room_type_id"],
                "provider_room_id": terms["provider_room_id"], "provider_rate_plan_id": terms["provider_rate_plan_id"],
                "meal": meal, "cancellation": normalized_cancellation,
                    "payment_timing": terms["payment_timing"], "confirmation_mode": terms["confirmation_mode"],
                    "included_benefits": sorted(set(terms["included_benefits"]))}, []

    def options(self, user_id: str, search: dict, provider_quotes: list[dict] | None = None, now: datetime | None = None):
        basis = self._basis(search)
        now = _utc(now) or datetime.now(timezone.utc)
        quotes = {}
        for quote in provider_quotes or []:
            provider = str(quote.get("provider") or "").upper()
            if provider in quotes:
                raise ValueError("MULTIPLE_PROVIDER_QUOTE_VARIANTS_REQUIRE_EXPLICIT_SELECTION")
            quotes[provider] = quote
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
            product, product_reasons = self._product_comparison(quote, basis) if not reasons else (None, ["VERIFIED_QUOTE_REQUIRED"])
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
                "eligible_for_price_comparison": not reasons and not product_reasons,
                "product_comparability": {"state": "COMPARABLE_WITHIN_GROUP" if product else "UNKNOWN",
                                          "reasons": product_reasons, "terms": product},
                "price_rank_within_group": None,
                "savings_against_group_highest_minor": None,
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
        groups = {}
        for item in items:
            if item["eligible_for_price_comparison"]:
                group_id = item["product_comparability"]["terms"]["group_id"]
                groups.setdefault(group_id, []).append(item)
        for peers in groups.values():
            if len(peers) < 2:
                continue
            amounts = sorted({peer["verified_member_price"]["total_amount_minor"] for peer in peers})
            for peer in peers:
                amount = peer["verified_member_price"]["total_amount_minor"]
                peer["price_rank_within_group"] = amounts.index(amount) + 1
                peer["savings_against_group_highest_minor"] = amounts[-1] - amount
        return {
            "comparison_groups": [{"group_id": key, "providers": [item["provider"] for item in peers]}
                                  for key, peers in groups.items()],
            "comparison_scope": "CURRENT_CONSUMER",
            "comparison_basis": basis,
            "misleading_price_prevention": {
                "rank_only_verified_fresh_same_basis_quotes": True,
                "rank_only_complete_equivalent_product_terms": True,
                "cross_group_ranking_and_savings_prohibited": True,
                "login_only_deep_links_are_not_prices": True,
                "suppressed_quote_amounts_are_not_returned": True,
                "maximum_quote_age_seconds": self.MAX_QUOTE_AGE_SECONDS,
            },
            "providers": items,
        }


consumer_ota_comparison_service = ConsumerOtaComparisonService()

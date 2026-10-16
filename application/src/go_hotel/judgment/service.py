from __future__ import annotations
import json
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, text
from go_hotel.db.session import SessionLocal
from go_hotel.autonomy.durable import transaction
from go_hotel.db.models import (
    ReviewSessionRow,RiskEventRuntimeRow,RiskRemediationRow,JudgmentHookRow,
    JudgmentEvidencePackageRow,JudgmentRuntimeRow,RecommendationDecisionRow,GoodHotelStandardAssessmentRow
)
from go_hotel.judgment.good_hotel_standard import good_hotel_standard_service
from go_hotel.domain.models import new_id, now_utc, Event
from go_hotel.repositories.sql import repo
from go_hotel.core.errors import not_found, unprocessable

MODEL_VERSION="GO_JUDGMENT_DETERMINISTIC_V1"
PROMPT_VERSION="NO_GENERATIVE_PROMPT_V1"
RULE_VERSION="GO_JUDGMENT_RULES_1.0"
RECOMMENDATION_RULE_VERSION="GO_RECOMMENDATION_CONSTITUTION_1.0"
COMMERCIAL_FIELDS={"subscription_amount","advertising_budget","commission","rebate","partnership_tier","investment_relationship","commercial_revenue","gmv","clicks","favorites","popularity","user_preference","traveler_fit","traveler_context","candidate_scores","personalization_score"}
PERSISTED_EVIDENCE_FIELDS={"completed_review_count","structured_experience_avg_milli","dimension_summary",
    "confirmed_serious_risk_count","monitoring_risk_count","verified_remediation_count","recommendation_authority"}

RECOMMENDATION_DIMENSIONS=(
    "WORK_OF_HOSPITALITY",
    "IRREPLACEABILITY",
    "SENSE_OF_PLACE",
    "AESTHETIC_JUDGMENT",
    "EMOTIONAL_RESONANCE",
    "WORTH_THE_JOURNEY",
)
RECOMMENDATION_STATES={"STRONG","PRESENT","LIMITED","ABSENT","UNKNOWN"}
ANNUAL_REVIEW_SOURCE_TYPE = "RECOMMENDATION_ANNUAL_REVIEW"
ANNUAL_REVIEW_REASON_CODE = "RECOMMENDATION_ANNUAL_REASSESSMENT"
RECOMMENDATION_VALIDITY_START_UNVERIFIED = "RECOMMENDATION_VALIDITY_START_UNVERIFIED"
RECOMMENDATION_ANNUAL_REASSESSMENT_REQUIRED = "RECOMMENDATION_ANNUAL_REASSESSMENT_REQUIRED"
RECOMMENDATION_EXPIRED_ANNUAL_REASSESSMENT_REQUIRED = "RECOMMENDATION_EXPIRED_ANNUAL_REASSESSMENT_REQUIRED"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _one_natural_year_after(value: datetime) -> datetime:
    value = _as_utc(value)
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


class JudgmentService:
    def _assessment_digest(self, assessment: dict) -> str:
        raw = json.dumps(assessment, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return sha256(raw).hexdigest()

    def _recommendation_authority_meta(self, rec, package):
        feature = {} if not package or not isinstance(package.feature_snapshot, dict) else dict(package.feature_snapshot)
        assessment = feature.get("recommendation_assessment")
        if not isinstance(assessment, dict):
            return None
        meta = feature.get("recommendation_authority")
        digest = self._assessment_digest(assessment)
        if meta is not None:
            # Never repair malformed metadata by assigning a fresh start date.
            try:
                started = datetime.fromisoformat(meta["started_at"])
                if started.tzinfo is None or meta["assessment_digest"] != digest:
                    return {"assessment_digest": digest}
                started = _as_utc(started)
                expires = _one_natural_year_after(started)
                if (_as_utc(datetime.fromisoformat(meta["expires_at"])) != expires
                    or _as_utc(datetime.fromisoformat(meta["review_due_at"])) != expires - timedelta(days=30)):
                    return {"assessment_digest": digest}
                return {"assessment_digest": digest, "started_at": started.isoformat(),
                        "review_due_at": (expires-timedelta(days=30)).isoformat(), "expires_at": expires.isoformat()}
            except (ValueError, TypeError, KeyError, OverflowError):
                return {"assessment_digest": digest}
        # Legacy decision.valid_from is a row lifecycle date, not proof of an
        # annual assessment's approval. Preserve history and require reassessment.
        return {"assessment_digest": digest}

    def _review_request_source_id(self, hotel_id: str, judgment_id: str, meta: dict | None) -> str:
        if meta and meta.get("started_at") and meta.get("expires_at"):
            material = f"{hotel_id}|{meta['assessment_digest']}|{meta['started_at']}|{meta['expires_at']}"
        else:
            material = f"{hotel_id}|{judgment_id}|legacy"
        return "annual_" + sha256(material.encode()).hexdigest()[:24]

    def _find_open_review_request_in(self, s, hotel_id: str, source_id: str | None = None):
        query = select(JudgmentHookRow).where(
            JudgmentHookRow.hotel_id == hotel_id,
            JudgmentHookRow.source_type == ANNUAL_REVIEW_SOURCE_TYPE,
            JudgmentHookRow.status == "REQUESTED",
        )
        if source_id is not None:
            query = query.where(JudgmentHookRow.source_id == source_id)
        return s.scalar(query.order_by(JudgmentHookRow.created_at.desc()))

    def _historical_assessment_meta(self, s, hotel_id, digest):
        # Include superseded decisions: A -> B -> A must retain A's first term.
        rows = s.execute(select(RecommendationDecisionRow, JudgmentEvidencePackageRow)
            .join(JudgmentRuntimeRow, JudgmentRuntimeRow.judgment_id == RecommendationDecisionRow.judgment_id)
            .join(JudgmentEvidencePackageRow, JudgmentEvidencePackageRow.package_id == JudgmentRuntimeRow.evidence_package_id)
            .where(RecommendationDecisionRow.hotel_id == hotel_id,
                   RecommendationDecisionRow.status == "GO_RECOMMENDED",
                   JudgmentEvidencePackageRow.hotel_id == hotel_id)
            .order_by(RecommendationDecisionRow.created_at, RecommendationDecisionRow.decision_id))
        for rec, package in rows:
            meta = self._recommendation_authority_meta(rec, package)
            if meta and meta.get("assessment_digest") == digest:
                return meta
        return None

    def _recommendation_state(self, s, hotel_id: str, judgment, rec, package, now: datetime | None = None):
        now = _as_utc(now or now_utc())
        if not rec:
            return {
                "status": "NOT_YET_RATED",
                "reason_codes": ["DECISION_PENDING"],
                "public_go_score": None,
                "validity": {"status": "UNKNOWN", "judgment_status": judgment.status if judgment else None},
                "authority_status": None,
                "authority_reason_codes": [],
            }
        authority_status = rec.status
        authority_reason_codes = list(rec.reason_codes or [])
        validity = {"status": "NOT_APPLICABLE", "judgment_status": judgment.status if judgment else None}
        status = authority_status
        reason_codes = list(authority_reason_codes)
        public_go_score = None if rec.public_go_score_milli is None else rec.public_go_score_milli / 1000
        meta = self._recommendation_authority_meta(rec, package)
        review_source_id = self._review_request_source_id(hotel_id, judgment.judgment_id, meta)
        open_request = self._find_open_review_request_in(s, hotel_id, review_source_id)
        if authority_status == "GO_RECOMMENDED":
            if not meta or not meta.get("started_at"):
                status = "NOT_YET_RATED"
                reason_codes = [
                    RECOMMENDATION_ANNUAL_REASSESSMENT_REQUIRED,
                    RECOMMENDATION_VALIDITY_START_UNVERIFIED,
                ]
                public_go_score = None
                review_source_id = self._review_request_source_id(hotel_id, judgment.judgment_id, None)
                open_request = self._find_open_review_request_in(s, hotel_id, review_source_id)
                validity.update({
                    "status": "START_UNVERIFIED",
                    "review_required": True,
                    "review_request_source_id": review_source_id,
                })
            else:
                started_at = datetime.fromisoformat(meta["started_at"])
                review_due_at = datetime.fromisoformat(meta["review_due_at"])
                expires_at = datetime.fromisoformat(meta["expires_at"])
                validity.update({
                    "valid_from": started_at.isoformat(),
                    "review_due_at": review_due_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "review_request_source_id": review_source_id,
                })
                if now < started_at:
                    status = "NOT_YET_RATED"
                    reason_codes = [RECOMMENDATION_VALIDITY_START_UNVERIFIED]
                    public_go_score = None
                    validity.update({"status": "START_UNVERIFIED", "review_required": True})
                elif now >= expires_at:
                    status = "NOT_YET_RATED"
                    reason_codes = [RECOMMENDATION_EXPIRED_ANNUAL_REASSESSMENT_REQUIRED]
                    public_go_score = None
                    validity.update({"status": "EXPIRED", "review_required": True})
                elif now >= review_due_at:
                    validity.update({"status": "REASSESSMENT_DUE", "review_required": True})
                else:
                    validity.update({"status": "ACTIVE", "review_required": False})
        if judgment and judgment.status != "ACTIVE" and authority_status == "GO_RECOMMENDED":
            status = "NOT_YET_RATED"
            reason_codes = ["RECOMMENDATION_SUPERSEDED"]
            public_go_score = None
            validity["status"] = "SUPERSEDED"
        if open_request:
            validity["review_request"] = {
                "hook_id": open_request.hook_id,
                "status": open_request.status,
                "created_at": _as_utc(open_request.created_at).isoformat(),
            }
        else:
            validity["review_request"] = None
        return {
            "status": status,
            "reason_codes": reason_codes,
            "public_go_score": public_go_score,
            "validity": validity,
            "authority_status": authority_status,
            "authority_reason_codes": authority_reason_codes,
        }

    def _evidence(self, hotel_id:str)->dict:
        with SessionLocal() as s:
            return self._evidence_in(s, hotel_id)

    def _evidence_in(self, s, hotel_id):
        reviews=s.scalars(select(ReviewSessionRow).where(ReviewSessionRow.hotel_id==hotel_id,ReviewSessionRow.status=="COMPLETED").order_by(ReviewSessionRow.completed_at)).all()
        risks=s.scalars(select(RiskEventRuntimeRow).where(RiskEventRuntimeRow.hotel_id==hotel_id).order_by(RiskEventRuntimeRow.created_at)).all()
        rems=[]
        for r in risks:
            rems.extend(s.scalars(select(RiskRemediationRow).where(RiskRemediationRow.risk_event_id==r.risk_event_id)).all())
        source_refs=[]; dims={}; experience=[]
        for r in reviews:
            source_refs.append({"type":"GO_TRUTH_REVIEW","id":r.review_id,"at":r.completed_at.isoformat() if r.completed_at else None})
            if r.experience_score_milli is not None: experience.append(r.experience_score_milli)
            for k,v in (r.dimension_result or {}).items():
                d=dims.setdefault(k,{"negative":0,"positive":0})
                if v=="NEGATIVE": d["negative"]+=1
                elif v=="POSITIVE": d["positive"]+=1
        confirmed=[r for r in risks if r.status in ("CONFIRMED","REMEDIATION_REQUIRED")]
        monitoring=[r for r in risks if r.status in ("REMEDIATION_VERIFIED","MONITORING")]
        for r in risks:
            source_refs.append({"type":"RISK_EVENT","id":r.risk_event_id,"status":r.status,"risk_type":r.risk_type,"at":r.created_at.isoformat()})
        for r in rems:
            source_refs.append({"type":"REMEDIATION","id":r.remediation_id,"status":r.status,"risk_event_id":r.risk_event_id,"at":r.submitted_at.isoformat()})
        avg_exp=(sum(experience)/len(experience)) if experience else None
        feature={
            "completed_review_count":len(reviews),
            "structured_experience_avg_milli":round(avg_exp) if avg_exp is not None else None,
            "dimension_summary":dims,
            "confirmed_serious_risk_count":len(confirmed),
            "monitoring_risk_count":len(monitoring),
            "verified_remediation_count":sum(1 for x in rems if x.status=="VERIFIED"),
        }
        return {"source_refs":source_refs,"feature_snapshot":feature,"source_summary":{"reviews":len(reviews),"risks":len(risks),"remediations":len(rems)}}

    def _score(self, f:dict)->tuple[int,dict,dict,int]:
        # V1 is deliberately deterministic and independent from raw user stars.
        # GO Truth structured outcomes and verified risks are evidence inputs, not a copied rating average.
        score=4600
        dims={"QUALITY_BASELINE":4600}
        negative=sum(v.get("negative",0) for v in f["dimension_summary"].values())
        positive=sum(v.get("positive",0) for v in f["dimension_summary"].values())
        score += min(200, positive*40)
        score -= min(500, negative*100)
        score -= f["confirmed_serious_risk_count"]*700
        score -= f["monitoring_risk_count"]*250
        score += min(150, f["verified_remediation_count"]*100)
        # Structured GO Truth score can refine confidence/quality slightly; raw star never enters this function.
        avg=f.get("structured_experience_avg_milli")
        if avg is not None:
            score += max(-200,min(200,int((avg-4000)*0.2)))
        score=max(1000,min(5000,score))
        dims.update({"STRUCTURED_NEGATIVE_SIGNALS":negative,"STRUCTURED_POSITIVE_SIGNALS":positive,"CONFIRMED_SERIOUS_RISKS":f["confirmed_serious_risk_count"],"MONITORING_RISKS":f["monitoring_risk_count"],"VERIFIED_REMEDIATIONS":f["verified_remediation_count"]})
        why=[]
        if f["confirmed_serious_risk_count"]: why.append("CONFIRMED_SERIOUS_RISK")
        if f["monitoring_risk_count"]: why.append("RISK_UNDER_MONITORING")
        if negative: why.append("STRUCTURED_EXPERIENCE_ISSUES")
        if f["verified_remediation_count"]: why.append("VERIFIED_REMEDIATION")
        if not why: why.append("NO_MATERIAL_NEGATIVE_EVIDENCE")
        confidence=min(9500,4500+f["completed_review_count"]*500+len(why)*150)
        explanation={"why_recommended_or_not":why,"strongest_value":"Evidence-backed baseline quality" if score>=4000 else "No positive claim beyond available evidence","main_shortcoming":"Confirmed/structured risks" if score<4300 else "No material shortcoming established","why_not_higher":"GO Judgment V1 remains conservative and evidence-limited","suitable_for":"Travelers who value independently audited fulfillment evidence","uncertainty":"Score may change when new verified evidence arrives"}
        return score,dims,explanation,confidence

    def _recommend(self, score:int, f:dict)->tuple[str,list[str],int|None]:
        # GO Recommendation Constitution 1.0: GO Score / review volume NEVER auto-create endorsement.
        # Operational facts may inform or veto an independent recommendation assessment, but are not the verdict itself.
        if f["confirmed_serious_risk_count"]>0:
            return "GO_NOT_RECOMMENDED",["UNRESOLVED_CONFIRMED_SERIOUS_RISK"],None
        assessment=f.get("recommendation_assessment")
        if not isinstance(assessment,dict):
            return "NOT_YET_RATED",["RECOMMENDATION_ASSESSMENT_REQUIRED"],None
        if assessment.get("commercial_independence_attested") is not True:
            return "NOT_YET_RATED",["COMMERCIAL_INDEPENDENCE_ATTESTATION_REQUIRED"],None
        dims=assessment.get("dimensions")
        if not isinstance(dims,dict) or any(k not in dims for k in RECOMMENDATION_DIMENSIONS):
            return "NOT_YET_RATED",["RECOMMENDATION_SIX_DIMENSION_EVIDENCE_INCOMPLETE"],None
        for key in RECOMMENDATION_DIMENSIONS:
            item=dims.get(key)
            if not isinstance(item,dict) or item.get("state") not in RECOMMENDATION_STATES or not str(item.get("evidence_summary") or "").strip():
                return "NOT_YET_RATED",["RECOMMENDATION_SIX_DIMENSION_EVIDENCE_INCOMPLETE"],None
        worth=assessment.get("worth_the_journey")
        verdict=assessment.get("verdict")
        if verdict=="GO_RECOMMENDED":
            if worth!="YES":
                return "NOT_YET_RATED",["WORTH_THE_JOURNEY_EXPLICIT_YES_REQUIRED"],None
            return "GO_RECOMMENDED",["GO_RECOMMENDATION_CONSTITUTION_PASSED","WORTH_THE_JOURNEY_YES","COMMERCIAL_INDEPENDENCE_ATTESTED"],score
        if verdict=="GO_NOT_RECOMMENDED":
            return "GO_NOT_RECOMMENDED",["GO_INDEPENDENT_RECOMMENDATION_NOT_ENDORSED"],None
        return "NOT_YET_RATED",["OBSERVATION_REQUIRED"],None


    def _assert_no_forbidden_features(self,value,path="extra_features"):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in COMMERCIAL_FIELDS:
                    unprocessable("JUDGMENT_COMMERCIAL_FIELD_FORBIDDEN",f"Commercial/popularity/user-fit field forbidden at {path}.{k}")
                self._assert_no_forbidden_features(v,f"{path}.{k}")
        elif isinstance(value,list):
            for i,v in enumerate(value): self._assert_no_forbidden_features(v,f"{path}[{i}]")

    def _lock_hotel_in(self, s, hotel_id):
        # An ACTIVE row cannot lock the first evaluation because it may not exist.
        # The database transaction lock also fences separate API/worker processes.
        if s.bind.dialect.name == "postgresql":
            key = int.from_bytes(sha256(("GO_JUDGMENT:" + hotel_id).encode()).digest()[:8], "big", signed=True)
            s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def _complete_hooks_in(self, hooks, judgment_id, package_id, source_refs):
        sources = {(x["type"], x["id"]) for x in source_refs}
        for hook in hooks:
            if (hook.source_type, hook.source_id) in sources:
                hook.status = "COMPLETED"
                hook.payload = {**(hook.payload or {}), "judgment_id": judgment_id,
                                "evidence_package_id": package_id}

    def _complete_review_requests_in(self, s, hotel_id, judgment_id, package_id, assessment_digest, outcome):
        hooks = s.scalars(select(JudgmentHookRow).where(
            JudgmentHookRow.hotel_id == hotel_id,
            JudgmentHookRow.source_type == ANNUAL_REVIEW_SOURCE_TYPE,
            JudgmentHookRow.status == "REQUESTED",
        ).with_for_update()).all()
        for hook in hooks:
            payload = hook.payload or {}
            if payload.get("assessment_digest") != assessment_digest:
                hook.status = "COMPLETED"
                hook.payload = {
                    **payload,
                    "judgment_id": judgment_id,
                    "evidence_package_id": package_id,
                    "reassessment_digest": assessment_digest,
                    "outcome": outcome,
                }

    def _reevaluate_in(self, s, hotel_id, extra_features, standard):
        now = now_utc()
        # Capture pending hooks before the evidence read. Hooks arriving after this
        # snapshot must remain REQUESTED for the next evaluation.
        hooks = list(s.scalars(select(JudgmentHookRow).where(
            JudgmentHookRow.hotel_id == hotel_id, JudgmentHookRow.status == "REQUESTED").with_for_update()))
        ev = self._evidence_in(s, hotel_id)
        feature = dict(ev["feature_snapshot"])
        if extra_features:
            protected = set(feature).intersection(extra_features)
            if protected:
                unprocessable("JUDGMENT_EVIDENCE_FIELD_FORBIDDEN", f"Persisted evidence fields cannot be overridden: {', '.join(sorted(protected))}")
            feature.update(extra_features)
        priors = list(s.scalars(select(JudgmentRuntimeRow).where(
            JudgmentRuntimeRow.hotel_id == hotel_id, JudgmentRuntimeRow.status == "ACTIVE").with_for_update()))
        prior_recs = list(s.scalars(select(RecommendationDecisionRow).where(
            RecommendationDecisionRow.hotel_id == hotel_id, RecommendationDecisionRow.valid_to.is_(None)).with_for_update()))
        score, dims, explanation, confidence = self._score(feature)
        rec_status, reasons, public_score = self._recommend(score, feature)
        assessment = feature.get("recommendation_assessment")
        prior_meta = None
        if isinstance(assessment, dict):
            digest_meta = {"assessment_digest": self._assessment_digest(assessment)}
            prior_meta = self._historical_assessment_meta(s, hotel_id, digest_meta["assessment_digest"])
            if rec_status == "GO_RECOMMENDED":
                if prior_meta is not None:
                    digest_meta = prior_meta
                else:
                    started_at = _as_utc(now)
                    expires_at = _one_natural_year_after(started_at)
                    digest_meta.update({
                        "started_at": started_at.isoformat(),
                        "review_due_at": (expires_at - timedelta(days=30)).isoformat(),
                        "expires_at": expires_at.isoformat(),
                    })
            feature["recommendation_authority"] = digest_meta
        else:
            feature.pop("recommendation_authority", None)
        raw = json.dumps({"hotel_id": hotel_id, "source_refs": ev["source_refs"], "feature_snapshot": feature},
                         sort_keys=True, separators=(",", ":"), default=str).encode()
        digest = sha256(raw).hexdigest()
        package = s.scalar(select(JudgmentEvidencePackageRow).where(JudgmentEvidencePackageRow.content_hash == digest))
        if package and package.hotel_id != hotel_id:
            unprocessable("JUDGMENT_EVIDENCE_IDENTITY_INVALID", "Sealed evidence belongs to another hotel")
        if len(priors) == len(prior_recs) == 1 and package:
            prior, rec = priors[0], prior_recs[0]
            if (prior.evidence_package_id == package.package_id and rec.judgment_id == prior.judgment_id
                and prior.good_hotel_standard_version_id == standard.good_hotel_standard_version_id
                and prior.model_version == MODEL_VERSION and prior.prompt_version == PROMPT_VERSION
                and prior.rule_version == RULE_VERSION and rec.rule_version == RECOMMENDATION_RULE_VERSION):
                self._complete_hooks_in(hooks, prior.judgment_id, package.package_id, ev["source_refs"])
                return prior.judgment_id, None
        package_id = package.package_id if package else new_id("evpkg")
        judgment_id, decision_id = new_id("jud"), new_id("rec")
        for prior in priors:
            prior.status = "SUPERSEDED"
            prior.valid_to = now
        for prior in prior_recs:
            prior.valid_to = now
        if not package:
            s.add(JudgmentEvidencePackageRow(package_id=package_id,hotel_id=hotel_id,source_refs=ev["source_refs"],source_summary=ev["source_summary"],feature_snapshot=feature,excluded_commercial_fields=sorted(COMMERCIAL_FIELDS),content_hash=digest,sealed_at=now,created_at=now))
        s.add(GoodHotelStandardAssessmentRow(good_hotel_standard_assessment_id=new_id('ghsa'),hotel_id=hotel_id,good_hotel_standard_version_id=standard.good_hotel_standard_version_id,evidence_package_id=package_id,dimension_result_json=dims,disqualifier_result_json=[x for x in standard.disqualifiers_json if x in reasons],assessment_state=rec_status,reason_codes_json=reasons,assessed_at=now))
        s.add(JudgmentRuntimeRow(judgment_id=judgment_id,hotel_id=hotel_id,evidence_package_id=package_id,go_score_milli=score,dimension_result=dims,explanation=explanation,confidence_bps=confidence,model_version=MODEL_VERSION,prompt_version=PROMPT_VERSION,rule_version=RULE_VERSION,good_hotel_standard_version_id=standard.good_hotel_standard_version_id,status="ACTIVE",public_at=now if rec_status=="GO_RECOMMENDED" else None,valid_from=now,valid_to=None,created_at=now))
        s.add(RecommendationDecisionRow(decision_id=decision_id,hotel_id=hotel_id,judgment_id=judgment_id,status=rec_status,reason_codes=reasons,public_go_score_milli=public_score,rule_version=RECOMMENDATION_RULE_VERSION,good_hotel_standard_version_id=standard.good_hotel_standard_version_id,valid_from=now,valid_to=None,created_at=now))
        self._complete_hooks_in(hooks, judgment_id, package_id, ev["source_refs"])
        if (isinstance(assessment, dict) and prior_meta is None
            and rec_status in {"GO_RECOMMENDED", "GO_NOT_RECOMMENDED"}
            and assessment.get("verdict") == rec_status):
            self._complete_review_requests_in(s, hotel_id, judgment_id, package_id,
                                             self._assessment_digest(assessment), rec_status)
        return judgment_id, {"package_id": package_id, "score": score, "decision_id": decision_id, "status": rec_status}

    def _publish_events(self, hotel_id, judgment_id, created):
        if created is None:
            return
        repo.append_event(Event(new_id("evt"),"JUDGMENT_CREATED","HOTEL",hotel_id,{"judgment_id":judgment_id,"evidence_package_id":created["package_id"],"go_score_milli":created["score"]}))
        repo.append_event(Event(new_id("evt"),"GO_SCORE_UPDATED","HOTEL",hotel_id,{"judgment_id":judgment_id,"go_score_milli":created["score"]}))
        repo.append_event(Event(new_id("evt"),"RECOMMENDATION_STATUS_CHANGED","HOTEL",hotel_id,{"decision_id":created["decision_id"],"status":created["status"],"judgment_id":judgment_id}))

    def reevaluate(self, hotel_id: str, extra_features: dict | None = None) -> dict:
        if extra_features:
            self._assert_no_forbidden_features(extra_features)
            # Reject caller replacement of persisted facts before even the lazy
            # standard bootstrap can write. Recheck actual fields under lock too.
            protected = PERSISTED_EVIDENCE_FIELDS.intersection(extra_features)
            if protected:
                unprocessable("JUDGMENT_EVIDENCE_FIELD_FORBIDDEN", f"Persisted evidence fields cannot be overridden: {', '.join(sorted(protected))}")
        standard = good_hotel_standard_service.active()
        with transaction(SessionLocal) as s:
            self._lock_hotel_in(s, hotel_id)
            judgment_id, created = self._reevaluate_in(s, hotel_id, extra_features, standard)
        self._publish_events(hotel_id, judgment_id, created)
        return self.get_judgment(judgment_id)

    def process_hook(self, hook_id: str) -> dict:
        standard = good_hotel_standard_service.active()
        with transaction(SessionLocal) as s:
            hook = s.get(JudgmentHookRow, hook_id)
            if not hook:
                not_found("JUDGMENT_HOOK_NOT_FOUND", "Judgment hook not found")
            hotel_id = hook.hotel_id
            self._lock_hotel_in(s, hotel_id)
            # Re-read after waiting for the hotel lock (another worker may finish).
            s.refresh(hook)
            if hook.hotel_id != hotel_id:
                unprocessable("JUDGMENT_HOOK_IDENTITY_INVALID", "Hook hotel changed")
            if hook.status == "COMPLETED":
                binding = hook.payload or {}
                judgment = s.get(JudgmentRuntimeRow, binding.get("judgment_id")) if binding.get("judgment_id") else None
                package = s.get(JudgmentEvidencePackageRow, binding.get("evidence_package_id")) if binding.get("evidence_package_id") else None
                source_bound = bool(package and any(x.get("type") == hook.source_type and x.get("id") == hook.source_id for x in package.source_refs))
                if hook.source_type == ANNUAL_REVIEW_SOURCE_TYPE and package:
                    assessment = (package.feature_snapshot or {}).get("recommendation_assessment")
                    source_bound = (isinstance(assessment, dict)
                        and self._assessment_digest(assessment) == binding.get("reassessment_digest")
                        and binding.get("outcome") == assessment.get("verdict"))
                if (not judgment or not package or judgment.hotel_id != hotel_id or package.hotel_id != hotel_id
                    or judgment.evidence_package_id != package.package_id
                    or not source_bound):
                    unprocessable("JUDGMENT_HOOK_RESULT_REVIEW_REQUIRED", "Completed hook has no matching durable result binding")
                judgment_id, created = judgment.judgment_id, None
            elif hook.status == "REQUESTED":
                if hook.source_type == ANNUAL_REVIEW_SOURCE_TYPE:
                    judgment_id, created = s.scalar(select(JudgmentRuntimeRow.judgment_id).where(
                        JudgmentRuntimeRow.hotel_id == hotel_id,
                        JudgmentRuntimeRow.status == "ACTIVE",
                    ).order_by(JudgmentRuntimeRow.created_at.desc())), None
                else:
                    judgment_id, created = self._reevaluate_in(s, hotel_id, None, standard)
            else:
                unprocessable("JUDGMENT_HOOK_STATE_INVALID", "Hook is not processable")
        self._publish_events(hotel_id, judgment_id, created)
        return self.get_judgment(judgment_id)

    def _ensure_annual_review_request(self, hotel_id: str):
        with transaction(SessionLocal) as s:
            self._lock_hotel_in(s, hotel_id)
            judgment = s.scalar(select(JudgmentRuntimeRow).where(
                JudgmentRuntimeRow.hotel_id == hotel_id,
                JudgmentRuntimeRow.status == "ACTIVE",
            ).order_by(JudgmentRuntimeRow.created_at.desc()))
            if not judgment:
                return None
            rec = s.scalar(select(RecommendationDecisionRow).where(
                RecommendationDecisionRow.judgment_id == judgment.judgment_id,
            ).order_by(RecommendationDecisionRow.created_at.desc()))
            if not rec or rec.status != "GO_RECOMMENDED":
                return None
            package = s.get(JudgmentEvidencePackageRow, judgment.evidence_package_id)
            state = self._recommendation_state(s, hotel_id, judgment, rec, package)
            validity = state["validity"]
            if validity.get("status") not in {"REASSESSMENT_DUE", "EXPIRED", "START_UNVERIFIED"}:
                return None
            source_id = validity["review_request_source_id"]
            if s.scalar(select(JudgmentHookRow.hook_id).where(
                JudgmentHookRow.hotel_id == hotel_id,
                JudgmentHookRow.source_type == ANNUAL_REVIEW_SOURCE_TYPE,
                JudgmentHookRow.source_id == source_id,
            )):
                return None
            hook_id = new_id("jhook")
            s.add(JudgmentHookRow(
                hook_id=hook_id,
                hotel_id=hotel_id,
                source_type=ANNUAL_REVIEW_SOURCE_TYPE,
                source_id=source_id,
                reason_code=ANNUAL_REVIEW_REASON_CODE,
                status="REQUESTED",
                payload={
                    "review_kind": ANNUAL_REVIEW_REASON_CODE,
                    "previous_judgment_id": judgment.judgment_id,
                    "previous_decision_id": rec.decision_id,
                    "assessment_digest": (self._recommendation_authority_meta(rec, package) or {}).get("assessment_digest"),
                    "validity": {
                        key: value for key, value in validity.items()
                        if key in {"status", "valid_from", "review_due_at", "expires_at"}
                    },
                },
                created_at=now_utc(),
            ))
            return hook_id

    def process_pending(self,limit:int=100)->list[dict]:
        # Keyset-page every active recommendation. A fixed newest-N query would
        # permanently starve older hotels; restarts safely rescan durable cycles.
        cursor = ""
        while True:
            with SessionLocal() as s:
                hotel_ids = list(s.scalars(select(RecommendationDecisionRow.hotel_id).where(
                    RecommendationDecisionRow.status == "GO_RECOMMENDED",
                    RecommendationDecisionRow.valid_to.is_(None),
                    RecommendationDecisionRow.hotel_id > cursor,
                ).distinct().order_by(RecommendationDecisionRow.hotel_id).limit(max(1, limit))))
            if not hotel_ids:
                break
            for hotel_id in hotel_ids:
                self._ensure_annual_review_request(hotel_id)
            cursor = hotel_ids[-1]
        with SessionLocal() as s:
            ids=[x.hook_id for x in s.scalars(select(JudgmentHookRow).where(
                JudgmentHookRow.status=="REQUESTED",
                JudgmentHookRow.source_type != ANNUAL_REVIEW_SOURCE_TYPE,
            ).order_by(JudgmentHookRow.created_at).limit(limit)).all()]
        return [self.process_hook(x) for x in ids]

    def public_summary_or_default(self,hotel_id:str)->dict:
        with SessionLocal() as s:
            j=s.scalar(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id==hotel_id,JudgmentRuntimeRow.status=="ACTIVE").order_by(JudgmentRuntimeRow.created_at.desc()))
            if not j:
                return {"judgment_id":None,"go_score":None,"recommendation_status":"NOT_YET_RATED","reason_codes":["INSUFFICIENT_EVIDENCE"]}
            r=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==j.judgment_id).order_by(RecommendationDecisionRow.created_at.desc()))
            p=s.get(JudgmentEvidencePackageRow,j.evidence_package_id)
            state = self._recommendation_state(s, hotel_id, j, r, p)
            return {
                "judgment_id":j.judgment_id,
                "go_score":state["public_go_score"],
                "recommendation_status":state["status"],
                "reason_codes":state["reason_codes"],
                "validity":state["validity"],
            }

    def public_view(self,hotel_id:str)->dict:
        latest=self.get_latest(hotel_id)
        return {"judgment_id":latest["judgment_id"],"hotel_id":hotel_id,"go_score":latest["public_go_score"],"recommendation":latest["recommendation"],"explanation":latest["explanation"],"confidence_bps":latest["confidence_bps"],"evidence_package_id":latest["evidence_package"]["package_id"],"validity":latest["recommendation"]["validity"]}

    def get_latest(self,hotel_id:str)->dict:
        with SessionLocal() as s:
            j=s.scalar(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id==hotel_id,JudgmentRuntimeRow.status=="ACTIVE").order_by(JudgmentRuntimeRow.created_at.desc()))
            if not j: not_found("JUDGMENT_NOT_FOUND","No judgment exists for hotel")
            jid=j.judgment_id
        return self.get_judgment(jid)

    def get_judgment(self,judgment_id:str)->dict:
        with SessionLocal() as s:
            j=s.get(JudgmentRuntimeRow,judgment_id)
            if not j: not_found("JUDGMENT_NOT_FOUND","Judgment not found")
            p=s.get(JudgmentEvidencePackageRow,j.evidence_package_id)
            r=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==judgment_id).order_by(RecommendationDecisionRow.created_at.desc()))
            state = self._recommendation_state(s, j.hotel_id, j, r, p)
            return {
                "judgment_id":j.judgment_id,
                "hotel_id":j.hotel_id,
                "go_score":j.go_score_milli/1000,
                "public_go_score":state["public_go_score"],
                "dimension_result":j.dimension_result,
                "explanation":j.explanation,
                "confidence_bps":j.confidence_bps,
                "model_version":j.model_version,
                "prompt_version":j.prompt_version,
                "rule_version":j.rule_version,
                "good_hotel_standard_version_id":j.good_hotel_standard_version_id,
                "status":j.status,
                "recommendation":{
                    "decision_id":r.decision_id,
                    "status":state["status"],
                    "reason_codes":state["reason_codes"],
                    "authority_status":state["authority_status"],
                    "authority_reason_codes":state["authority_reason_codes"],
                    "rule_version":r.rule_version,
                    "good_hotel_standard_version_id":r.good_hotel_standard_version_id,
                    "validity":state["validity"],
                } if r else None,
                "evidence_package":{
                    "package_id":p.package_id,
                    "content_hash":p.content_hash,
                    "source_refs":p.source_refs,
                    "source_summary":p.source_summary,
                    "feature_snapshot":p.feature_snapshot,
                    "excluded_commercial_fields":p.excluded_commercial_fields,
                    "sealed_at":p.sealed_at.isoformat(),
                } if p else None,
            }

judgment_service=JudgmentService()

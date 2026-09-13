from __future__ import annotations

RC20_PASS_DIMENSIONS = [
    ("NORMAL_PATH", "正常路径能跑通"),
    ("EXCEPTION_RECOVERY", "异常路径能恢复"),
    ("STATE_MACHINE", "状态机完整"),
    ("EVIDENCE_CHAIN", "证据链完整"),
    ("HUMAN_OPERABLE", "真实人能操作"),
]

# RC20 is a depth contract, not a claim that any external supplier is LIVE.
# Staging browser/external-provider evidence remains a separate gate.
VERTICAL_DEPTH = {
    "HOTEL": {
        "label": "酒店",
        "normal_path": ["发现/Canonical", "酒店商品事实", "房型/房态房价", "Official Direct/Offer", "预订", "支付状态", "入住履约", "取消/退款"],
        "exception_recovery": ["发现源超时自动重试", "Canonical 冲突进入异常中心", "供应异常 fail-closed", "支付/履约异常保留证据并可恢复"],
        "state_machine": ["DISCOVERED", "CANONICALIZED", "PRODUCT_READY", "BOOKING_PENDING", "CONFIRMED", "IN_STAY", "COMPLETED", "CANCELLED", "FAILED", "MANUAL_REVIEW"],
        "evidence": ["source snapshot", "canonical provenance", "offer/prebook evidence", "order/payment evidence", "fulfillment/refund evidence"],
        "operator_surface": ["酒店数字基础设施", "酒店运营", "订单履约", "异常中心"],
        "external_dependency": "酒店/渠道正式生产连接器与酒店自主供给",
    },
    "FLIGHT": {
        "label": "机票",
        "normal_path": ["搜索", "Fare Family/行李规则", "Prebook", "下单", "支付授权", "PNR/出票", "GO Trips", "改签/退票"],
        "exception_recovery": ["报价过期 fail-closed", "无效 prebook 拒绝", "改签 quote 过期拒绝", "退款保留原支付方式证据", "外部未知状态走 reconciliation"],
        "state_machine": ["PAYMENT_PENDING", "PAYMENT_AUTHORIZED", "TICKETED", "REFUNDED", "FAILED", "UNKNOWN_EXTERNAL_STATE", "MANUAL_REVIEW"],
        "evidence": ["offer", "prebook", "payment method reference", "PNR/ticket", "change quote", "refund record"],
        "operator_surface": ["机票运营", "订单履约", "交易状态与证据", "异常中心"],
        "external_dependency": "航司/GDS/NDC/票台正式生产连接器",
    },
    "RAIL": {
        "label": "铁路",
        "normal_path": ["车次搜索", "席别/余票", "Prebook", "实名乘车人", "下单", "支付", "出票", "改签/退票"],
        "exception_recovery": ["余票变化 fail-closed", "无效 prebook 拒绝", "改签不可用拒绝", "退款证据", "未知外部状态 reconciliation"],
        "state_machine": ["PAYMENT_PENDING", "PAYMENT_AUTHORIZED", "TICKETED", "REFUNDED", "FAILED", "UNKNOWN_EXTERNAL_STATE", "MANUAL_REVIEW"],
        "evidence": ["offer", "prebook", "passenger", "booking reference/ticket", "change quote", "refund record"],
        "operator_surface": ["铁路运营", "订单履约", "交易状态与证据", "异常中心"],
        "external_dependency": "铁路票务正式生产连接器",
    },
    "RIDE": {
        "label": "接送用车",
        "normal_path": ["搜索", "车型/容量", "航班关联", "下单", "确认", "时间修改", "履约", "取消/退款"],
        "exception_recovery": ["不可修改状态拒绝", "重复取消幂等/拒绝", "航班变化进入受控更新", "供应未知状态 reconciliation"],
        "state_machine": ["CONFIRMED", "IN_PROGRESS", "COMPLETED", "REFUNDED", "FAILED", "UNKNOWN_EXTERNAL_STATE", "MANUAL_REVIEW"],
        "evidence": ["offer", "order", "flight link", "supplier reference", "modification", "refund record"],
        "operator_surface": ["接送用车运营", "订单履约", "交易状态与证据", "异常中心"],
        "external_dependency": "接送用车正式生产连接器",
    },
    "RENTAL": {
        "label": "租车",
        "normal_path": ["搜索", "车型", "保险/里程/押金", "下单", "确认", "取还车", "修改", "取消/退款"],
        "exception_recovery": ["不可修改状态拒绝", "重复取消拒绝", "供应未知状态 reconciliation", "押金/履约差异进入异常中心"],
        "state_machine": ["CONFIRMED", "IN_PROGRESS", "COMPLETED", "REFUNDED", "FAILED", "UNKNOWN_EXTERNAL_STATE", "MANUAL_REVIEW"],
        "evidence": ["offer", "insurance/mileage/deposit", "order", "supplier reference", "modification", "refund record"],
        "operator_surface": ["租车运营", "订单履约", "交易状态与证据", "异常中心"],
        "external_dependency": "租车正式生产连接器",
    },
    "ATTRACTION": {
        "label": "景点门票与体验",
        "normal_path": ["搜索", "日期/场次", "库存/人群票", "Prebook", "下单", "电子凭证", "改期", "核销/退款"],
        "exception_recovery": ["库存变化 fail-closed", "不可退产品拒绝退款", "不可改产品拒绝改期", "闭园/供应未知状态 reconciliation"],
        "state_machine": ["CONFIRMED", "FULFILLED", "REFUNDED", "FAILED", "UNKNOWN_EXTERNAL_STATE", "MANUAL_REVIEW"],
        "evidence": ["offer", "eligibility", "inventory", "voucher", "change quote", "refund record"],
        "operator_surface": ["景点门票与体验", "订单履约", "交易状态与证据", "异常中心"],
        "external_dependency": "门票/体验正式生产连接器",
    },
}


def readiness() -> dict:
    verticals = []
    for key in ("HOTEL", "FLIGHT", "RAIL", "RIDE", "RENTAL", "ATTRACTION"):
        spec = VERTICAL_DEPTH[key]
        verticals.append({
            "vertical": key,
            "label": spec["label"],
            "dimensions": [
                {"dimension": "NORMAL_PATH", "label": "正常路径", "requirements": spec["normal_path"], "candidate_state": "CODE_PATH_PRESENT"},
                {"dimension": "EXCEPTION_RECOVERY", "label": "异常恢复", "requirements": spec["exception_recovery"], "candidate_state": "CODE_PATH_PRESENT"},
                {"dimension": "STATE_MACHINE", "label": "状态机", "requirements": spec["state_machine"], "candidate_state": "CONTRACT_DEFINED"},
                {"dimension": "EVIDENCE_CHAIN", "label": "证据链", "requirements": spec["evidence"], "candidate_state": "EVIDENCE_REQUIRED"},
                {"dimension": "HUMAN_OPERABLE", "label": "真人可操作", "requirements": spec["operator_surface"], "candidate_state": "STAGING_BROWSER_REQUIRED"},
            ],
            "external_live_state": "PROVIDER_REQUIRED",
            "external_dependency": spec["external_dependency"],
            "rc20_pass_state": "STAGING_E2E_REQUIRED",
        })
    return {
        "release_target": "RC20",
        "pass_rule": "五维全部有真实证据才允许 PASS；接口/页面/Gate 单独存在均不构成模块完成。",
        "pass_dimensions": [{"dimension": k, "label": v} for k, v in RC20_PASS_DIMENSIONS],
        "verticals": verticals,
        "overall_state": "CANDIDATE_DEPTH_CONTRACT_READY_STAGING_E2E_REQUIRED",
        "external_live_note": "RC20 工程闭环与外部正式生产供给分开验收；未接正式 Provider 不得标记 LIVE。",
    }

SUPPLIER_ROLES = {
    "SUPPLIER_OWNER", "SUPPLIER_ADMIN", "FRONT_DESK", "REVENUE_MANAGER", "FINANCE", "REVIEW_MANAGER", "READ_ONLY"
}
CONSUMER_ROLES = {"CONSUMER"}
ADMIN_ROLES = {
    "GO_GOVERNANCE", "GO_ORDER_OPS", "GO_TRUST", "GO_FINANCE", "GO_CONNECTOR", "GO_RULE_ADMIN", "GO_READ_ONLY"
}

PERMISSIONS = {
    "CONSUMER": {"consumer:read","consumer:write","consumer:book","consumer:wallet"},
    "SUPPLIER_OWNER": {"supplier:read","supplier:orders","supplier:finance","supplier:risk","supplier:review"},
    "SUPPLIER_ADMIN": {"supplier:read","supplier:orders","supplier:finance","supplier:risk","supplier:review"},
    "FRONT_DESK": {"supplier:read","supplier:orders"},
    "REVENUE_MANAGER": {"supplier:read","supplier:orders"},
    "FINANCE": {"supplier:read","supplier:finance"},
    "REVIEW_MANAGER": {"supplier:read","supplier:risk","supplier:review"},
    "READ_ONLY": {"supplier:read"},
    "GO_GOVERNANCE": {"admin:read","admin:orders","admin:trust","admin:finance","admin:connector","admin:rules","admin:approve"},
    "GO_ORDER_OPS": {"admin:read","admin:orders"},
    "GO_TRUST": {"admin:read","admin:trust"},
    "GO_FINANCE": {"admin:read","admin:finance"},
    "GO_CONNECTOR": {"admin:read","admin:connector"},
    "GO_RULE_ADMIN": {"admin:read","admin:rules"},
    "GO_READ_ONLY": {"admin:read"},
}

HIGH_RISK_OPERATIONS = {
    "COMPENSATION", "SUPPLIER_LIABILITY", "BANK_DEBIT", "RISK_FINALIZATION",
    "CONNECTOR_ACTIVATION", "CONNECTOR_SUSPENSION", "RULE_VERSION_RELEASE", "HIGH_RISK_ADMIN_WORKFLOW"
}

def permissions_for(roles:list[str]) -> set[str]:
    out=set()
    for r in roles: out |= PERMISSIONS.get(r,set())
    return out

from __future__ import annotations

import os
import sys
from sqlalchemy import create_engine, text

EXPECTED = os.getenv("EXPECTED_STAGING_HEAD", "0112_ti_p0_20260829").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    print("DATABASE_URL missing")
    raise SystemExit(2)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
with engine.connect() as conn:
    rows = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()

print("alembic_version=" + ",".join(rows))
if len(rows) != 1:
    print(f"R8.2_RDS_LINEAGE_PROBE: BLOCK head_count={len(rows)}")
    raise SystemExit(1)
if EXPECTED and rows[0] != EXPECTED:
    print(f"R8.2_RDS_LINEAGE_PROBE: BLOCK expected={EXPECTED} actual={rows[0]}")
    raise SystemExit(1)
print("R8.2_RDS_LINEAGE_PROBE: PASS")

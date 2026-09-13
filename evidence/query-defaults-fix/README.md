# Query defaults compatibility repair

PRODUCT_FIX / TEST_ONLY. Based on PR66 commit 9f28f822110e187c22baf82391063c8b05c039c1.

The route's four Query objects were Python defaults, so direct calls received metadata rather than values. Move constraints into Annotated and retain ordinary defaults 1, 1, 50, None. Authentication dependencies and SQL/refund logic are unchanged.

Local isolated Python 3.12 / SQLite: original test_admin_hotel_refund_amount_is_real_column passes unchanged (1 test). Existing pagination/search/invalid-input/auth tests plus six direct-call equivalence cases pass (34 tests). Raw JUnit and console output are adjacent. Existing FastAPI 0.128.2 / SQLAlchemy 2.0.50 dependencies were reused through PYTHONPATH.

binding.json records all 1332 application file hashes; only operations_console.py differs from the fixed base. No historical results are promoted to this candidate's PASS. Full regression and remote CI remain separate. No Hong Kong or Production operation, migration, topology or permission change.

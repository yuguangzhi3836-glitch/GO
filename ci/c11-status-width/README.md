# C11 status capacity repair

Change classes: PRODUCT_FIX, MIGRATION, TEST_ONLY.

This independent stacked candidate starts from PR73 source
6c7dd392b61368dcd11addea93dcb0de4ef2042f (the workflow pins the full parent SHA).
It changes only FlightOrderRow.status from 32 to 64 and adds migration
0134_flight_status_width after 0133_flight_change_plan. Existing history is retained.
The original 10-case C11 PostgreSQL driver and process actor are unchanged.
Frozen dependencies are inherited.

Original failure: https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34805831670/job/103857416453
Original artifact: https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34805831670/artifacts/10332554861

Validation includes incremental widening of a simulated existing 0133-shaped flight
table, exact row/index retention, full 35-character status storage, refusal of
unsafe narrowing, and safe downgrade/re-upgrade. This is not a replay of the full
historical migration chain. The original ten process cases run in a separate fresh
schema created from the candidate model. Results must remain separately labelled.

This workflow is scoped to this stacked repair PR. Parent source-fingerprint
manifests and old PASS evidence are preserved unchanged, not rewritten to claim
this new candidate passed parent acceptance. Integration must rebind candidate
manifests and satisfy the broader release gates.

No Hong Kong/Production migration is executed. Existing image 47bb66c4 and its
scoped results remain bound to application tree 995d0d83. This source fix does not
rebuild, replace, deploy, or certify that image. No merge/deployment is included.

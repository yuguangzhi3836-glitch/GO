# DEPTH31 independent evidence — release HOLD

Candidate `b15159167b36fc9db71eb67ff1ad752d9bdc2130`.
Run 34422477135, job 102700695798; test output completed
2026-09-10 00:46:42 UTC (08:46:42 Asia/Shanghai).

Directly inspected original workflow log and decoded its exported JUnit files.
Both JUnit lengths and SHA256 match the producer records. Backend 181 testcases,
frontend 219, zero failures/errors/skips. Source fingerprint matches before and
after execution: 1232 files, tree
`2b9095df2e9a58f8f5ac6861c514163cbbc9e135def204c4e2d5edb65b3f68e0`.

Environment: ephemeral GitHub runner, Python 3.13.5 with repository-frozen
wheels and SQLite TestClient; Node 22.22.0 frontend VM/native pure functions.
Warnings are Alembic legacy path configuration and Node module/deprecation
notices. No browser login, viewport/device test, native build, PostgreSQL,
Redis, live provider sandbox, Hong Kong action or deployment was performed.
Original results from older source trees retain their original scope.

See ACCEPTANCE_LIMITS.json for missing prerequisites and uncompleted scope.
HK_SOURCE_REVIEW.json records missing original task/receipt commits rather
than interpreting unavailable evidence as a failed execution.

Next gate is actual three-role UX/login on an accessible isolated runtime tied
to this exact candidate, with approved test identities and desktop/mobile
coverage. Do not bypass earlier gates or infer deployment authority from CI.

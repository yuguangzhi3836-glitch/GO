# V7 R3 Actual Work-Product Runner Trigger

Recorded: 2026-09-14 +08

Purpose: replace the prior ACK-only `py_compile + heartbeat` worker-start probe with actual task-bound pytest execution for C01-C05 and C07-C12.

This trigger does **not** claim an autonomous coding agent exists. It only starts real task-bound test execution and archives raw Evidence. Any Cell that lacks a fixed candidate or a real coding-agent work product remains incomplete.

Source product anchor: `8ffcde66d36c1bbf849218529ef015f6e81725af`.

Rules:
- preserve inherited PASS;
- actual pytest execution required;
- raw log + SHA256 required;
- test execution alone is not DONE_SCOPED;
- candidate SHA + changed files are still required for a fixed candidate;
- first complete fixed candidate goes C14 -> independent C13;
- FINAL_RELEASE / HK_DEPLOY / PRODUCTION remain HOLD.

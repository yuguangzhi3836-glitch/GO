# Two-connection money diagnostic - 2026-10-03

TEST_ONLY + DOCUMENTATION. Original Codespace, unchanged historical application. Three natural rounds plus artificial-lock calibration: 19 CAPTURE calls. Independently committed AUTH setup, per-movement ledger and unique fulfillment assertions passed.

Natural same-root groups produced blocking samples; different-root group had no sampled blocker. Missing samples do not prove no short wait. Natural calls about 5.7-12.3 ms; calibration excluded. Different workloads are not performance A/B. This verifies observer and narrow business behavior, not the cause of historical 100-actor seconds-scale delay.

Next: correlate scheduling, connection holds and PostgreSQL waits in 20/100 diagnostic; report cold and warmed windows separately; retain original correctness and acceptance thresholds. No product query changes, merge, HK access, deployment, ABBA PASS or capacity claim.

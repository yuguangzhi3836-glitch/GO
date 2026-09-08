#!/usr/bin/env python3
"""Hyatt 10-real-hotel three-generation worker drain and authoritative DB gate.

Generation 1 builds all ten hotels; hotel #1 is force-killed by the dedicated
recovery harness before its real build completes. Generations 2 and 3 explicitly
requeue the ACKED business task and execute the production pipeline again. Each
generation then captures a PostgreSQL-authoritative snapshot of hotel entities,
room entities, durable media ledger state and page/LKG event state. The matrix
cannot PASS unless generation 1->2 and 1->3 show zero proliferation.
"""

# C13 independent acceptance — Draft capability

This is an offline, fail-closed C13-only control-plane candidate. It accepts only
an immutable candidate SHA, application-tree fingerprint and C14 receipt ID.
Runner identity comes from a host-owned qualification registry and must identify
itself as independent of both implementation and C14. The task profile disables
network, providers, payments, deployment and production; only isolated PostgreSQL
and frozen tests are permitted by the installed runner.

It does not install a runner, contain a signing key, dispatch a task, merge a PR,
or modify Hong Kong/Production. Installation requires a separate reviewed action.

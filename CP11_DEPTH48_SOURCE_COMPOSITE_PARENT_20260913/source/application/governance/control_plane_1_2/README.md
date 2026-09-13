# GO Control Bridge 1.2 — read-only candidate

This implementation does **not** certify a connection to Hong Kong. The current
external gate is HOLD: no approved HTTPS endpoint, node credentials or CA file
are available in this workspace. There is no deployment or database-write action.

## Components

`python -m go_hotel.control_plane.server --config /approved/server.json --check`
validates server configuration without opening a listener. Without `--check`, it
binds only `127.0.0.1:4180`; an independently configured TLS proxy must expose the
approved HTTPS endpoint. Node and operator bearer tokens must differ and contain
at least 32 characters. Supply generated secrets through the host's secret store,
never through committed files.

`python -m go_hotel.control_plane.worker --config /approved/node.json --check`
requires CONTROL_API_ENDPOINT, NODE_TOKEN, TASK_HMAC_KEY, CA_PEM and GO_CP_NODE_ID.
The endpoint must be HTTPS; certificate verification is mandatory, redirects are
disabled and each HTTP request has a 10-second timeout. `--check` returns only
CONFIGURED_NOT_CONNECTED; it is not connectivity evidence. Without `--check`, the
worker performs one bounded poll and exits. Missing dependencies produce HOLD.

Operator routes: POST /v1/tasks, GET /v1/tasks/{task_id}. Node routes:
POST /v1/nodes/{node_id}/lease and /evidence. Task submission requires exactly
task_id (canonical UUID), node_id, action, target, ttl_seconds (30–300).
The server and node independently allowlist target names and read-only actions.

Tasks have signed payloads, a 30-second lease, at most three delivery attempts and
an absolute expiry. Receipts bind task hash, node and lease and carry a separate
HMAC signature. Stale/conflicting receipts fail closed. Completed evidence and
node execution results survive process restart in separate SQLite journals.
A lost receipt reuses the completed local result. A crash before local commit can
repeat a **read-only** probe; this is not an exactly-once side-effect system.

Allowed probes: file SHA256 under an approved root; selected docker identity
fields; fixed systemd unit status; fixed HTTPS health endpoint. A successful
identity/status observation does not by itself certify a healthy service.
rds_head_readonly remains HOLD until an approved read-only wrapper is integrated.
Never substitute application metadata creation for a production migration check.

## Required external acceptance

1. Bind the server and HK node to the same approved target inventory and distinct
   credentials; install the endpoint certificate chain through CA_PEM.
2. Submit one runtime identity, one artifact SHA256 and one health task. Archive
   the server task, signed delivery, signed receipt, acknowledgement hash and node
   journal. Compare artifact hash with the sealed delivery manifest.
3. Observe a controlled transport interruption and receipt recovery on the real
   node. Retain timestamps and endpoint identity; isolated TestClient results do
   not satisfy this gate.
4. Resolve the read-only RDS wrapper and actual migration head evidence before
   any release decision. Deployment and production write operations are outside
   this transport's action vocabulary.

Evidence must omit secrets. Protect journal/config paths with host permissions;
retain them across restarts. A missing endpoint, failed task, incomplete receipt,
unconfigured probe or expired task remains HOLD rather than silently succeeding.

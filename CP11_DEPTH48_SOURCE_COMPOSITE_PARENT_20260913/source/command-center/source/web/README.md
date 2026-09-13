# GO AI 指挥中心

Phase 1 web command surface. It is deliberately isolated from the business ECS and does not execute shell commands, deploy code, or hold business-system credentials.

## Security model

- WebAuthn/Passkeys only; no password database.
- HTTPS-only, server-side signed session cookie, secure cookie flags, CSP, strict origin validation in WebAuthn.
- SQLite is local to the command ECS and must not be exposed over the network.
- Tasks are received and approved only. A separate future executor must use least privilege and an explicit approval policy.

## Deploy

Run as `goadmin` with a Python virtual environment. Service configuration is intentionally separate because enabling it requires local sudo confirmation.

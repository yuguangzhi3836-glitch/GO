# Sprint 1U Frontend Security Model

Supplier Console and GO Admin are served by the same FastAPI origin as the Production BFF.

## Production auth path

- Browser code never receives or stores access/refresh tokens.
- `go_access` and `go_refresh` are HttpOnly cookies set by `/bff/auth/*`.
- `go_refresh` is path-scoped to `/bff/auth`.
- `go_csrf` is a non-HttpOnly double-submit cookie; mutation requests copy it into `X-CSRF-Token`.
- Access expiry is handled by `/bff/auth/refresh`, which rotates both the refresh token and CSRF token.
- Supplier tenant scope remains JWT/session-derived; the frontend never supplies `supplier_id` as an authority boundary.
- GO Admin high-risk commands still require maker-checker approval and controlled domain commands.

The frontend must be served same-origin through FastAPI at:

- `/supplier-console/`
- `/go-admin/`
- `/console-assets/`

Do not deploy this frontend as a separate static origin without introducing a dedicated BFF/reverse-proxy design and an explicit origin/CSRF review.

## Browser hardening

Sprint 1U emits CSP, frame denial, MIME sniffing protection, referrer policy, permissions policy, and HSTS when secure-cookie mode is enabled. Inline script/style dependencies are intentionally avoided so CSP does not require `unsafe-inline`.

## MFA / SSO

- TOTP enrollment: `/bff/auth/mfa/setup` then `/bff/auth/mfa/confirm`.
- Corporate SSO uses OIDC Authorization Code + PKCE + state + nonce validation.
- Production should provision admin identities/roles deliberately rather than relying on permissive default role creation.

## Required production configuration

Use TLS and set `COOKIE_SECURE=true`. Replace bootstrap passwords and signing/encryption keys. Configure OIDC only against the approved corporate IdP and run the PostgreSQL security/concurrency CI gates before production activation.

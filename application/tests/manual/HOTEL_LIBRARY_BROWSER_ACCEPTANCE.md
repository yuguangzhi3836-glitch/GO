# Hotel library candidate browser acceptance

This is a reproducible **component integration** harness, not the full supplier
application, a production deployment, or proof of login/authentication acceptance.
It executes the candidate supplier library component extracted verbatim from
`frontend/shared/app.js`, against the candidate FastAPI hotel core/media routes.
Only shell rendering, HTTP adaptation, and supplier authentication are fixtures.

## Run

From `application/`, use the project's Python environment with its normal
dependencies plus `uvicorn` and `Pillow`:

```sh
PYTHONPATH=src python tests/manual/hotel_library_browser_harness.py
```

Open `http://127.0.0.1:8765` in a browser allowed to access the test machine.
The listener is loopback-only. Never deploy this test entry point publicly.
Stop with Ctrl-C. Each process receives a new temporary SQLite database and media
cache. No real hotel data, credentials, orders, or remote writes are used.
The test principal override is confined to the newly constructed fixture app;
the product authentication dependency and application are not modified.

Two synthetic hotels each have two existing room types. The page provides a
source-room JSON fixture and a 1600×900 generated JPEG download. It displays the
SHA256 of the full candidate `app.js`. `GET /fixture-state` returns the actual
service graphs and HTTP request/status history, allowing browser claims to be
checked against persisted state. Source is re-read for every page/script request;
restart the harness whenever Python service or API code changes.

For direct HTTP verification without browser rendering, run:

```sh
PYTHONPATH=src python tests/manual/hotel_library_http_acceptance.py
```

This starts its own Uvicorn listener and tests the real HTTP routes in the same
process with a fresh fixture. Do not run both commands simultaneously on the
same host because both bind port 8765. It reports six named assertions and exits
nonzero on failure. Its output explicitly marks browser acceptance as blocked.

## Scenario checklist

1. Select hotel A, preview a package, select contact information and map its source
   room to an existing room. Preview alone must not write records.
2. Switch to hotel B and verify its room options and hotel identity. Switch back
   and check hotel A's unsaved draft remains associated with A.
3. Confirm only selected fields. Existing mapped room count must remain two;
   hotel's B name, contacts and rooms must remain unchanged.
4. Confirm room import without a complete mapping and verify Chinese feedback,
   no write, and retained input. Confirm a valid mapping and verify re-import
   does not duplicate a room.
5. Upload the synthetic high-resolution file with the fixture rights declaration.
   Confirm decoded dimensions, draft state and original-file readback.
6. Bind the image to the selected property's hero/gallery or selected room.
   Confirm another hotel's room cannot be used.
7. Exercise publication blockers and any successful publication using only the
   synthetic fixture. Record exact stage: uploaded, bound, submitted/reviewed,
   published. Do not equate draft upload or request submission with publication.
8. Inspect narrow/mobile layout and confirm identifiers/internal error codes are
   not shown as user-facing failure messages.

## Current browser limitation

The cloud browser navigation to `http://127.0.0.1:8765` returned
`ERR_BLOCKED_BY_CLIENT` in this run. Therefore browser-rendered interactions,
mobile layout and browser screenshots are **BLOCKED / NOT VERIFIED**. There is
no tunnel, proxy, alternate driver or network-policy workaround. Direct HTTP and
Node component results must be reported separately and cannot replace browser
acceptance.

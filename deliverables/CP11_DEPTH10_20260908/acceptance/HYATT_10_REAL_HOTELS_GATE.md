# DEPTH10 Hyatt 10-real-hotel end-to-end gate

The first real acceptance cohort is selected automatically from the official Hyatt directory output; it is not a hand-authored hotel list. The cohort must include at least 10 distinct official property IDs and, where the directory provides enough diversity, multiple brands/cities and more than one property-page shape.

## Per-hotel evidence

For each hotel preserve:

- official directory URL and directory snapshot SHA-256;
- official property ID, canonical name, city/country and final official property URL;
- discovery/source snapshot identifiers;
- complete official room/suite catalog count and independent parity evidence;
- room facts captured where official evidence exists: area, bed, occupancy, view, floor, amenities;
- room-specific media bindings and hotel-wide media scene coverage;
- zero cross-room image borrowing;
- page/build version and quality-gate result;
- rerun result proving no profile/snapshot/page/task proliferation;
- duration, HTTP request count, retries, omissions and manual interventions.

## End-to-end assertions

1. Directory enumeration can continue by cursor until complete without manual hotel seeds.
2. Re-running the same directory snapshot does not create duplicate chain tasks or duplicate canonical hotels.
3. Snapshot drift during resume fails closed rather than mixing inventories.
4. A failed/incomplete candidate never replaces the last known good page.
5. All ten hotels complete through the durable claim/lease/ACK path; forced interruption is included in the cohort run.
6. Media index writes are atomic/durable before this gate may pass.
7. Real browser validation covers mobile 375/390/430 plus representative tablet and desktop.
8. Hong Kong staging validation is required before release status can become PASS.

## PASS policy

This gate is all-or-nothing for the 10-hotel cohort. Any identity merge error, missing official room type without explicit source evidence, room/media cross-bind, unrecoverable worker loss, duplicate publication, corrupt media index, or unverified browser/HK result is HOLD.

`HYATT_10_REAL_HOTELS_GATE=HOLD` until actual evidence is attached. Synthetic fixtures do not satisfy this gate.

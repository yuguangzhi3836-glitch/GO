# Mobile Privacy / Data Map

GO ID stores only data needed for travel/account functions. Payment card PAN/CVC is never stored by GO; the mobile app must use the PSP's tokenization SDK/API. Device push token is encrypted server-side and can be revoked by unregistering the device. Travel-document data is encrypted and masked on ordinary readback. Access/refresh tokens are stored only with OS secure storage APIs.

Before store submission, map the actual production SDK inventory to Apple Privacy Nutrition Labels and Google Play Data Safety. Do not claim "no tracking" or similar until all analytics/crash/marketing SDKs are finalized and reviewed.

# GO Mobile Store Submission Checklist — Sprint 2C

## Apple / TestFlight
- Paid Apple Developer membership active.
- App Store Connect app record exists before binary upload.
- Production bundle identifier matches signed build.
- Distribution certificate/provisioning or EAS managed signing is valid.
- App Store Connect API key/service credentials configured for CI.
- Privacy policy URL, support URL, app description, age rating and required privacy declarations prepared.
- Production `.ipa` uploaded and processed in App Store Connect.
- Internal TestFlight group configured; first P0 testers installed the build.
- Test notes include staging environment and known limitations.

## Google Play Internal Testing
- Play Console app record exists.
- Android package/application id matches signed AAB.
- Play App Signing / upload key configured.
- Service account/API credentials configured for CI submission where used.
- Internal testing list/group and feedback channel configured.
- Signed `.aab` uploaded to Internal Testing and available to testers.
- Store/privacy/data disclosures required for intended release stage prepared.

## Shared GO release checks
- Version/build numbers are immutable and traceable to Git SHA.
- Staging API URL is not production by accident.
- No mock PSP, mock connector or demo completion endpoint is enabled for production release.
- Push credentials are environment-scoped.
- Universal/App Links are served over HTTPS and bind only GO-owned domains/app identifiers.
- Rollback version and incident contacts are recorded before release.

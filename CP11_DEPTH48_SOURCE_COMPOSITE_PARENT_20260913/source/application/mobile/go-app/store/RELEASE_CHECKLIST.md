# TestFlight / Google Play Internal Release Checklist

## Required credentials
- Expo/EAS project ID
- Apple Developer Team + App Store Connect app record + signing/provisioning
- Google Play service account + Android signing key
- Production/staging APNs/FCM credentials
- Universal Link `apple-app-site-association` and Android `assetlinks.json` on `go.travel`
- Staging and production API URLs over TLS
- Real PSP mobile SDK/tokenization credentials

## Build gates
1. Resolve and commit a reviewed lockfile, then run deterministic dependency install in release CI
2. `npx expo-doctor`
3. `npm run typecheck`
4. mobile contract tests
5. backend + PostgreSQL + Redis integration suite
6. EAS preview builds (iOS/Android)
7. physical-device P0 matrix
8. push receipt lifecycle certification
9. Universal/App Link validation
10. privacy/permission strings and store metadata review
11. EAS production build
12. TestFlight / Play Internal Testing submission

No store promotion is permitted from this repository solely because a build artifact exists; release requires the physical-device and staging gates above.

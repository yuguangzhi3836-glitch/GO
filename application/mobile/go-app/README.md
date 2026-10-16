# GO Consumer Mobile — Sprint 2A

React Native / Expo native product surface for the complete hotel Golden Path.

Implemented screens: Login, Home, Search, Hotel Detail, Prebook/Booking Review, Booking Success, GO Trips, Order Detail, Change, Cancel/Refund, 365-day property-only Stay Credit, Wallet, Notifications, Profile, and GO Truth Quick Review.

Mobile event behavior:
- ORDER_CONFIRMED -> booking success push -> `go://trips/order/{order_id}`
- check-in reminder -> order deep link
- REFUND_COMPLETED -> refund push -> order deep link
- COMPENSATION_COMPLETED -> compensation push -> order deep link
- FULFILLMENT_COMPLETED -> first review invite scheduled four hours after checkout (inside locked 2–10 hour window) -> `go://reviews/{review_id}`
- if still NOT_REVIEWED, authenticated foreground app-open returns one Uber-style blocking Quick Review intent
- if review is COMPLETED, all later review jobs are cancelled / app-open returns NONE

Security: tokens live only in `expo-secure-store`; consumer-owned fare mutations use mobile wrappers that derive account ownership from JWT. Payment remains Authorization -> Supplier Book -> Capture.

## Open the Android project in Android Studio

The native Android project is generated in `android/` from this Expo app configuration.

1. Install Node.js and Android Studio with the Android SDK.
2. From this directory, run `npm ci` to install the locked JavaScript dependencies.
3. Open this directory's `android/` folder in Android Studio and allow Gradle Sync to finish.
4. Select an emulator or connected Android device and run the `app` configuration.

For command-line development, run `npm run android` from this directory. The app uses the configured development API URL by default; set `EXPO_PUBLIC_API_URL` when targeting another API environment.

## Build, install, and share a debug APK

From the repository root, run:

```powershell
.\application\mobile\go-app\scripts\build-install-android.cmd -Launch
```

The script builds a Debug APK with the JavaScript bundle embedded, verifies that bundle, installs it on the connected Android device, and optionally launches the app. The installed APK does not need Metro. The script and app configuration default to `https://staging-api.goaidirect.com`; pass `-ApiBaseUrl http://127.0.0.1:8000` for local WSL testing.

Common options:

| Option | Effect |
|---|---|
| `-DeviceSerial <serial>` | Select a device when more than one ADB device is connected. |
| `-ApiBaseUrl <url>` | Build with the specified `EXPO_PUBLIC_API_URL`. |
| `-OutputPath <file.apk>` | Copy the built APK to this path and print its SHA-256 hash. |
| `-NoInstall` | Build the APK without installing it. |
| `-Launch` | After installation, open the app. For a loopback API URL, configure API port forwarding to the connected device. |
| `-Logcat` | Launch the app and save device logs for 120 seconds. |
| `-LogcatSeconds <seconds>` | Change the log capture duration (10–3600 seconds). |

To build an APK for another tester, bind the publicly reachable HTTPS API URL and skip local installation:

```powershell
.\application\mobile\go-app\scripts\build-install-android.cmd -NoInstall -OutputPath .\application\mobile\go-app\artifacts\GO-consumer-staging.apk
```

The API URL is embedded at build time. The recipient does not enter a URL or build parameter; they install the APK, allow installation from the app they used to open it if Android prompts, and connect to the internet. Do not distribute an APK built with `localhost` as its API URL. This Debug APK is for tester distribution, not app-store release; the Android `release` variant still uses the debug signing configuration. See [the local backend and APK guide](../../../docs/GO_LOCAL_BACKEND_AND_ANDROID_APK.md) for the complete registration and sharing flow.

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

## Build, install, and launch a debug APK

From the repository root, run:

```powershell
.\application\mobile\go-app\scripts\build-install-android.cmd -Launch
```

The script builds the Debug APK, installs it on the connected Android device, and launches the app. On launch it starts Metro when needed and configures `adb reverse` for port 8081. When the API URL is loopback (the default is `http://localhost:8000`), it also forwards that API port to the phone. Keep the Metro process running while using this Debug APK.

Common options:

| Option | Effect |
|---|---|
| `-DeviceSerial <serial>` | Select a device when more than one ADB device is connected. |
| `-ApiBaseUrl <url>` | Build with the specified `EXPO_PUBLIC_API_URL`. |
| `-NoInstall` | Build the APK without installing it. |
| `-Launch` | After installation, ensure Metro is running, configure USB port forwarding, and open the app. |
| `-Logcat` | Launch the app and save device logs for 120 seconds. |
| `-LogcatSeconds <seconds>` | Change the log capture duration (10–3600 seconds). |

For example, select a specific USB-connected phone and API environment:

```powershell
.\application\mobile\go-app\scripts\build-install-android.cmd -DeviceSerial YOUR_DEVICE_SERIAL -ApiBaseUrl https://api.example.com -Launch
```

If the app shows `Unable to load script`, run the build/install script with `-Launch`; it starts Metro when needed and configures the phone's 8081 reverse. If the error remains, inspect the Metro log for bundle errors. A `packager-status:running` response confirms only that Metro is listening. See [the mobile frontend implementation guide](../../../docs/GO_移动端前端代码设计说明.md#93-android-debug-apk-的-metro-加载流程) for recovery steps.

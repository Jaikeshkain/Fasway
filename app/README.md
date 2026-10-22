# Fasway – Android app

Native Flutter app for Fasway: the same features as the web app, plus what a browser page can't do.

| Feature | Notes |
|---|---|
| Pair by **scanning the QR** in the Fasway window | The app pins the laptop's certificate fingerprint from the QR, so there is no "Not secure" warning and an impostor can't pretend to be your laptop |
| **Finds the laptop by itself** on any Wi-Fi | Android network service discovery (`_fasway._tcp`); falls back to the last known IPs, then `fasway-<id>.local` |
| Touchpad, Keyboard (live typing), Voice (Hindi / English / Hinglish), Apps, Controls | Same messages as the web app (`web/app.js`) |
| Screen preview with laptop sound | `flutter_webrtc`. Sound plays as media (speaker / Bluetooth). Full screen is real Android immersive landscape |
| Clipboard | Laptop → phone copies into the phone clipboard reliably (the browser often couldn't) |
| Screen stays on while the app is open | `FLAG_KEEP_SCREEN_ON` in `MainActivity.kt` |

## Build

Toolchain (installed under `E:\dev`): Flutter SDK, Android SDK (platform 36, build tools, NDK 28.2), JDK 21.

Every release goes through the build script. It raises the version (one version for the phone app and the
laptop app, in `pubspec.yaml` and `fasway/version.py`) and names the APKs after Fasway:

```powershell
cd app
.\tool\build_apk.ps1           # fixes / small changes: 1.1.0 -> 1.1.1
.\tool\build_apk.ps1 -Minor    # new features:          1.1.1 -> 1.2.0
```

The APKs land in `app/dist/`: `Fasway-v1.2.0-arm64.apk` is the one almost every phone needs (`-arm32` for old
phones, `-x86_64` for emulators). The version is shown in the app's Settings and in the laptop window.

## Install on the phone
- **USB / wireless debugging:** `adb install -r dist\Fasway-v1.2.0-arm64.apk`.
- **Without a cable:** copy the APK to the phone (Drive, WhatsApp, USB) and open it. Android will ask you to allow installs from that app once.

## Tests

```bash
flutter test                         # QR parsing
flutter test test/connection_test.dart --dart-define=FASWAY_TEST_FP=<fingerprint>
```

The second command also runs the live tests: pinning, pairing, trusted login, impostor refused and stranger rejected. They run against a Fasway test server on port 18470 that prints its certificate fingerprint.

## Layout
```
lib/core/   laptop (QR), identity (phone key), discovery (mDNS), connection (pinning, pairing,
            reconnect), settings, app_state
lib/ui/     connect_screen, home_screen, touchpad_tab, keyboard_tab (+ live_typing),
            voice_tab, apps_tab, controls_tab, screen_preview (WebRTC + gestures), settings_sheet
```

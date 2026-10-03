# Universal Text Extractor

A small native Android utility for copying text that is visibly rendered on the screen. It uses Android's user-approved **MediaProjection** screen-capture flow and bundled, on-device ML Kit OCR. It does not read app databases, accessibility nodes, hidden text, or server content.

## Build and install

Requirements:

- Android Studio (current stable) or JDK 17 and Android SDK Platform 35
- Android Gradle Plugin 8.7.3 / Gradle 8.9 (the included `gradlew` bootstraps Gradle 8.9 on first use)

Open this repository in Android Studio and sync Gradle, or run:

```sh
./gradlew assembleDebug
./gradlew testDebugUnitTest
```

Install the debug APK at `app/build/outputs/apk/debug/app-debug.apk`. The app supports Android 8.0 (API 26) and newer. The bundled ML Kit models are included in the APK, so OCR can work offline; the first build downloads normal Android/Gradle dependencies from Google Maven and Maven Central.

## Using it

1. Open **Universal Text Extractor** and tap **Extract Text**, or start from another app using the Quick Settings tile or optional floating button.
2. On first use, review the explanation; then approve Android's screen-capture prompt. Later launches go straight to Android's prompt. Android may offer a full-screen or single-app capture choice, and consent is requested for every capture.
3. The app returns to the screen being captured, reads one frame, runs OCR locally, and opens the editable result if the app is in the foreground. When started from another app, tap the result notification to review it.
4. Select text normally in the editor. Use **Copy** for the selection, **Copy all**, **Share**, or **Save edits to history**. The original OCR result is added to local history automatically.

To add the tile, expand Quick Settings, tap **Edit**, then drag **Extract text** into the active tiles. To use the floating shortcut, go to **Settings → Floating button**, then enable the named service in Android Accessibility settings. You can hide the shortcut in the app or disable the service from Android settings at any time. Accessibility is optional: Home capture and the Quick Settings tile do not require it.

## Architecture

- `CapturePermissionActivity` explains the request and launches Android's MediaProjection consent UI.
- `CaptureService` runs as a short-lived media-projection foreground service and captures one frame using `ImageReader`/`VirtualDisplay`. It stops the projection immediately after that frame.
- `OcrEngine` is the replaceable OCR boundary. `MlKitOcrEngine` currently runs bundled Latin and Devanagari recognizers. The preprocessing stage trims only small flat borders, scales to a bounded image size, applies grayscale/contrast, and has optional thresholding (off by default to preserve antialiased glyphs). Filtered scaling also reduces minor capture noise.
- `ReadingOrderFormatter` merges duplicate detections and approximates lines/paragraphs from OCR bounding boxes.
- Room stores extracted text locally in `extractor_history.db`. Screenshots are never written to disk. There is no `INTERNET` permission, analytics, or remote OCR endpoint.
- The optional `FloatingAccessibilityService` only draws and drags a `TYPE_ACCESSIBILITY_OVERLAY` button. It declares `canRetrieveWindowContent=false` and intentionally ignores accessibility events. The Quick Settings tile and notification action launch the same explicit consent flow.

## Permissions and privacy

- **MediaProjection consent:** required by Android for every screen capture. The system prompt is controlled by Android; the app cannot silently capture.
- **Accessibility service (optional):** used only to display the floating trigger. It does not inspect accessibility nodes, key input, or screen text. The app remains usable without it.
- **Notifications (optional):** used to reach results when capture starts from another app and to offer “Review” / “Extract again” actions. Extracted text is not included in notifications.
- No storage, contacts, microphone, camera, or network permission is requested. OCR is on-device. The captured bitmap is held temporarily in memory and discarded after OCR; only text is persisted in local history. Clipboard and sharing happen only when the user chooses them.

## Limitations and safe use

- Android secure-window and DRM-protected regions can be blacked out or excluded by the system. This app does not and cannot bypass those protections.
- Some apps prohibit capture, and some Android versions/device vendors limit whether an entire display or only one app can be selected. If Android blocks a screen, respect that restriction.
- OCR accuracy varies with resolution, language/script, font, contrast, animation, and screen layout. The bundled models cover Latin-script text (including English) and Devanagari-script text (for example Hindi and Marathi); they do not currently cover every Indian script. `OcrEngine` is the extension point for additional on-device models.
- Reading order is approximate, particularly for multi-column layouts, tables, vertical text, and mixed scripts. Review and edit text before using it.
- A conservative text check declines obvious password/sign-in/verification screens, but it cannot identify every sensitive screen. Do not use the utility to extract passwords, authentication codes, payment secrets, or content you are not entitled to view.
- Screen contents can include personal information. History stays on-device but is not encrypted separately from Android's app sandbox; delete entries from History or Settings when no longer needed.

## Test notes

Unit tests cover OCR line ordering/cleanup and the authentication-screen guard. Device testing should also verify projection consent and cancellation, secure-window behavior, Quick Settings setup, notification permission denial, optional Accessibility toggle, rotation, and OCR on the specific scripts/device models you intend to support.

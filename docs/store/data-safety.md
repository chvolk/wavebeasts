# Play Console: Data safety, permissions and policy declarations — WaveBeasts 0.13.0

Based on `android/app/src/main/java/net/wavebeasts/app/MainActivity.java`, the `play` flavor
manifest, `templates/privacy.html`, and the Play Billing integration. Re-check whenever a
permission or endpoint changes.

## Overview questions

| Question | Answer |
|---|---|
| Does your app collect or share any of the required user data types? | **Yes** |
| Is all of the user data collected by your app encrypted in transit? | **Yes** (HTTPS to wavebeasts.com; the engine's own API is loopback only) |
| Do you provide a way for users to request that their data is deleted? | **Yes** — in-app (Account › Delete my online account) and https://wavebeasts.com/me/delete |
| Account creation | App lets users create an account (web sign-in via Chrome Custom Tab). Deletion URL: https://wavebeasts.com/me/delete |

"Collected" below means sent off the device to wavebeasts.com. Nothing is sent unless the user signs
in; local play is fully offline. Nothing is shared with third parties other than the processors
listed (hosting provider, Google Play Billing).

## Data types

| Data type | Collected? | Shared? | Optional? | Purpose | Notes |
|---|---|---|---|---|---|
| **Location › Approximate** | Yes | No | Yes (only when signed in and submitting a scan) | App functionality | Scans include coarse-binned position for the beast generator; raw coordinates are never stored. |
| **Location › Precise** | Yes | No | Yes | App functionality | Fine location permission is needed by Android to read nearby Wi-Fi networks. Treated as above. |
| **Personal info › Name** | Yes | No | Yes (account only) | Account management | Display name from the identity provider. |
| **Personal info › Email address** | Yes | No | Yes (account only) | Account management | Shown in the Account tab. |
| **Financial info › Purchase history** | Yes | Yes (Google) | Yes | App functionality (entitlement) | Google Play purchase token and subscription status; Google is the payment processor. No card data. |
| **App activity › In-app actions** | Yes | No | Yes | App functionality | Scans submitted, beasts caught/traded, battles, shop purchases, activity receipts. |
| **App info & performance › Crash logs** | No | — | — | — | No crash reporting SDK. |
| **Device or other IDs** | Yes | No | Yes | App functionality | Wi-Fi BSSIDs (router hardware ids) and Bluetooth addresses seen in a scan, as scan entropy. Also a per-device random node token the user creates. No advertising ID, no IMEI. |
| **Photos and videos** | No | — | — | — | Camera frames are decoded on-device for barcodes/QR; only the decoded text (or a perceptual hash for "image" mode) is used. No images leave the device. |
| **Messages, Contacts, Calendar, Audio, Files, Health, Web browsing, Search history** | No | — | — | — | — |

Data handling: all collected types are **not** processed ephemerally (they persist in the account),
**are** deletable (account deletion), and are **not** used for advertising, analytics, personalization
or fraud prevention beyond rate limiting.

## Permissions declaration

| Permission | Why | Console answer |
|---|---|---|
| `CAMERA` | Scan barcodes/QR and capture image features for a scan. On-device only. | Core functionality |
| `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION` | Android requires location to list nearby Wi-Fi networks, which are a scan signal; optional GPS gives a coarse geo signal. Only in use while the app is open; no background location. | Core functionality; **no** background location |
| `ACCESS_WIFI_STATE`, `CHANGE_WIFI_STATE` | Trigger and read Wi-Fi scans for signal entropy. | — |
| `INTERNET` | Loopback engine + optional account sync and Play Billing. | — |
| `POST_NOTIFICATIONS` | Persistent "engine running" notification for the foreground service; opens Scan. | — |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE` | See justification below. | Special use |
| `com.android.vending.BILLING` | Added by the Play Billing Library. | — |

Not requested: `READ_PHONE_STATE` (removed in 0.13.0), `REQUEST_INSTALL_PACKAGES` (sideload build
only, absent from the Play build), background location, storage.

### Foreground service (specialUse) justification — paste into the console

> WaveBeasts bundles its game engine as a local HTTP server on 127.0.0.1 that renders the game UI and
> runs optional, user-enabled automatic "sweeps" every 30 minutes that read ambient sensors and
> generate creatures. The foreground service keeps that engine process alive while the user plays in
> other apps so (a) the opt-in automatic sweep continues and (b) companion apps on the same device can
> reach the engine's loopback API, which the app documents for integrators. A visible, dismissable
> notification with a Stop action is shown the whole time. None of the predefined foreground service
> types (mediaPlayback, location, dataSync, etc.) describe a locally hosted game engine serving a
> loopback API; the service does not use location or sync remote data on its own.

Video demo requested by the console: record Scan tab → toggle AUTO on → background the app → show
the persistent notification and the Stop action → return and show the auto-sweep history.

## Other policy forms

| Form | Answer |
|---|---|
| Ads | No ads |
| App access | All features available without special access except Premium, which needs a Google Play test subscription; provide a license-tester Google account in the "App access" notes. |
| Content rating (IARC) | Game; fantasy/cartoon violence (creature battles, no blood); no sexual content, profanity, drugs, gambling, or realistic weapons; users can interact (trading offers, no free-text chat); shares location (coarse) with the developer only when signed in; digital purchases: yes. |
| News app | No |
| COVID-19 contact tracing | No |
| Data safety → Security practices | Encrypted in transit; users can request deletion; independent security review: No |
| Government apps | No |
| Financial features | None (no loans, payments between users use in-game currency only) |
| Health | No |
| Target audience | 13 and over (adult-only "18+" not required). Not designed for children. |
| Families policy | Not participating |

## Deep links to verify after upload

Digital Asset Links statement: https://wavebeasts.com/.well-known/assetlinks.json must list the Play
App Signing certificate SHA-256. If Play re-signs with a different key than
`06:5F:AC:93:8F:94:73:31:00:E9:0E:92:F5:AA:42:A2:50:F5:2C:43:A6:BB:F1:DF:64:A9:07:26:CF:B5:AE:FB`,
add that fingerprint to `ANDROID_CERT_SHA256` (comma-separated) on Railway.

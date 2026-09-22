# Account, paid features, PWA, wiki and camera validation

Validated 2026-09-21 for standalone Android 0.12.1 (version code 20).

## Implemented

- Website favicon, touch icons and install icons derive from the app's red-eyed waveform mark.
- World validates link codes before saving and displays account email, name, plan, balances,
  beast count and device usage. Failed relinking preserves the previous link.
- Root-scoped manifest/service worker, standalone display, maskable Android icon, Apple touch
  icon and safe-area layout. Download page offers installation and iOS instructions.
- Thirteen separate wiki pages, grouped navigation, prominent AI setup, downloadable/copyable
  prompts for the account listener and the full local engine. Legacy manual anchors redirect.
- Camera detection automatically stages the full code, shows a truncated “Code grabbed” preview,
  closes the overlay and stops media tracks. Late detection after cancellation is ignored.
  One typed input and one camera input are allowed; repeated manual types replace their slot.
  A camera capture without a detected code no longer silently substitutes a photo.
- Paid fixes: closed listings can reopen; unlisting refunds pending offers; listed/offered beasts
  cannot be released; transfers remove old Buddy/team/ladder references; boosts extend; lapsed
  subscriptions cannot compete; Buddy rewards/care run transactionally; unsigned webhooks are
  rejected when production signing configuration is missing; mutations require POST.

## Checks

- Django suite: 74 tests, including isolated paid workflows and real Go resolver integration.
  Command: `WB_INTEGRATION_RESOLVER=http://127.0.0.1:18779 .venv/bin/python manage.py test play --noinput`.
- Go: `go test ./...`, plus native engine build; link validation, redirect handling and account relay tests.
- Real Stripe **test-mode** monthly/annual Checkout creation and expiration, plus customer portal
  creation. Temporary customer deleted; no payment submitted. Signed webhook lifecycle tests
  cover activation/cancellation locally; a completed hosted payment and live webhook delivery
  were not exercised.
- Persistent Chromium context: zero manifest/installability errors; service worker controls page;
  offline navigation shows reconnect page; cache contains only public offline HTML; reconnection works.
- Real local Django + Go account relay: fixture account email/plan/device visible; invalid relink rejected.
- Playwright at 390px: all 13 wiki pages fit viewport; legacy AI link redirects; clipboard prompt works;
  no JS errors. Camera tests use simulated media/detector: auto-close, track stop, exact full code,
  safe truncated text, replacement, cancellation and no-detection behavior pass.
  Reusable test: `scripts/check-browser-ui.py` (Playwright/Chromium; disposable services on 18080/18780).
- Android ARM64/ARMv7 engines and APK assembled successfully with SDK 35 and Gradle 8.9.
- Shared brand assets match via `python scripts/sync-ui-brand.py --check`.

## Device limits

Physical iOS/Android installation and real camera decoding were not available in this environment.
Chromium installation criteria and browser behavior were checked; this is not a claim of a physical
Safari/WebView test. The online site requires a connection for account/gameplay operations; its PWA
offers an offline reconnect screen. The standalone app has the separate local game engine.

iOS install guidance follows [WebKit's Home Screen documentation](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)
and [Safari 26 web app changes](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/).
Android manifest checks follow [Chrome's installability guidance](https://developer.chrome.com/docs/lighthouse/pwa/installable-manifest).

## 0.12.2 follow-up

The large generated shop illustration was removed from both bundled asset sets. A hand-drawn
96×64 vector pixel sprite now supplies the cart, hooded keeper, blink/breathing and lantern idle;
reduced-motion disables animation. There is no “Strange company” tagline.

Wild account sightings expose their deadline/lifetime through the API and the local `/node/beasts`
relay. Website and standalone Beasts views show a bar and live HH:MM:SS / MM:SS countdown.
Zero disables catch controls; server-side web catches reject expired sightings without consuming
inventory. Legacy sightings receive a deadline based on their original creation time.

77 Django tests pass, including expiry API/page parity, legacy deadlines and expired catches.
Go tests and browser checks pass for the account relay, live decrement, zero state, responsive shop,
and the three-desktop/two-mobile download layout. The social card is a 1200×630 PNG rendered from
the existing pixel font and vector logo; OG/Twitter URLs use the canonical HTTPS site URL and a
new filename. Regenerate with `scripts/render-social-card.py`.

The iOS simulator test initially exposed XcodeGen overwriting the release version with 1.0/build 1;
explicit generated-plist properties now preserve 0.12.2/build 21. iOS uses Apple Vision as a fallback
when WKWebView lacks BarcodeDetector, with a generated-QR decoding test. Sensor/camera bridge
messages are restricted to loopback content, and external account links open outside the local web view.

Final iOS validation: [GitHub Actions run 35670673473](https://github.com/chvolk/wavebeast/actions/runs/35670673473)
passed the device build and both simulator tests: embedded engine/current shop/countdown/version,
and exact QR decoding. Vision's current request revision returned no result for a valid QR fixture
on this runtime; the compatible request revision plus Core Image QR fallback passes. The public
`wavebeast-ios-unsigned.ipa` contains version 0.12.2/build 21 and still requires personal signing.
Physical camera capture, sensor readings and device installation were not exercised by the simulator.

## 0.12.3 discovery controls

Website and standalone Beasts cards allow dismissal of queued wild sightings. Standalone cards
also catch directly through the account relay. Both interfaces list only capture drives with positive
account inventory, including quantities; an empty bag shows a supply link and keeps dismissal available.
After any attempt the standalone queue reloads authoritative stock. Dismissal consumes no inventory,
and owned or another user's beasts cannot be dismissed. Catch and dismiss transactions lock the
sighting; catching also locks inventory. Non-drive items and stale stock are rejected without spending.
Expired catch controls disable independently of Dismiss.

Validation: all 83 Django cases passed across the default suite (80 passed, 3 integration cases skipped)
and the explicit real-engine integration run (3 passed); Go tests pass. Browser tests against real local
Django/Go services verify website drive filtering, spending the last drive, refreshing all native cards,
both dismissal routes, mobile layout and zero script errors. Only isolated fixture accounts were used.

Android 0.12.3/build 22 assembled successfully. iOS device compilation and both simulator tests
passed in [run 35673199889](https://github.com/chvolk/wavebeast/actions/runs/35673199889);
the unsigned IPA metadata was verified as 0.12.3/build 22 before publication.

## 0.12.4 selected-host authority and manual Premium web scanner

The engine's standard gameplay routes now use the selected account/engine for wallet,
inventory, collection, purchases, catches, training and scans. `/host` identifies the authority;
`/state` returns its combined state. Existing local saves remain intact and are never silently
used on an account/network failure. The shared GUI shows/change hosts and refreshes visible state.
Omnitool now defaults to wavebeasts.com and explicitly supports a self-hosted URL or the standalone
app's selected host. Its scanner, bag and collection share one client selection.

Premium `/scan/` uses camera permission, local perceptual image hashing/palette extraction, QR/barcode
recognition (vendored ZXing fallback), optional actual orientation readings and manual submission.
No image endpoint, image upload or automatic browser scanning was added. Session auth + CSRF + the
paid gate protect submission; a single browser node shares cooldown across tabs and normal node quota.

Validation:
- Django: 89 discovered, 86 passed, 3 opt-in skipped; those 3 real-Go integration cases separately passed.
- Go: full tests and vet passed, including shared remote stores, linked account purchases/scans,
  preserving the local database, failed host replacement and no fallback on outages/auth/payment errors.
- Flutter: changed-file analysis clean; 20 isolated client/Buddy regression tests passed. A real Dart
  client switched between direct account access and the engine's API and observed identical currency,
  drives, beasts and cooldown after mutations in both directions.
- Playwright: the shared GUI bought supplies, dismissed sightings and trained a beast; two linked
  engines agreed with account state. Mobile layout and JS-error checks passed.
- Playwright: a chosen image emitted only a compact hash/palette/dimensions JSON payload; a real QR
  camera fixture decoded with the native detector disabled, displayed code grabbed and stopped all
  tracks. Late camera permission after cancellation stopped its tracks. No automatic submissions.
- Real browser session/CSRF submission used the Go resolver and shared the resulting wallet with the
  engine; another browser tab saw the same cooldown.

Android standalone 0.12.4/build 23 and Omnitool build 0921-1913 compiled successfully. Physical device
camera/sensor acceptance remains outside these browser/API checks. iOS CI result recorded below.

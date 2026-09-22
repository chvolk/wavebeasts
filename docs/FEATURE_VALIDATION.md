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


Final compatibility patch: **0.12.5/build 24** preserves the existing `/buddy` `individual_id`
contract through the selected account, including explicit unslot and malformed-input rejection.
Its regression also checks that `/beast/release` retains the distinct `id` request field.
Go tests/vet and rebuilt Android + six desktop targets passed. Both real QR and Code 128 barcode
camera fixtures decoded without native BarcodeDetector support. Updated binaries replace 0.12.4.

Final iOS CI run **35679500246** at engine commit `913c7da` passed device compilation and
both simulator tests (including the host-chooser visibility assertion). Published unsigned IPA
is 0.12.5/build 24, SHA-256 `7ebdf3ad9c6a1197c1dbec0932557050bbdb41185eb6c9e27366a77776921957`.
Final Android APK SHA-256 is `8e2806578ffa09a818016ef62dd428ac533ab7fee43cf6cb68cf03b8acfe981f`.
Final Omnitool build **0921-1924** includes host-specific offline instructions and protected engine
sprite requests. Its published updater manifest includes size and checksum. The final engine's
legacy Buddy slot/read/unslot and beast release also passed against real disposable Django data.
Railway confirmed the application deployment successful, and the live scanner JavaScript matched
source exactly. All test accounts/data were isolated; production wallets and inventories were untouched.

## Scan discovery and gym overhaul (2026-09-22, local changes)

Premium Scan now lists the latest 100 available node/app/browser beast discoveries and 100
submission records, scoped to the signed-in account with private/no-store responses. Beast search,
rarity/type filters and newest/rarity/level/type/name ordering are available on Scan and Beastiary;
activity filters by device/outcome and sorts newest/oldest. The standalone app filters before scan
pagination and now includes rarity, level and shiny badges on account sightings.

The Go resolver owns gym scaling and combat. Gyms require a complete three-beast opposing team;
levels track the strongest selected beast, later slots gain `slot * level / 40` levels (cap 100), and
IVs are 16. Seeded speed ties remove the fixed challenger advantage, and a 0.65 damage multiplier
reduces burst damage across shared combat. No persistent-health mechanic was added.

Structured events identify attacker/defender by side and slot, with damage, remaining/max HP and
fainting. Site and standalone replays use actual rendered beast sprites, attack/hit animations,
then HP updates and log rows, revealing the verdict last. Skip and reduced-motion are supported.
Full sprite payloads are requested only for gym/interactive replays, not routine ladder/scan battles.
Deploy the updated resolver alongside the site to enable the new replay contract.

Validation:
- 103 Django tests: 100 passed in the default suite; three opt-in real-engine tests separately passed.
- Full Go suite and vet passed; native engine builds. Tests cover deterministic replay/HP consistency,
  opponent scaling without modifying source individuals, incomplete-gym rejection and sprite payloads.
- 120 seeded balance fixtures at levels 1/10/30/65: damage taken in all fights; full teams won 53/120,
  solo beasts won 0/120; average 14.8 rounds. These are synthetic fixtures, not live-player telemetry.
- Chromium at 390px against disposable Django/Go services: private scan feed, rarity sorting/filtering,
  name search, no horizontal overflow, account rarity badges, actual site/app gym sprites, animation
  before log rows, delayed verdict, skip and battle-button recovery; no script errors. Standalone
  collection/detail fixtures were supplied through intercepted API responses; battles used the real
  Go resolver. Production accounts, inventory and databases were not used.
- Shared brand copies match. No commit, push, production deployment or native APK/IPA release made.

Native build follow-up: the standalone Android preview compiled successfully on Aphrodite in
`~/dev/wavebeast-discovery-preview`, isolated from the regular build checkout. Artifact:
`../wavebeast/dist/wavebeast-discovery-preview.apk` (13,485,402 bytes; SHA-256
`a9e6f3f156ad2c224ea11666bdcf4e5c7a284d9f76120a48e76cc4d2629fc7be`). Android
`apksigner verify` passed; remote/local hashes match. ZIP integrity, ARM64/ARMv7 ELF architectures,
and inclusion of the new filters/replay UI in both bundled engines were verified. This preview
retains version 0.12.9/build 28; release versioning and physical-phone acceptance remain pending.
The site resolver also cross-compiled to `../wavebeast/dist/wavebeast-linux-amd64-discovery-preview`
(SHA-256 `cdb208a90c38dd38d569f5a7bf77b69ce87dc8251bce157e6a2adb8e26498220`).
Artifacts are local; public downloads and production services remain unchanged.

## 0.12.10 release (2026-09-22)

User authorized publishing the app and live site. Android version 0.12.10/build 29 was rebuilt,
signature-verified and published with the six desktop/server engine binaries. APK SHA-256:
`1071e444faf495a8a8771bf8ce9dcf2f1122670b9996a0727dfde5bf5833ed83`.
Linux amd64 resolver SHA-256: `cdb208a90c38dd38d569f5a7bf77b69ce87dc8251bce157e6a2adb8e26498220`.
Engine source commit: `3b14442`; iOS build/test run: `35764448423`.
The site increments its Android update manifest to build 29 and busts the Docker resolver cache
with `ENGINE_REV=2026-09-22-discovery-gym-0.12.10`. Go tests and 30 focused Django checks passed
again for the release. Production deployment verification is recorded in the release follow-up.

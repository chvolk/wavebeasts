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

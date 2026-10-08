# Android general-release plan (Google Play) — target 0.13.0 / build 38

Scope: ship the standalone Android app on Google Play with in-app sign-in, an in-app account
screen, and Premium purchased through Google Play Billing, while keeping the existing sideload
channel and the website's Stripe billing working. Repos: `~/Code/wavebeast` (engine + Android
shell + GUI) and `~/Code/WaveBeasts` (site). Both currently on `release/discovery-gym-0.12.10`.

## Where we are

- The published APK is `assembleDebug`, debug-signed, built remotely on Aphrodite by
  `scripts/build-android.sh`. No keystore or `signingConfig` exists. There is an in-app APK
  self-updater using `REQUEST_INSTALL_PACKAGES`.
- Account linking = paste a node token copied from the website. Sign-in is Clerk (web only).
  Premium is Stripe Checkout on the website; `Wallet.subscribed` gates paid features.
- `WBNative` is a synchronous JS bridge (sensors + `ensurePerms`). The GUI is the engine's
  embedded `index.html`, shared with desktop; `body.native-app` switches to bottom tabs.
- Externally-targeted links (`window.open`, `target=_blank`) are dead inside the WebView: no
  `shouldOverrideUrlLoading`, no multiple-window support.
- Manifest: global cleartext allowed, `allowBackup=true`, `READ_PHONE_STATE`, fine location,
  `specialUse` foreground service, no `strings.xml`, hardcoded label.

## Decisions (recommended defaults; confirm before Phase 0)

1. **One release key for both channels.** Generate a release keystore (kept out of git, on
   Aphrodite + offline backup), and enrol it with Play App Signing as the *app signing key*
   ("use existing key"), so Play installs and sideload installs share a certificate and can
   upgrade each other. Existing debug-signed sideload users reinstall once; the site's download
   page and the `/api/app/version` notes say so for one release.
2. **Two product flavors, same `applicationId`.** `play` (Play Billing, no self-updater, no
   install-packages permission, updates point to the store) and `sideload` (current updater).
   Flavor is exposed to the GUI via `WBNative.channel()`.
3. **Premium on Play = same offer.** One subscription product `premium` with base plans
   `monthly` ($5) and `annual` ($50). Google's cut is absorbed; price parity avoids steering
   complaints. An account has one billing provider at a time (`stripe` or `play`).
4. **Sign-in via Chrome Custom Tab + one-time link code**, not Clerk inside the WebView (Google
   OAuth blocks embedded WebViews). The site mints an `app` node and a 5-minute one-time code;
   the app exchanges it for the node token through the engine. Return path is an Android App
   Link (`https://wavebeasts.com/app/callback`) with `wavebeast://link` as fallback, both
   bound to a client-generated `state` nonce.
5. **Account deletion in-app and on the web.** Play requires it for apps that create accounts.
6. **No third-party crash/analytics SDKs.** Privacy policy promises none; use Play vitals.

## Phase 0 — Release build foundation (wavebeast repo)

- `android/app/build.gradle`: `signingConfigs.release` read from `keystore.properties` (gitignored)
  or `WB_KEYSTORE_*` env; `buildTypes.release` uses it; `productFlavors { play; sideload }`
  with `dimension "channel"`, `buildConfigField "String", "CHANNEL"`.
- Bump `compileSdk`/`targetSdk` to the current Play requirement (verify; expected API 36 for
  updates after Aug 2026). Bump AGP/Gradle on Aphrodite as needed. Add `strings.xml`
  (`app_name`, notification strings), `backup_rules.xml`/`data_extraction_rules.xml` excluding
  `wavebeast.db` and metas (node token), `allowBackup=false` as the simple alternative.
- Network security config: cleartext permitted for `127.0.0.1` only in `play`; `sideload` keeps
  user-entered LAN engines working (verify whether any WebView request, e.g. sprite URLs for a
  self-hosted host, needs cleartext; relay through the engine if so).
- Permissions: drop `READ_PHONE_STATE` (keep signal bars via `getSignalStrength`, drop 2G–5G
  label). Keep camera, fine/coarse location (Wi-Fi scan), notifications, FGS. Write the
  `specialUse` FGS justification for the Play Console (local game engine server on loopback,
  background auto-sweep, companion apps).
- Manifest per flavor: `REQUEST_INSTALL_PACKAGES` + FileProvider only in `sideload`.
  `MainActivity.checkForUpdate` in `play` opens the Play listing instead of downloading an APK.
- Splash: Android 12 SplashScreen theme attrs + a native loading view until the first successful
  page load (today: dark blank for the engine warm-up).
- `shouldOverrideUrlLoading`: anything not `127.0.0.1` opens in a Chrome Custom Tab
  (`androidx.browser`). Also fixes the dead wiki/site links.
- `scripts/build-android.sh`: build both `bundlePlayRelease` (AAB) and `assembleSideloadRelease`
  (APK); run `apksigner verify`; check 16 KB page-size compliance of `libwavebeast.so` on arm64
  with `readelf -lW` (Go rounds arm64 segments to 64 KB; confirm on the actual binary).
- Version sync: `build.gradle`, `internal/api/updates.go`, site `play/appversion.py` → 0.13.0/38.
  Extend the existing version test if the flavor adds a field.

## Phase 1 — Sign-in and in-app account (site + engine + GUI)

**Site (`WaveBeasts`)**
- `LinkCode` model: `code` (random, unique), `node` FK, `state`, `expires_at`, `used_at`.
- `GET /app/connect?state=&device=` (`@login_required`; sign-in must honour `next` → add `next`
  passthrough to `sign_in`/`auth_clerk`/`auth.html`). Page: "Connect *device* to *account*?"
  with Connect/Cancel. On POST: node-limit check, create `Node(kind="app", name=device)`, mark
  wallet onboarded, create `LinkCode`, redirect to
  `https://wavebeasts.com/app/callback?code=&state=` (App Link; page body also offers a
  `wavebeast://link?code=&state=` button for devices where the App Link isn't verified).
- `POST /api/app/link/exchange {code, state}` → `{token, site, node}`; single use, expiry
  enforced, constant-time compare.
- `POST /api/account/delete` (node-token auth, requires `{confirm: "DELETE"}`) and web
  `/me/delete` (POST, confirm). Cascade is already FK-driven; cancel Stripe subscription first
  (`stripe.Subscription.cancel`) and, for Play, note that Google manages cancellation; delete
  the Clerk user via backend API when `CLERK_SECRET_KEY` is set.
- `/.well-known/assetlinks.json` served with the release cert SHA-256 (settings-driven).
- `api_account` gains `billing_provider`, `renews_at`/`expires_at`, `manage_url` (Stripe portal
  URL only when provider is stripe and the caller is not the Play channel).
- Terms: replace "may be offered in the future" with live subscription terms incl. Google Play
  purchases/refunds; Privacy: mention Google Play purchase tokens.

**Engine (`wavebeast`)**
- `POST /node/config` accepts `{site, code, state}` as an alternative to `token`: performs the
  exchange, then the existing validation path. Return the account summary on success.
- `GET /node/account` passes new fields through (no change needed if it's a relay; verify).
- `POST /node/account/delete` relay → site, then clears link metas and switches host to `local`.

**Android shell**
- `WBNative.signIn(site)`: generates `state`, stores it, opens Custom Tab to `/app/connect`.
  App Link intent filter (`autoVerify`) for `/app/callback`; `extractCode` learns reserved host
  `link`. On callback: verify `state`, call engine `/node/config {site, code, state}`, then
  `evaluateJavascript("WBLinked()")` so the GUI refreshes.
- `WBNative.channel()`, `WBNative.openExternal(url)`.

**GUI (`index.html` + a new `brand/account.js`, synced to the site's `play/static/brand/`)**
- World tab becomes **Account**:
  - Not linked: hero card "Sign in or create an account" (one button → `WBNative.signIn`),
    "Play offline on this device" secondary, collapsed "Advanced: node token / self-hosted
    engine" with the current modal.
  - Linked: account card (name, email, plan chip, balances, device name), **Premium card**
    (Phase 2), node health (existing), actions: Refresh, Switch account, Sign out (unlink),
    Delete account (typed confirmation, calls `/node/account/delete`).
  - Submit snapshot / upload / sync stay but move below the account card.
- Desktop/browser GUI (no native bridge) keeps the token flow but gains the same layout.
- Remove dead `target=_blank` links in native mode in favour of `WBNative.openExternal`.

## Phase 2 — Google Play Billing

**Play Console**: create subscription `premium`, base plans `monthly`/`annual`, prices; enable
Real-time developer notifications to a Pub/Sub topic; service account with Android Publisher
access; license testers.

**Site**
- Wallet: `billing_provider` (`""|stripe|play`), `play_purchase_token`, `play_product_id`,
  `play_expires_at`, `play_obfuscated_id`.
- `play/playbilling.py`: `google-auth` service-account token → REST
  `purchases.subscriptionsv2.get`; `verify_and_apply(wallet, token)` sets `subscribed`,
  `subscription_status`, expiry; `acknowledge` if not acknowledged; rejects a token already
  bound to another wallet; maps `obfuscatedExternalAccountId` = HMAC(user id).
- `POST /api/billing/play/verify {purchase_token, product_id}` (node-token auth) → account
  summary. Idempotent; called after purchase and on every app launch for the cached purchase.
- `POST /webhooks/play` Pub/Sub push: verify the OIDC token audience, decode
  `subscriptionNotification.purchaseToken`, re-fetch state, apply. Returns 200 always after
  logging (Pub/Sub retries on non-2xx).
- `GET /api/billing/offers` → provider policy for the caller: Play channel gets product/plan ids
  and never gets Stripe URLs; web keeps Stripe. If `billing_provider == stripe` and active, the
  app shows "Premium is managed on your WaveBeasts web account" (status only, no link).
- Stripe `apply_event` sets `billing_provider="stripe"`; a Play purchase when Stripe is active
  is refused with a clear message before launching the flow.
- Management command `play_reconcile` to re-verify expiring Play subscriptions daily (safety net
  if RTDN is missed).
- Tests: mock Google API; verify/ack/expiry/other-wallet/RTDN paths; provider exclusivity.

**Android shell** (`play` flavor only; `sideload` returns `unavailable`)
- `com.android.billingclient:billing:7.x`. `BillingBridge`: connect, `queryProductDetailsAsync`
  for `premium`, `launchBillingFlow(basePlanId)` with `setObfuscatedAccountId`,
  `PurchasesUpdatedListener` → POST purchase token to engine `/node/billing/play/verify` (relay
  to site, which acknowledges). `queryPurchasesAsync` on resume → re-verify. Results delivered
  via `evaluateJavascript("window.__wbBilling(json)")`.
- `WBNative.billingOffers()`, `WBNative.buy(basePlanId)`, `WBNative.manageSubscription()`
  (deep link `https://play.google.com/store/account/subscriptions?sku=premium&package=…`).

**GUI** Premium card: offer tiles with localized Play prices, Subscribe buttons; subscribed via
Play → status, renewal date, "Manage on Google Play"; subscribed via Stripe → status only;
sideload/desktop → link to the website billing page (allowed outside the Play build).

## Phase 3 — Store readiness and QA

- Store listing: 512 px icon (`scripts/gen_icon.py`), 1024×500 feature graphic, ≥4 phone
  screenshots at 1080×1920 (Scan, Beasts, Battle, Account) via Playwright against the native
  bridge shim, short/full description, category Games › Casual, content rating questionnaire,
  Data safety form (location, device identifiers = Wi-Fi BSSIDs, purchase history; all
  encrypted in transit; deletion available), target audience 13+.
- Site: `/download/` gets a Play badge; `app_version` returns `play_url`; download page
  explains the one-time reinstall for sideload users.
- Device QA on a real phone (none attached to this Pi; use `adb` over Wi-Fi or Aphrodite):
  cold start → splash → engine up; sign-in round trip incl. App Link; test purchase with a
  license tester account; cancel/renew via Play test clocks; account delete; background
  auto-sweep survives screen off; camera scan; share/deep-link intents; rotation; Android 10
  and 15 devices if available.
- Internal testing track first, then closed testing (Play requires 12+ testers for 14 days for
  new personal developer accounts — check whether the developer account is personal or org).
- Update `docs/FEATURE_VALIDATION.md` with the release record; merge both release branches to
  `main`; tag `v0.13.0` in the engine repo.

## Order of work

Phase 0 → Phase 1 (site, engine, shell, GUI in that order so each layer can be tested against
the previous) → Phase 2 → Phase 3. Phase 0 and the site half of Phase 1 can proceed in
parallel. Each phase ends with Django + Go suites green, `sync-ui-brand.py --check` clean, and a
build from Aphrodite.

## Owner decisions (2026-10-07)

- Decisions 1–3 confirmed (shared key, flavors, Play price parity).
- Play developer account exists and is **personal**: closed testing with 12+ testers for 14 days
  is required before production. Plan the tester list early.
- No Google Cloud project yet: create one (`wavebeasts-play`), enable the Android Publisher API
  and Pub/Sub, create the service account and the RTDN topic/push subscription in Phase 2.
  gcloud CLI is installed at `~/.local/opt/google-cloud-sdk/bin/gcloud` on this Pi.
- **iOS is dropped for now**: remove the iOS project, gomobile binding, CI workflow, build
  script, publish asset, and every site mention (download tile, wiki section). The connect
  flow stays platform-neutral so iOS can return later.
- Release keystore generated 2026-10-07 at `~/.config/wavebeast/release.jks` with
  `keystore.properties` beside it (alias `wavebeast`, RSA 4096, valid to 2056). **Back it up
  off this Pi.** Cert SHA-256:
  `06:5F:AC:93:8F:94:73:31:00:E9:0E:92:F5:AA:42:A2:50:F5:2C:43:A6:BB:F1:DF:64:A9:07:26:CF:B5:AE:FB`
- Work happens on `release/play-0.13.0` in both repos.

## Phase 2 site implementation notes (2026-10-07)

**Endpoints** (node-token auth = header `X-WB-Node-Token`):
- `POST /api/billing/play/verify` `{purchase_token, product_id}` — app node only (`app_node_required`
  otherwise); 30/IP/min. Verifies via `purchases.subscriptionsv2`, binds the token to the wallet, acknowledges
  when pending, returns `{ok, account}` (same `account` dict as `/api/account`). Errors: `invalid_token` 400,
  `account_mismatch` 403, `token_in_use` 409, `stripe_active` 409, `play_unavailable` 502,
  `play_not_configured` 503, `rate_limited` 429.
- `GET /api/billing/offers?channel=play|sideload|web` — `{provider, subscribed, status, renews_at,
  auto_renewing, obfuscated_id, play:{product_id, base_plans, package, manage_url, obfuscated_account_id}}`;
  `web:{billing_url, portal_available}` is omitted for `channel=play`; `managed_elsewhere: true` when the
  provider is Stripe. The app passes `obfuscated_id` to `launchBillingFlow(setObfuscatedAccountId)`.
- `POST /webhooks/play` — Pub/Sub push (RTDN). OIDC bearer token verified against `PLAY_RTDN_AUDIENCE`
  and `PLAY_RTDN_SERVICE_ACCOUNT` when set; 401 on failure, otherwise always 2xx (204 for unparseable).
  Unknown tokens are resolved through `Wallet.play_obfuscated_id`.
- `/api/account` `account` now fills `renews_at` and `manage_url` (Play manage page) for Play subscribers.
- `python manage.py play_reconcile [--limit N]` — daily safety net; no-op when unconfigured.

**Model**: `Wallet.billing_provider` (`""|stripe|play`), `play_purchase_token`, `play_product_id`,
`play_base_plan`, `play_expires_at`, `play_auto_renewing`, `play_linked_at`, `play_obfuscated_id`
(migration `0020_wallet_play_billing`). State map: ACTIVE→active, IN_GRACE_PERIOD→past_due (access kept),
ON_HOLD→past_due (lost), PAUSED→paused, CANCELED→canceled until `expiryTime` then expired,
EXPIRED/PENDING→no access. Expiry clears `billing_provider` but keeps the token fields for audit.
Stripe `apply_event` refuses to activate while Play is active and vice versa; the web checkout and
`/billing/` show "managed through Google Play" with a Play manage link instead of the Stripe portal.

**Env (Railway)**: `PLAY_PACKAGE_NAME` (default `net.wavebeasts.app`), `PLAY_SERVICE_ACCOUNT_JSON`
(base64 or raw key JSON), `PLAY_RTDN_AUDIENCE` (default `SITE_URL/webhooks/play`),
`PLAY_RTDN_SERVICE_ACCOUNT` (push SA email), `PLAY_PRODUCT_ID` (default `premium`). Dependency:
`google-auth>=2.30`. `scripts/setup-play-cloud.sh` prints the values.

**Play Console steps**: (1) Setup → API access → link Cloud project `wavebeasts-play`, grant
`play-verify@…` "View financial data" + "Manage orders and subscriptions". (2) Monetize → Products →
Subscriptions: product `premium`, base plans `monthly` ($5) and `annual` ($50), activate. (3) Monetize →
Monetization setup → RTDN topic `projects/wavebeasts-play/topics/play-rtdn`, send test notification
(expect `outcome: test` in site logs). (4) Setup → License testing: add tester Gmail accounts so test
purchases don't charge. (5) Schedule `play_reconcile` daily on Railway.

## Status 2026-10-07 (end of day)

- Phases 0–2 implemented in both repos on `release/play-0.13.0` (uncommitted pending owner OK).
  Django 187 tests (3 skips) and Go suite green; signed `dist/wavebeast-play.aab` and
  `dist/wavebeast.apk` built on Aphrodite with the release key.
- Google Cloud project `wavebeasts-play` (number 297565430377) created and billed. Enabled:
  Android Publisher, Pub/Sub, IAM. Service accounts: `play-verify@…` (key at
  `~/.config/wavebeast/play-verify-key.json`) and `play-rtdn-push@…`. Topic
  `projects/wavebeasts-play/topics/play-rtdn` grants Google Play publisher; push subscription
  `play-rtdn-site` → `https://wavebeasts.com/webhooks/play` with OIDC auth.
- Remaining owner steps: Play Console app + App Signing with the existing key, link the Cloud
  project under API access and grant the verify service account, create subscription `premium`
  (`monthly` $5 / `annual` $50), set the RTDN topic, license testers, Railway env vars
  (`PLAY_PACKAGE_NAME`, `PLAY_SERVICE_ACCOUNT_JSON`, `PLAY_RTDN_AUDIENCE`,
  `PLAY_RTDN_SERVICE_ACCOUNT`, optionally `ANDROID_CERT_SHA256`). No Railway CLI on this Pi.
- Remaining engineering: store assets + listing copy + data safety (in progress under
  `docs/store/`), device QA of sign-in and a test purchase, validation record, merge to main.

## Status 2026-10-08

- Both repos merged to `main` and pushed; site deployed (`/api/app/version` → 38, assetlinks
  served). Public downloads release `chvolk/wavebeast-dl` v1 carries the 0.13.0 engines and the
  signed sideload APK; the iOS asset was removed.
- Railway has the four `PLAY_*` variables; `/webhooks/play` now answers 401 to unauthenticated
  posts (fail-closed path active).
- Device QA on a Samsung SM-S948U (Android 17): Android verified the App Link
  (`pm get-app-links` → `wavebeasts.com: verified`). Account tab → Custom Tab sign-in →
  Connect → App Link callback linked the account; the Account tab showed the online profile,
  Premium status, counters and this device. The site listed the phone as "heartbeat unavailable"
  until the two-minute auto-loop tick; the engine now heartbeats immediately after linking.
  The Android shell also stops asking for a Wi-Fi scan every second (now one per 30s).
- Still owner-only: Play Console App Signing with the existing key, API access grant for
  `play-verify@…`, subscription `premium` (`monthly`/`annual`), RTDN topic + test notification,
  license testers, upload `dist/wavebeast-play.aab` to internal testing, then a test purchase.


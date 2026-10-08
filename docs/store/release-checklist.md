# Release checklist: WaveBeasts 0.13.0 on Google Play

Owner: personal Play developer account (same Google account as Cloud project `wavebeasts-play`).
Artifacts: `~/Code/wavebeast/dist/wavebeast-play.aab` (Play), `~/Code/wavebeast/dist/wavebeast.apk`
(sideload). Key: `~/.config/wavebeast/release.jks`, alias `wavebeast`, passwords in
`~/.config/wavebeast/keystore.properties`. **Back that directory up off the Pi before step 1.**

## A. Code and infrastructure (this side)

- [ ] Commit both repos on `release/play-0.13.0` (engine + site), run Django + Go suites, build via
      `scripts/build-android.sh`, confirm the AAB/APK cert SHA-256 is `06:5F:AC:93…B5:AE:FB`.
- [ ] Railway env for the site (values printed by `scripts/setup-play-cloud.sh`):
      `PLAY_PACKAGE_NAME=net.wavebeasts.app`,
      `PLAY_SERVICE_ACCOUNT_JSON=$(base64 -w0 ~/.config/wavebeast/play-verify-key.json)`,
      `PLAY_RTDN_AUDIENCE=https://wavebeasts.com/webhooks/play`,
      `PLAY_RTDN_SERVICE_ACCOUNT=play-rtdn-push@wavebeasts-play.iam.gserviceaccount.com`,
      `ANDROID_CERT_SHA256=<cert fingerprint(s), comma separated>`.
- [ ] Deploy the site (migrations 0019/0020 run from the Procfile). Check
      `https://wavebeasts.com/.well-known/assetlinks.json` and `https://wavebeasts.com/api/app/version`
      (version_code 38, `play_url`).
- [ ] Publish the sideload APK + desktop engines with `scripts/publish-downloads.sh` so
      `/download/app.apk` serves 0.13.0 (site notes tell debug-build users to uninstall first).
- [ ] Schedule `python manage.py play_reconcile` daily (Railway cron or the matchmaker worker loop).

## B. Play Console: app and signing

- [ ] Create app: name "WaveBeasts: Scan & Collect", default language en-US, Game, Free, package
      `net.wavebeasts.app` (set by the first upload).
- [ ] **Play App Signing** → "Use an existing key" → "Export and upload a key from a Java keystore".
      Download PEPK, then:
      ```
      java -jar pepk.jar --keystore ~/.config/wavebeast/release.jks --alias wavebeast \
        --output ~/.config/wavebeast/play-upload.zip --include-cert \
        --rsa-aes-encryption --encryption-key-path encryption_public_key.pem
      ```
      Upload the zip. Result: app signing key == our key, so sideload and Play builds share a
      certificate. Keep the same key as the upload key (no separate upload key).
- [ ] After the first upload, copy the "App signing key certificate" SHA-256 from Setup › App
      signing and confirm it equals the fingerprint above; otherwise append it to
      `ANDROID_CERT_SHA256` on Railway.

## C. Play Console: monetization and API access

- [ ] Setup › **API access** → Link an existing Google Cloud project → `wavebeasts-play`.
- [ ] Same page → Service accounts → `play-verify@wavebeasts-play.iam.gserviceaccount.com` → Manage
      Play Console permissions → app-level permissions for WaveBeasts: **View financial data, orders
      and cancellation survey responses** and **Manage orders and subscriptions**. Invite / save.
      (Permission propagation can take up to 24–36 h for a brand-new link; a 401 from the verify
      endpoint before then is expected.)
- [ ] Monetize › Products › **Subscriptions** → Create subscription, product id `premium`, name
      "WaveBeasts Premium". Base plans: `monthly` (auto-renewing, 1 month, $5.00 USD, set other
      regions from the USD price) and `annual` (1 year, $50.00 USD). Activate both. No offers yet.
- [ ] Monetize › **Monetization setup** → Real-time developer notifications → topic name
      `projects/wavebeasts-play/topics/play-rtdn` → Save → **Send test notification**. Then check
      the Railway log for `play rtdn: test`.
- [ ] Setup › **License testing** → add your Google account(s); license response "RESPOND_NORMALLY".
      Test purchases on these accounts renew every 5 minutes (monthly) / 30 minutes (annual).

## D. Store listing and policy

- [ ] Main store listing: title, short and full description from `docs/store/listing.md`; icon
      `icon-512.png`; feature graphic `feature-graphic.png`; phone screenshots `screens/01…05`.
- [ ] App content: privacy policy URL, ads = no, app access (provide a license-tester login note),
      content rating questionnaire, target audience 13+, news = no, data safety from
      `docs/store/data-safety.md`, government = no, financial = none, health = no.
- [ ] App content → **Account deletion**: "yes, users can request deletion"; URL
      `https://wavebeasts.com/me/delete`; data types deleted: all.
- [ ] App content → **Foreground service permissions**: specialUse; paste the justification from
      `data-safety.md`; upload a short screen recording.
- [ ] App content → Photo and video permissions: not applicable (camera only).
- [ ] Store settings: category Games › Casual, tags, contact email, website.

## E. Testing tracks

- [ ] **Internal testing** → create release → upload `wavebeast-play.aab` → release name 0.13.0 (38)
      → notes from `listing.md`. Add your account to the internal tester list, install from the
      opt-in link.
- [ ] On the phone, verify App Links: `adb shell pm get-app-links net.wavebeasts.app` must show
      `wavebeasts.com: verified`. If `none`/`legacy_failure`, check assetlinks.json and the cert.
      Force re-check: `adb shell pm verify-app-links --re-verify net.wavebeasts.app`.
- [ ] Walk the flows: cold start (splash → engine up < 3 s), camera scan, Sign in → Chrome Custom
      Tab → Connect → returns to the app signed in, Account shows name/email, Premium tiles show
      Play prices, test purchase of `monthly`, Account flips to "Premium via Google Play", cancel in
      Play › Subscriptions and watch the RTDN flip status to canceled → expired (5-minute test
      renewals), Restore purchases, Sign out, Delete account (then confirm on the web the user is
      gone). Rotate, background with AUTO on, share text into the app, `wavebeast://` deep link.
- [ ] **Closed testing**: personal developer accounts created after Nov 2023 must run a closed test
      with **at least 12 testers opted in continuously for 14 days** before applying for production.
      Create a closed track, add a tester email list or Google Group, share the opt-in link, and keep
      the count ≥ 12 for the whole window. Fix anything found; each new build restarts nothing (the
      14-day clock is per track, not per build).
- [ ] After 14 days: Dashboard → "Apply for production access" → answer the questionnaire (what was
      tested, feedback, who the app is for).

## F. Production

- [ ] Production → create release from the tested bundle, staged rollout 20 % → 100 %.
- [ ] Update `docs/FEATURE_VALIDATION.md` with the release record (versions, hashes, test results),
      merge `release/play-0.13.0` → `main` in both repos, tag `v0.13.0` in the engine repo.
- [ ] Add the Play badge/link to `/download/` (the `play_url` is already in the version manifest).
- [ ] Watch Play vitals (ANR/crash) and the Railway log for `play rtdn` outcomes during the first
      week; run `python manage.py play_reconcile` manually once to confirm it is a no-op.

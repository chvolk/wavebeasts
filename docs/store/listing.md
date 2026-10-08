# Google Play listing copy — WaveBeasts 0.13.0

Assets in this folder: `icon-512.png` (512×512), `feature-graphic.png` (1024×500),
`screens/01…05-*.png` (1080×1920). Regenerate with `scripts/render-store-assets.py`.

## App title (≤30 chars)

`WaveBeasts: Scan & Collect` (26)

## Short description (≤80 chars)

`Scan barcodes, Wi-Fi and sensors to discover, train and battle pixel beasts.` (77)

## Full description (≤4000 chars)

Turn the real world into monsters.

WaveBeasts is a scan-to-creature game. Point the camera at a barcode or QR code, or just sweep the
room: your phone's Wi-Fi, light, magnetic field and motion sensors are folded into every scan. The
richer and more varied the signals, the rarer the beast you might discover. Every encounter is
generated on your device by a procedural engine, so no two players' collections look the same.

FREE LOCAL PLAY
• Scan anything: product barcodes, QR codes, Wi-Fi around you, ambient sensor readings
• Twelve pixel-art anatomy families with hand-tuned palettes, names and personalities
• Catch wild beasts with drives, feed them, train them and watch them evolve
• Build a team of three and fight gyms with animated replays
• Keep a field journal for every beast: origin, traits, memories and battle record
• Works completely offline. No account needed for local play.

OPTIONAL ONLINE ACCOUNT
Sign in from the Account tab to keep your beasts in the cloud, submit scans from every device you
own (a Raspberry Pi can be a listener node), and see your sightings and activity on wavebeasts.com.

PREMIUM (OPTIONAL SUBSCRIPTION)
Premium unlocks the online layer: trading with other trainers, online battles and the async ladder,
Buddy care and away events, uploading your local catches to your account, node cadence boosts and
up to 12 linked devices. Premium is $5.00 per month or $50.00 per year, billed through Google Play
and renewing automatically until you cancel in your Google Play subscriptions. Local play stays
free forever.

PRIVACY FIRST
No ads. No third-party trackers. We never sell your data. Sensor readings are used only to generate
beasts, stay on your device unless you sign in, and your account can be deleted from inside the app.
Read the policy at https://wavebeasts.com/privacy/.

OPEN TO TINKERERS
The game engine runs on your phone and speaks plain HTTP on localhost. Share text into WaveBeasts
from any app, open wavebeast:// links from NFC tags or QR codes, or run the same engine on a Pi,
Mac, Linux or Windows machine. The integration guide is on wavebeasts.com.

Prefer not to go through Google Play? The same app is available as a direct download at
wavebeasts.com/download.

## Release notes 0.13.0 (≤500 chars)

```
Now on Google Play. Sign in or create your WaveBeasts account right from the new Account tab, and
go Premium with a Google Play subscription. New splash screen, faster start, and links to the wiki
and website now open properly. Fewer permissions: the app no longer asks for phone state. Existing
sideload users: 0.13.0 uses a new signing key, so uninstall the old build once before installing.
```

## Store settings

| Field | Value |
|---|---|
| Category | Games › Casual |
| Tags | Collecting, Monster, Augmented reality (light), Pixel art, Offline |
| Contact email | `support@wavebeasts.com` (placeholder — set up this mailbox or replace) |
| Website | https://wavebeasts.com |
| Privacy policy | https://wavebeasts.com/privacy/ |
| Account deletion | https://wavebeasts.com/me/delete |
| Target audience | 13+ (accounts, user-to-user trading) |
| Ads | No |
| In-app purchases | Yes — subscription `premium` (`monthly` $5.00, `annual` $50.00) |
| Content rating | Fantasy violence (cartoon creature battles), no blood, no gambling; user interaction via trading; shares approximate location only to the service when linked |

## What's new for existing sideload users

Builds before 0.13.0 were debug-signed. 0.13.0 is signed with the release key that Google Play also
uses, so Android refuses to update over the old build. Uninstall the previous WaveBeasts first (local
beasts in that install are lost unless you uploaded them to an account), then install 0.13.0 from
Google Play or wavebeasts.com/download. Future updates install over each other normally, and a
Play install and a direct-download install share the same signature.

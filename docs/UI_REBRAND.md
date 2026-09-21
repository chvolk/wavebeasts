# WaveBeasts interface review and rebrand

Scope: the Django website, standalone Android/iOS app, and engine's local browser UI.
Omnitool is an independent API consumer, **not part of the WaveBeasts suite**. It is an example of a custom app built around the public API, such as a virtual-pet companion. No Omnitool files are changed.

## Findings and changes

| Area | Previous experience | New experience |
|---|---|---|
| Identity | Rounded dark panels, gradient labels, little distinction between primary and secondary content | Angular charcoal panels, vermilion actions, silver waveforms, pixel headings and a red-eyed beast mark |
| Motion | Entire cards floated, distracting from reading and controls | Stable content; moving waveform strips, occasional title glitch and a hero scan line; reduced-motion support |
| Website | Text-only landing page, weak collection hierarchy | Illustrated identity panel, stronger page headings, numbered introduction, consistent navigation and controls |
| Standalone app | Desktop-like top tabs; manual sensor fields above Sweep | Native-only bottom tabs, primary scan controls first, expandable manual inputs |
| Shop | Plain text cards/table; little context or purchase feedback | Pixel-art storefront, illustrated supplies, search/categories, owned counts, quantity steppers, totals and remaining balance, insufficient-funds states, pending guards and visible feedback |
| Beastiary | Account health absent; local battle HP buried in stats | Segmented health bars with numerical values, warning colors and explicit health semantics |

## Health semantics

The website shows the existing account health pool (0–100), including passive recovery and fainted state. Reading the view does not modify stored health. Local beasts do not have persistent damage between fights: the engine now exposes their calculated starting battle HP in its existing collection/detail DTO, and the local UI labels it accordingly. This does not introduce new combat or healing mechanics.

## Assets and maintenance

`play/static/brand/` owns the shared CSS, shop interactions, Silkscreen font (OFL license included), SVG item illustrations, SVG brand mark, and storefront artwork. The engine embeds a copy in `internal/api/web/brand/` so it works offline. Run `python scripts/sync-ui-brand.py` after shared asset edits; `--check` verifies parity. The app shell uses the same HTML as the browser with native-bridge detection for its bottom navigation.

The SVG mark is the editable source for the favicon and launcher identity. In the engine checkout, `scripts/gen_icon.py` renders Android legacy/round icons, safe-area adaptive vector artwork, and the iOS icon; it requires CairoSVG. Android preview version: 0.12.0 (19).

Storefront generated using the built-in imagegen tool. Final asset: `play/static/brand/storefront.png` (also copied into the engine). Generation prompt:

> Use case: stylized-concept. Create a production pixel-art banner asset for the WaveBeasts monster collecting game's shop. Wide 3:1 landscape composition. A beautiful detailed 16-bit side-view nocturnal electronics and monster-supply storefront, dark charcoal metal shutters and angular industrial architecture, glowing vermilion red striped awning, a tiny mysterious shopkeeper with two red eyes behind the counter, shelves of pixelated capture cartridges, potions and food, silver waveform motif across the shop sign. Restrained charcoal black, warm white silver, signal red and small amber lights palette. Crisp deliberate square pixels, arcade adventure game environment art, strong silhouette, charming and slightly eerie. Shop centered with atmospheric cables and antennas at sides, all major details in center safe area for mobile cropping. No lettering, no words, no watermark, no rounded app frame. Actual standalone artwork, not a website mockup. Save generated asset to disk and return its path.

## Validation

- Django: existing 47 tests pass; system checks pass.
- Go: `go test ./...` and Linux build pass.
- Chromium/Playwright with isolated temporary databases: website and local purchases, purchase-failure recovery, categories/search/empty results and filter persistence, quantity totals, native bottom navigation, responsive layouts (320–1440px), local health bars, and reduced motion. No browser JavaScript errors in these flows.
- Previews use synthetic accounts and beasts, not production data.
- Native layout checked using the Android bridge in Chromium; physical Android and iOS runtime checks remain separate from this browser verification.
- Android debug APK builds successfully for ARM64 and ARMv7. Preview artifact: `../wavebeast/dist/wavebeast-ui-preview-0.12.0.apk`.
- Screenshots: `docs/ui-previews/`.
- Initial review was performed before release. User subsequently authorized publishing to main; the release is Android 0.12.0 (19), with matching site update metadata and refreshed engine download assets.

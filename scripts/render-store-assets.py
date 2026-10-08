#!/usr/bin/env python3
"""Render Google Play listing assets into docs/store/.

- Phone screenshots (1080x1920) of the standalone app GUI in native mode: Scan, Beasts, Battle, Account
  signed-out, Account signed-in with Google Play Premium tiles. A disposable engine runs on a scratch DB;
  the first-run tutorial is marked done and a fake WBNative bridge makes the page render with bottom tabs.
- Feature graphic (1024x500) and hi-res icon (512x512) from the shared brand mark and Silkscreen font.

Usage: .venv/bin/python scripts/render-store-assets.py [--engine PATH] [--port 18777] [--out docs/store]
Needs: Playwright (python package; uses /usr/bin/chromium), Pillow, rsvg-convert.
"""
import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = os.path.join(ROOT, 'play/static/brand/mark.svg')
PIXEL_FONT = os.path.join(ROOT, 'play/static/brand/silkscreen.ttf')
BG = '#090b0e'

FAKE_NATIVE = """
try { localStorage.setItem('wb_tutorial_v1','done'); } catch(e) {}
window.WBNative = {
  available: () => true,
  signals: () => JSON.stringify([
    {kind:'wifi', id:'aa:bb:cc:dd:ee:01', strength:0.72, value:{ssid:'homenet', bssid:'aa:bb:cc:dd:ee:01', rssi:-47}},
    {kind:'wifi', id:'aa:bb:cc:dd:ee:02', strength:0.41, value:{ssid:'cafe-guest', bssid:'aa:bb:cc:dd:ee:02', rssi:-65}},
    {kind:'scalar', strength:0.56, value:{metric:'lux', n:420}},
    {kind:'scalar', strength:0.38, value:{metric:'emf_ut', n:46.2}},
    {kind:'scalar', strength:0.12, value:{metric:'motion_g', n:1.07}},
    {kind:'cell', strength:0.75, value:{bars:3}}
  ]),
  ensurePerms: () => {},
  channel: () => 'play',
  openExternal: (u) => {},
  signIn: (s) => {},
  billingAvailable: () => true,
  billingProducts: () => setTimeout(() => window.__wbBilling && window.__wbBilling({event:'products', products:[
    {base_plan_id:'monthly', product_id:'premium', price:'$5.00', period:'P1M'},
    {base_plan_id:'annual',  product_id:'premium', price:'$50.00', period:'P1Y'}
  ]}), 150),
  buy: (p, o) => {}, restorePurchases: () => {}, manageSubscription: () => {}
};
"""

ACCOUNT = {
    "ok": True,
    "account": {"name": "Rowan", "email": "rowan@example.com", "plan": "Free", "subscribed": False,
                "subscription_status": "free", "shards": 1240, "cores": 3, "beasts": 27, "nodes": 2,
                "node_limit": 3, "billing_provider": "", "renews_at": None, "manage_url": None},
    "node": {"name": "Pixel 8", "kind": "app", "next_snapshot_in": 0},
    "node_health": [
        {"id": 1, "name": "Pixel 8", "kind": "app", "status": "healthy", "last_seen_at": "2026-10-07T20:00:00Z",
         "last_attempt_at": "2026-10-07T19:40:00Z", "last_snapshot_at": "2026-10-07T19:40:00Z",
         "next_attempt_at": None, "scan_mode": "manual", "failures": 0, "last_error": "", "client_version": "0.13.0",
         "client_app": "wavebeast-engine", "update": {"update_available": False, "update_required": False}},
        {"id": 2, "name": "Kitchen Pi", "kind": "pi", "status": "healthy", "last_seen_at": "2026-10-07T20:05:00Z",
         "last_attempt_at": "2026-10-07T19:50:00Z", "last_snapshot_at": "2026-10-07T19:50:00Z",
         "next_attempt_at": "2026-10-07T20:20:00Z", "scan_mode": "auto", "failures": 0, "last_error": "",
         "client_version": "1.2.0", "client_app": "wavebeast-node", "update": {"update_available": False, "update_required": False}},
    ],
    "recent_snapshots": [],
}
OFFERS = {"provider": "", "subscribed": False, "status": "free", "renews_at": None, "auto_renewing": False,
          "obfuscated_id": "fixture",
          "play": {"product_id": "premium", "base_plans": ["monthly", "annual"], "package": "net.wavebeasts.app",
                   "manage_url": "https://play.google.com/store/account/subscriptions?sku=premium&package=net.wavebeasts.app",
                   "obfuscated_account_id": "fixture"}}

SEED_CODES = ['WB:GARDEN-7', '036000291452', 'WB:ROOFTOP-ANTENNA', '4006381333931', 'WB:TIDE-POOL-3',
              '9780140328721', 'WB:SUBWAY-PLATFORM', '5000159484695', 'WB:OBSERVATORY', '012345678905',
              'WB:THUNDERHEAD', '7622210449283', 'WB:NIGHT-MARKET', '8410100000005', 'WB:GLACIER-RIM',
              'WB:HARBOR-CRANE', 'WB:ATTIC-RADIO', 'WB:GREENHOUSE-9', 'WB:LIGHTHOUSE', 'WB:TRAIN-YARD',
              'WB:CANYON-ECHO', 'WB:ARCADE-FLOOR', 'WB:MOSS-WELL', 'WB:WIND-FARM', 'WB:BAKERY-OVEN']


def wait_http(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except Exception:
            time.sleep(0.25)
    raise SystemExit(f'engine did not come up at {url}')


def post(base, path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=20) as r:
        return json.loads(r.read())


def db_exec(db, *statements):
    for _ in range(20):
        try:
            with sqlite3.connect(db, timeout=5) as c:
                for sql in statements:
                    c.execute(sql)
            return
        except sqlite3.OperationalError:
            time.sleep(0.2)


def reset_cooldown(db):
    """The local engine yields at most once per 300 s (meta last_yield). Rewind it for seeding."""
    db_exec(db, "UPDATE meta SET v='0' WHERE k='last_yield'")


def stock_up(db):
    """A lived-in wallet for the screenshots, plus strong drives so wild encounters can be caught."""
    db_exec(db, "INSERT OR REPLACE INTO currency(kind,amount) VALUES('shards',1240),('cores',3)",
            "INSERT OR REPLACE INTO inventory(item_id,qty) VALUES('nova_drive',60),('spark_drive',5),('kibble',4),('potion',2)")


def seed(base, db, want=8):
    """Scan distinct codes with a rich sensor bundle until the collection holds `want` beasts. Only the
    first catch is free; later encounters are wild, so throw nova drives until each one is caught."""
    stock_up(db)
    signals = [{"kind": "wifi", "strength": 0.8, "value": {"ssid": "homenet", "bssid": "aa:bb:cc:dd:ee:01", "rssi": -45}},
               {"kind": "ble", "strength": 0.5, "value": {"addr": "11:22:33:44:55:66", "rssi": -60}},
               {"kind": "scalar", "strength": 0.6, "value": {"metric": "lux", "n": 400}},
               {"kind": "scalar", "strength": 0.4, "value": {"metric": "emf_ut", "n": 48}},
               {"kind": "scalar", "strength": 0.5, "value": {"metric": "temp_c", "n": 21.5}}]
    for code in SEED_CODES:
        owned = [b for b in get(base, '/collection').get('beasts', get(base, '/collection')) if isinstance(b, dict)]
        if len(owned) >= want:
            break
        reset_cooldown(db)
        kind = 'qr' if code.startswith('WB:') else 'code'
        value = {"data": code} if kind == 'qr' else {"symbology": "ean13", "data": code}
        bundle = {"schema": "wavebeast.scanbundle", "v": 1, "client": {"id": "store-shots", "app": "render"},
                  "signals": [{"kind": kind, "strength": 1.0, "value": value}] + signals}
        try:
            resp = post(base, '/scan', bundle)
        except Exception as e:  # noqa: BLE001
            print('scan failed', code, e)
            continue
        # First catch is free (`individual`); later encounters are wild (`wild`) unless they fled.
        ind = resp.get('wild')
        if resp.get('outcome') != 'beast' or not ind or resp.get('fled'):
            continue
        for _ in range(8):
            try:
                if post(base, '/catch', {"individual": ind, "drive": "nova_drive"}).get('caught'):
                    break
            except Exception as e:  # noqa: BLE001
                print('catch failed', code, e)
                break
    reset_cooldown(db)
    col = get(base, '/collection')
    beasts = col.get('beasts', col) if isinstance(col, dict) else col
    return [b for b in beasts if isinstance(b, dict)]


async def shoot(base, out, team_ids):
    from playwright.async_api import async_playwright
    os.makedirs(out, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        ctx = await browser.new_context(viewport={'width': 360, 'height': 640}, device_scale_factor=3,
                                        is_mobile=True, has_touch=True, color_scheme='dark', locale='en-US')
        await ctx.add_init_script(FAKE_NATIVE)
        await ctx.add_init_script("try{localStorage.setItem('wb_team',%s)}catch(e){}" % json.dumps(json.dumps(team_ids)))
        page = await ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))

        async def tab(name):
            await page.click(f'.tabs button[data-t="{name}"]')
            await page.evaluate("window.scrollTo(0,0)")  # don't carry a previous tab's scroll offset
            await page.wait_for_timeout(600)

        async def settle():
            await page.wait_for_load_state('networkidle')
            await page.evaluate("document.querySelectorAll('img').forEach(i=>i.loading='eager')")
            await page.wait_for_function("[...document.images].every(i=>i.complete)")
            await page.wait_for_timeout(500)

        # 1. Scan — wait for the sweep button to leave CHECKING…
        await page.goto(base + '/')
        await page.wait_for_function("document.querySelector('#sweepbtn') && document.querySelector('#sweepbtn').textContent!=='CHECKING…'", timeout=15000)
        await settle()
        await page.screenshot(path=os.path.join(out, '01-scan.png'))

        # 2. Beasts — scroll so the collection grid (not only goals + filters) is in frame
        await tab('beasts')
        await settle()
        await page.evaluate("document.querySelector('#collection').scrollIntoView({block:'start'}); window.scrollBy(0,-120)")
        await page.wait_for_timeout(300)
        await page.screenshot(path=os.path.join(out, '02-beasts.png'))

        # 3. Battle (team prepicked via localStorage)
        await tab('battle')
        await settle()
        await page.screenshot(path=os.path.join(out, '03-battle.png'))

        # 4. Account, signed out (host is local on this scratch engine)
        await tab('account')
        await page.wait_for_selector('text=Sign in or create account')
        await settle()
        await page.screenshot(path=os.path.join(out, '04-account-signin.png'))

        # 5. Account, signed in with Play Premium offers — fixture the account relay routes only.
        async def host(route):
            await route.fulfill(json=({"ok": True, "api_version": 2, "host": {"kind": "account", "url": "https://wavebeasts.com"}}))
        async def cfg(route):
            await route.fulfill(json={"ok": True, "site": "https://wavebeasts.com", "linked": True})
        async def account(route):
            await route.fulfill(json=ACCOUNT)
        async def offers(route):
            await route.fulfill(json=OFFERS)
        await page.route('**/host', host)
        await page.route('**/node/config', cfg)
        await page.route('**/node/account', account)
        await page.route('**/account/api/billing/offers**', offers)
        await page.evaluate('renderNode()')
        await page.wait_for_selector('text=Best value', timeout=10000)
        await settle()
        await page.evaluate("document.querySelector('#premium-card').scrollIntoView({block:'start'}); window.scrollBy(0,-70)")
        await page.wait_for_timeout(300)
        await page.screenshot(path=os.path.join(out, '05-account-premium.png'))
        await browser.close()
        return errors


def render_svg(svg_path, size):
    png = tempfile.mktemp(suffix='.png')
    subprocess.run(['rsvg-convert', '-w', str(size), '-h', str(size), '-o', png, svg_path], check=True)
    img = Image.open(png).convert('RGBA')
    os.unlink(png)
    return img


def icon(out):
    img = Image.new('RGBA', (512, 512), BG)
    mark = render_svg(MARK, 512)
    img.alpha_composite(mark)
    img.convert('RGB').save(os.path.join(out, 'icon-512.png'))


def feature_graphic(out):
    W, H = 1024, 500
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    # faint waveform strips along the top and bottom edges, clear of the text column
    for y in (34, 466):
        pts = []
        for x in range(0, W + 1, 16):
            k = (x // 16) % 8
            dy = (0, -10, 0, 10, 0, -6, 0, 6)[k]
            pts.append((x, y + dy))
        d.line(pts, fill=(42, 46, 54), width=3)
    mark = render_svg(MARK, 360)
    img.paste(mark, (56, 70), mark)
    title = ImageFont.truetype(PIXEL_FONT, 72)
    tag = ImageFont.truetype(PIXEL_FONT, 22)
    x = 450
    d.text((x + 3, 170 + 3), 'WAVEBEASTS', font=title, fill=(224, 54, 47))
    d.text((x, 170), 'WAVEBEASTS', font=title, fill=(238, 241, 246))
    d.text((x, 262), 'Turn real-world signals', font=tag, fill=(199, 204, 214))
    d.text((x, 296), 'into collectible beasts', font=tag, fill=(199, 204, 214))
    d.rectangle((x, 345, x + 420, 349), fill=(224, 54, 47))
    d.text((x, 366), 'SCAN  ·  COLLECT  ·  BATTLE', font=tag, fill=(144, 149, 160))
    img.save(os.path.join(out, 'feature-graphic.png'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine', default=os.environ.get('WB_ENGINE', os.path.join(ROOT, '..', 'wavebeast', 'dist', 'wavebeast-linux-arm64')))
    ap.add_argument('--port', type=int, default=18777)
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'store'))
    ap.add_argument('--skip-screens', action='store_true')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    icon(args.out)
    feature_graphic(args.out)
    if not args.skip_screens:
        work = tempfile.mkdtemp(prefix='wb-store-')
        db = os.path.join(work, 'store.db')
        base = f'http://127.0.0.1:{args.port}'
        env = dict(os.environ, WAVEBEAST_DB=db, WAVEBEAST_ADDR=f'127.0.0.1:{args.port}')
        proc = subprocess.Popen([args.engine], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_http(base + '/capabilities')
            beasts = seed(base, db)
            team = [b['id'] for b in beasts[:3]]
            errors = asyncio.run(shoot(base, os.path.join(args.out, 'screens'), team))
            print('beasts seeded:', len(beasts), 'page errors:', errors)
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            shutil.rmtree(work, ignore_errors=True)
    for name in sorted(os.listdir(args.out)):
        path = os.path.join(args.out, name)
        if name.endswith('.png'):
            print(name, Image.open(path).size)
    screens = os.path.join(args.out, 'screens')
    if os.path.isdir(screens):
        for name in sorted(os.listdir(screens)):
            print('screens/' + name, Image.open(os.path.join(screens, name)).size)


if __name__ == '__main__':
    main()

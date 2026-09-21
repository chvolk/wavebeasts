"""Render the shared brand's social PNG. Requires Playwright and Chromium."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=await browser.new_page(viewport={'width':1200,'height':630},device_scale_factor=1)
        # File origin allows the local bundled font and vector mark to load without a server.
        html=ROOT/'play/static/social-card-preview.html'
        html.write_text('''<!doctype html><style>
        @font-face{font-family:Pixel;src:url(brand/silkscreen.ttf)}
        *{box-sizing:border-box}body{margin:0;background:#090b0e;color:#e9ebf0;font-family:Pixel;width:1200px;height:630px;padding:56px;overflow:hidden}
        .frame{position:absolute;inset:20px;border:2px solid #303c43;z-index:-1}
        .top{color:#f04c40;font-size:18px;letter-spacing:3px;margin-bottom:55px}
        h1{font-size:72px;font-weight:normal;letter-spacing:-4px;margin:0 0 28px;line-height:1}
        p{font-size:24px;line-height:1.5;margin:0;color:#9da8ae;max-width:670px}
        img{position:absolute;right:54px;top:150px;width:280px;height:280px}
        .bottom{position:absolute;bottom:58px;left:56px;right:56px;border-top:2px solid #303c43;padding-top:23px;display:flex;justify-content:space-between;font-size:19px}
        .red{color:#f04c40}.wave{position:absolute;left:56px;top:414px;width:680px;height:34px}
        </style><div class="frame"></div><div class="top">A creature in every signal.</div>
        <h1>WAVEBEASTS</h1><p>Scan the world.<br>Catch. Train. Trade. Battle.</p><img src="brand/mark.svg" alt="">
        <svg class="wave" viewBox="0 0 680 34" shape-rendering="crispEdges"><path fill="none" stroke="#f04c40" stroke-width="4" d="M0 18h38V8h14v18h16V4h14v26h16V12h14v6h60v-6h14v18h14V4h14v22h14v-8h48V8h14v18h14V4h14v26h14V12h14v6h66V8h14v18h14V4h14v26h14V12h14v6h80"/></svg>
        <div class="bottom"><span>Local play. Connected worlds.</span><span class="red">wavebeasts.com</span></div>''')
        try:
            await page.goto(html.as_uri())
            await page.evaluate('document.fonts.ready')
            await page.screenshot(path=str(ROOT/'play/static/social-card-v2.png'))
        finally:
            html.unlink(missing_ok=True)
            await browser.close()
asyncio.run(main())

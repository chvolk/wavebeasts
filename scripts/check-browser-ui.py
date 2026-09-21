"""Optional Playwright smoke test. Run against disposable site/engine instances on 18080/18780.
Camera hardware is simulated; it does not submit a gameplay scan.
"""
import asyncio,json
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=await browser.new_page(viewport={'width':390,'height':844});errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.add_init_script("localStorage.setItem('wb_cookie','accept')")
  for path in ['','ai-setup/','local-play/','nodes/','scanning/','beasts/','type-chart/','catching/','battles/','buddy/','premium/','sensors/','api/']:
   response=await page.goto('http://127.0.0.1:18080/docs/'+path)
   assert response.status==200,path
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth'),path
  await page.goto('http://127.0.0.1:18080/docs/#llm')
  await page.wait_for_url('**/docs/ai-setup/#llm')
  await page.context.grant_permissions(['clipboard-read','clipboard-write'])
  await page.get_by_role('button',name='Copy node prompt').click()
  await page.get_by_text('Copied. Paste into your agent.').wait_for()
  assert '/api/account' in await page.evaluate('navigator.clipboard.readText()')
  await page.screenshot(path='/tmp/wb-wiki-mobile.png',full_page=True)
  await page.goto('http://127.0.0.1:18780')
  await page.evaluate('''() => {
    window.cameraStops=0;window.detectedCode='TEST-QR-123';
    const stream={getTracks:()=>[{stop:()=>window.cameraStops++}]};
    navigator.mediaDevices.getUserMedia=async()=>stream;
    Object.defineProperty(HTMLMediaElement.prototype,'srcObject',{set(v){},get(){return null},configurable:true});
    HTMLMediaElement.prototype.play=async()=>{};
    window.BarcodeDetector=class {async detect(){return [{rawValue:window.detectedCode}]}};
  }''')
  await page.locator('#code').fill('typed-text')
  await page.get_by_role('button',name='Scan with camera',exact=True).click()
  await page.get_by_text('Code grabbed: TEST-QR-123',exact=True).wait_for()
  assert not await page.locator('#cam').is_visible()
  assert await page.evaluate('cameraStops')==1
  assert await page.locator('#code').input_value()=='typed-text'
  await page.evaluate("window.detectedCode='<script>'+ 'A'.repeat(100)")
  await page.get_by_role('button',name='Scan with camera',exact=True).click()
  await page.wait_for_function('cameraStops===2')
  assert await page.locator('#staged .chip').count()==1
  assert len(await page.locator('#capture-feedback').inner_text())<=94
  assert await page.evaluate('staged[0].value.data.length')==108
  assert await page.locator('#staged script').count()==0
  await page.evaluate("stageSignal({kind:'scalar',value:{metric:'temp_c',n:20}});stageSignal({kind:'scalar',value:{metric:'temp_c',n:25}});stageSignal({kind:'scalar',value:{metric:'lux',n:10}});renderStaged()")
  assert await page.locator('#staged .chip').count()==3
  assert await page.evaluate("staged.find(s=>s.value.metric==='temp_c').value.n")==25
  assert 'inputSlot' not in await page.evaluate('JSON.stringify(staged)')
  # An in-flight detector must not add a value after cancellation.
  await page.evaluate("window.BarcodeDetector=class {detect(){return new Promise(resolve=>window.lateResult=resolve)}};openCamera()")
  await page.wait_for_function('!!window.lateResult')
  await page.evaluate("closeCamera();lateResult([{rawValue:'late-code'}])")
  await page.wait_for_timeout(350)
  assert not await page.evaluate("staged.some(s=>s.value.data==='late-code')")
  # No detection must keep the camera open, not silently add an image.
  await page.evaluate("window.BarcodeDetector=class {async detect(){return []}};openCamera()")
  await page.wait_for_timeout(350)
  await page.get_by_role('button',name='CAPTURE',exact=True).click()
  assert await page.locator('#cam').is_visible()
  assert 'No code detected yet' in await page.locator('#camstatus').inner_text()
  await page.evaluate('closeCamera()')
  assert not errors,errors
  print(json.dumps({'wiki_pages':13,'mobile_overflow':False,'legacy_link':'passed','prompt_copy':'passed','automatic_scan_close':'passed','camera_replacement':'passed','manual_type_replacement':'passed','late_detection_cancel':'passed','no_detection':'passed','script_errors':errors}))
  await browser.close()
asyncio.run(main())

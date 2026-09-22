/* Manual Premium browser scanner. Pixel data never crosses the network. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), root = $('browser-scanner');
  if (!root) return;
  let staged = null, stream = null, generation = 0, decodeTimer = null, reader = null;
  let orientation = null, orientationAt = 0, busy = false;
  let readyAt = Date.now() + Number(root.dataset.cooldown || 0) * 1000;
  const video = $('camera');
  function closeCamera() {
    generation++;
    clearTimeout(decodeTimer);
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null; video.srcObject = null; $('camera-box').hidden = true;
  }
  function stage(signal, label) {
    staged = signal;
    $('staged-camera').textContent = label;
    $('clear-camera').hidden = false;
  }
  function hashImage(drawable, width, height) {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 8;
    const ctx = canvas.getContext('2d', {willReadFrequently: true});
    ctx.drawImage(drawable, 0, 0, 8, 8);
    const data = ctx.getImageData(0, 0, 8, 8).data, gray = [], palette = [];
    let sum = 0;
    for (let i = 0; i < 64; i++) {
      const r = data[i*4], g = data[i*4+1], b = data[i*4+2];
      const value = Math.round(.299*r + .587*g + .114*b); gray.push(value); sum += value;
      if (i % 11 === 0) palette.push([r,g,b]);
    }
    // Hex nibbles keep hashing compatible with browsers without BigInt.
    let phash = '';
    for (let i = 0; i < 64; i += 4) {
      let n = 0; for (let j = 0; j < 4; j++) n = (n << 1) | (gray[i+j] > sum/64 ? 1 : 0);
      phash += n.toString(16);
    }
    return {kind:'image_features', strength:.9, value:{phash, palette, dims:[width,height]}};
  }
  async function decodeFrame() {
    const canvas = document.createElement('canvas');
    canvas.width = Math.min(960, video.videoWidth);
    canvas.height = Math.round(video.videoHeight * canvas.width / video.videoWidth);
    const ctx = canvas.getContext('2d', {willReadFrequently:true});
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    if ('BarcodeDetector' in window) {
      try { const found = await new BarcodeDetector().detect(canvas); if (found[0]?.rawValue) return found[0].rawValue; } catch (_) { /* Try the bundled decoder. */ }
    }
    const rgba = ctx.getImageData(0,0,canvas.width,canvas.height).data;
    const gray = new Uint8ClampedArray(canvas.width * canvas.height);
    for (let i=0; i<gray.length; i++) gray[i] = (rgba[i*4] + 2*rgba[i*4+1] + rgba[i*4+2]) / 4;
    reader ||= new ZXing.MultiFormatReader();
    try {
      const source = new ZXing.RGBLuminanceSource(gray,canvas.width,canvas.height);
      return reader.decode(new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(source))).getText();
    } finally { reader.reset(); }
  }
  async function decodeLoop(ticket) {
    if (ticket !== generation || !stream) return;
    if (video.readyState >= 2 && video.videoWidth) {
      try {
        const text = await decodeFrame();
        if (ticket !== generation) return;
        if (text && text.length <= 4096) {
          stage({kind:'code',strength:1,value:{symbology:'barcode',data:text}}, 'Code grabbed: ' + (text.length > 80 ? text.slice(0,80)+'…' : text));
          closeCamera(); return;
        }
      } catch (_) { /* An undecodable frame is normal while aiming. */ }
    }
    if (ticket === generation) decodeTimer = setTimeout(() => decodeLoop(ticket), 350);
  }
  async function openCamera(mode) {
    closeCamera(); const ticket = generation;
    $('camera-box').hidden = false;
    $('capture-photo').hidden = mode !== 'photo';
    $('camera-status').textContent = 'Waiting for camera permission…';
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera unavailable. Use HTTPS and allow camera access, or choose an image.');
      const camera = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280}},audio:false});
      if (ticket !== generation) { camera.getTracks().forEach(track => track.stop()); return; }
      stream = camera; video.srcObject = camera; await video.play();
      if (ticket !== generation) return;
      $('camera-status').textContent = mode === 'photo' ? 'Frame your image, then hash it locally.' : 'Aim at a QR code or barcode.';
      if (mode === 'barcode') decodeLoop(ticket);
    } catch (error) {
      if (ticket !== generation) return;
      closeCamera(); $('scan-status').textContent = error.name === 'NotAllowedError' ? 'Camera permission denied. Allow it in browser settings, or choose an image.' : error.message;
    }
  }
  $('open-barcode').onclick = () => openCamera('barcode');
  $('open-photo').onclick = () => openCamera('photo');
  $('close-camera').onclick = closeCamera;
  $('capture-photo').onclick = () => {
    if (!video.videoWidth) { $('camera-status').textContent = 'Wait for a camera frame.'; return; }
    stage(hashImage(video,video.videoWidth,video.videoHeight), 'Image hashed on this device. No photo will be uploaded.'); closeCamera();
  };
  $('clear-camera').onclick = () => { staged = null; $('staged-camera').textContent = 'No camera input yet.'; $('clear-camera').hidden = true; };
  $('pick-photo').onclick = () => { closeCamera(); $('photo-file').click(); };
  $('photo-file').onchange = async event => {
    const file = event.target.files[0]; event.target.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/') || file.size > 20*1024*1024) { $('scan-status').textContent = 'Choose an image smaller than 20 MB.'; return; }
    closeCamera(); const ticket = generation, url = URL.createObjectURL(file);
    try {
      const img = new Image(); img.src = url; await img.decode();
      if (ticket !== generation) return;
      if (img.naturalWidth > 16384 || img.naturalHeight > 16384) throw new Error('Choose a smaller image.');
      stage(hashImage(img,img.naturalWidth,img.naturalHeight), 'Image hashed on this device. No photo will be uploaded.');
    } catch (error) { $('scan-status').textContent = error.message || 'Could not read that image.'; }
    finally { URL.revokeObjectURL(url); }
  };
  function onOrientation(event) {
    const values = {};
    for (const key of ['alpha','beta','gamma']) if (Number.isFinite(event[key])) values['orientation_'+key] = Math.round(event[key]*10)/10;
    if (Object.keys(values).length) { orientation = values; orientationAt = Date.now(); $('sensor-status').textContent = 'Orientation readings ready · sampled on this device.'; }
  }
  $('enable-sensors').onclick = async () => {
    try {
      if (!window.DeviceOrientationEvent) throw new Error('This browser does not expose orientation readings. Camera and text still work.');
      if (typeof DeviceOrientationEvent.requestPermission === 'function' && await DeviceOrientationEvent.requestPermission() !== 'granted') throw new Error('Orientation permission denied. Camera and text still work.');
      window.addEventListener('deviceorientation',onOrientation);
      $('sensor-status').textContent = 'Listening for orientation. Some browsers/devices do not provide readings.';
    } catch (error) { $('sensor-status').textContent = error.message; }
  };
  function updateButton() {
    const seconds = Math.max(0,Math.ceil((readyAt-Date.now())/1000));
    $('submit-scan').disabled = busy || seconds > 0;
    $('submit-scan').textContent = busy ? 'SCANNING…' : seconds ? `READY IN ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}` : 'SCAN NOW';
  }
  $('scan-form').onsubmit = async event => {
    event.preventDefault(); if (busy || Date.now() < readyAt) return;
    const signals = [], code = $('scan-code').value.trim();
    if (code) signals.push({kind:'code',strength:1,value:{symbology:'manual',data:code}});
    if (staged) signals.push(staged);
    if (!signals.length) { $('scan-status').textContent = 'Add text, scan a barcode, or hash an image first.'; return; }
    if (orientation && Date.now()-orientationAt < 10000) for (const [metric,n] of Object.entries(orientation)) signals.push({kind:'scalar',strength:.5,value:{metric,n}});
    closeCamera(); busy = true; updateButton(); $('scan-status').textContent = 'Reading your signals…';
    try {
      const response = await fetch('/api/browser/scan',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':$('scan-form').elements.csrfmiddlewaretoken.value},body:JSON.stringify({signals})});
      const result = await response.json();
      if (response.status === 429) readyAt = Date.now()+(result.retry_after||1)*1000;
      if (!response.ok) throw new Error(response.status===429?'This account’s browser scanner is cooling down.':result.error||'Scan failed. Sign in again if needed.');
      readyAt = Date.now()+(result.next_snapshot_in||300)*1000;
      $('scan-status').textContent = result.detail || result.outcome || 'Scan complete.';
      const box = $('scan-result'); box.replaceChildren(); box.hidden = false;
      const title = document.createElement('h2'); title.textContent = result.beast ? (result.caught?'Caught ':'Sighted ')+result.beast.name : result.outcome==='resource'?'Supplies found':'No clear signal';box.append(title);
      if (result.beast?.id) { const img = document.createElement('img'); img.src='/sprite/'+Number(result.beast.id)+'.png';img.width=128;img.height=128;img.style.imageRendering='pixelated';img.alt=result.beast.name;box.append(img); }
      const text = document.createElement('p');text.textContent=result.detail||'Try a different code next time.';box.append(text);
      const link = document.createElement('a');link.href='/me/';link.className='btn';link.textContent=result.beast&&!result.caught?'Catch in your discovery queue':'View your collection';box.append(link);
      if(result.wallet) for(const key of ['shards','cores']) document.querySelectorAll(`[data-wallet="${key}"]`).forEach(el=>el.textContent=result.wallet[key]);
    } catch (error) { $('scan-status').textContent = error.message || 'Could not reach your account. Try again.'; }
    finally { busy=false;updateButton(); }
  };
  document.addEventListener('visibilitychange',()=>{if(document.hidden){closeCamera();orientation=null;}});
  window.addEventListener('pagehide',closeCamera);
  updateButton();setInterval(updateButton,1000); // Countdown only; never submits a scan.
})();

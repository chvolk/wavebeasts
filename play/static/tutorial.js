/* First-run field guide. No scans, purchases or permissions are triggered by the tour. */
(()=>{
  const config=document.querySelector('[data-wb-tutorial]'); if(!config)return;
  const app=config.dataset.wbTutorial==='app', key='wb_tutorial_v1';
  const steps=[
    ['01 / SCAN','Find a signal',app?'Open Scan and tap SWEEP to read available signals. You can add one text code and one camera capture or barcode. Manual scans are available every 5 minutes; the button shows your cooldown. Open HOST to choose where your beasts and balance live.':'Open Scan for manual browser scanning with Premium. Enter a code, scan a barcode, or capture an image. Camera access is optional and images are processed on your device. For free local play, install the app from Download.'],
    ['02 / YOUR BEASTS','Meet your collection',app?'Your caught creatures live in BEASTS. Open a beast to see its stats and HP. New, uncaught sightings stay in the results at the bottom of Scan.':'Your caught creatures live in Beastiary. Open a beast to see its stats and HP. New, uncaught sightings stay on Scan until you catch or dismiss them.'],
    ['03 / CATCH','Make the catch','Find a wild sighting in Scan results and choose a drive from your inventory to try catching it. Drives are consumed and catches can fail. Watch the countdown and timer bar: sightings expire. Dismiss any you do not want.'],
    ['04 / AUTO','Let the signals come to you',app?'Turn AUTO on in Scan for a passive attempt every 30 minutes while the engine is running. Manual sweeps still have their own 5-minute cooldown. Check the Auto Activity card below the scanner for results, and turn AUTO off whenever you like.':'Auto mode lives in the standalone app and running nodes, not the website. It makes a passive attempt every 30 minutes while the engine is running. Review results in the app’s Auto Activity card; Premium accounts can also see recent node submissions in World.'],
    ['05 / SUPPLIES','Stock up for the next hunt',app?'Open SHOP / BAG to see your inventory and buy drives and supplies with shards or cores. Resource scans can yield currency, drives or food; some scans find nothing. The selected HOST determines your balance and inventory, so use the same host/account on all your devices.':'Open Shop to see available drives and supplies and their prices in shards or cores. Resource scans can yield currency, drives or food; some scans find nothing. Linked apps must use the same host/account to share your balance, inventory and beasts.'],
    ['06 / FIELD MANUAL','Keep the wiki close','Open How to for the page-based wiki. Choose a topic in its navigation, then use the previous/next links to keep reading. Start with scanning and catching; “Set up with an AI agent” walks you through a node or local GUI setup. You can replay this tutorial anytime.']
  ];
  const dialog=document.createElement('dialog'); dialog.className='wb-tour';
  dialog.setAttribute('aria-labelledby','wb-tour-title');dialog.setAttribute('aria-describedby','wb-tour-copy');
  dialog.innerHTML='<form method="dialog"><button class="wb-tour-close" aria-label="Dismiss tutorial">×</button></form><p id="wb-tour-step"></p><h2 id="wb-tour-title"></h2><p id="wb-tour-copy"></p><a id="wb-tour-docs" target="_blank" rel="noopener">Open the wiki ↗</a><p id="wb-tour-status" role="status"></p><div class="wb-tour-actions"><button type="button" id="wb-tour-skip">Skip tutorial</button><button type="button" id="wb-tour-back">Back</button><button type="button" id="wb-tour-next">Next →</button></div>';
  document.body.append(dialog);
  let step=0,opener=null,saving=false;
  const el=id=>dialog.querySelector('#wb-tour-'+id);
  function render(){const s=steps[step];el('step').textContent=s[0]+' · '+(step+1)+' / '+steps.length;el('title').textContent=s[1];el('copy').textContent=s[2];el('back').disabled=step===0;el('next').textContent=step===steps.length-1?'Start exploring':'Next →';el('docs').hidden=step!==steps.length-1;el('docs').href=app?'https://wavebeasts.com/docs/':'/docs/';el('next').focus();}
  function open(){if(dialog.open)return;opener=document.activeElement;step=0;el('status').textContent='';dialog.showModal();render();}
  async function dismiss(){
    if(saving)return;saving=true;
    if(!app && config.dataset.first==='true'){
      try{const response=await fetch('/onboarding/',{method:'POST',headers:{'X-CSRFToken':config.querySelector('input').value,'Accept':'application/json'}});if(!response.ok)throw Error();config.dataset.first='false';}
      catch(e){el('status').textContent='Could not save your preference. You can keep exploring; the tutorial may appear again next time.';}
    }
    try{localStorage.setItem(key,'done');}catch(e){}
    dialog.close();saving=false;if(opener?.isConnected)opener.focus();
  }
  dialog.querySelector('form').addEventListener('submit',e=>{e.preventDefault();dismiss();});
  dialog.addEventListener('cancel',e=>{e.preventDefault();dismiss();});
  el('skip').onclick=dismiss;el('back').onclick=()=>{if(step>0){step--;render();}};
  el('next').onclick=()=>{if(step===steps.length-1)dismiss();else{step++;render();}};
  document.querySelectorAll('[data-replay-tutorial]').forEach(button=>button.addEventListener('click',open));
  let seen=false;try{seen=localStorage.getItem(key)==='done';}catch(e){}
  if(app?!seen:config.dataset.first==='true')open();
})();

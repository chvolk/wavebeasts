/* Shared encounter feedback. Results always come from the host, never the animation. */
(()=>{
 const modal=document.createElement('dialog');modal.className='wb-encounter';modal.setAttribute('aria-labelledby','encounter-title');
 modal.innerHTML='<button class="encounter-close" aria-label="Close result">×</button><div class="encounter-scene" aria-hidden="true"><img alt=""><i></i></div><p class="encounter-label">SIGNAL / CAPTURE</p><h2 id="encounter-title"></h2><p class="encounter-message" role="status"></p><p class="encounter-sync" role="status"></p><button class="encounter-done">Keep exploring</button>';
 const notice=document.createElement('button');notice.className='encounter-notice';notice.hidden=true;notice.setAttribute('aria-live','polite');
 document.body.append(modal,notice);
 let busy=false,opener=null;
 const q=s=>modal.querySelector(s), reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
 function close(){modal.close();if(opener?.isConnected)opener.focus({preventScroll:true});if(busy){notice.textContent=modal.dataset.state==='pending'?'Encounter processing… · View':q('h2').textContent+' · View result';notice.hidden=false;}}
 q('.encounter-close').onclick=q('.encounter-done').onclick=close;
 modal.addEventListener('cancel',e=>{e.preventDefault();close();});
 notice.onclick=()=>{notice.hidden=true;modal.showModal();q('.encounter-done').focus({preventScroll:true});};
 async function run({action,name,sprite,request,sync}){
  if(busy)return;busy=true;opener=document.activeElement;notice.hidden=true;
  modal.dataset.state='pending';q('.encounter-label').textContent=action==='dismiss'?'SIGNAL / RELEASE':'SIGNAL / CAPTURE';
  q('img').src=sprite||'';q('img').hidden=!sprite;q('h2').textContent=action==='dismiss'?'Releasing sighting…':'Throwing drive…';
  q('.encounter-message').textContent=name||'Waiting for your host…';q('.encounter-sync').textContent='You can close this panel while the host responds.';
  if(!modal.open)modal.showModal();q('.encounter-done').focus({preventScroll:true});
  const animation=new Promise(resolve=>setTimeout(resolve,reduced()?0:650));
  let syncing;
  try{
   const result=await request();
   syncing=Promise.resolve().then(sync).then(()=>true,()=>false);
   await animation;
   modal.dataset.state=action==='dismiss'?'dismissed':result.caught?'caught':'escaped';
   q('h2').textContent=action==='dismiss'?'Sighting dismissed':result.caught?'Caught!':'It broke free';
   q('.encounter-message').textContent=result.message||(action==='dismiss'?'Removed from your discovery queue.':result.caught?'Your beast is in your collection.':'Your drive was used. This beast is still wild.');
  }catch(error){
   syncing=Promise.resolve().then(sync).then(()=>true,()=>false);
   await animation;modal.dataset.state='error';q('h2').textContent='Could not confirm the action';
   q('.encounter-message').textContent=error.message||'Connection interrupted. Check the refreshed queue before trying again.';
  }
  q('.encounter-sync').textContent='Updating your queue and inventory…';
  if(!modal.open){notice.textContent=q('h2').textContent+' · View result';notice.hidden=false;}
  const synced=await syncing;
  q('.encounter-sync').textContent=synced?'Queue and inventory are up to date.':'Refresh delayed. Your host may have saved the action; check your connection before trying again.';
  busy=false;
 }
 // Keep the surrounding page steady and animate cards into their new positions.
 function replace(root,html){
  const before=new Map([...root.querySelectorAll('[data-beast-id]')].map(e=>[e.dataset.beastId,e.getBoundingClientRect()]));
  const choices=new Map([...root.querySelectorAll('[data-beast-id] select[name=drive]')].map(e=>[e.closest('[data-beast-id]').dataset.beastId,e.value]));
  root.style.minHeight=Math.max(root.offsetHeight,parseFloat(root.style.minHeight)||0)+'px';
  root.innerHTML=html;
  root.querySelectorAll('[data-beast-id]').forEach(e=>{
   const select=e.querySelector('select[name=drive]'),choice=choices.get(e.dataset.beastId);
   if(select && [...select.options].some(o=>o.value===choice))select.value=choice;
   const old=before.get(e.dataset.beastId),now=e.getBoundingClientRect();
   if(!reduced()&&e.animate)e.animate(old?[{transform:`translate(${old.left-now.left}px,${old.top-now.top}px)`},{transform:'none'}]:[{opacity:0},{opacity:1}],{duration:240,easing:'ease-out'});
  });
 }
 window.WBEncounter={run,replace,get busy(){return busy;}};
})();

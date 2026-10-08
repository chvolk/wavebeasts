/* Refresh only discovery modules. Never repeat a mutation after a network failure. */
(()=>{
 const root=document.getElementById('scan-finds');if(!root)return;
 let revision=0;
 async function refresh(url=location.href){
  const request=++revision;
  const response=await fetch(url,{headers:{'X-Requested-With':'XMLHttpRequest'},cache:'no-store'});
  if(!response.ok)throw Error('Could not refresh discoveries.');
  const doc=new DOMParser().parseFromString(await response.text(),'text/html'),next=doc.getElementById('scan-finds');
  if(!next)throw Error('Sign in again to refresh your discoveries.');
  if(request!==revision)return;
  WBEncounter.replace(root,next.innerHTML);
  for(const key of ['shards','cores']){
   const value=doc.querySelector(`[data-wallet="${key}"]`)?.textContent;
   if(value!=null)document.querySelectorAll(`[data-wallet="${key}"]`).forEach(e=>e.textContent=value);
  }
  const feed=doc.getElementById('scan-feed');
  if(feed&&window.WBScanFeed)WBScanFeed.replace(feed.innerHTML);
  window.WBSightings?.tick();
 }
 root.addEventListener('submit',async event=>{
  const form=event.target,card=form.closest('[data-wild-card]');
  if(!card){
   if(form.method.toLowerCase()!=='get')return;
   event.preventDefault();if(WBEncounter.busy)return;
   const url=new URL(location.href);url.search=new URLSearchParams(new FormData(form)).toString();url.hash='scan-finds';
   try{await refresh(url.href);history.pushState(null,'',url);}catch(e){showRefreshError(e);}
   return;
  }
  event.preventDefault();if(WBEncounter.busy)return;
  revision++;const data=new FormData(form),action=form.action.endsWith('/dismiss')?'dismiss':'catch';
  const disabled=[...root.querySelectorAll('[data-wild-card] button,[data-wild-card] select')];disabled.forEach(e=>e.disabled=true);
  await WBEncounter.run({action,name:card.querySelector('.nm').textContent,sprite:card.querySelector('img')?.src,
   request:async()=>{
    const response=await fetch(form.action,{method:'POST',body:data,headers:{Accept:'application/json'}});
    let result;try{result=await response.json();}catch(e){throw Error('Connection interrupted or session expired. Check the queue before trying again.');}
    if(!response.ok)throw Error(result.error||'Could not update this sighting.');return result;
   },sync:()=>refresh()});
  disabled.forEach(e=>e.disabled=false);window.WBSightings?.tick();
 });
 function showRefreshError(error){
  let message=root.querySelector('[data-refresh-error]');
  if(!message){message=document.createElement('p');message.dataset.refreshError='';message.setAttribute('role','status');root.prepend(message);}
  message.textContent=error.message+' Please try again.';
 }
 root.addEventListener('click',async event=>{
  const link=event.target.closest('nav a');if(!link||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button!==0)return;
  event.preventDefault();if(WBEncounter.busy)return;
  try{await refresh(link.href);history.pushState(null,'',link.href);}catch(e){showRefreshError(e);}
 });
 window.addEventListener('popstate',()=>{if(!WBEncounter.busy)refresh().catch(showRefreshError);});
 // A user interacting with a filter or drive selector keeps that control until they finish.
 setInterval(()=>{if(!document.hidden&&!WBEncounter.busy&&!(root.contains(document.activeElement)&&document.activeElement.matches('input,select,textarea')))refresh().catch(()=>{});},15000);
 window.addEventListener('focus',()=>{if(!WBEncounter.busy&&!(root.contains(document.activeElement)&&document.activeElement.matches('input,select,textarea')))refresh().catch(()=>{});});
 window.WBDiscovery={refresh};
})();

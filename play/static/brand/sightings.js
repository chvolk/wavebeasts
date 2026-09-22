/* One live deadline per sighting. Expiry is server-owned; rendering never extends it. */
(() => {
  function markup(beast) {
    if (!Number.isFinite(beast.expires_in)) return '';
    const remaining=Math.max(0,beast.expires_in), duration=Math.max(1,Number(beast.expiry_duration)||86400);
    if (!beast._expiryDeadline) beast._expiryDeadline=Date.now()+remaining*1000;
    return `<div class="sighting-expiry" data-expires-in="${remaining}" data-expiry-duration="${duration}" data-expiry-deadline="${beast._expiryDeadline}"><div class="expiry-label"><span>TIME LEFT</span><b data-expiry-text></b></div><div class="expiry-track" role="progressbar" aria-label="Sighting time remaining" aria-valuemin="0" aria-valuemax="${duration}"><i></i></div></div>`;
  }
  function tick() {
    document.querySelectorAll('[data-expires-in]').forEach(node=>{
      if (!node.dataset.expiryDeadline) node.dataset.expiryDeadline=Date.now()+Math.max(0,Number(node.dataset.expiresIn)||0)*1000;
      const seconds=Math.max(0,Math.ceil((Number(node.dataset.expiryDeadline)-Date.now())/1000));
      const total=Math.max(1,Number(node.dataset.expiryDuration)||86400), pct=Math.min(100,seconds/total*100);
      const h=Math.floor(seconds/3600), m=Math.floor(seconds%3600/60), s=seconds%60;
      const text=seconds?`${h?String(h).padStart(2,'0')+':':''}${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:'Expired';
      node.querySelector('[data-expiry-text]').textContent=text;
      const bar=node.querySelector('[role=progressbar]');
      bar.setAttribute('aria-valuenow',Math.min(total,seconds));bar.setAttribute('aria-valuetext',seconds?`${h} hours ${m} minutes ${s} seconds remaining`:'Expired');
      bar.querySelector('i').style.width=pct+'%';
      node.classList.toggle('expiring',seconds>0&&seconds<=300);node.classList.toggle('expired',seconds===0);
      if(!seconds){
        const card=node.closest('[data-wild-card]');
        if(card){card.classList.add('sighting-expired');card.querySelectorAll('[data-wild-action],[data-catch-form] button,[data-catch-form] select').forEach(control=>{control.disabled=true;control.setAttribute('aria-disabled','true');if(control.tagName==='A')control.removeAttribute('href');});}
      }
    });
  }
  window.WBSightings={markup,tick};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',tick);else tick();
  setInterval(tick,1000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});
})();

/* Reveal authoritative events only after each sprite animation has finished. */
window.WBBattle = {async play(root,result){
 result=result||{};
 const esc=WBCollection.esc;
 if(!result.events?.length||!result.teams){root.style.whiteSpace='pre-line';root.textContent=[...(result.log||[]),result.winner?`${result.winner==='a'?'Victory':result.winner==='b'?'Defeat':'Draw'} · ${result.turns} turns`:'No replay available.'].join('\n');return;}
 let skipped=false;
 root.innerHTML='<div class="battle-arena"><div data-side="a"></div><b>VS</b><div data-side="b"></div></div><p data-turn role="status">Entering the arena…</p><button type="button" class="btn sec sm" data-skip>Skip replay</button><div class="battle-rows" role="log"></div><h3 data-verdict hidden></h3>';
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const hp={a:result.teams.a.map(b=>b.hp),b:result.teams.b.map(b=>b.hp)};
 const slots={a:0,b:0};
 function show(side,slot){slots[side]=slot;const b=result.teams[side][slot],box=root.querySelector(`[data-side="${side}"]`);box.innerHTML=`<div class="nm">${esc(b.name)} · Lv ${Number(b.level)}</div><img alt="${esc(b.name)}" src="${b.sprite?.startsWith('data:image/png;base64,')?b.sprite:''}"><progress max="${b.hp}" value="${hp[side][slot]}" aria-label="${esc(b.name)} HP"></progress><div>${hp[side][slot]} / ${b.hp} HP</div>`;}
 show('a',0);show('b',0);
 root.querySelector('[data-skip]').onclick=()=>{skipped=true;root.getAnimations({subtree:true}).forEach(a=>a.finish());};
 for(const event of result.events){
  const other=event.side==='a'?'b':'a';
  show(event.side,event.attacker);show(other,event.defender);
  root.querySelector('[data-turn]').textContent=`Turn ${event.turn}`;
  if(!skipped){
   const attacker=root.querySelector(`[data-side="${event.side}"] img`),defender=root.querySelector(`[data-side="${other}"] img`);
   await attacker.animate(reduced?[{opacity:1},{opacity:.65},{opacity:1}]:[{transform:'translateX(0)'},{transform:`translateX(${event.side==='a'?24:-24}px) scale(1.12)`},{transform:'translateX(0)'}],{duration:reduced?180:420}).finished;
   if(!skipped)await defender.animate([{opacity:1},{opacity:.25},{opacity:1}],{duration:reduced?150:280}).finished;
  }
  hp[other][event.defender]=event.hp;show(other,event.defender);
  const row=document.createElement('p');row.textContent=event.text;root.querySelector('.battle-rows').append(row);row.parentElement.scrollTop=row.parentElement.scrollHeight;
  if(!skipped)await new Promise(resolve=>setTimeout(resolve,400));
 }
 const verdict=root.querySelector('[data-verdict]');verdict.hidden=false;verdict.textContent=`${result.winner==='a'?'Victory':result.winner==='b'?'Defeat':'Draw'} · ${result.turns} turns`;
 root.querySelector('[data-skip]').hidden=true;root.querySelector('[data-turn]').textContent='Battle complete';
}};
document.addEventListener('DOMContentLoaded',()=>{const data=document.getElementById('battle-replay');if(data)WBBattle.play(document.getElementById('battle-stage'),JSON.parse(data.textContent)).then(()=>{document.getElementById('battle-reward').hidden=false;});});

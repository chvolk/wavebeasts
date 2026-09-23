/* Shared discovery controls. Filter before pagination; keep rarity order explicit. */
window.WBCollection = (() => {
 const rarities=['common','uncommon','rare','epic','legendary'];
 const types=['ember','tide','leaf','spark','stone','gale','frost','shade','lumen'];
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function controls(id){return `<div class="collection-controls" id="${id}"><label>Search<input data-field="search" type="search" placeholder="Beast name"></label><label>Rarity<select data-field="rarity"><option value="">All rarities</option>${rarities.map(r=>`<option>${r}</option>`).join('')}</select></label><label>Type<select data-field="type"><option value="">All types</option>${types.map(t=>`<option>${t}</option>`).join('')}</select></label><label>Collection<select data-field="favorite"><option value="">All beasts</option><option value="yes">Favorites</option></select></label><label>Sort<select data-field="sort"><option value="recent">Newest</option><option value="rarity">Rarest first</option><option value="level">Highest level</option><option value="type">Type A–Z</option><option value="name">Name A–Z</option></select></label></div>`;}
 function select(rows,root){
  if(!root)return rows;
  const v=k=>root.querySelector(`[data-field="${k}"]`).value;
  const name=b=>String(b.nickname||b.name||'');
  return rows.filter(b=>(!v('favorite')||b.favorite)&&(!v('rarity')||b.rarity===v('rarity'))&&(!v('type')||(b.types||[]).includes(v('type')))&&name(b).toLowerCase().includes(v('search').toLowerCase())).slice().sort((a,b)=>{
   switch(v('sort')){
    case 'rarity':return rarities.indexOf(b.rarity)-rarities.indexOf(a.rarity);
    case 'level':return Number(b.level||0)-Number(a.level||0);
    case 'type':return (a.types||[]).join('/').localeCompare((b.types||[]).join('/'));
    case 'name':return name(a).localeCompare(name(b));
    default:return 0;
   }
  });
 }
 function mount(id,onchange){const host=document.getElementById(id);host.innerHTML=controls(id+'-fields');host.addEventListener('input',onchange);}
 function bindSite(){document.querySelectorAll('[data-collection]').forEach(root=>{
  const toolbar=root.querySelector('[data-controls]');toolbar.innerHTML=controls('filters-'+root.id);
  const groups=[...root.querySelectorAll('[data-beast-list]')].map(list=>({list,rows:[...list.querySelectorAll('[data-beast]')].map(el=>({el,...JSON.parse(el.dataset.beast)}))}));
  const update=()=>{let count=0;for(const {list,rows} of groups){const visible=select(rows,toolbar);rows.forEach(b=>b.el.hidden=true);visible.forEach(b=>{b.el.hidden=false;list.append(b.el)});count+=visible.length;}root.querySelector('[data-filter-count]').textContent=count+' matching beasts';};
  toolbar.addEventListener('input',update);update();
 });}
 document.addEventListener('DOMContentLoaded',bindSite);
 return {controls,select,mount,esc};
})();

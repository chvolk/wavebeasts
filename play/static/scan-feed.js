(()=>{
 const feed=document.getElementById('scan-feed'),source=document.getElementById('feed-source'),order=document.getElementById('feed-order');
 let rows=[];
 function update(){let count=0;for(const row of (order.value==='old'?[...rows].reverse():rows)){row.hidden=!!(source.value&&source.value!==row.dataset.source);feed.append(row);if(!row.hidden)count++;}document.getElementById('feed-count').textContent=count+' resource finds';}
 function init(){const selected=source.value;rows=[...feed.querySelectorAll('[data-source]')];source.replaceChildren(new Option('All devices',''));for(const name of [...new Set(rows.map(r=>r.dataset.source))].sort())source.add(new Option(name,name));source.value=[...source.options].some(o=>o.value===selected)?selected:'';update();}
 [source,order].forEach(el=>el.addEventListener('change',update));init();
 window.WBScanFeed={replace(html){const scroller=feed.closest('[role=region]'),top=scroller.scrollTop;feed.innerHTML=html;init();scroller.scrollTop=top;}};
})();

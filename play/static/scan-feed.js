const feed=document.getElementById('scan-feed'),rows=[...feed.querySelectorAll('[data-source]')],source=document.getElementById('feed-source'),outcome=document.getElementById('feed-outcome'),order=document.getElementById('feed-order');
for(const name of [...new Set(rows.map(r=>r.dataset.source))].sort()){source.add(new Option(name,name));}
function updateFeed(){let count=0;for(const row of (order.value==='old'?[...rows].reverse():rows)){row.hidden=!!((source.value&&source.value!==row.dataset.source)||(outcome.value&&outcome.value!==row.dataset.outcome));feed.append(row);if(!row.hidden)count++;}document.getElementById('feed-count').textContent=count+' matching submissions';}
[source,outcome,order].forEach(el=>el.addEventListener('change',updateFeed));updateFeed();

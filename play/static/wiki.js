(() => {
  // Preserve old links to the former single-page manual.
  const legacy={overview:'overview',how:'scanning',currencies:'scanning',types:'beasts',chart:'type-chart',rarity:'beasts',natures:'beasts',tribes:'beasts',battle:'battles',catching:'catching',nodes:'nodes',cli:'nodes',sensors:'sensors',llm:'ai-setup',premium:'premium'};
  if (location.pathname === '/docs/' && location.hash) {
    const id=location.hash.slice(1);
    if (legacy[id]) location.replace('/docs/'+legacy[id]+'/'+location.hash);
  }
  document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
    const source=document.getElementById(button.dataset.copy),status=button.parentElement.querySelector('[role=status]');
    try {
      await navigator.clipboard.writeText(source.textContent);
      if(status)status.textContent='Copied. Paste into your agent.';
    } catch (_) {
      if(status)status.textContent='Copy unavailable. Select the text below, or download the prompt.';
    }
  }));
})();

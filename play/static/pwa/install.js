(() => {
  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js', {scope:'/'}).catch(() => {}));
  }
  const button = document.getElementById('pwa-install');
  const hint = document.getElementById('pwa-install-hint');
  if (!button || matchMedia('(display-mode: standalone)').matches || navigator.standalone) return;
  let prompt;
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); prompt = event; button.hidden = false;
  });
  button.addEventListener('click', async () => {
    if (!prompt) return;
    await prompt.prompt();
    const choice = await prompt.userChoice;
    prompt = null; button.hidden = true;
    if (choice.outcome === 'accepted' && hint) hint.hidden = true;
  });
  if (hint) {
    hint.hidden = false;
    const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    hint.textContent = ios ? 'On iPhone or iPad: open in Safari, tap Share, then Add to Home Screen. Enable Open as Web App if shown.' : 'Install from your browser’s menu using Install app or Add to Home screen.';
  }
  window.addEventListener('appinstalled', () => { button.hidden = true; if (hint) hint.hidden = true; });
})();

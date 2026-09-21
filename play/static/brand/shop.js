/* Shared progressive enhancement for the website and embedded app shop. */
window.WBSupply = {
  init(root, purchase) {
    if (!root) return;
    let category = 'all';
    let saved = {};
    try { saved = JSON.parse(sessionStorage.getItem('wb_supply_filter') || '{}'); } catch (_) {}
    const search = root.querySelector('[data-shop-search]');
    const filter = () => {
      const term = (search?.value || '').trim().toLowerCase();
      try { sessionStorage.setItem('wb_supply_filter', JSON.stringify({category, search: search?.value || ''})); } catch (_) {}
      let visible = 0;
      root.querySelectorAll('.shopitem').forEach(card => {
        card.hidden = !(category === 'all' || card.dataset.category === category) || !card.dataset.name.toLowerCase().includes(term);
        if (!card.hidden) visible++;
      });
      const empty = root.querySelector('[data-no-results]');
      if (empty) empty.hidden = visible > 0 || !root.querySelector('.shopitem');
    };
    root.querySelectorAll('.shop-filters button').forEach(button => button.addEventListener('click', () => {
      category = button.dataset.category;
      root.querySelectorAll('.shop-filters button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
      filter();
    }));
    search?.addEventListener('input', filter);
    if (search) search.value = saved.search || '';
    const selected = Array.from(root.querySelectorAll('.shop-filters button')).find(b => b.dataset.category === saved.category);
    if (selected) selected.click(); else filter();
    root.querySelectorAll('.purchase-form').forEach(form => {
      const input = form.querySelector('[name=qty]');
      const buy = form.querySelector('[type=submit]');
      const total = form.querySelector('.purchase-total');
      const update = () => {
        const qty = Number(input.value), price = Number(form.dataset.price), currency = form.dataset.currency;
        const balance = Number(root.dataset[currency] || 0);
        const valid = Number.isInteger(qty) && qty >= 1 && qty <= 99;
        const affordable = qty * price <= balance;
        buy.disabled = !valid || !affordable;
        buy.textContent = valid && !affordable ? 'Need ' + currency : 'Buy';
        total.textContent = !valid ? 'Choose a quantity from 1–99.' : `Total: ${qty * price} ${currency} · ${affordable ? balance - qty * price + ' left' : qty * price - balance + ' more needed'}`;
        form.querySelector('[data-step="-1"]').disabled = qty <= 1;
        form.querySelector('[data-step="1"]').disabled = qty >= 99;
      };
      form.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => {
        input.value = Math.max(1, Math.min(99, (Number(input.value) || 1) + Number(button.dataset.step)));
        update();
      }));
      input.addEventListener('input', update);
      form.addEventListener('submit', async event => {
        if (form.dataset.pending === 'true') { event.preventDefault(); return; }
        update();
        if (buy.disabled || !form.reportValidity()) { event.preventDefault(); return; }
        form.dataset.pending = 'true';
        buy.disabled = true; buy.textContent = 'Buying…';
        if (purchase) {
          event.preventDefault();
          try { await purchase(form.elements.item_id.value, Number(input.value)); }
          finally { form.dataset.pending = 'false'; update(); }
        }
      });
      update();
    });
  }
};
document.addEventListener('DOMContentLoaded', () => WBSupply.init(document.getElementById('supply-shop')));

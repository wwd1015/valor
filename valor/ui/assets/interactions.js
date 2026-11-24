// Valor UI interactions. Delegated listeners on document survive Dash re-renders.

// Filter chips: [data-filter-group=X] chips toggle [data-filter-target=X] [data-group] items.
(function () {
  document.addEventListener('click', function (e) {
    const chip = e.target.closest('[data-filter]');
    if (!chip) return;
    const group = chip.closest('[data-filter-group]');
    if (!group) return;
    const name = group.getAttribute('data-filter-group'), value = chip.getAttribute('data-filter');
    group.querySelectorAll('[data-filter]').forEach(c => c.classList.toggle('on', c === chip));
    document.querySelectorAll('[data-filter-target="' + name + '"] [data-group]').forEach(el => {
      el.classList.toggle('hidden-by-filter', value !== 'all' && el.getAttribute('data-group') !== value);
    });
  });
})();

// Expanding cards: [data-expand=id] grows into the #id overlay sheet, from where the card sits.
(function () {
  let opener = null;
  function open(card) {
    const ov = document.getElementById(card.getAttribute('data-expand'));
    if (!ov) return;
    opener = card;
    ov.classList.add('open');
    document.body.classList.add('sheet-open');
    const sheet = ov.querySelector('.sheet'), r = card.getBoundingClientRect(), s = sheet.getBoundingClientRect();
    sheet.style.setProperty('--ox', (r.left + r.width / 2 - s.left) + 'px');
    sheet.style.setProperty('--oy', (r.top + r.height / 2 - s.top) + 'px');
    sheet.style.animation = 'none'; void sheet.offsetHeight; sheet.style.animation = '';
    setTimeout(() => window.dispatchEvent(new Event('resize')), 60);   // let charts size to the sheet
    const close = ov.querySelector('[data-close]'); if (close) close.focus();
  }
  function closeAll() {
    document.querySelectorAll('.sheet-overlay.open').forEach(o => o.classList.remove('open'));
    document.body.classList.remove('sheet-open');
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-close]') || e.target.classList.contains('sheet-overlay')) { closeAll(); return; }
    if (e.target.closest('.sheet a')) { closeAll(); return; }        // a link inside a sheet navigates away
    const card = e.target.closest('[data-expand]');
    if (card) open(card);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll();
    const card = e.target.closest && e.target.closest('[data-expand]');
    if (card && (e.key === 'Enter' || e.key === ' ') && e.target === card) { e.preventDefault(); open(card); }
  });
})();

// Scroll to a #hash target once Dash has rendered it (e.g. /case/X/valuation#whatif).
(function () {
  let done = '';
  new MutationObserver(() => {
    const h = location.hash.slice(1);
    if (!h || done === location.href) return;
    const el = document.getElementById(h);
    if (el) { done = location.href; setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150); }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();

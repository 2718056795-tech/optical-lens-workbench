(() => {
  const menus = document.querySelectorAll('.toolmenu');

  function closeMenu(menu, returnFocus = false) {
    menu.open = false;
    if (returnFocus) menu.querySelector('summary').focus({preventScroll: true});
  }

  document.addEventListener('click', event => {
    const action = event.target.closest('.toolmenu-panel button, .toolmenu-panel a');
    const control = event.target.closest('a[href], button, input, label, select, summary, textarea, [tabindex]');
    for (const menu of menus) {
      if (!menu.open) continue;
      if (!menu.contains(event.target)) {
        closeMenu(menu, !control);
      } else if (action && !action.disabled && action.getAttribute('aria-disabled') !== 'true') {
        closeMenu(menu, true);
      }
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || document.querySelector('dialog[open]')) return;
    const openMenu = Array.from(menus).find(menu => menu.open);
    if (openMenu) {
      event.preventDefault();
      closeMenu(openMenu, true);
    }
  });
})();

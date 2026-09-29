// The SPA's top nav for static pages (research write-ups), which live outside
// the hash router. Links point back into the app via the page's data-root.
//
//   <nav class="nav" data-site-nav data-root="../"></nav>
//   <script type="module" src="../js/site-nav.js"></script>

import { el } from './core/dom.js';
import { NAV_GROUPS, NAV_ROUTES } from './nav-shared.js';

function buildNav(nav) {
  const root = nav.dataset.root || './';
  const route = view => root + (NAV_ROUTES[view] || '#/' + view);

  nav.appendChild(el('a', { class: 'nav-brand', href: route('snapshot') }, 'Purrtfolio'));

  for (const group of NAV_GROUPS) {
    const dropdown = el('div', { class: 'nav-dropdown' });
    const toggle = (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('open');
    };
    dropdown.appendChild(el('div', {
      class: 'nav-dropdown-label',
      tabindex: 0,
      onclick: toggle,
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(e); }
      },
    }, group.label));
    const menu = el('div', { class: 'nav-dropdown-menu' });
    for (const item of group.items) {
      menu.appendChild(el('a', { class: 'nav-link', href: route(item.view) }, item.label));
    }
    dropdown.appendChild(menu);
    nav.appendChild(dropdown);
  }

  nav.appendChild(el('a', {
    class: 'nav-dropdown-label nav-flat active',
    href: root + 'research/',
    'aria-current': 'page',
  }, 'Research'));

  nav.appendChild(el('input', {
    class: 'nav-search',
    type: 'search',
    placeholder: 'Search ticker (e.g. NVDA) and press Enter…',
    onkeydown: (e) => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        location.href = root + '#/ticker/' + encodeURIComponent(e.target.value.trim().toUpperCase());
      }
    },
  }));
  nav.appendChild(el('div', { class: 'nav-spacer' }));
}

document.querySelectorAll('[data-site-nav]').forEach(buildNav);

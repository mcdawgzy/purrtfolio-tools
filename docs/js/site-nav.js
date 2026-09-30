// The SPA's top nav for static pages (research write-ups), which live outside
// the hash router. Links point back into the app via the page's data-root.
//
//   <nav class="nav" data-site-nav data-root="../"></nav>
//   <script type="module" src="../js/site-nav.js"></script>

import { el } from './core/dom.js';
import { NAV_CTA, NAV_GROUPS, NAV_ROUTES } from './nav-shared.js';

function buildNav(nav) {
  const root = nav.dataset.root || './';
  const route = view => root + (NAV_ROUTES[view] || '#/' + view);

  nav.appendChild(el('a', { class: 'nav-brand', href: root + 'research/' }, 'Purrtfolio'));

  nav.appendChild(el('a', {
    class: 'nav-dropdown-label nav-flat active',
    href: root + 'research/',
    'aria-current': 'page',
  }, 'Research'));

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

  nav.appendChild(el('div', { class: 'nav-spacer' }));
  nav.appendChild(el('a', { class: 'btn btn-primary nav-cta', href: NAV_CTA.href }, NAV_CTA.label));
}

document.querySelectorAll('[data-site-nav]').forEach(buildNav);

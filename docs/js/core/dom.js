// DOM helpers and small shared widgets.

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    if (c instanceof Node) {
      e.appendChild(c);
    } else {
      e.appendChild(document.createTextNode(String(c)));
    }
  }
  return e;
}

// Only allow http(s) links from scraped data (blocks javascript:, data:, etc.).
export function safeUrl(u) {
  if (!u) return '#';
  try {
    const url = new URL(String(u));
    return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : '#';
  } catch (e) {
    return '#';
  }
}

export function stat(label, value, cls = '') {
  return el('div', { class: 'stat' },
    el('div', { class: 'stat-label' }, label),
    el('div', { class: 'stat-value ' + cls }, value));
}

export function th(label) {
  return el('th', {}, label);
}

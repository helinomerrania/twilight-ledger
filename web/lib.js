/* Formatting, markup helpers and the one way this app talks to the server.
   Everything here is pure except the functions that call the server. */

import { localiseNow } from './i18n.js';

export const S = {               // whatever the server last told us
  data: null,
  tab: 'tonight',
  page: {},                      // which page of each screen is open: {month: 'settle'}
  month: null,
  on: null,                      // the night on screen
  picked: false,                 // ... picked by hand, rather than tonight's
  count: null,                   // which stock count is on screen
  draft: {},                     // what is half-typed or half-chosen on screen
  search: null,                  // {q, rows} while Books is showing a search
  statement: null,               // a supplier's statement, when one is open
};

/* ----------------------------------------------------------------- numbers */

export const money = n => {
  const v = Math.round(Number(n) || 0);
  return (v < 0 ? '-' : '') + Math.abs(v).toLocaleString('en-US');
};

export const cls = n => (Number(n) > 0 ? 'pos' : Number(n) < 0 ? 'neg' : '');

export const pct = n => (n === null || n === undefined ? '—' : Number(n).toFixed(1) + '%');

export const signed = n => (Number(n) > 0 ? '+' : '') + money(n);

/* ------------------------------------------------------------------- dates */

export const today = () => (S.data ? S.data.today : new Date().toISOString().slice(0, 10));

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];

export const monthName = m =>
  m ? `${MONTHS[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}` : '';

export const monthOf = d => String(d || '').slice(0, 7);

/* ------------------------------------------------------------------ markup */

export const esc = s => String(s === null || s === undefined ? '' : s)
  .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                               '"': '&quot;', "'": '&#39;' }[c]));

/** A JSON value carried in a data- attribute, for the generic handlers. */
export const args = o => esc(JSON.stringify(o));

export const card = (inner, extra = '') =>
  `<div class="card${extra ? ' ' + extra : ''}">${inner}</div>`;

export const tile = (k, v, note = '', kls = '') =>
  `<div class="tile"><div class="k">${esc(k)}</div>
     <div class="v ${kls}">${v}</div>
     ${note ? `<div class="n">${esc(note)}</div>` : ''}</div>`;

export const tiles = list => `<div class="tiles">${list.filter(Boolean).join('')}</div>`;

export const table = (head, body, foot = '') => body
  ? `<div class="scroll"><table><thead><tr>${head}</tr></thead>
       <tbody>${body}</tbody>${foot ? `<tfoot>${foot}</tfoot>` : ''}</table></div>`
  : '';

export const empty = text => `<div class="empty">${esc(text)}</div>`;

export const options = (list, chosen) => (list || []).map(o => {
  const value = typeof o === 'object' ? o.value : o;
  const label = typeof o === 'object' ? o.label : o;
  return `<option value="${esc(value)}"${String(value) === String(chosen ?? '') ? ' selected' : ''}>${esc(label)}</option>`;
}).join('');

/** Pots to pay from or into. Only the ones in use — a pot that has not moved
    in a month and holds nothing is not offered — plus whichever is already
    chosen. The main pot comes first and is the default. */
export const potOptions = chosen => {
  const pots = S.data.pots.filter(p => p.active && (p.in_use || p.name === chosen));
  return options(pots.map(p => p.name), chosen || S.data.main_pot);
};

export const field = (label, inner) => `<div><label>${esc(label)}</label>${inner}</div>`;

export const kindName = k => (S.data && S.data.kinds[k]) || String(k || '').replace(/_/g, ' ');

/* --------------------------------------------------------------- the server */

async function call(path, init) {
  const r = await fetch(path, init);
  let body;
  try { body = await r.json(); } catch { body = { error: `the server replied ${r.status}` }; }
  if (!r.ok || body.error) {
    const err = new Error(body.error || `the server replied ${r.status}`);
    err.status = r.status;
    err.extra = body;
    throw err;
  }
  return body;
}

export const load = (month, on, countDate) => {
  const q = new URLSearchParams();
  if (month) q.set('month', month);
  if (on) q.set('on', on);
  if (countDate) q.set('count_date', countDate);
  return call('/api/state?' + q);
};

/** Do something, and get the whole new state back in the same reply, so the
    screen can never show a figure from before the change. */
export const send = (action, body = {}) => call('/api/do/' + action, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ ...body, view_month: S.month, view_on: S.picked ? S.on : null,
                         view_count: S.count }),
});

export const get = path => call(path);

export const post = (path, body = {}) => call(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const closeCheck = month => call('/api/close?month=' + encodeURIComponent(month));

/* -------------------------------------------------------------------- toast */

/** A short message in the corner. `undo`, when given, is {label, run}: a
    button on the message itself, for a step that is easy to take back. */
export function say(text, isError = false, undo = null) {
  const host = document.getElementById('toast');
  const el = document.createElement('div');
  el.className = isError ? 'msg err' : 'msg';
  const words = document.createElement('span');
  words.textContent = text;
  el.append(words);
  if (undo) {
    const b = document.createElement('button');
    b.className = 'mini';
    b.textContent = undo.label;
    b.onclick = () => { el.remove(); undo.run(); };
    el.append(b);
  }
  host.append(el);
  setTimeout(() => el.remove(), isError ? 9000 : undo ? 8000 : 3200);
}

/** The app's own confirm box, because a destructive or unusual step should
    not be one unguarded click, and the browser's own dialog is easy to
    dismiss without reading. Resolves true for the first button. */
export function ask(title, body, yes = 'Yes', no = 'Cancel') {
  return new Promise(resolve => {
    const host = document.getElementById('toast');
    const box = document.createElement('div');
    box.className = 'ask';
    box.innerHTML = `<strong>${esc(title)}</strong>
      <p style="margin:6px 0 10px;white-space:pre-line">${esc(body)}</p>
      <div class="row"><button class="btn primary" data-yes>${esc(yes)}</button>
        <button class="btn" data-no>${esc(no)}</button></div>`;
    const done = answer => {
      box.remove();
      if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
      resolve(answer);
    };
    const opener = document.activeElement;
    box.setAttribute('role', 'alertdialog');
    box.querySelector('[data-yes]').onclick = () => done(true);
    box.querySelector('[data-no]').onclick = () => done(false);
    box.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); done(false); }
    });
    host.append(box);
    box.querySelector('[data-yes]').focus();
  });
}

/** Ask which stock item something is, from a box offering every item's
    name. Resolves the item, or null. */
export function pickItem(title, body, items) {
  return new Promise(resolve => {
    const host = document.getElementById('toast');
    const box = document.createElement('div');
    box.className = 'ask';
    box.innerHTML = `<strong>${esc(title)}</strong>
      <p style="margin:6px 0 10px;white-space:pre-line">${esc(body)}</p>
      <input list="pickNames" data-scan placeholder="Item" autocomplete="off" spellcheck="false">
      <datalist id="pickNames">${items.map(i => `<option value="${esc(i.name)}">`).join('')}</datalist>
      <p class="neg" style="margin:6px 0 0" hidden>Pick one from the list.</p>
      <div class="row" style="margin-top:10px"><button class="btn primary" data-yes>That is it</button>
        <button class="btn" data-no>Cancel</button></div>`;
    const input = box.querySelector('input');
    const opener = document.activeElement;
    const done = answer => {
      box.remove();
      if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
      resolve(answer);
    };
    const yes = () => {
      const v = input.value.trim().toLowerCase();
      const it = items.find(i => i.name.toLowerCase() === v);
      if (!it) {
        box.querySelector('p.neg').hidden = false;
        input.focus();
        return;
      }
      done(it);
    };
    box.setAttribute('role', 'dialog');
    box.querySelector('[data-yes]').onclick = yes;
    box.querySelector('[data-no]').onclick = () => done(null);
    box.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); done(null); }
      if (e.key === 'Enter' && e.target === input) { e.preventDefault(); e.stopPropagation(); yes(); }
    });
    host.append(box);
    input.focus();
  });
}

/* -------------------------------------------------------------------- print */

/** Print a whole page, A4, the way a report is printed or saved as a PDF to
    send on. It is in Kurdish before it prints, if the screens are. */
export function printPage(html) {
  const page = document.getElementById('page');
  page.innerHTML = html;
  localiseNow(page);
  document.body.classList.add('paging');
  const done = () => {
    document.body.classList.remove('paging');
    window.removeEventListener('afterprint', done);
  };
  window.addEventListener('afterprint', done);
  window.print();
  setTimeout(done, 1500);
}

/** Print a till slip. The page is stripped to the slip only while printing,
    then put back, so the 72mm roll does not feed blank paper first. */
export function printSlip(html) {
  const slip = document.getElementById('slip');
  slip.innerHTML = html;
  localiseNow(slip);
  document.body.classList.add('slipping');
  const done = () => {
    document.body.classList.remove('slipping');
    window.removeEventListener('afterprint', done);
  };
  window.addEventListener('afterprint', done);
  window.print();
  setTimeout(done, 1500);
}

/* Boot, the five screens, and the event handlers.

   A screen is a list of cards and nothing else — no markup of its own. If a
   screen starts needing its own layout, that is a sign a card is missing.

   Every change goes to the server and the whole new state comes back in the
   same reply, so the screen is redrawn from scratch after each one. Two rules
   keep that from getting in the way:

     * nothing typed is lost. Anything typed but not yet saved is put back
       after a redraw, and the cursor stays where it was — except the boxes
       the change has just used, which come back empty.
     * a payment that would take a pot below zero is not simply refused. The
       server says so, and the screen asks whether to go ahead. */

import * as C from './cards.js';
import { said, setLanguage, setNames, useBooks, watch } from './i18n.js';
import {
  S, ask, askDate, closeCheck, empty, en, esc, get, load, loadWords, money, monthName, monthWords, pickItem,
  post, printPage, printSlip, say, send, signed, t, th, withName,
} from './lib.js';

/* ------------------------------------------------------------- the screens */

// each is called tab.<it> in the words
const TABS = ['tonight', 'stock', 'month', 'books', 'setup'];

/* Each screen is a few pages, so nothing has to be scrolled through to find
   it: [key, its label's name in the words, cards, the name of a line under
   the tabs]. The first page is the one a screen opens on, until another is
   picked; HEADS go above every page. */
const PAGES = {
  tonight: [
    ['close', 'page.closing_up', [C.needsALook, C.closingUp, C.nightDrawer]],
    ['today', 'page.today', [C.todayFigures, C.todayEntries]],
    ['sold', 'page.sold_tonight', [C.nightSold]],
  ],
  stock: [
    ['count', 'page.count', [C.stockFigures, C.countPicker, C.countSheet]],
    ['fill', 'page.fill', [C.fillCard]],
    ['receipts', 'page.receipts', [C.receiptForm, C.receiptList]],
    ['shelf', 'page.shelf', [C.countPicker, C.expectedCard, C.ratiosCard]],
    ['counts', 'page.past_counts', [C.countHistory]],
  ],
  month: [
    ['profit', 'page.profit', [C.monthFigures, C.soFarCard, C.resultCard]],
    ['settle', 'page.settle', [C.settleCard, C.electricityCard, C.payrollCard, C.partnersCard,
                               C.suppliersCard]],
    ['cash', 'page.cash', [C.moneyFlow, C.cashDifferences]],
    ['sales', 'page.sales', [C.salesByDay, C.monthSold, C.monthWhen, C.monthMakes]],
    ['close', 'page.checks', [C.allChecks, C.closeCard, C.everyMonth]],
  ],
  books: [
    ['entries', 'page.entries', [C.newEntryCard, C.entryList]],
    ['cash', 'page.cash_counts', [C.whereMoneyIs, C.cashCountsCard]],
    ['changes', 'page.changes', [C.recentChanges]],
  ],
  setup: [
    ['people', 'page.people', [
      () => C.editAccounts('staff', t('people.staff'), t('people.staff_note')),
      () => C.editAccounts('supplier', t('people.suppliers'), t('people.suppliers_note')),
      () => C.editAccounts('partner', t('people.partners'), t('people.partners_note'))]],
    ['cash', 'page.cash', [
      () => C.editAccounts('cash', t('people.pots'), t('people.pots_note')),
      C.floatsCard, C.cashCountingCard]],
    ['bills', 'page.bills', [C.editFixed, C.editElecFactors]],
    ['stock', 'page.stock', [C.editItems, C.menuUses, C.editTares, C.editConversions], 'page.stock_note'],
    ['lists', 'page.lists', [
      () => C.editList('expense', t('lists.expense'), t('lists.expense_note')),
      () => C.editList('income', t('lists.income'), ''),
      () => C.editList('reason', t('lists.reason'), '')], 'page.lists_note'],
    ['sambapos', 'page.sambapos', [C.sambaposCard, C.sambaposAccounts, C.sambaposMenu], 'page.sambapos_note'],
    ['app', 'page.app', [C.businessCard, C.languageCard, C.backupCard, C.updateCard], 'page.app_note'],
  ],
};

const HEADS = { month: C.periodPicker };

/** One card, drawn on its own: a card that cannot be drawn says so in its
    place, and the rest of the page is still drawn and still works. */
function draw(card) {
  try {
    return card() || '';
  } catch (err) {
    console.error(err);
    return `<div class="banner bad"><strong>${th('app.part_not_drawn')}</strong>
      <p style="margin:0">${esc(err.message)}</p></div>`;
  }
}

/** How many checks that are not right point at each page ('books/cash'),
    and at each screen; Checks and closing has all of them. */
function pageMarks() {
  const out = {};
  if (!S.data) return out;
  const bad = S.data.checks.filter(c => !c.ok);
  for (const c of bad) {
    if (!c.go) continue;
    out[c.go] = (out[c.go] || 0) + 1;
    const screen = c.go.split('/')[0];
    out[screen] = (out[screen] || 0) + 1;
  }
  if (bad.length) out['month/close'] = bad.length;
  return out;
}

/** The page of `tab` that is open. */
const pageOf = tab => {
  const pages = PAGES[tab];
  return pages.find(p => p[0] === S.page[tab]) || pages[0];
};
const onPage = (tab, key) => S.tab === tab && pageOf(tab)[0] === key;

/* ----------------------------------------------- what is typed, and where */

/** A name for a box that survives a redraw: what it is, not where it is. */
function fieldKey(el) {
  if (el.dataset.pot !== undefined) return 'pot:' + el.dataset.pot;
  if (el.id) return '#' + el.id;
  const item = el.closest('[data-item]');
  if (item && el.dataset.k) return `item:${item.dataset.receipt || ''}:${item.dataset.item}:${el.dataset.k}`;
  const edit = el.closest('[data-edit]');
  if (edit && el.dataset.e) return `edit:${edit.dataset.edit}:${el.dataset.e}`;
  const line = el.closest('[data-line]');
  if (line && el.dataset.s) return `settle:${line.dataset.line}:${el.dataset.s}`;
  if (el.dataset.save) return `save:${el.dataset.save}:${el.dataset.args}:${el.dataset.field}`;
  const add = el.closest('.addrow');
  const btn = add && add.querySelector('[data-add]');
  if (btn && el.dataset.f) return `add:${btn.dataset.add}:${btn.dataset.args}:${el.dataset.f}`;
  return null;
}

const firstValue = sel => {
  const o = [...sel.options].find(x => x.defaultSelected) || sel.options[0];
  return o ? o.value : '';
};

/** Typed into, and not saved yet. */
const dirty = el => (el.tagName === 'SELECT' ? el.value !== firstValue(el)
                                             : el.value !== el.defaultValue);

const fields = () => [...document.querySelectorAll('#main input, #main select, #main textarea')];

/* ------------------------------------------------------------------ render */

function renderRail() {
  const rail = document.getElementById('rail');
  rail.setAttribute('aria-label', t('app.screens'));
  const bad = S.data ? S.data.checks.filter(c => !c.ok).length : 0;
  rail.querySelectorAll('button.tab').forEach(b => b.remove());
  let foot = rail.querySelector('.foot');
  if (!foot) {
    foot = document.createElement('div');
    foot.className = 'foot';
    rail.append(foot);
  }
  const marks = pageMarks();
  TABS.forEach(key => {
    const b = document.createElement('button');
    b.className = 'tab';
    b.dataset.go = key;
    b.setAttribute('aria-current', String(key === S.tab));
    // Tonight counts everything that needs a look; a screen with a page that needs one shows a dot
    b.innerHTML = `<span>${th(`tab.${key}`)}</span>`
      + (key === 'tonight' && bad ? `<span class="flag" title="${th('rail.need_look', bad)}">${bad}</span>`
        : key !== 'tonight' && marks[key] ? `<span class="dot" title="${th('rail.need_look', marks[key])}"></span>` : '');
    rail.insertBefore(b, foot);
  });
  if (!S.data) return;
  document.getElementById('brandsub').textContent =
    (S.data.business.name || '') + ' · ' + S.data.today;
  foot.innerHTML = `<div>${th('rail.on_hand', `<strong>${money(S.data.cash)}</strong>`)}</div>
    <span>${th('rail.version', esc(S.data.version))}</span>`;
}

/* Drawing the screen again takes away the box being typed in, and the browser
   takes that for leaving it: a half-typed 8 of an 83 was saved as the count, as
   the screen was drawn again for the line before. While what is typed in it is
   being put into the box drawn in its place, this is that box, and nothing is
   saved for it. */
let drawing = null;

/* A number box half way through 12.5 says it holds 12, and has no point to be
   read back; what was last typed into it says there was one. */
let typedLast = null;
document.addEventListener('input', e => { typedLast = { el: e.target, data: e.data }; }, true);

/** Redraw the screen. Unless `fresh`, whatever was typed and not saved is put
    back, and the cursor is put back where it was. `skip` names the boxes the
    change just used, which should come back as the server now has them. */
function render({ fresh = false, skip = [] } = {}) {
  const main = document.getElementById('main');
  const kept = new Map();
  let focus = null;
  if (!fresh) {
    for (const el of fields()) {
      const k = fieldKey(el);
      if (k && dirty(el) && !skip.includes(k)) kept.set(k, el.value);
    }
    const a = document.activeElement;
    if (a && main.contains(a) && a.matches('input, select, textarea')) {
      focus = { key: fieldKey(a), start: null, end: null,
                point: a.type === 'number' && typedLast?.el === a && typedLast.data === '.' };
      try { focus.start = a.selectionStart; focus.end = a.selectionEnd; } catch { /* number boxes */ }
    }
  }
  renderRail();
  const title = t(`tab.${S.tab}`);
  const [key, , cards, note] = pageOf(S.tab);
  const marks = pageMarks();
  const tabs = PAGES[S.tab].map(([k, label]) => {
    const n = marks[`${S.tab}/${k}`];
    // Checks and closing says how many are not right; any other page just shows it needs a look
    const count = S.tab === 'month' && k === 'close';
    return `<button data-go="${S.tab}/${k}" aria-current="${k === key}"><span>${th(label)}</span>${n
      ? `<span class="dot${count ? ' n' : ''}" title="${th('rail.need_look', n)}">${count ? n : ''}</span>` : ''}</button>`;
  }).join('');
  // a date far ahead of the books is doubted before anything is charged on it
  const clock = S.data.clock ? `<div class="banner bad"><strong>${th('clock.title')}</strong>
      <p style="margin:6px 0 10px">${th('clock.says', esc(S.data.today), ...monthWords(S.data.clock.last))}</p>
      <button class="btn" data-do="clock_ok" data-args="{}"
        data-confirm="${th('clock.ask')}"
        data-confirm-body="${th('clock.ask_body')}"
        data-yes="${th('clock.yes')}">${th('clock.right')}</button></div>` : '';
  const stayed = S.stayed && S.on === S.stayed ? `<div class="banner">
      <strong>${th('night.past_six')}</strong>
      <p style="margin:6px 0 10px">${th('night.still_on', esc(S.stayed))}</p>
      <button class="btn" data-act="newNight">${th('night.go_new')}</button></div>` : '';
  drawing = focus && kept.has(focus.key) ? document.activeElement : null;
  try {
    main.innerHTML = clock + stayed + `<h1>${esc(title)}</h1>`
      + `<div class="pagebar"><nav class="pages" aria-label="${esc(title)}">${tabs}</nav>`
      + `${HEADS[S.tab] ? draw(HEADS[S.tab]) : ''}</div>`
      + (note ? `<p class="pagenote">${th(note)}</p>` : '')
      + (cards.map(draw).join('') || `<div class="card">${empty(t('app.nothing_here'))}</div>`);
  } finally {
    drawing = null;
  }
  if (onPage('stock', 'fill') && S.draft.fill) fillFigures();
  applyFind();
  if (!kept.size && !focus) return;
  const byKey = new Map();
  for (const el of fields()) {
    const k = fieldKey(el);
    if (k) byKey.set(k, el);
  }
  kept.forEach((v, k) => {
    const el = byKey.get(k);
    if (!el || el.disabled) return;
    if (el.tagName === 'SELECT' && ![...el.options].some(o => o.value === v)) return;
    el.value = v;
  });
  const el = focus && focus.key && byKey.get(focus.key);
  if (el) {
    el.focus({ preventScroll: true });
    if (focus.start !== null) {
      try { el.setSelectionRange(focus.start, focus.end); } catch { /* not a text box */ }
    } else if (el.type === 'number') {
      // A number box cannot say where its cursor was, and drawn again it had it
      // before the number: on to a line that held 74 as the line left was saved,
      // a 7 typed over it made 774. Not typed in yet, its number is picked, to be
      // typed over as it was on the way in; typed in, the cursor goes after it.
      if (kept.has(focus.key) || focus.point) {
        const v = el.value;
        el.value = '';
        el.value = v;
        if (focus.point) document.execCommand('insertText', false, '.');
      } else el.select();
    }
    if (kept.has(focus.key) && el.tagName !== 'SELECT') carry(el);
  }
}

/* What was typed is put back into the box drawn in its place; put back by the
   app, it is no change to the browser, and leaving the box would not save it.
   It is saved on leaving, as it would have been. */
function carry(el) {
  let told = false;
  el.addEventListener('change', () => { told = true; }, { once: true });
  el.addEventListener('blur', () => {
    if (!told && drawing !== el && dirty(el)) el.dispatchEvent(new Event('change', { bubbles: true }));
  }, { once: true });
}

/** English or Kurdish, and in Kurdish, the Kurdish kept in the books from
    before it came with the app. The language is also kept in this browser,
    so the next start opens the right way round before the books arrive. */
let booksAsked = false;

async function useLanguage(state) {
  const l = state.lang || {};
  setLanguage(l.language);
  try { localStorage.setItem('twilight.lang', l.language || 'en'); } catch { /* not kept */ }
  if (l.language === 'ckb' && !booksAsked) {
    booksAsked = true;
    try { useBooks(await get('/api/lang')); } catch { booksAsked = false; }
  }
  setNames(state);
}

/** Take a new state from the server, refresh anything open beside it, and
    redraw. */
let applied = 0;
let shownAt = 0;             // when the state on screen arrived
let pageNight = null;         // the night it was when this screen last moved on
let loadedAs = null;         // the app's version when this page was loaded

async function apply(state, opts = {}) {
  // A page left open across an update is still running the old screens
  // against the new app: load the new ones before showing or sending anything.
  if (loadedAs && state.version && state.version !== loadedAs) { location.reload(); return; }
  loadedAs = loadedAs || state.version;
  applied++;
  shownAt = Date.now();
  pageNight = pageNight || state.tonight;
  S.data = state;
  S.month = state.month;
  S.on = state.day.on;
  S.count = state.stock.count_date;
  await useLanguage(state);
  try {
    if (S.search) {
      S.search.rows = await get(`/api/entries?q=${encodeURIComponent(S.search.q)}&limit=300`);
    }
    if (S.statement) {
      S.statement = await get(`/api/supplier?id=${S.statement.id}&month=${S.month}`);
    }
  } catch {
    /* leave what is on screen; the next change will try again */
  }
  render(opts);
  watchBackups();
}

/* SambaPOS's backups are read by the server in the background. While some are
   still to be read, the screen asks again every few seconds, so a night shows
   up by itself without anything being clicked. A quiet look never replaces a
   state that arrived while it was on its way, and waits while a question is
   being asked. */
let watchTimer = 0;
let watchTries = 0;

async function refreshQuietly() {
  if (document.querySelector('.ask')) return watchBackups();
  const gen = applied;
  try {
    const state = await load(S.month, picked(), S.count);
    if (applied === gen && !document.querySelector('.ask')) await apply(state);
  } catch {
    /* the next change will bring the state anyway */
  }
  return undefined;
}

/* The night on screen is the night the lounge is in, which runs until six in
   the morning, unless another day was picked. A page left open goes on to
   the next night by itself, so tonight's figure is never typed into last
   night's books; a day picked by hand is let go when the night changes. */
const picked = () => (S.picked ? S.on : null);

function nightNow() {
  const ends = (S.data && S.data.night_ends) || 6;
  const d = new Date(Date.now() - ends * 3600 * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/* Six in the morning ends the night. A screen left alone moves on to the new
   night by itself, and lets go of a day picked by hand, so that tonight's
   takings are never typed over last night's. One still in use then, while
   the night is being closed up, stays on it until asked to move on: it went
   on to the new night under him, and the drawer counted at ten to six and
   saved at five past, or the next expense typed in, was dated the new night,
   which then showed money it had never taken while the night it belonged to
   showed none counted. */
let touched = 0;                 // when this screen was last typed or clicked in
for (const ev of ['input', 'keydown', 'click']) {
  document.addEventListener(ev, () => { touched = Date.now(); }, true);
}
const IN_USE = 15 * 60 * 1000;   // touched within the last quarter of an hour

const inUse = () => Date.now() - touched < IN_USE || !!document.querySelector('.ask')
  || fields().some(el => el.type !== 'search' && dirty(el));

/* The night has ended under a screen still on tonight's. */
const nightOver = () => !!S.data && !S.picked && !!pageNight && nightNow() !== pageNight;

/* Keep the night on screen, as if picked by hand, and say so. */
function stayOnTheNight() {
  S.picked = true;
  S.stayed = S.on;
}

function followTheNight() {
  if (!S.data || !pageNight || nightNow() === pageNight) return;
  if (inUse()) {
    if (!S.picked) {
      stayOnTheNight();
      render();
    }
    return;
  }
  S.picked = false;
  S.stayed = null;
  pageNight = nightNow();
  refreshQuietly();
}
setInterval(followTheNight, 60 * 1000);

/* A second window on the books (the shortcut opens one each time it is
   started while the app is already open) went on showing what the books said
   when it was last used: a salary paid in the other window still unpaid, and
   one click from being paid twice. Brought back to the front, it asks again. */
function lookAgain() {
  if (document.hidden || !S.data) return;
  if (pageNight && nightNow() !== pageNight) followTheNight();
  else if (Date.now() - shownAt > 3000) refreshQuietly();
}
window.addEventListener('focus', lookAgain);
document.addEventListener('visibilitychange', lookAgain);
window.addEventListener('pageshow', e => { if (e.persisted) lookAgain(); });

/* Started from its desktop icon, the app has no black window to close: it
   stops once the last of its windows has gone. So each page tells it that it
   is open, now and every so often, and says goodbye as it goes; a page being
   loaded again does both, and the app waits a moment for it. */
const PAGE = Math.random().toString(36).slice(2) + Date.now().toString(36);
// the answer is read, or the browser keeps its connection waiting for someone to
const here = () => fetch(`/api/here?page=${PAGE}`, { cache: 'no-store' }).then(r => r.text()).catch(() => {});
here();
setInterval(here, 20 * 1000);
window.addEventListener('pagehide', () => navigator.sendBeacon(`/api/bye?page=${PAGE}`));
window.addEventListener('pageshow', e => { if (e.persisted) here(); });

function watchBackups() {
  clearTimeout(watchTimer);
  const a = S.data && S.data.pos && S.data.pos.auto;
  if (!a || !(a.waiting || a.reading)) {
    watchTries = 0;
    return;
  }
  if (++watchTries <= 40) watchTimer = setTimeout(refreshQuietly, 2500);
}

/* Amounts of money show their commas as they are typed: 1250000 is shown as
   1,250,000, with the cursor still after the same digit. */
function moneyBox(el, how) {
  let raw = westernDigits(el.value).replace(NO_FILS, '');
  let at = el.selectionStart ?? raw.length;
  const digitsOf = s => westernDigits(String(s)).replace(/[^\d]/g, '');
  // Delete or Backspace on a comma took only the comma, which would come
  // straight back and leave the box stuck: take the digit beyond it instead
  if ((how === 'deleteContentBackward' || how === 'deleteContentForward')
      && digitsOf(raw) === digitsOf(el.dataset.was ?? el.defaultValue)) {
    const i = how === 'deleteContentBackward' ? at - 1 : at;
    if (i >= 0 && i < raw.length) {
      raw = raw.slice(0, i) + raw.slice(i + 1);
      if (how === 'deleteContentBackward') at = i;
    }
  }
  const before = raw.slice(0, at).replace(/[^\d]/g, '').length;
  const digits = raw.replace(/[^\d]/g, '').replace(/^0+(?=\d)/, '');
  const shown = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  el.dataset.was = shown;
  if (shown === el.value) return;
  el.value = shown;
  let pos = 0;
  for (let seen = 0; pos < shown.length && seen < before; pos++) if (/\d/.test(shown[pos])) seen++;
  try { el.setSelectionRange(pos, pos); } catch { /* not focused */ }
}

/* A find box keeps only the rows whose name has what was typed, with their
   brand or flavours, and hides a group, or a heading, with nothing left
   under it. What was typed stays when the screen is redrawn. */
function applyFind() {
  document.querySelectorAll('#main input.find').forEach(box => {
    const q = ((S.draft.find || {})[box.dataset.find] || '').trim().toLowerCase();
    const scope = box.closest('.card');
    const rows = [...scope.querySelectorAll('tr[data-name]')];
    const shown = new Set(rows.filter(r => !q || r.dataset.name.includes(q)));
    if (q) {
      for (const r of [...shown]) {
        if (r.dataset.of) scope.querySelectorAll(`tr[data-brand="${r.dataset.of}"]`).forEach(b => shown.add(b));
        if (r.dataset.brand) scope.querySelectorAll(`tr[data-of="${r.dataset.brand}"]`).forEach(f => shown.add(f));
      }
    }
    rows.forEach(r => { r.hidden = !shown.has(r); });
    scope.querySelectorAll('tr.typeh').forEach(h => {
      let n = h.nextElementSibling;
      let any = false;
      while (n && !n.classList.contains('typeh')) { if (n.dataset.name && !n.hidden) any = true; n = n.nextElementSibling; }
      h.hidden = Boolean(q) && !any;
    });
    scope.querySelectorAll('.findgroup').forEach(g => {
      g.hidden = Boolean(q) && !g.querySelector('tr[data-name]:not([hidden])');
    });
    if (q) scope.querySelectorAll('details').forEach(d => { if (d.querySelector('tr[data-name]:not([hidden])')) d.open = true; });
  });
}

document.addEventListener('input', e => {
  const el = e.target;
  if (!(el instanceof HTMLInputElement)) return;
  if (el.dataset.money !== undefined) moneyBox(el, e.inputType);
  if (el.dataset.find) {
    S.draft.find = { ...(S.draft.find || {}), [el.dataset.find]: el.value };
    applyFind();
  }
});

/** Open a screen, or one page of it: 'month' or 'month/settle'. */
function setTab(where) {
  const [tab, page] = String(where || '').split('/');
  if (!PAGES[tab]) return;
  if (page && PAGES[tab].some(p => p[0] === page)) S.page[tab] = page;
  S.tab = tab;
  try { history.replaceState(null, '', `#${tab}/${pageOf(tab)[0]}`); } catch { /* not important */ }
  render({ fresh: true });
  window.scrollTo(0, 0);
  // opening Tonight looks for a new SambaPOS backup
  const a = S.data && S.data.pos && S.data.pos.auto;
  if (tab === 'tonight' && a && a.on) refreshQuietly();
}

/* ----------------------------------------------------------------- helpers */

/** What a box holds: an amount of money without its commas. */
/* A dinar has nothing after the point: a figure pasted as 250,000.00 is
   250,000, not 25,000,000. */
const NO_FILS = /\.0{1,2}$/;

const plain = el => (el.dataset.money !== undefined
  ? westernDigits(el.value).replace(NO_FILS, '').replace(/[^\d]/g, '') : el.value.trim());

const val = id => {
  const el = document.getElementById(id);
  return el ? plain(el) : '';
};

const num = id => {
  const v = val(id).replace(/,/g, '');
  return v === '' ? 0 : Number(v);
};

const focusOn = id => {
  const el = document.getElementById(id);
  if (el) el.focus();
};

/** Run one change. Returns the server's reply, or null if it failed or the
    person decided against it. */
let sent = 0;
let shown = 0;

async function act(fn, { skip = [], onError = null } = {}) {
  if (nightOver()) stayOnTheNight();
  const mine = ++sent;
  try {
    const out = await fn();
    if (!out) return null;
    if (out.state && mine >= shown) {
      shown = mine;
      await apply(out.state, { skip });
    }
    // saved, but something after it was not: said, and never as a failure
    if (out.warning) {
      say(out.warning, true);
      if (!out.state) refreshQuietly();
    }
    return out;
  } catch (err) {
    say(err.message, true);
    if (onError) onError(err);
    return null;
  }
}

/** The message after a change that wrote an entry, with Undo: the entry is
    taken back, and whatever it corrected or replaced stands again. Only for
    a change whose answer is the one entry it wrote. */
function done(text, out) {
  if (!out || typeof out.id !== 'number') return say(text);
  say(text, false, { label: t('common.undo'), run: () => undoChange(out.id) });
}

async function undoChange(id) {
  const out = await act(() => send('undo', { id }));
  if (out) say(out.put_back && out.put_back.length ? t('undo.replaced_back') : t('undo.taken_back'));
}

/** Send a change that moves money. If it would take a pot below zero the
    server refuses with 409 and says by how much; the person is asked, and
    the change is sent again only if they say so. */
async function sendGuarded(action, body, yes = t('guard.pay_anyway')) {
  try {
    return await send(action, body);
  } catch (err) {
    const short = err.status === 409 && err.extra && err.extra.overdraw;
    if (!short || !short.length) throw err;
    const s = short[0];
    const hint = !S.data.day.sales ? t('guard.no_sales') : t('guard.elsewhere', s.pot);
    const ok = await ask(t('guard.title', s.pot),
      `${t('guard.holds', money(s.holds), money(s.short_by), s.on)}\n\n${hint}`, yes, t('guard.go_back'));
    if (!ok) return null;
    return send(action, { ...body, allow_overdraw: true });
  }
}

const nightLabel = kind => (C.NIGHT.includes(kind) ? t(`night_kind.${kind}`) : kind);

/** Keep a copy of SambaPOS, and say which nights it covered. Reading a
    backup or the database takes a moment, so the button says so meanwhile. */
async function keepPos(el, action) {
  const label = el.textContent;
  el.disabled = true;
  el.textContent = t('keep.reading');
  try {
    const out = await act(() => send(action));
    if (!out) return;
    const kept = (out.kept || []).filter(l => l.tickets);
    // a folder of backups can hold the same work period many times; the
    // last line for each is the one that counts
    const last = new Map(kept.map(l => [`${l.pos_id}|${l.started_at}`, l]));
    const fresh = kept.filter(l => l.status === 'new' || l.status === 'updated');
    const nights = [...new Set(fresh.map(l => l.night))];
    if (out.failed && out.failed.length) say(out.failed.join(' '), true);
    if (!kept.length) {
      say(t('keep.no_tickets'), true);
    } else if (!nights.length) {
      say(t('keep.nothing_new'));
    } else {
      const unpaid = [...last.values()].reduce((n, l) => n + l.unpaid, 0);
      const live = action === 'pos_live';
      say((nights.length === 1 ? t('keep.night', nights[0]) : t('keep.nights', nights.length))
        + (unpaid && live ? t('keep.unpaid', money(unpaid)) : ''),
        !!(unpaid && live));
    }
  } finally {
    el.disabled = false;
    el.textContent = label;
  }
}

/* ------------------------------------------------------------------- slips */

/* The top of every slip: whose, what, which month, and when it was printed. */
function slipHead(title, sub = '') {
  const n = new Date();
  const hm = `${String(n.getHours()).padStart(2, '0')}:${String(n.getMinutes()).padStart(2, '0')}`;
  return `<div class="head"><h3>${esc(S.data.business.name || t('slip.default_name'))}</h3>
    <div><strong>${esc(title)}</strong></div>${sub ? `<div>${esc(sub)}</div>` : ''}
    <div>${th('slip.printed', esc(S.data.today), hm)}</div></div>
    <div class="rule"></div>`;
}

/* A line of a slip; both sides are markup already made safe. */
const slipRow = (left, right, strong = false) => (strong
  ? `<tr><td><strong>${left}</strong></td><td style="text-align:end"><strong>${right}</strong></td></tr>`
  : `<tr><td>${left}</td><td style="text-align:end">${right}</td></tr>`);

const dayMonth = on => `${on.slice(8, 10)}/${on.slice(5, 7)}`;

/* A day and what happened on it, each its own piece, so that the words are
   put into Kurdish whatever the day. */
const pair = (...pieces) => pieces.filter(Boolean).map(p => `<span>${p}</span>`).join(' ');

/* "for October 2026", on a payment that paid what was owed from before the
   month, or "300,000 for October 2026" when it paid only part of it. */
const forMonth = l => (l.earlier || []).map(([m, v]) => esc(v === l.amount
  ? t('entries.for_month', ...monthWords(m)) : t('flow.amount_for', money(v), ...monthWords(m)))).join(', ');

/* What went out this month for earlier months: each month, what it was, and
   each name, for the Cash slips. */
const earlierRows = f => f.earlier.map(m => slipRow(esc(monthName(m.month)), money(m.total), true)
  + m.kinds.map(k => slipRow(`&nbsp;&nbsp;${esc(k.label)}`, money(k.total))
    + k.rows.map(([n, v]) => slipRow(`&nbsp;&nbsp;&nbsp;&nbsp;${esc(n)}`, money(v))).join('')).join(''))
  .join('');

/* An entry's day, and its time where the books know it. */
const when = l => dayMonth(l.on) + (l.time ? ` ${l.time}` : '');

/* ----------------------------------------------------------------- actions */

const H = {
  go(el) { setTab(el.dataset.go); },

  lookToggle(el) {
    S.draft.lookOpen = !S.draft.lookOpen;
    el.closest('details').open = S.draft.lookOpen;
  },

  /* ---------------------------------------------------------- moving around */

  async newNight() {
    S.picked = false;
    S.stayed = null;
    pageNight = nightNow();
    try { await apply(await load(S.month, null, S.count), { fresh: true }); }
    catch (err) { say(err.message, true); }
  },

  async setDay(el) {
    const on = el.dataset.on || el.value;
    // A year is typed a digit at a time, and the box says 0002, 0020, 0202 on
    // the way to 2025: those are not nights to show, nor to say are wrong.
    if (!/^2\d{3}-/.test(on)) return;
    S.picked = on !== S.data.tonight;
    S.stayed = null;
    try { await apply(await load(S.month, S.picked ? on : null, S.count), { fresh: true }); }
    catch (err) { say(err.message, true); }
  },

  async setMonth(el) {
    const m = el.dataset.m || el.value;
    if (!m) return;
    try {
      await apply(await load(m, picked()), { fresh: true });
      if (el.dataset.m) window.scrollTo(0, 0);
    } catch (err) { say(err.message, true); }
  },

  async setCount(el) {
    try { await apply(await load(S.month, picked(), el.value), { fresh: true }); }
    catch (err) { say(err.message, true); }
  },

  /* ---------------------------------------------------------------- tonight */

  nKind(el) {
    S.draft.nKind = el.dataset.k;
    S.draft.nWho = val('nWho');           // kept when it is in the new list
    S.draft.nPot = val('nPot');
    render({ skip: ['#nWho'] });
    focusOn('nAmt');
  },

  nWho(el) {
    S.draft.nWho = el.dataset.who;
    const sel = document.getElementById('nWho');
    if (sel) sel.value = el.dataset.who;
    el.parentElement.querySelectorAll('button')
      .forEach(b => b.setAttribute('aria-pressed', String(b === el)));
    focusOn('nAmt');
  },

  async sales() {
    const amount = num('nSales');
    if (!amount) return say(t('sales.type_first'), true);
    const out = await act(() => sendGuarded('sales', { amount, on: S.on }, t('guard.save_anyway')),
                          { skip: ['#nSales'] });
    if (out) done(t('sales.saved', S.on, money(amount)), out);
  },

  async usePos(el) {
    const amount = Number(el.dataset.amount);
    const out = await act(() => sendGuarded('sales', { amount, on: S.on }, t('guard.save_anyway')),
                          { skip: ['#nSales'] });
    if (out) done(t('sales.saved_pos', S.on, money(amount)), out);
  },

  async nAdd() {
    const kind = S.draft.nKind || 'expense';
    const who = val('nWho');
    const amount = num('nAmt');
    const pot = val('nPot');
    if (!who) return say(t('night_add.pick_who'), true);
    if (!amount) return say(t('common.type_amount'), true);
    S.draft.nWho = who;
    S.draft.nPot = pot;
    const out = await act(() => sendGuarded(kind, { amount, who, detail: who, pot, on: S.on },
                                            kind === 'staff_repay' ? t('guard.save_anyway') : t('guard.pay_anyway')),
                          { skip: ['#nAmt'] });
    if (!out) return;
    done(`${nightLabel(kind)}: ${who}, ${money(amount)}.`, out);
    focusOn('nAmt');
  },

  async saveCount() {
    const pots = {};
    const keys = [];
    document.querySelectorAll('#main [data-pot]').forEach(el => {
      pots[el.dataset.pot] = plain(el);
      keys.push(fieldKey(el));
    });
    if (!Object.values(pots).some(v => v !== '')) return say(t('cash_count.at_least_one'), true);
    const out = await act(() => send('cash_count', { on: S.on, reason: val('nReason'), pots }),
                          { skip: [...keys, '#nReason'] });
    if (!out) return;
    if (!out.diff) return say(t('cash_count.ties'));
    say(t('cash_count.out_by', signed(out.diff)));
  },

  /* ------------------------------------------------------------------ books */

  pickKind(el) {
    S.draft.kind = el.value;
    render({ skip: ['#eDetail'] });
  },

  async addEntry() {
    const kind = val('eKind');
    const amount = num('eAmt');
    if (!amount) return say(t('common.type_amount'), true);
    const body = { amount, on: val('eDate'), period: val('ePeriod') };
    if (kind === 'transfer') {
      body.from = val('eFrom');
      body.to = val('eTo');
      if (body.from === body.to) return say(t('new_entry.two_pots'), true);
    } else {
      body.detail = val('eDetail');
      body.who = body.detail;
      body.pot = val('ePot');
    }
    const yes = ['income', 'staff_repay', 'partner_in'].includes(kind) ? t('guard.save_anyway') : t('guard.pay_anyway');
    const out = await act(() => sendGuarded(kind, body, yes), { skip: ['#eAmt', '#ePeriod'] });
    if (out) done(t('common.added'), out);
  },

  edit(el) {
    S.draft.editing = Number(el.dataset.id);
    render();
    const row = document.querySelector(`[data-edit="${S.draft.editing}"]`);
    const first = row && row.querySelector('[data-e="amount"]');
    if (first) first.focus();
  },

  cancelEdit() {
    S.draft.editing = null;
    render();
  },

  async saveEdit(el) {
    const row = el.closest('[data-edit]');
    const id = Number(row.dataset.edit);
    const f = {};
    row.querySelectorAll('[data-e]').forEach(x => { f[x.dataset.e] = plain(x); });
    const body = { id, on: f.on, amount: String(f.amount || '').replace(/,/g, '') };
    for (const k of ['detail', 'pot', 'pot_to', 'what', 'terms']) {
      if (k in f) body[k] = f[k];
    }
    // the month only travels when it was changed on purpose; otherwise it
    // follows the date, or stays where it was deliberately put
    const per = row.querySelector('[data-e="period"]');
    if (per && per.value !== per.dataset.was) body.period = per.value;
    S.draft.editing = null;
    const out = await act(() => sendGuarded('edit_entry', body, t('guard.save_anyway')),
                          { onError: () => { S.draft.editing = id; } });
    if (out) done(t('entries.corrected'), out);
    else if (S.draft.editing === null) S.draft.editing = id;     // said no: keep the row open
  },

  async void(el) {
    const id = Number(el.dataset.id);
    if (S.draft.editing === id) S.draft.editing = null;
    const out = await act(() => sendGuarded('void', { id }, t('entries.delete_anyway')));
    if (out) say(t('entries.deleted'), false, { label: t('recent.put_back'), run: () => H.putBack({ dataset: { id } }) });
  },

  async putBack(el) {
    const out = await act(() => sendGuarded('put_back', { id: Number(el.dataset.id) },
                                            t('entries.put_back_anyway')));
    if (out) say(t('entries.put_back_done'));
  },

  async search() {
    const q = val('q');
    if (!q) return H.clearSearch();
    try {
      S.search = { q, rows: await get(`/api/entries?q=${encodeURIComponent(q)}&limit=300`) };
      render({ fresh: true });
    } catch (err) { say(err.message, true); }
  },

  clearSearch() {
    S.search = null;
    render({ fresh: true });
  },

  async writeOff(el) {
    const id = Number(el.dataset.id);
    const c = S.data.counts.find(x => x.id === id);
    if (!c) return;
    const short = c.diff < 0;
    const month = monthWords(c.on.slice(0, 7));
    const ok = await ask(short ? t('write_off.short', money(Math.abs(c.diff))) : t('write_off.over', money(Math.abs(c.diff))),
      `${short ? t('write_off.less', c.on, ...month) : t('write_off.more', c.on, ...month)}\n\n${t('write_off.sure')}`,
      t('write_off.yes'));
    if (!ok) return;
    const out = await act(() => send('write_off', { id }));
    if (out) say(t('write_off.done'));
  },

  async deleteCashCount(el) {
    const c = S.data.counts.find(x => x.id === Number(el.dataset.id));
    if (!c) return;
    const ok = await ask(t('count.delete_ask', c.on),
      t('cash_count.delete_body'),
      t('common.delete_it'));
    if (!ok) return;
    const out = await act(() => send('delete_cash_count', { id: c.id }));
    if (out) say(t('cash_count.deleted'));
  },

  /* ------------------------------------------------------------------ stock */

  async openCount() {
    const on = val('newCount');
    if (!on) return say(t('count.pick_date'), true);
    const was = S.count;
    S.count = on;
    const out = await act(() => send('open_count', { on }), { onError: () => { S.count = was; } });
    if (out) say(t('count.started', on));
  },

  async deleteCount() {
    const on = S.data.stock.count_date;
    const ok = await ask(t('count.delete_ask', on),
      t('count.delete_body'), t('common.delete_it'));
    if (!ok) return;
    const was = S.count;
    S.count = null;
    const out = await act(() => send('delete_count', { on }), { onError: () => { S.count = was; } });
    if (out) say(t('count.deleted', on));
  },

  async receipt() {
    const amount = num('rAmt');
    if (!amount) return say(t('receipt_form.type_total'), true);
    const out = await act(() => sendGuarded('receipt', {
      amount, on: val('rDate'), who: val('rSup'), number: val('rNo'),
      what: val('rWhat') || en('receipt.several'), terms: val('rTerms'), pot: val('rPot'),
    }), { skip: ['#rAmt', '#rNo', '#rWhat'] });
    if (!out) return;
    S.draft.rlines = out.receipt || null;            // what came in, while the receipt is in hand
    render();
    document.getElementById('rlItem')?.focus();
    done(t('receipt_form.added'), out);
  },

  receiptLines(el) {
    const id = Number(el.dataset.id);
    S.draft.rlines = S.draft.rlines === id ? null : id;
    render();
    if (S.draft.rlines) document.getElementById('rlItem')?.focus();
  },

  /* An item for the open receipt, by name or by barcode: a scanner types the
     code and presses Enter, which lands here. */
  addRLine() {
    const box = document.getElementById('rlItem');
    const v = box ? westernDigits(box.value.trim()) : '';
    if (!v || !S.draft.rlines) return;
    const items = S.data.setup.items.filter(i => i.letter !== 'A');
    const it = items.find(i => (i.barcodes || []).includes(v))
            || items.find(i => i.name.toLowerCase() === v.toLowerCase());
    if (!it) {
      return say(t('rline.not_found', v), true);
    }
    box.value = '';
    receiptItem(it);
  },

  /* ---------------------------------------------------- filling a bucket */

  fillMix(el) {
    const id = Number(el.value) || null;
    const mix = S.data.stock.mixes.find(m => m.id === id);
    S.draft.fill = mix ? usualOf(mix) : null;
    render({ skip: fillKeys() });
  },

  fillUsual() {
    const mix = S.data.stock.mixes.find(m => m.id === (S.draft.fill || {}).mix);
    if (!mix) return;
    S.draft.fill = { ...usualOf(mix), on: S.draft.fill.on };
    fillValues();
    render({ skip: fillKeys() });
  },

  fillAdd() {
    const box = document.getElementById('fillItem');
    const v = box ? westernDigits(box.value.trim()) : '';
    if (!v) return;
    const sealed = S.data.setup.items.filter(i => i.letter === 'B');
    const it = sealed.find(i => (i.barcodes || []).includes(v))
            || sealed.find(i => i.name.toLowerCase() === v.toLowerCase());
    if (!it) return say(t('fill.not_found', v), true);
    box.value = '';
    fillItem(it, 0);
  },

  fillDrop(el) {
    const id = Number(el.dataset.id);
    const f = S.draft.fill;
    f.order = f.order.filter(i => i !== id);
    delete f.packs[id];
    render({ skip: fillKeys() });
  },

  fillCancel() {
    S.draft.fill = null;
    render();
  },

  async fillBucket() {
    const f = S.draft.fill;
    if (!f) return;
    fillValues();
    const lines = f.order.map(id => ({ item: id, packs: f.packs[id] })).filter(l => Number(l.packs) > 0);
    if (!lines.length) return say(t('fill.say_packs_first'), true);
    const mix = S.data.stock.mixes.find(m => m.id === f.mix);
    const out = await act(() => send('bucket_fill', {
      mix: f.mix, on: val('fillOn'), lines, gross_grams: val('fillGross'),
      tare_id: val('fillTare'), usual: document.getElementById('fillKeep').checked,
    }), { skip: ['#fillGross', '#fillOn', '#fillTare'] });
    if (!out) return;
    S.draft.fill = null;
    render();
    say(t('fill.filled', mix.name, out.grams.toLocaleString('en-US'), money(Math.round(out.value * 1000 / out.grams)))
      + (out.price_after !== out.price_before ? t('fill.price_now', money(out.price_after)) : ''));
  },

  async deleteFill(el) {
    const ok = await ask(t('fill.delete_ask'),
      t('fill.delete_body'),
      t('common.delete_it'));
    if (!ok) return;
    const out = await act(() => send('bucket_fill_delete', { id: Number(el.dataset.id) }));
    if (out) say(t('fill.deleted'));
  },

  dropRLine(el) {
    const rid = S.draft.rlines;
    const p = (S.draft.rpending || {})[rid];
    if (p) S.draft.rpending[rid] = p.filter(i => i !== Number(el.dataset.id));
    render();
  },

  /* ------------------------------------------------------------------ month */

  async settle(el) {
    const row = el.closest('[data-line]');
    const line = S.data.settle.find(l => `${l.action}|${l.who}` === row.dataset.line);
    if (!line) return;
    const amount = Number(plain(row.querySelector('[data-s="amount"]'))) || 0;
    if (!amount) return say(t('common.type_amount'), true);
    // whatever is paid from here belongs to the month on screen, whatever today's date is;
    // after six, while the night is still being closed up, it is paid that night
    if (nightOver()) stayOnTheNight();
    const body = { amount, who: line.who, pot: row.querySelector('[data-s="pot"]').value,
                   period: S.month, ...(S.stayed ? { on: S.stayed } : {}) };
    const out = await act(() => sendGuarded(line.action, body),
                          { skip: [`settle:${row.dataset.line}:amount`] });
    if (out) {
      done(t('settle_up.paid', line.who, money(amount), ...monthWords(S.month)), out);
    }
  },

  async saveElectricity() {
    const out = await act(() => send('set_electricity', {
      month: S.month, private_price: val('elPP'), elevator_price: val('elPE'),
      last_reading: val('elLast'), now_reading: val('elNow'),
    }), { skip: ['#elPP', '#elPE', '#elLast', '#elNow'] });
    if (out) say(t('elec.charged_say', ...monthWords(S.month), money(out.bill.total)));
  },

  async statement(el) {
    const id = Number(el.dataset.id);
    if (S.statement && S.statement.id === id) return H.closeStatement();
    try {
      S.statement = await get(`/api/supplier?id=${id}&month=${S.month}`);
      render();
    } catch (err) { say(err.message, true); }
  },

  closeStatement() {
    S.statement = null;
    render();
  },

  async closeAsk() {
    let check;
    try { check = await closeCheck(S.month); } catch (err) { return say(err.message, true); }
    if (!check.can_close) return say(check.stops.join(' '), true);
    const warn = check.warnings.length
      ? `\n\n${t('close_ask.worth_a_look')}\n• ${check.warnings.join('\n• ')}` : '';
    const ok = await ask(t('close_ask.title', ...monthWords(S.month)),
      t('close_ask.body', money(check.result.net), check.count_date) + warn, t('close_card.close'));
    if (!ok) return;
    const out = await act(() => send('close_month', { month: S.month }));
    if (out) say(t('close_ask.closed', ...monthWords(S.month)));
  },

  async reopen() {
    const ok = await ask(t('reopen.title', ...monthWords(S.month)), t('reopen.body'), t('close_card.reopen'));
    if (!ok) return;
    const out = await act(() => send('reopen_month', { month: S.month }));
    if (out) say(t('reopen.done', ...monthWords(S.month)));
  },

  /* --------------------------------------------------------------- sambapos */

  async posLive(el) { await keepPos(el, 'pos_live'); },
  async posAuto(el) {
    const label = el.textContent;
    el.disabled = true;
    el.textContent = t('pos_auto.looking');
    try {
      const out = await act(() => send('pos_auto'));
      if (!out) return;
      const nights = [...new Set((out.kept || []).map(l => l.night))];
      const bad = out.failed || [];
      if (bad.length) {
        say(bad.length === 1 ? t('pos_auto.failed_one', said(bad[0].note))
          : t('pos_auto.failed_many', bad.length, said(bad[0].note)), true);
      } else if (nights.length) {
        say(nights.length === 1 ? t('pos_auto.night', nights[0]) : t('pos_auto.nights', nights.length));
      } else {
        say(out.read ? t('pos_auto.nothing_new') : t('pos_auto.no_new'));
      }
    } finally {
      el.disabled = false;
      el.textContent = label;
    }
  },
  async posFolder(el) { await keepPos(el, 'pos_folder'); },

  async moveRest(el) {
    const to = document.getElementById('restTo').value;
    if (!to) return say(t('closing.pick_rest'), true);
    const out = await act(() => sendGuarded('move_rest', {
      amount: Number(el.dataset.amount), to, on: S.on }));
    if (out) done(t('closing.moved', money(Number(el.dataset.amount)), to), out);
  },

  async posAddNight(el) {
    el.disabled = true;
    try {
      const out = await act(() => sendGuarded('pos_add_night', { on: S.on }, t('drawer.add_anyway')));
      if (out) say(out.added === 1 ? t('pos_add.one', 1, out.night) : t('pos_add.many', out.added, out.night));
    } finally {
      el.disabled = false;
    }
  },

  async posLeft(el) {
    const name = el.dataset.name || t('pos_left.they');
    const body = { pos_id: Number(el.dataset.pos) };
    if (el.dataset.staff) {
      body.left_on = await askDate(withName('ask.when_leave', name), t('pos_left.staff_body'),
        S.data.tonight, S.data.today, t('pos_accounts.mark_left'));
      if (!body.left_on) return;
    } else if (!await ask(t('pos_left.title', name), t('pos_left.body'), t('pos_accounts.mark_left'))) {
      return;
    }
    const out = await act(() => send('pos_left', body));
    if (out) say(out.note || t('pos_left.marked', out.name), Boolean(out.note));
  },

  async posTold(el) {
    const out = await act(() => send('pos_told', { pos_id: Number(el.dataset.pos) }));
    if (out) say(t('pos_account.noted'));
  },

  async posTest(el) {
    el.disabled = true;
    try {
      const out = await send('pos_test');
      const p = out.probe || {};
      say(p.open_periods === 1 ? t('pos_test.one', p.db, p.who, p.tickets, 1)
        : t('pos_test.many', p.db, p.who, p.tickets, p.open_periods));
    } catch (err) { say(err.message, true); }
    finally { el.disabled = false; }
  },

  /* ------------------------------------------------------------------ setup */

  /* Someone on the staff has left. The day they left decides their last
     month: it is charged for the days they worked of it. */
  async hasLeft(el) {
    const name = el.dataset.name;
    const on = await askDate(withName('ask.when_leave', name), t('staff_day.leave_body'),
      el.dataset.on || S.data.tonight, S.data.today, el.dataset.on ? t('staff_day.save') : t('staff_day.has_left'));
    if (!on || on === el.dataset.on) return;
    const out = await act(() => send('account_active',
      { id: Number(el.dataset.id), active: 0, left_on: on }));
    if (!out) return;
    if (out.note) say(out.note, true);
    else say(el.dataset.on ? t('common.saved') : t('staff_day.left', name));
  },

  /* Someone who left is back. The days they were away are not paid for;
     the day after their last day means they were never away. */
  async cameBack(el) {
    const next = new Date(`${el.dataset.on}T12:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    const never = next.toISOString().slice(0, 10);
    const on = await askDate(withName('ask.when_back', el.dataset.name), t('staff_day.back_body', never),
      S.data.tonight, S.data.today, t('staff_day.are_back'));
    if (!on) return;
    const out = await act(() => send('account_active',
      { id: Number(el.dataset.id), active: 1, back_on: on }));
    if (out) say(out.note || t('common.saved'), Boolean(out.note));
  },

  /* The day someone on the staff started, put right. */
  async started(el) {
    const on = await askDate(withName('ask.when_start', el.dataset.name), t('staff_day.start_body'),
      el.dataset.on, S.data.today, t('staff_day.save'));
    if (!on || on === el.dataset.on) return;
    const out = await act(() => send('staff_started', { id: Number(el.dataset.id), on }));
    if (out) say(out.note || t('common.saved'), Boolean(out.note));
  },

  async backupNow() {
    const out = await act(() => send('backup_now'));
    if (!out) return;
    const b = out.backup;
    if (!b.second) say(t('backup_now.no_second'));
    else if (b.second_ok) say(t('backup_now.both', b.second));
    else say(t('backup_now.not_second', b.second, b.second_error), true);
  },

  async checkUpdate() {
    try { S.draft.update = await get('/api/update'); }
    catch (err) { S.draft.update = { error: err.message }; }
    render();
  },

  async installUpdate() {
    const u = S.draft.update;
    const ok = await ask(t('install.title', u.latest), t('install.body'), t('install.yes'));
    if (!ok) return;
    try { await post('/api/update'); } catch (err) { return say(err.message, true); }
    say(t('install.installing'));
    const from = S.data.version;
    for (let i = 0; i < 90; i += 1) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const h = await get('/api/health');
        if (h.version && h.version !== from) { location.reload(); return; }
      } catch { /* still restarting */ }
    }
    say(t('install.not_back'), true);
  },

  /* -------------------------------------------------------------- language */

  async langPick(el) {
    if (el.dataset.lang === S.data.lang.language) return;
    // everything is drawn again, the new way round
    if (await act(() => send('language_set', { language: el.dataset.lang }))) location.reload();
  },

  async health() {
    try {
      const r = await get('/api/health');
      say(r.ok ? t('health.sound', money(r.entries))
               : t('health.wrong'),
          !r.ok);
    } catch (err) { say(err.message, true); }
  },

  /* ------------------------------------------------------------------ print */

  /* Every supplier's month: what was owed coming in, what arrived, what was
     paid, and what is owed at the end. */
  printSuppliers() {
    const sup = S.data.suppliers;
    const end = sup.reduce((a, s) => a + s.closing, 0);
    printSlip(slipHead(t('suppliers.title'), monthName(S.data.month))
      + (sup.length ? `<table>${sup.map(s => slipRow(esc(s.name), money(s.closing), true)
          + slipRow(`&nbsp;&nbsp;${th('suppliers.coming_in')}`, money(s.brought_forward))
          + (s.received ? slipRow(`&nbsp;&nbsp;${th('suppliers.arrived')}`, money(s.received)) : '')
          + (s.paid ? slipRow(`&nbsp;&nbsp;${th('common.paid')}`, money(-s.paid)) : '')).join('')}</table>`
        : `<div>${th('suppliers.none')}</div>`)
      + `<div class="rule"></div>
      <table>${slipRow(th('suppliers.end_of_month'), money(end), true)}
        ${S.data.owed !== end ? slipRow(th('slip.owed_today'), money(S.data.owed)) : ''}</table>`);
  },

  printStatement() {
    const st = S.statement;
    if (!st) return;
    printSlip(slipHead(st.name, monthName(st.month))
      + `<table>${slipRow(th('suppliers.coming_in'), money(st.opening))}</table>
      ${st.lines.length ? `<div class="rule"></div><table>${st.lines.map(l =>
        slipRow(pair(esc(dayMonth(l.on)), esc(l.what)), signed(l.amount))).join('')}</table>` : ''}
      <div class="rule"></div>
      <table>${st.received ? slipRow(th('slip.arrived'), money(st.received)) : ''}
        ${st.paid ? slipRow(th('slip.paid'), money(-st.paid)) : ''}
        ${slipRow(th('suppliers.end_of_month'), money(st.closing), true)}</table>
      ${st.on_shelves ? `<div class="rule"></div>
        <table>${slipRow(th('slip.on_shelves'), money(st.on_shelves))}</table>` : ''}`);
  },

  /* Where the cash went: each kind, and each name under it. */
  printFlow() {
    const f = S.data.flow;
    const part = (label, groups) => (groups.length ? `<div class="sub">${esc(label)}</div>
      <table>${groups.map(g => slipRow(esc(g.label), money(g.total), true)
        + g.rows.map(([n, v]) => slipRow(`&nbsp;&nbsp;${esc(n)}`, money(v))).join('')).join('')}</table>` : '');
    printSlip(slipHead(t('flow.title'), monthName(S.data.month))
      + part(t('common.out'), f.out) + (f.in.length ? '<div class="rule"></div>' + part(t('common.in'), f.in) : '')
      + `<div class="rule"></div>
      <table>${slipRow(th('common.out'), money(f.out_total), true)}${slipRow(th('common.in'), money(f.in_total), true)}</table>`
      + (f.earlier_total ? `<div class="rule"></div><div class="sub">${th('slip.of_out')}</div>
        <table>${earlierRows(f)}</table>
        <table>${slipRow(th('common.total'), money(f.earlier_total), true)}</table>` : ''));
  },

  /* What went out this month for earlier months, on its own. */
  printEarlier() {
    const f = S.data.flow;
    printSlip(slipHead(t('earlier.title'), monthName(S.data.month))
      + `<table>${earlierRows(f)}</table>
      <div class="rule"></div>
      <table>${slipRow(th('common.total'), money(f.earlier_total), true)}</table>`);
  },

  /* One kind, such as every staff advance: each name, and each of its
     entries with its date and time. */
  printKind(el) {
    const f = S.data.flow;
    const out = el.dataset.side !== 'in';
    const g = (out ? f.out : f.in).find(x => x.kind === el.dataset.k);
    if (!g) return;
    const lines = f.lines.filter(l => l.kind === g.kind && l.out === out);
    printSlip(slipHead(g.label, monthName(S.data.month))
      + `<table>${g.rows.map(([n, v]) => slipRow(esc(n), money(v), true)
          + lines.filter(l => l.name === n).map(l =>
            slipRow(`&nbsp;&nbsp;${pair(esc(when(l)), forMonth(l))}`, money(l.amount))).join('')).join('')}</table>
      <div class="rule"></div>
      <table>${slipRow(th('common.total'), money(g.total), true)}</table>`);
  },

  /* Everything under one name this month, whatever it was for. */
  printName(el) {
    const name = el.dataset.n;
    const lines = S.data.flow.lines.filter(l => l.name === name);
    const sum = side => lines.filter(l => l.out === side).reduce((a, l) => a + l.amount, 0);
    printSlip(slipHead(name, monthName(S.data.month))
      + `<table>${lines.map(l => slipRow(pair(esc(when(l)), esc(l.label), forMonth(l)),
          l.out ? money(l.amount) : `+${money(l.amount)}`)).join('')}</table>
      <div class="rule"></div>
      <table>${sum(true) ? slipRow(th('common.out'), money(sum(true)), true) : ''}
        ${sum(false) ? slipRow(th('common.in'), money(sum(false)), true) : ''}
        ${slipRow(lines.length === 1 ? th('flow.entries_one', 1) : th('flow.entries_many', lines.length), '')}</table>`);
  },

  printChanges() {
    const rows = S.data.recent.slice(0, 40);
    printSlip(slipHead(t('recent.title'))
      + `<table>${rows.map(r => `<tr><td>${pair(esc(C.localTime(r.at)), esc(r.summary))}</td></tr>`).join('')}</table>`);
  },

  /* A name in Where the cash went: its entries open under it, or close. */
  flowName(el) {
    const { k, side, n } = el.dataset;
    const f = S.draft.flow || {};
    const same = f.kind === k && f.side === side && f.name === n;
    S.draft.flow = same ? { kind: k, side } : { kind: k, side, name: n };
    render();
  },

  printMonth() {
    const r = S.data.result;
    const line = (k, v) => `<tr><td>${esc(k)}</td>
      <td style="text-align:end">${money(v)}</td></tr>`;
    printSlip(slipHead(S.data.so_far ? t('slip.in_progress', ...monthWords(S.data.month)) : monthName(S.data.month))
      + `<table>
        ${line(t('result.sales'), r.rev)}
        ${line(t('result.cogs'), -((r.cogs || {}).value || 0))}
        ${line(t('slip.gross'), r.gross)}
        ${line(t('slip.expenses'), -(r.daily || 0))}
        ${r.elec ? line(t('result.electricity'), -r.elec) : ''}
        ${line(t('slip.rent'), -(r.fixed || 0))}
        ${line(t('result.salaries'), -(r.salaries || 0))}
        ${r.differences ? line(t('result.written_off'), -r.differences) : ''}
      </table>
      <div class="rule"></div>
      <table>${line(t('result.net_profit'), r.net)}
        ${S.data.so_far ? line(t('slip.so_far', S.data.so_far.days), S.data.so_far.net) : ''}</table>
      <div class="rule"></div>
      <div>${th('slip.cash_on_hand', money(S.data.cash))}</div>
      <div>${th('slip.owed_suppliers', money(S.data.owed))}</div>`);
  },

  /* One A4 page for the partner: the month, each partner's part of it, and
     where the money is. A month in progress is shown so far, rent and
     salaries counted for the days gone, as the Month screen does. */
  printSummary() {
    const d = S.data;
    const sf = d.so_far;
    const r = d.result || {};
    const now = sf ? {
      rev: sf.rev, cogs: sf.cogs, daily: sf.daily, elec: sf.elec, fixed: sf.fixed,
      salaries: sf.salaries, differences: sf.differences, net: sf.net,
    } : {
      rev: r.rev, cogs: (r.cogs || {}).value || 0, daily: r.daily, elec: r.elec, fixed: r.fixed,
      salaries: r.salaries, differences: r.differences, net: r.net,
    };
    const p = d.prev && d.prev.rev ? {
      rev: d.prev.rev, cogs: (d.prev.cogs || {}).value || 0, daily: d.prev.daily,
      elec: d.prev.elec, fixed: d.prev.fixed, salaries: d.prev.salaries,
      differences: d.prev.differences, net: d.prev.net,
    } : null;
    const gross = x => (x.rev || 0) - (x.cogs || 0);
    const pct = (a, b) => (b ? ` <span style="color:#555">(${Math.round(a / b * 100)}%)</span>` : '');
    const row = (label, k, sign = -1, cls = '') => {
      const v = x => (k === 'gross' ? gross(x) : (x[k] || 0) * (k === 'rev' || k === 'net' ? 1 : sign));
      if (!v(now) && !(p && v(p)) && !['rev', 'gross', 'net'].includes(k)) return '';
      return `<tr class="${cls}"><td>${esc(label)}</td>
        <td class="n">${money(v(now))}${k === 'gross' || k === 'net' ? pct(v(now), now.rev) : ''}</td>
        ${p ? `<td class="n">${money(v(p))}</td>` : ''}</tr>`;
    };
    const out = (d.flow.out || []).find(g => g.kind === 'daily_expense');
    const spent = out ? out.rows.slice().sort((a, b) => b[1] - a[1]).slice(0, 8) : [];
    const partners = (d.partners || []).filter(x => x.share || x.taken || x.put_in);
    const stock = d.stock && d.stock.cogs ? d.stock.cogs : null;
    const title = monthName(d.month);
    printPage(`<h1>${esc(d.business.name || t('slip.default_name'))} — ${esc(title)}</h1>
      <div class="meta">${sf ? th('summary.in_progress', sf.days, sf.days_in_month || 30) : d.period.status === 'closed' ? th('summary.closed')
        : th('summary.not_closed')} ${th('summary.printed', esc(d.today))}</div>
      <h2>${th('summary.the_month')}</h2>
      <table><tr><th></th><th class="n">${sf ? th('summary.month_so_far', ...monthWords(d.month)) : esc(title)}</th>
        ${p ? `<th class="n">${esc(monthName(d.prev.month))}</th>` : ''}</tr>
        ${row(t('result.sales'), 'rev')}
        ${row(t('summary.stock_used'), 'cogs')}
        ${row(t('result.gross_profit'), 'gross', 1, 'total')}
        ${row(t('summary.daily'), 'daily')}
        ${row(t('result.electricity'), 'elec')}
        ${row(t('summary.rent'), 'fixed')}
        ${row(t('result.salaries'), 'salaries')}
        ${row(t('result.written_off'), 'differences')}
        ${row(t('result.net_profit'), 'net', 1, 'total')}
      </table>
      ${spent.length ? `<h2>${th('summary.daily_went')}</h2>
        <table>${spent.map(([n, v]) => `<tr><td>${esc(n)}</td><td class="n">${money(v)}</td></tr>`).join('')}
        </table>` : ''}
      ${partners.length ? `<h2>${th('partners.title')}</h2>
        <table><tr><th>${th('partners.partner')}</th><th class="n">${th('partners.share')}</th><th class="n">${th('summary.their_part')}</th>
          <th class="n">${th('summary.taken_out')}</th><th class="n">${th('partners.put_in')}</th><th class="n">${th('summary.this_month')}</th></tr>
        ${partners.map(x => `<tr><td>${esc(x.name)}</td><td class="n">${Math.round(x.share * 100)}%</td>
          <td class="n">${money(x.profit)}</td><td class="n">${money(x.taken)}</td>
          <td class="n">${money(x.put_in)}</td><td class="n">${money(x.this_month)}</td></tr>`).join('')}
        </table>` : ''}
      <h2>${th('pots.title')}</h2>
      <table>
        <tr><td>${th('summary.cash_every_pot')}</td><td class="n">${money(d.cash)}</td></tr>
        ${(d.pots || []).filter(x => x.balance).map(x => `<tr><td style="padding-inline-start:5mm">${esc(x.name)}</td>
          <td class="n">${money(x.balance)}</td></tr>`).join('')}
        <tr><td>${th('summary.owed_suppliers')}</td><td class="n">${money(d.owed)}</td></tr>
        ${stock && stock.date ? `<tr><td>${th('summary.stock_counted', esc(stock.date))}</td>
          <td class="n">${money(stock.closing)}</td></tr>` : ''}
      </table>
      <div class="foot">${th('summary.foot', esc(d.version))}</div>`);
  },
};

/* A change is sent once, however fast a button is clicked twice or Enter is
   pressed twice: while one is on its way, the same one again is let go. A
   double click on Add would otherwise write the expense twice. */
const running = new Set();
async function once(key, fn) {
  if (running.has(key)) return undefined;
  running.add(key);
  try {
    return await fn();
  } finally {
    running.delete(key);
  }
}

/* ------------------------------------------------------------------ events */

const ON_CHANGE = new Set(['setDay', 'setMonth', 'setCount', 'pickKind', 'fillMix']);

// choosing a day, a month or a tab is not a change: the latest choice wins
for (const [name, fn] of Object.entries(H)) {
  if (!ON_CHANGE.has(name) && name !== 'go') H[name] = (...a) => once(name, () => fn(...a));
}

document.addEventListener('click', async e => {
  /* Setup: one button does one thing, described entirely by its attributes */
  const doer = e.target.closest('[data-do]');
  if (doer) {
    e.preventDefault();
    await once(`do:${doer.dataset.do}:${doer.dataset.args || ''}`, async () => {
      if (doer.dataset.confirm
          && !await ask(doer.dataset.confirm, doer.dataset.confirmBody || '', doer.dataset.yes || t('common.yes'))) {
        return;
      }
      const out = await act(() => send(doer.dataset.do, JSON.parse(doer.dataset.args || '{}')));
      if (out) say(typeof out.note === 'string' ? out.note : t('common.saved'), typeof out.note === 'string');
    });
    return;
  }
  const adder = e.target.closest('[data-add]');
  if (adder) {
    e.preventDefault();
    await once(`add:${adder.dataset.add}:${adder.dataset.args || ''}`, async () => {
      const body = JSON.parse(adder.dataset.args || '{}');
      const keys = [];
      adder.closest('.addrow').querySelectorAll('[data-f]').forEach(el => {
        body[el.dataset.f] = plain(el);
        if (el.dataset.keep === undefined) keys.push(fieldKey(el));     // kept for the next one
      });
      // someone new on the staff: the day they started decides their first month
      const who = String(body.name || '').trim();
      if (adder.dataset.add === 'account_add' && body.kind === 'staff' && who) {
        body.started_on = await askDate(withName('ask.when_start', who), t('staff_day.start_body'),
          S.data.tonight, S.data.today, t('common.add'));
        if (!body.started_on) return;
      }
      const out = await act(() => send(adder.dataset.add, body), { skip: keys });
      if (out) say(out.note || t('common.added'), Boolean(out.note));
    });
    return;
  }
  const el = e.target.closest('[data-act], [data-go]');
  if (!el || (el.tagName === 'SELECT' || el.tagName === 'INPUT')) return;
  const fn = H[el.dataset.act || 'go'];
  if (fn) {
    e.preventDefault();
    fn(el);
  }
});

document.addEventListener('change', async e => {
  if (e.target === drawing) return;
  const box = e.target.closest('[data-save]');
  if (box) {
    const body = JSON.parse(box.dataset.args || '{}');
    body[box.dataset.field] = plain(box);
    const key = fieldKey(box);
    const out = await act(() => send(box.dataset.save, body),
                          { skip: [key], onError: () => render({ skip: [key] }) });
    if (!out) return;
    const b = out.backup;
    if (!b) say(t('common.saved'));
    else if (b.second_ok) say(t('save.copied', b.second));
    else say(t('save.not_copied', b.second_error), true);
    return;
  }
  if (e.target.id === 'nWho') {
    S.draft.nWho = e.target.value;
    document.querySelectorAll('[data-act="nWho"]')
      .forEach(b => b.setAttribute('aria-pressed', String(b.dataset.who === e.target.value)));
    return;
  }
  const el = e.target.closest('[data-act]');
  if (el && ON_CHANGE.has(el.dataset.act)) H[el.dataset.act](el);
});

document.addEventListener('input', e => {
  if (e.target.dataset && e.target.dataset.fillpack !== undefined) {
    S.draft.fill.packs[e.target.dataset.fillpack] = e.target.value.trim();
    fillFigures();
  }
});

/* A stock count saves a line when you leave it. Typing a figure and walking
   away should not lose it, and a Save button at the bottom of a sheet of
   fifty items is a Save button nobody reaches. */
document.addEventListener('focusout', e => {
  if (e.target === drawing) return;
  const row = e.target.closest && e.target.closest('[data-item]');
  if (!row) return;
  if (e.relatedTarget && row.contains(e.relatedTarget)) return;     // still on this line
  const boxes = [...row.querySelectorAll('[data-k]')];
  if (!boxes.some(dirty) || boxes.some(b => b.disabled)) return;
  saveLine(row);
});

async function saveLine(row) {
  if (row.dataset.receipt) return saveReceiptLine(row);
  const body = { on: S.data.stock.count_date, item: Number(row.dataset.item) };
  const keys = [];
  row.querySelectorAll('[data-k]').forEach(el => {
    body[el.dataset.k] = plain(el);
    keys.push(fieldKey(el));
  });
  const before = S.data.stock.count.closing;
  const out = await act(() => send('count_line', body), { skip: keys });
  if (out && out.closing !== before) say(t('count.value_now', money(out.closing)));
}

/** A scanner types through the keyboard layout in use: with a Kurdish or
    Arabic layout the digits of a code can arrive as ٠١٢… They are the same
    code. */
const westernDigits = s => s.replace(/[\u0660-\u0669]/g, d => d.charCodeAt(0) - 0x0660)
                            .replace(/[\u06F0-\u06F9]/g, d => d.charCodeAt(0) - 0x06F0);

/* A number box throws away the digits a Kurdish keyboard types, so on that
   keyboard a count could not be typed at all: each is put in as its Western
   digit instead, and the Arabic decimal point as a point. */
document.addEventListener('beforeinput', e => {
  const el = e.target;
  if (!(el instanceof HTMLInputElement) || el.type !== 'number' || !e.data) return;
  const put = westernDigits(e.data).replace(/\u066B/g, '.');
  if (put === e.data) return;
  e.preventDefault();
  document.execCommand('insertText', false, put);
});

/** A fill starting from a mix's usual batch. */
function usualOf(mix) {
  const packs = {};
  mix.usual.forEach(u => { packs[u.item] = String(u.packs); });
  return { mix: mix.id, order: mix.usual.map(u => u.item), packs, on: S.data.tonight };
}

/** The packs typed on the fill so far, into the draft, so a redraw keeps them. */
function fillValues() {
  const f = S.draft.fill;
  if (!f) return;
  document.querySelectorAll('[data-fillpack]').forEach(el => { f.packs[el.dataset.fillpack] = el.value.trim(); });
}

const fillKeys = () => [...document.querySelectorAll('[data-fillpack]')].map(el => '#' + el.id);

/** Grams and cost of each line and of the whole fill, as the packs stand. */
function fillFigures() {
  const f = S.draft.fill;
  if (!f) return;
  const items = Object.fromEntries(S.data.setup.items.map(i => [i.id, i]));
  let grams = 0;
  let value = 0;
  document.querySelectorAll('[data-fillpack]').forEach(el => {
    const it = items[el.dataset.fillpack];
    const g = Math.round((Number(el.value) || 0) * it.pack_grams);
    const v = g * it.cost / 1000;
    grams += g;
    value += v;
    document.querySelector(`[data-fillgrams="${it.id}"]`).textContent = g ? t('unit.g', g.toLocaleString('en-US')) : '';
    document.querySelector(`[data-fillvalue="${it.id}"]`).textContent = g ? money(Math.round(v)) : '';
  });
  const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  set('fillGrams', grams ? t('unit.g', grams.toLocaleString('en-US')) : '');
  set('fillValue', grams ? money(Math.round(value)) : '');
  set('fillPrice', grams ? t('fill.a_kilo', money(Math.round(value * 1000 / grams))) : '');
}

/** One more pack of a tobacco on the fill (a scan), or just its line (Add). */
function fillItem(it, more) {
  const f = S.draft.fill;
  fillValues();
  if (!f.order.includes(it.id)) f.order.push(it.id);
  if (more) f.packs[it.id] = String((Number(f.packs[it.id]) || 0) + more);
  S.draft.found = it.id;
  render({ skip: fillKeys().concat(['#fill-' + it.id, '#fillItem']) });
  const box = document.getElementById('fill-' + it.id);
  if (box) {
    box.closest('tr').scrollIntoView({ block: 'nearest' });
    if (!more) box.focus();
  }
  setTimeout(() => {
    if (S.draft.found === it.id) S.draft.found = null;
    document.querySelectorAll(`tr.found[data-fill="${it.id}"]`).forEach(r => r.classList.remove('found'));
  }, 1600);
}

/** Put an item on the open receipt, or go to its line if it is there. */
function receiptItem(it) {
  const rid = S.draft.rlines;
  const p = (S.draft.rpending = S.draft.rpending || {});
  p[rid] = p[rid] || [];
  if (!p[rid].includes(it.id)) p[rid].push(it.id);
  render({ skip: ['#rlItem'] });
  const row = document.querySelector(`tr[data-receipt="${rid}"][data-item="${it.id}"]`);
  if (row) row.querySelector('input[data-k]').focus();
}

/* A barcode scanner is a keyboard that types very fast and then presses
   Enter. Wherever the cursor is, a scan is caught here and taken back out of
   the box it landed in, so a code can never become a count or an amount.
   A box marked data-scan is meant for codes and takes it as typed. */
const SCAN = { el: null, before: '', chars: '', first: 0, last: 0 };

window.addEventListener('keydown', e => {
  const now = performance.now();
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (now - SCAN.last > 80) {                 // a new burst of typing
      const el = document.activeElement;
      SCAN.el = el;
      SCAN.before = el && 'value' in el ? el.value : '';
      SCAN.chars = '';
      SCAN.first = now;
    }
    SCAN.chars += e.key;
    SCAN.last = now;
    return;
  }
  if (e.key === 'Shift') return;
  const code = SCAN.chars;
  SCAN.chars = '';
  if (e.key !== 'Enter' || code.length < 6 || now - SCAN.last > 80
      || (SCAN.last - SCAN.first) / (code.length - 1) > 35) return;   // a person typing
  const el = document.activeElement;
  if (el && el.dataset && el.dataset.scan !== undefined) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  if (SCAN.el === el && el && 'value' in el) el.value = SCAN.before;
  scanned(code.trim());
}, true);

/** What a scan does depends on what is open: the receipt being listed takes
    the item, else the count sheet goes to its line, else it says what it is.
    A code nobody has seen is asked about once and remembered. */
async function scanned(raw) {
  const code = westernDigits(raw);
  if (!S.data || !/^[0-9A-Za-z._-]{3,64}$/.test(code)) return;
  const items = S.data.setup.items;
  let it = items.find(i => (i.barcodes || []).includes(code));
  if (!it) {
    it = await pickItem(t('scan.new', code), t('scan.which'),
                        items.filter(i => i.active));
    if (!it) return;
    const out = await act(() => send('item_update', { id: it.id, barcode_add: code }));
    if (!out) return;
    say(t('scan.now_is', code, it.name));
  }
  if (onPage('stock', 'fill') && S.draft.fill && S.draft.fill.mix) {
    if (it.letter !== 'B') return say(t('scan.only_sealed', it.name), true);
    return fillItem(it, 1);
  }
  if (onPage('stock', 'receipts') && S.draft.rlines && document.getElementById('rlItem')) {
    if (it.letter === 'A') return say(t('scan.is_mix', it.name), true);
    return receiptItem(it);
  }
  const sheet = onPage('stock', 'count') && S.data.stock.count.date;
  if (sheet) {
    let row = document.querySelector(`#main tr[data-item="${it.id}"]:not([data-receipt])`);
    if (!row) return say(t('scan.not_on_count', it.name), true);
    if (row.hidden) {
      (S.draft.find || {}).count = '';
      applyFind();
      row = document.querySelector(`#main tr[data-item="${it.id}"]:not([data-receipt])`);
    }
    row.scrollIntoView({ block: 'center' });
    S.draft.found = it.id;                      // lit, even if the screen is redrawn meanwhile
    row.classList.add('found');
    setTimeout(() => {
      if (S.draft.found === it.id) S.draft.found = null;
      document.querySelectorAll(`#main tr.found[data-item="${it.id}"]`).forEach(r => r.classList.remove('found'));
    }, 1600);
    const box = row.querySelector('input:not([disabled]), select:not([disabled])');
    if (box) box.focus({ preventScroll: true });
    return;
  }
  say(t('scan.is', code, it.name));
}

async function saveReceiptLine(row) {
  const rid = Number(row.dataset.receipt);
  const item = Number(row.dataset.item);
  const body = { receipt: rid, item };
  const keys = [];
  row.querySelectorAll('[data-k]').forEach(el => {
    body[el.dataset.k] = plain(el);
    keys.push(fieldKey(el));
  });
  const out = await act(() => send('receipt_line', body), { skip: keys });
  if (!out) return;
  const p = (S.draft.rpending || {})[rid];
  if (p) S.draft.rpending[rid] = p.filter(i => i !== item);   // saved, so no longer waiting
  say(out.removed ? t('rline.taken_off') : t('common.saved'));
}

document.addEventListener('keydown', e => {
  const el = e.target;
  if (!(el instanceof HTMLElement)) return;
  if (e.key === 'Escape' && el.closest('[data-edit]')) {
    e.preventDefault();
    H.cancelEdit();
    return;
  }
  if (e.key !== 'Enter' || e.isComposing || !el.matches('input, select')) return;

  const submit = { nSales: 'sales', nAmt: 'nAdd', eAmt: 'addEntry', rAmt: 'receipt', q: 'search',
                   rlItem: 'addRLine', fillItem: 'fillAdd' };
  if (submit[el.id]) {
    e.preventDefault();
    H[submit[el.id]](el);
    return;
  }
  if (el.dataset.pot !== undefined) {           // next pot, then save
    e.preventDefault();
    const boxes = [...document.querySelectorAll('#main [data-pot]')];
    const next = boxes[boxes.indexOf(el) + 1];
    if (next) next.focus(); else H.saveCount();
    return;
  }
  const edit = el.closest('[data-edit]');
  if (edit) {
    e.preventDefault();
    H.saveEdit(edit.querySelector('[data-act="saveEdit"]'));
    return;
  }
  if (el.closest('[data-item]')) {              // down a line, like a spreadsheet
    e.preventDefault();
    const target = lineBox(el, 1);
    if (target) goTo(target); else el.blur();
    return;
  }
  const line = el.closest('[data-line]');
  if (line) {
    e.preventDefault();
    H.settle(line.querySelector('[data-act="settle"]'));
    return;
  }
  const add = el.closest('.addrow');
  if (add) {
    e.preventDefault();
    add.querySelector('[data-add]').click();
    return;
  }
  if (el.dataset.save) {
    e.preventDefault();
    el.blur();                                  // saves through the change event
  }
});

document.addEventListener('wheel', e => {
  const el = document.activeElement;
  if (el && el.type === 'number' && e.target === el) el.blur();
}, { passive: true });

/* The box on the line below a sheet's line (step 1), or above it (-1): the same
   column if that line has it, else its first box, on into the next group; lines
   a find box hides are passed over. */
function lineBox(el, step) {
  const item = el.closest('[data-item]');
  const rows = [...item.closest('.card').querySelectorAll('tr[data-item]')]
    .filter(r => !r.hidden && (r.dataset.receipt || '') === (item.dataset.receipt || ''));
  const at = rows.indexOf(item);
  const open = 'input:not([disabled]):not([type="checkbox"])';
  for (const r of step > 0 ? rows.slice(at + 1) : rows.slice(0, at).reverse()) {
    const box = r.querySelector(`[data-k="${el.dataset.k}"]:not([disabled])`) || r.querySelector(open);
    if (box) return box;
  }
  return null;
}

function goTo(box) {
  box.focus();
  box.scrollIntoView({ block: 'nearest' });
  try { box.select(); } catch { /* not a text box */ }
}

/* In a number box ↑ and ↓ add or take away a step, where someone going up or
   down a count sheet meant the line above or below: a count of 12 became 11.9,
   and was saved as he left the box. They never change a number here: on a
   sheet's lines they go to the line above or below. */
document.addEventListener('keydown', e => {
  const el = e.target;
  if ((e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || e.altKey || e.ctrlKey || e.metaKey
      || !(el instanceof HTMLInputElement) || el.type !== 'number') return;
  e.preventDefault();
  if (!el.closest('[data-item]')) return;
  const target = lineBox(el, e.key === 'ArrowDown' ? 1 : -1);
  if (target) goTo(target);
}, true);

/* An address typed or picked from the browser's history opens its screen. */
window.addEventListener('hashchange', () => {
  const where = location.hash.slice(1);
  if (S.data && where !== `${S.tab}/${pageOf(S.tab)[0]}`) setTab(where);
});

/* -------------------------------------------------------------------- boot */

/** Ask until the app answers: just after an update it is still starting
    again, for a few seconds. What it answers, even a refusal, is the answer. */
async function patiently(question) {
  for (let tries = 1; ; tries += 1) {
    try {
      return await question();
    } catch (err) {
      if (!(err instanceof TypeError) || tries >= 60) throw err;    // TypeError: no answer at all
      await new Promise(r => setTimeout(r, 1000));
    }
  }
}

(async function start() {
  try {
    await patiently(loadWords);
  } catch (err) {
    // without its words the app has nothing to say anything in but the reason
    document.getElementById('main').textContent = String(err && err.message);
    return;
  }
  // the language this browser last had, until the books say
  try { setLanguage(localStorage.getItem('twilight.lang')); } catch { /* English */ }
  document.title = t('app.name');
  document.getElementById('brand').prepend(t('app.name'));
  document.getElementById('brandsub').textContent = t('app.loading');
  document.getElementById('main').innerHTML = `<p class="empty">${th('app.opening')}</p>`;
  const [tab, page] = location.hash.slice(1).split('/');
  if (PAGES[tab]) S.tab = tab;
  if (PAGES[tab] && page && PAGES[tab].some(p => p[0] === page)) S.page[tab] = page;
  watch();
  try {
    await apply(await patiently(() => load()), { fresh: true });
    const bad = S.data.checks.filter(c => !c.ok).length;
    if (bad) say(bad === 1 ? t('look.one', 1) : t('look.many', bad));
  } catch (err) {
    document.getElementById('main').innerHTML =
      `<div class="banner bad"><h2>${th('boot.could_not_open')}</h2>
        <p style="margin:0">${esc(err.message)}</p></div>`;
  }
})();

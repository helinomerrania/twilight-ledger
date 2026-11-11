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
import {
  S, ask, closeCheck, esc, get, load, money, monthName, pickItem, post, printSlip,
  say, send, signed,
} from './lib.js';

/* ------------------------------------------------------------- the screens */

const TABS = [
  ['tonight', 'Tonight'],
  ['stock', 'Stock'],
  ['month', 'Month'],
  ['books', 'Books'],
  ['setup', 'Setup'],
];

const section = (title, note) =>
  `<div class="sectionhead">${esc(title)}<span>${esc(note)}</span></div>`;

const VIEWS = {
  tonight: () => C.needsALook() + C.closingUp() + C.nightDrawer() + C.todayFigures()
               + C.todayEntries() + C.nightSold(),

  stock: () => C.stockFigures() + C.fillCard() + C.countPicker() + C.countSheet() + C.expectedCard()
             + C.receiptForm() + C.receiptList() + C.countHistory(),

  month: () => C.periodPicker() + C.monthFigures() + C.soFarCard() + C.resultCard()
             + C.settleCard() + C.electricityCard() + C.payrollCard() + C.partnersCard()
             + C.suppliersCard() + C.moneyFlow() + C.salesByDay() + C.cashDifferences()
             + C.monthSold() + C.allChecks()
             + C.closeCard() + C.everyMonth(),

  books: () => C.newEntryCard() + C.entryList() + C.recentChanges()
             + C.whereMoneyIs() + C.cashCountsCard(),

  setup: () => section('People and money', 'Who is paid, who is owed, and where the cash sits')
    + C.editAccounts('staff', 'Staff', 'A salary change applies from the month on screen if it is open, never to a closed one.')
    + C.editAccounts('supplier', 'Suppliers', 'A positive balance is what you owe them.')
    + C.editAccounts('partner', 'Partners', 'Shares decide how a closed month’s profit is split.')
    + C.editAccounts('cash', 'Cash pots', 'Where the business keeps its money. The first one is the main pot, used unless another is picked.')
    + C.floatsCard() + C.cashCountingCard()
    + C.editFixed() + C.editElecFactors()
    + section('Stock', 'What is counted and what it is worth')
    + C.editItems() + C.editTares() + C.editConversions()
    + section('Lists', 'What the pickers offer')
    + C.editList('expense', 'Daily expenses', 'The first twelve show as buttons on Tonight.')
    + C.editList('income', 'Other income', '')
    + C.editList('reason', 'Reasons for a cash difference', '')
    + section('SambaPOS', 'Keeping each night before the reset deletes it')
    + C.sambaposCard() + C.sambaposAccounts() + C.sambaposMenu() + C.sambaposStock()
    + section('This app', 'The business, the backups, and updates')
    + C.businessCard() + C.backupCard() + C.updateCard(),
};

const TITLES = {
  tonight: ['Tonight', 'The nightly job, in the order you do it.'],
  stock: ['Stock', 'What arrived, what is left, and what it is worth.'],
  month: ['Month', 'What the month came to, and settling it.'],
  books: ['Books', 'The record: correcting it, searching it, and the cash counts.'],
  setup: ['Setup', 'The lists and accounts everything else is built from.'],
};

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

const fields = () => [...document.querySelectorAll('#main input, #main select')];

/* ------------------------------------------------------------------ render */

function renderRail() {
  const rail = document.getElementById('rail');
  const bad = S.data ? S.data.checks.filter(c => !c.ok).length : 0;
  rail.querySelectorAll('button.tab').forEach(b => b.remove());
  let foot = rail.querySelector('.foot');
  if (!foot) {
    foot = document.createElement('div');
    foot.className = 'foot';
    rail.append(foot);
  }
  TABS.forEach(([key, label]) => {
    const b = document.createElement('button');
    b.className = 'tab';
    b.dataset.go = key;
    b.setAttribute('aria-current', String(key === S.tab));
    b.innerHTML = esc(label)
      + (key === 'tonight' && bad ? `<span class="flag" title="${bad} need a look">${bad}</span>` : '');
    rail.insertBefore(b, foot);
  });
  if (!S.data) return;
  document.getElementById('brandsub').textContent =
    (S.data.business.name || '') + ' · ' + S.data.today;
  foot.innerHTML = `<strong>${money(S.data.cash)}</strong> on hand
    <br><span>version ${esc(S.data.version)}</span>`;
}

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
    if (a && main.contains(a) && a.matches('input, select')) {
      focus = { key: fieldKey(a), start: null, end: null };
      try { focus.start = a.selectionStart; focus.end = a.selectionEnd; } catch { /* number boxes */ }
    }
  }
  renderRail();
  const [title, sub] = TITLES[S.tab];
  main.innerHTML = `<h1>${esc(title)}</h1><p class="sub">${esc(sub)}</p>` + VIEWS[S.tab]();
  if (S.tab === 'stock' && S.draft.fill) fillFigures();
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
    }
  }
}

/** Take a new state from the server, refresh anything open beside it, and
    redraw. */
let applied = 0;

async function apply(state, opts = {}) {
  applied++;
  S.data = state;
  S.month = state.month;
  S.on = state.day.on;
  S.count = state.stock.count_date;
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
    const state = await load(S.month, S.on, S.count);
    if (applied === gen && !document.querySelector('.ask')) await apply(state);
  } catch {
    /* the next change will bring the state anyway */
  }
  return undefined;
}

function watchBackups() {
  clearTimeout(watchTimer);
  const a = S.data && S.data.pos && S.data.pos.auto;
  if (!a || !(a.waiting || a.reading)) {
    watchTries = 0;
    return;
  }
  if (++watchTries <= 40) watchTimer = setTimeout(refreshQuietly, 2500);
}

function setTab(tab) {
  if (!VIEWS[tab]) return;
  S.tab = tab;
  try { history.replaceState(null, '', '#' + tab); } catch { /* not important */ }
  render({ fresh: true });
  window.scrollTo(0, 0);
  // opening Tonight looks for a new SambaPOS backup
  const a = S.data && S.data.pos && S.data.pos.auto;
  if (tab === 'tonight' && a && a.on) refreshQuietly();
}

/* ----------------------------------------------------------------- helpers */

const val = id => {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
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
  const mine = ++sent;
  try {
    const out = await fn();
    if (!out) return null;
    if (out.state && mine >= shown) {
      shown = mine;
      await apply(out.state, { skip });
    }
    return out;
  } catch (err) {
    say(err.message, true);
    if (onError) onError(err);
    return null;
  }
}

/** Send a change that moves money. If it would take a pot below zero the
    server refuses with 409 and says by how much; the person is asked, and
    the change is sent again only if they say so. */
async function sendGuarded(action, body, yes = 'Pay anyway') {
  try {
    return await send(action, body);
  } catch (err) {
    const short = err.status === 409 && err.extra && err.extra.overdraw;
    if (!short || !short.length) throw err;
    const s = short[0];
    const hint = !S.data.day.sales
      ? `Tonight's sales are not entered yet. If this was paid out of tonight's
         takings, enter the sales first and it will fit.`
      : `If it was paid from somewhere else, pick that pot instead. Going ahead
         leaves ${s.pot} below zero until the missing money is entered.`;
    const ok = await ask(`${s.pot} does not hold that much`,
      `It holds ${money(s.holds)}. This would leave it ${money(s.short_by)} short `
      + `on ${s.on}.\n\n${hint.replace(/\s+/g, ' ')}`, yes, 'Go back');
    if (!ok) return null;
    return send(action, { ...body, allow_overdraw: true });
  }
}

const nightLabel = kind => (C.NIGHT.find(n => n[0] === kind) || [kind, kind])[1];

/** Keep a copy of SambaPOS, and say which nights it covered. Reading a
    backup or the database takes a moment, so the button says so meanwhile. */
async function keepPos(el, action) {
  const label = el.textContent;
  el.disabled = true;
  el.textContent = 'Reading SambaPOS…';
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
      say('SambaPOS has no tickets to keep right now. If the reset has already run, '
        + 'that night is gone from SambaPOS; enter it from the printed report.', true);
    } else if (!nights.length) {
      say('Nothing new: everything in it was already kept.');
    } else {
      const unpaid = [...last.values()].reduce((t, l) => t + l.unpaid, 0);
      const live = action === 'pos_live';
      say(`Kept ${nights.length === 1 ? 'the night of ' + nights[0] : nights.length + ' nights'} from SambaPOS.`
        + (unpaid && live ? ` ${money(unpaid)} is still unpaid on open tickets — close them, `
                            + 'then bring it in again before the reset.' : ''),
        !!(unpaid && live));
    }
  } finally {
    el.disabled = false;
    el.textContent = label;
  }
}

/* ----------------------------------------------------------------- actions */

const H = {
  go(el) { setTab(el.dataset.go); },

  /* ---------------------------------------------------------- moving around */

  async setDay(el) {
    const on = el.dataset.on || el.value;
    if (!on) return;
    try { await apply(await load(S.month, on, S.count), { fresh: true }); }
    catch (err) { say(err.message, true); }
  },

  async setMonth(el) {
    const m = el.dataset.m || el.value;
    if (!m) return;
    try {
      await apply(await load(m, S.on), { fresh: true });
      if (el.dataset.m) window.scrollTo(0, 0);
    } catch (err) { say(err.message, true); }
  },

  async setCount(el) {
    try { await apply(await load(S.month, S.on, el.value), { fresh: true }); }
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
    if (!amount) return say('Type tonight’s figure first.', true);
    const out = await act(() => sendGuarded('sales', { amount, on: S.on }, 'Save it anyway'),
                          { skip: ['#nSales'] });
    if (out) say(`Sales for ${S.on}: ${money(amount)}.`);
  },

  async usePos(el) {
    const amount = Number(el.dataset.amount);
    const out = await act(() => sendGuarded('sales', { amount, on: S.on }, 'Save it anyway'),
                          { skip: ['#nSales'] });
    if (out) say(`Sales for ${S.on}: ${money(amount)}, from SambaPOS.`);
  },

  async nAdd() {
    const kind = S.draft.nKind || 'expense';
    const who = val('nWho');
    const amount = num('nAmt');
    const pot = val('nPot');
    if (!who) return say('Pick who or what it was first.', true);
    if (!amount) return say('Type an amount first.', true);
    S.draft.nWho = who;
    S.draft.nPot = pot;
    const out = await act(() => sendGuarded(kind, { amount, who, detail: who, pot, on: S.on },
                                            kind === 'staff_repay' ? 'Save it anyway' : 'Pay anyway'),
                          { skip: ['#nAmt'] });
    if (!out) return;
    say(`${nightLabel(kind)}: ${who}, ${money(amount)}.`);
    focusOn('nAmt');
  },

  async saveCount() {
    const pots = {};
    const keys = [];
    document.querySelectorAll('#main [data-pot]').forEach(el => {
      pots[el.dataset.pot] = el.value.trim().replace(/,/g, '');
      keys.push(fieldKey(el));
    });
    if (!Object.values(pots).some(v => v !== '')) return say('Count at least one pot.', true);
    const out = await act(() => send('cash_count', { on: S.on, reason: val('nReason'), pots }),
                          { skip: [...keys, '#nReason'] });
    if (!out) return;
    const c = S.data.counts.find(x => x.on === S.on);
    if (!c || c.diff === 0) return say('Counted, and it ties exactly.');
    say(`Counted. Out by ${signed(c.diff)} — find the missing entry, or write it off on Books.`);
  },

  /* ------------------------------------------------------------------ books */

  pickKind(el) {
    S.draft.kind = el.value;
    render({ skip: ['#eDetail'] });
  },

  async addEntry() {
    const kind = val('eKind');
    const amount = num('eAmt');
    if (!amount) return say('Type an amount first.', true);
    const body = { amount, on: val('eDate'), period: val('ePeriod') };
    if (kind === 'transfer') {
      body.from = val('eFrom');
      body.to = val('eTo');
      if (body.from === body.to) return say('Pick two different pots.', true);
    } else {
      body.detail = val('eDetail');
      body.who = body.detail;
      body.pot = val('ePot');
    }
    const yes = ['income', 'staff_repay', 'partner_in'].includes(kind) ? 'Save it anyway' : 'Pay anyway';
    const out = await act(() => sendGuarded(kind, body, yes), { skip: ['#eAmt', '#ePeriod'] });
    if (out) say('Added.');
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
    row.querySelectorAll('[data-e]').forEach(x => { f[x.dataset.e] = x.value.trim(); });
    const body = { id, on: f.on, amount: String(f.amount || '').replace(/,/g, '') };
    for (const k of ['detail', 'pot', 'pot_to', 'what', 'terms']) {
      if (k in f) body[k] = f[k];
    }
    // the month only travels when it was changed on purpose; otherwise it
    // follows the date, or stays where it was deliberately put
    const per = row.querySelector('[data-e="period"]');
    if (per && per.value !== per.dataset.was) body.period = per.value;
    S.draft.editing = null;
    const out = await act(() => sendGuarded('edit_entry', body, 'Save it anyway'),
                          { onError: () => { S.draft.editing = id; } });
    if (out) say('Corrected. The original is kept in the record, marked as corrected.');
    else if (S.draft.editing === null) S.draft.editing = id;     // said no: keep the row open
  },

  async void(el) {
    const id = Number(el.dataset.id);
    if (S.draft.editing === id) S.draft.editing = null;
    const out = await act(() => sendGuarded('void', { id }, 'Delete it anyway'));
    if (out) say('Deleted.', false, { label: 'Put back', run: () => H.putBack({ dataset: { id } }) });
  },

  async putBack(el) {
    const out = await act(() => sendGuarded('put_back', { id: Number(el.dataset.id) },
                                            'Put it back anyway'));
    if (out) say('Put back.');
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
    const ok = await ask(`Write off ${money(Math.abs(c.diff))} ${short ? 'short' : 'over'}?`,
      `The count on ${c.on} found ${short ? 'less' : 'more'} than the books said. Writing it off `
      + `sets the pot to what was counted, and the difference becomes `
      + `${short ? 'a cost' : 'a gain'} of ${monthName(c.on.slice(0, 7))}.\n\n`
      + 'Only do this once you are sure no entry is missing. The write-off shows '
      + 'on Books like any entry, and can be deleted there.', 'Write it off');
    if (!ok) return;
    const out = await act(() => send('write_off', { id }));
    if (out) say('Written off.');
  },

  async deleteCashCount(el) {
    const c = S.data.counts.find(x => x.id === Number(el.dataset.id));
    if (!c) return;
    const ok = await ask(`Delete the count for ${c.on}?`,
      'Only the count goes — no money moves. Count again on Tonight if it was wrong.',
      'Delete it');
    if (!ok) return;
    const out = await act(() => send('delete_cash_count', { id: c.id }));
    if (out) say('Count deleted.');
  },

  /* ------------------------------------------------------------------ stock */

  async openCount() {
    const on = val('newCount');
    if (!on) return say('Pick the date of the count.', true);
    const was = S.count;
    S.count = on;
    const out = await act(() => send('open_count', { on }), { onError: () => { S.count = was; } });
    if (out) say(`Count started for ${on}. Each box saves as you leave its line.`);
  },

  async deleteCount() {
    const on = S.data.stock.count_date;
    const ok = await ask(`Delete the count for ${on}?`,
      'Every line typed into it goes with it, and this cannot be put back.', 'Delete it');
    if (!ok) return;
    const was = S.count;
    S.count = null;
    const out = await act(() => send('delete_count', { on }), { onError: () => { S.count = was; } });
    if (out) say(`Count for ${on} deleted.`);
  },

  async receipt() {
    const amount = num('rAmt');
    if (!amount) return say('Type the receipt total first.', true);
    const out = await act(() => sendGuarded('receipt', {
      amount, on: val('rDate'), who: val('rSup'), number: val('rNo'),
      what: val('rWhat') || 'Several items', terms: val('rTerms'), pot: val('rPot'),
    }), { skip: ['#rAmt', '#rNo', '#rWhat'] });
    if (!out) return;
    S.draft.rlines = out.receipt || null;            // what came in, while the receipt is in hand
    render();
    document.getElementById('rlItem')?.focus();
    say('Receipt added. List what came in now, or later.');
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
      return say(`Nothing is called ${v}, and no item has that barcode. Add it in Setup → Stock items first.`, true);
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
    if (!it) return say(`No sealed tobacco is called ${v}, and none has that barcode.`, true);
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
    if (!lines.length) return say('Say how many packs of which tobacco went in.', true);
    const mix = S.data.stock.mixes.find(m => m.id === f.mix);
    const out = await act(() => send('bucket_fill', {
      mix: f.mix, on: val('fillOn'), lines, gross_grams: val('fillGross'),
      tare_id: val('fillTare'), usual: document.getElementById('fillKeep').checked,
    }), { skip: ['#fillGross', '#fillOn', '#fillTare'] });
    if (!out) return;
    S.draft.fill = null;
    render();
    say(`Filled ${mix.name}: ${out.grams.toLocaleString('en-US')} g at ${money(Math.round(out.value * 1000 / out.grams))} a kilo.`
      + (out.price_after !== out.price_before ? ` Its price is now ${money(out.price_after)} a kilo.` : ''));
  },

  async deleteFill(el) {
    const ok = await ask('Delete this fill?',
      'The packs go back to their tobacco, and the mix’s price goes back to what it was if nothing has changed it since.',
      'Delete it');
    if (!ok) return;
    const out = await act(() => send('bucket_fill_delete', { id: Number(el.dataset.id) }));
    if (out) say('Fill deleted.');
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
    const amount = Number(String(row.querySelector('[data-s="amount"]').value).replace(/,/g, '')) || 0;
    if (!amount) return say('Type an amount first.', true);
    const body = { amount, who: line.who, pot: row.querySelector('[data-s="pot"]').value };
    // a salary, rent or bill paid from here belongs to the month on screen;
    // a supplier is a running account, so a payment is simply dated today
    if (line.action !== 'pay_supplier') body.period = S.month;
    const out = await act(() => sendGuarded(line.action, body),
                          { skip: [`settle:${row.dataset.line}:amount`] });
    if (out) {
      say(`Paid ${line.who} ${money(amount)}`
        + (body.period ? `, counted for ${monthName(S.month)}.` : '.'));
    }
  },

  async saveElectricity() {
    const out = await act(() => send('set_electricity', {
      month: S.month, private_price: val('elPP'), elevator_price: val('elPE'),
      last_reading: val('elLast'), now_reading: val('elNow'),
    }), { skip: ['#elPP', '#elPE', '#elLast', '#elNow'] });
    if (out) say(`Electricity charged to ${monthName(S.month)}: ${money(out.bill.total)}.`);
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
      ? '\n\nWorth a look first:\n• ' + check.warnings.join('\n• ') : '';
    const ok = await ask(`Close ${monthName(S.month)}?`,
      `Net profit ${money(check.result.net)}, with the stock counted on ${check.count_date}. `
      + 'Closing freezes these figures, splits the profit between the partners and '
      + 'carries the stock into the next month. It can be reopened.' + warn,
      'Close the month');
    if (!ok) return;
    const out = await act(() => send('close_month', { month: S.month }));
    if (out) say(`${monthName(S.month)} closed.`);
  },

  async reopen() {
    const ok = await ask(`Reopen ${monthName(S.month)}?`,
      'Its entries can be changed again until it is closed again. The figures it '
      + 'was closed with stay in the record.', 'Reopen');
    if (!ok) return;
    const out = await act(() => send('reopen_month', { month: S.month }));
    if (out) say(`${monthName(S.month)} reopened.`);
  },

  /* --------------------------------------------------------------- sambapos */

  async posLive(el) { await keepPos(el, 'pos_live'); },
  async posAuto(el) {
    const label = el.textContent;
    el.disabled = true;
    el.textContent = 'Looking…';
    try {
      const out = await act(() => send('pos_auto'));
      if (!out) return;
      const nights = [...new Set((out.kept || []).map(l => l.night))];
      const bad = out.failed || [];
      if (bad.length) {
        say(`${bad.length === 1 ? 'One backup' : bad.length + ' backups'} could not be read: `
          + bad[0].note, true);
      } else if (nights.length) {
        say(`Kept ${nights.length === 1 ? 'the night of ' + nights[0] : nights.length + ' nights'}`
          + ' from SambaPOS’s backups.');
      } else {
        say(out.read ? 'Nothing new in the new backups.' : 'No new backups in the folder.');
      }
    } finally {
      el.disabled = false;
      el.textContent = label;
    }
  },
  async posFolder(el) { await keepPos(el, 'pos_folder'); },

  async moveRest(el) {
    const to = document.getElementById('restTo').value;
    const dr = S.data.drawer;
    if (!to) return say('Pick where the rest goes.', true);
    const out = await act(() => sendGuarded('move_rest', {
      amount: Number(el.dataset.amount), to, on: S.on }));
    if (out) say(`Moved ${money(Number(el.dataset.amount))} to ${to}.`);
  },

  async posAddNight(el) {
    el.disabled = true;
    try {
      const out = await act(() => sendGuarded('pos_add_night', { on: S.on }, 'Add it anyway'));
      if (out) say(`Added ${out.added} entr${out.added === 1 ? 'y' : 'ies'} from SambaPOS for ${out.night}.`);
    } finally {
      el.disabled = false;
    }
  },

  async posLeft(el) {
    const name = el.dataset.name || 'They';
    const ok = await ask(`Mark ${name} as left?`,
      'SambaPOS no longer has an account for them. Their history in the books stays; '
      + 'they stop being offered for new entries.', 'Mark as left');
    if (!ok) return;
    const out = await act(() => send('pos_left', { pos_id: Number(el.dataset.pos) }));
    if (out) say(`${out.name} is marked as left.`);
  },

  async posTold(el) {
    const out = await act(() => send('pos_told', { pos_id: Number(el.dataset.pos) }));
    if (out) say('Noted. Remove the account from SambaPOS when you can.');
  },

  async posTest(el) {
    el.disabled = true;
    try {
      const out = await send('pos_test');
      const p = out.probe || {};
      say(`Connected to ${p.db} as ${p.who}: ${p.tickets} tickets in SambaPOS now, `
        + `${p.open_periods} work period${p.open_periods === 1 ? '' : 's'} open.`);
    } catch (err) { say(err.message, true); }
    finally { el.disabled = false; }
  },

  /* ------------------------------------------------------------------ setup */

  async backupNow() {
    const out = await act(() => send('backup_now'));
    if (!out) return;
    const b = out.backup;
    if (!b.second) say('Copied and checked on this PC. Choose a second folder so a copy lives somewhere else too.');
    else if (b.second_ok) say(`Copied and checked, here and in ${b.second}.`);
    else say(`Copied here, but not to ${b.second}: ${b.second_error}`, true);
  },

  async checkUpdate() {
    try { S.draft.update = await get('/api/update'); }
    catch (err) { S.draft.update = { error: err.message }; }
    render();
  },

  async installUpdate() {
    const u = S.draft.update;
    const ok = await ask(`Install version ${u.latest}?`,
      'The books are copied aside first and this version is kept, so it can be put '
      + 'back. The app restarts by itself, and this page reloads when it is back.',
      'Install');
    if (!ok) return;
    try { await post('/api/update'); } catch (err) { return say(err.message, true); }
    say('Installing… this page reloads when the app is back.');
    const from = S.data.version;
    for (let i = 0; i < 90; i += 1) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const h = await get('/api/health');
        if (h.version && h.version !== from) { location.reload(); return; }
      } catch { /* still restarting */ }
    }
    say('The app has not come back. Close its window and start it again.', true);
  },

  async health() {
    try {
      const r = await get('/api/health');
      say(r.ok ? `Sound: ${money(r.entries)} entries, every one balanced.`
               : 'Something is wrong. Run the check from the start file and send Claude what it says.',
          !r.ok);
    } catch (err) { say(err.message, true); }
  },

  /* ------------------------------------------------------------------ print */

  printSuppliers() {
    const rows = S.data.suppliers.filter(s => s.owed_now > 0);
    printSlip(`<h3>${esc(S.data.business.name || 'Twilight')}</h3>
      <div>Owed to suppliers</div><div>${esc(S.data.today)}</div>
      <div class="rule"></div>
      <table>${rows.map(s => `<tr><td>${esc(s.name)}</td>
        <td style="text-align:right">${money(s.owed_now)}</td></tr>`).join('')}</table>
      <div class="rule"></div>
      <table><tr><td><strong>Total</strong></td>
        <td style="text-align:right"><strong>${money(S.data.owed)}</strong></td></tr></table>`);
  },

  printStatement() {
    const st = S.statement;
    if (!st) return;
    let run = st.opening;
    printSlip(`<h3>${esc(S.data.business.name || 'Twilight')}</h3>
      <div>${esc(st.name)}</div><div>${esc(monthName(st.month))}</div>
      <div class="rule"></div>
      <table><tr><td>Owed coming in</td><td style="text-align:right">${money(st.opening)}</td></tr>
      ${st.lines.map(l => {
        run += l.amount;
        return `<tr><td>${esc(l.on.slice(5))} ${esc(l.what)}</td>
          <td style="text-align:right">${signed(l.amount)}</td></tr>`;
      }).join('')}</table>
      <div class="rule"></div>
      <table><tr><td><strong>Owed at the end</strong></td>
        <td style="text-align:right"><strong>${money(st.closing)}</strong></td></tr></table>`);
  },

  printMonth() {
    const r = S.data.result;
    const line = (k, v) => `<tr><td>${esc(k)}</td>
      <td style="text-align:right">${money(v)}</td></tr>`;
    printSlip(`<h3>${esc(S.data.business.name || 'Twilight')}</h3>
      <div>${esc(monthName(S.data.month))}${S.data.so_far ? ' (in progress)' : ''}</div>
      <div class="rule"></div>
      <table>
        ${line('Sales', r.rev)}
        ${line('Cost of goods', -((r.cogs || {}).value || 0))}
        ${line('Gross', r.gross)}
        ${line('Expenses', -(r.daily || 0))}
        ${r.elec ? line('Electricity', -r.elec) : ''}
        ${line('Rent', -(r.fixed || 0))}
        ${line('Salaries', -(r.salaries || 0))}
        ${r.differences ? line('Cash written off', -r.differences) : ''}
      </table>
      <div class="rule"></div>
      <table>${line('Net profit', r.net)}
        ${S.data.so_far ? line(`So far (${S.data.so_far.days} days)`, S.data.so_far.net) : ''}</table>
      <div class="rule"></div>
      <div>Cash on hand ${money(S.data.cash)}</div>
      <div>Owed to suppliers ${money(S.data.owed)}</div>`);
  },
};

/* ------------------------------------------------------------------ events */

const ON_CHANGE = new Set(['setDay', 'setMonth', 'setCount', 'pickKind', 'fillMix']);

document.addEventListener('click', async e => {
  /* Setup: one button does one thing, described entirely by its attributes */
  const doer = e.target.closest('[data-do]');
  if (doer) {
    e.preventDefault();
    if (doer.dataset.confirm
        && !await ask(doer.dataset.confirm, doer.dataset.confirmBody || '', doer.dataset.yes || 'Yes')) {
      return;
    }
    const out = await act(() => send(doer.dataset.do, JSON.parse(doer.dataset.args || '{}')));
    if (out) say('Saved.');
    return;
  }
  const adder = e.target.closest('[data-add]');
  if (adder) {
    e.preventDefault();
    const body = JSON.parse(adder.dataset.args || '{}');
    const keys = [];
    adder.closest('.addrow').querySelectorAll('[data-f]').forEach(el => {
      body[el.dataset.f] = el.value.trim();
      if (el.dataset.keep === undefined) keys.push(fieldKey(el));     // kept for the next one
    });
    const out = await act(() => send(adder.dataset.add, body), { skip: keys });
    if (out) say('Added.');
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
  const box = e.target.closest('[data-save]');
  if (box) {
    const body = JSON.parse(box.dataset.args || '{}');
    body[box.dataset.field] = box.value.trim();
    const key = fieldKey(box);
    const out = await act(() => send(box.dataset.save, body),
                          { skip: [key], onError: () => render({ skip: [key] }) });
    if (!out) return;
    const b = out.backup;
    if (!b) say('Saved.');
    else if (b.second_ok) say(`Saved, and a copy is already in ${b.second}.`);
    else say(`Saved, but a copy could not be put there: ${b.second_error}`, true);
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
    body[el.dataset.k] = el.value.trim();
    keys.push(fieldKey(el));
  });
  const before = S.data.stock.count.closing;
  const out = await act(() => send('count_line', body), { skip: keys });
  if (out && out.closing !== before) say(`Counted value now ${money(out.closing)}.`);
}

/** A scanner types through the keyboard layout in use: with a Kurdish or
    Arabic layout the digits of a code can arrive as ٠١٢… They are the same
    code. */
const westernDigits = s => s.replace(/[\u0660-\u0669]/g, d => d.charCodeAt(0) - 0x0660)
                            .replace(/[\u06F0-\u06F9]/g, d => d.charCodeAt(0) - 0x06F0);

/** A fill starting from a mix's usual batch. */
function usualOf(mix) {
  const packs = {};
  mix.usual.forEach(u => { packs[u.item] = String(u.packs); });
  return { mix: mix.id, order: mix.usual.map(u => u.item), packs, on: S.data.today };
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
    document.querySelector(`[data-fillgrams="${it.id}"]`).textContent = g ? `${g.toLocaleString('en-US')} g` : '';
    document.querySelector(`[data-fillvalue="${it.id}"]`).textContent = g ? money(Math.round(v)) : '';
  });
  const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  set('fillGrams', grams ? `${grams.toLocaleString('en-US')} g` : '');
  set('fillValue', grams ? money(Math.round(value)) : '');
  set('fillPrice', grams ? `${money(Math.round(value * 1000 / grams))} a kilo` : '');
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
    it = await pickItem(`${code} is new`, 'Which item is it? Once you say, every scan of it knows.',
                        items.filter(i => i.active));
    if (!it) return;
    const out = await act(() => send('item_update', { id: it.id, barcode_add: code }));
    if (!out) return;
    say(`${code} is now ${it.name}.`);
  }
  if (S.tab === 'stock' && S.draft.fill && S.draft.fill.mix) {
    if (it.letter !== 'B') return say(`Only sealed tobacco goes into a mix, not ${it.name}.`, true);
    return fillItem(it, 1);
  }
  if (S.tab === 'stock' && S.draft.rlines && document.getElementById('rlItem')) {
    if (it.letter === 'A') return say(`${it.name} is a mix, made here, not bought.`, true);
    return receiptItem(it);
  }
  const sheet = S.tab === 'stock' && S.data.stock.count.date;
  if (sheet) {
    const row = document.querySelector(`#main tr[data-item="${it.id}"]:not([data-receipt])`);
    if (!row) return say(`${it.name} is not on this count.`, true);
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
  say(`${code} is ${it.name}.`);
}

async function saveReceiptLine(row) {
  const rid = Number(row.dataset.receipt);
  const item = Number(row.dataset.item);
  const body = { receipt: rid, item };
  const keys = [];
  row.querySelectorAll('[data-k]').forEach(el => {
    body[el.dataset.k] = el.value.trim();
    keys.push(fieldKey(el));
  });
  const out = await act(() => send('receipt_line', body), { skip: keys });
  if (!out) return;
  const p = (S.draft.rpending || {})[rid];
  if (p) S.draft.rpending[rid] = p.filter(i => i !== item);   // saved, so no longer waiting
  say(out.removed ? 'Line taken off.' : 'Saved.');
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
  const item = el.closest('[data-item]');
  if (item) {                                   // down a line, like a spreadsheet
    e.preventDefault();
    let next = item.nextElementSibling;
    while (next && !next.querySelector(`[data-k="${el.dataset.k}"]`)) next = next.nextElementSibling;
    if (next) next.querySelector(`[data-k="${el.dataset.k}"]`).focus();
    else el.blur();
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

/* -------------------------------------------------------------------- boot */

(async function start() {
  const tab = location.hash.slice(1);
  if (VIEWS[tab]) S.tab = tab;
  try {
    await apply(await load(), { fresh: true });
    const bad = S.data.checks.filter(c => !c.ok).length;
    if (bad) say(`${bad} thing${bad === 1 ? '' : 's'} need${bad === 1 ? 's' : ''} a look.`);
  } catch (err) {
    document.getElementById('main').innerHTML =
      `<div class="banner bad"><h2>Could not open the books</h2>
        <p style="margin:0">${esc(err.message)}</p></div>`;
  }
})();

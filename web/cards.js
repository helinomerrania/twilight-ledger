/* One function per card. A card reads the state and returns markup; it never
   fetches and never computes a figure the server already worked out. That is
   deliberate: in the old app the cards did their own arithmetic, and the cards
   disagreed. */

import {
  S, args, card, cls, empty, esc, field, kindName, money, monthName, monthOf,
  options, pct, potOptions, signed, table, tile, tiles,
} from './lib.js';

const go = c => (c.go ? ` <button class="mini link" data-go="${esc(c.go)}">Open ${esc(c.go)}</button>` : '');
const amountInput = (id, value = '', extra = '') =>
  `<input type="number" step="${S.data.note}" min="0" id="${id}" value="${esc(value)}"
     placeholder="0" inputmode="numeric" ${extra}>`;

/* ============================================================ needs a look */

export function needsALook() {
  const bad = S.data.checks.filter(c => !c.ok);
  if (!bad.length) return '';
  const show = bad.slice(0, 4);
  return `<div class="banner${bad.some(b => b.label === 'The books balance') ? ' bad' : ''}">
    <h2>Needs a look</h2>
    <ul>${show.map(c => `<li><strong>${esc(c.label)}</strong>${c.detail ? ' — ' + esc(c.detail) : ''}
      <br><span class="quiet">${esc(c.fix || '')}</span>${go(c)}</li>`).join('')}</ul>
    ${bad.length > show.length
      ? `<p style="margin:8px 0 0"><button class="btn" data-go="month">See all
           ${bad.length}</button></p>` : ''}
  </div>`;
}

export function allChecks() {
  return card(`<h2>Checks</h2><p class="sub">Each one is a question with a yes or
      no answer, and says what to do about a no.</p>
    ${S.data.checks.map(c => `<div class="check ${c.ok ? 'ok' : 'no'}">
      <span class="mark">${c.ok ? '✓' : '!'}</span>
      <span><span class="label">${esc(c.label)}</span>
        ${c.detail ? ` <span class="detail">— ${esc(c.detail)}</span>` : ''}
        ${!c.ok && c.fix ? `<br><span class="fix">${esc(c.fix)}</span>${go(c)}` : ''}</span>
    </div>`).join('')}`);
}

/* ================================================================== tonight */

/* What can leave or come back to the box at night, in the order they are
   most used. Each says what it does to the books, because the difference
   between an expense and an advance is the whole difference to profit. */
export const NIGHT = [
  ['expense', 'Expense', 'A cost of running tonight. It comes straight off this month’s profit.'],
  ['staff_advance', 'Staff advance', 'Money a member of staff takes against their salary. It never touches profit — it comes off what they are paid.'],
  ['partner_draw', 'Partner took cash', 'A partner taking money out. It comes off their share of the profit, not off the profit itself.'],
  ['pay_salary', 'Salary', 'Handing over a salary. The salary is already charged to the month, so this is only cash leaving.'],
  ['pay_supplier', 'Supplier', 'Paying down what a supplier is owed. The goods are already in the cost of goods, so profit does not change.'],
  ['pay_fixed', 'Rent', 'Paying rent. It is charged to every month already, so this is only cash leaving.'],
  ['staff_repay', 'Money back', 'A member of staff handing money back. Cash comes in and their advances go down.'],
];

function nightNames(kind) {
  const p = S.data.people;
  const active = list => list.filter(a => a.active).map(a => a.name);
  return {
    expense: S.data.lists.expense || [],
    staff_advance: active(p.staff), pay_salary: active(p.staff), staff_repay: active(p.staff),
    partner_draw: active(p.partner), pay_supplier: active(p.supplier),
    pay_fixed: S.data.fixed_names || [],
  }[kind] || [];
}

export function closingUp() {
  const d = S.data.day;
  const kind = S.draft.nKind || 'expense';
  const names = nightNames(kind);
  const pick = names.includes(S.draft.nWho) ? S.draft.nWho : (names[0] || '');
  const counted = {};
  const lastCount = S.data.counts.find(c => c.on === d.on);
  if (lastCount) lastCount.pots.forEach(p => { counted[p.name] = p.counted; });
  const pots = d.pots.filter(p => p.active && (p.in_use || p.name in counted));
  const chips = kind === 'expense' ? names.slice(0, 12) : names;

  // a blind count shows what was expected only once the count is saved
  const dr = S.data.drawer || {};
  const blind = dr.blind && !lastCount;
  const potCards = pots.map(p => {
    const got = counted[p.name];
    const diff = got === undefined ? null : got - p.balance;
    const pos = p.name === dr.pot && dr.pos && !blind ? dr.pos : null;
    return `<div class="pot">
      <div class="nm">${esc(p.name)}</div>
      ${blind ? '<div class="bal quiet">?</div><div class="sub">count it first</div>'
        : `<div class="bal">${money(p.balance)}</div><div class="sub">the books say</div>`}
      <input type="number" step="${S.data.note}" min="0" placeholder="count it"
             data-pot="${esc(p.name)}" value="${got === undefined ? '' : got}" inputmode="numeric">
      ${diff === null ? '' : `<div class="sub ${cls(diff)}" style="margin-top:6px">
         ${diff === 0 ? 'ties exactly' : signed(diff)}</div>`}
      ${pos ? `<div class="sub" style="margin-top:6px" title="What SambaPOS says went
          into and out of its drawer this night">SambaPOS: cash ${money(pos.cash)}${pos.out
          ? `, out ${money(pos.out)}` : ''}${pos.in ? `, in ${money(pos.in)}` : ''}${pos.expected
          !== undefined ? `<br>with the float: ${money(pos.expected)}` : ''}</div>` : ''}
    </div>`;
  }).join('');
  const sd = dr.sales_differ;
  const hidden = sd && !blind
    ? `<p class="note warnc">The books' sales this night are ${money(sd.books)}, but SambaPOS took
         ${money(sd.pos)}. If the sales were worked out from the count, a
         ${sd.gap > 0 ? 'shortage' : 'surplus'} of ${money(Math.abs(sd.gap))} is hidden in them.
         Use SambaPOS's figure in step 1, and let the count show the difference.</p>` : '';
  const there = counted[dr.pot];
  const rest = there === undefined ? 0 : there - (dr.float || 0);
  const move = !dr.float || !lastCount || there === undefined ? ''
    : dr.moved ? `<p class="note">Moved ${money(dr.moved)} out of ${esc(dr.pot)} today.</p>`
      : rest > 0 ? `<div class="row" style="margin-top:12px">
          <span>Leave the float of ${money(dr.float)} in ${esc(dr.pot)} and move the rest,
            <strong>${money(rest)}</strong>, to</span>
          <select id="restTo" style="max-width:180px">${options(
            S.data.pots.filter(p => p.active && p.name !== dr.pot).map(p => p.name), dr.rest_to)}</select>
          <button class="btn" data-act="moveRest" data-amount="${rest}">Move it</button></div>` : '';

  return card(`
    <div class="cardhead">
      <h2>Closing up</h2>
      <div class="right"><input type="date" id="nightDate" value="${esc(d.on)}"
           max="${esc(S.data.today)}" data-act="setDay" style="width:auto"></div>
    </div>
    <div class="steps">

      <div class="step"><div class="no">1</div><div>
        <h3>Tonight's sales</h3>
        <p>The one figure from the till. Saving it again replaces it.</p>
        <div class="row">
          ${amountInput('nSales', d.sales || '', 'class="big" style="max-width:220px"')}
          <button class="btn primary" data-act="sales">${d.sales ? 'Replace' : 'Save'}</button>
          ${d.sales ? `<span class="quiet">recorded ${money(d.sales)}</span>` : ''}
        </div>
        ${posLine()}${missingNights()}</div></div>

      <div class="step"><div class="no">2</div><div>
        <h3>What went out</h3>
        <div class="chips kinds">
          ${NIGHT.map(([k, label]) => `<button data-act="nKind" data-k="${k}"
             aria-pressed="${k === kind}">${esc(label)}</button>`).join('')}
        </div>
        <div class="chips">
          ${chips.map(c => `<button data-act="nWho" data-who="${esc(c)}"
             aria-pressed="${c === pick}">${esc(c)}</button>`).join('')
            || `<span class="quiet">Nothing set up for this yet — add it in Setup.</span>`}
        </div>
        <div class="row">
          <select id="nWho" style="max-width:220px">${options(names, pick)}</select>
          ${amountInput('nAmt', '', 'style="max-width:140px"')}
          <select id="nPot" style="max-width:150px" title="${kind === 'staff_repay' ? 'into' : 'paid from'}">
            ${potOptions(S.draft.nPot)}</select>
          <button class="btn primary" data-act="nAdd">Add</button>
          ${d.paid_out ? `<span class="quiet">${money(d.paid_out)} out so far</span>` : ''}
        </div>
        <p class="note">${esc((NIGHT.find(n => n[0] === kind) || [])[2] || '')}</p>
        </div></div>

      <div class="step"><div class="no">3</div><div>
        <h3>Count the cash</h3>
        <p>Count each place the money sits. A difference then tells you which
           pot it is in, instead of just that there is one.</p>
        ${blind ? '<p class="note">Counting blind: what the books expect shows once the count is saved.</p>' : ''}
        <div class="potgrid">${potCards || empty('No pots in use.')}</div>
        ${hidden}
        <div class="row" style="margin-top:12px">
          <select id="nReason" style="max-width:260px">
            <option value="">no reason needed</option>
            ${options(S.data.lists.reason, lastCount ? lastCount.reason : '')}</select>
          <button class="btn primary" data-act="saveCount">
            ${lastCount ? 'Update count' : 'Save count'}</button>
        </div>${move}</div></div>
    </div>`);
}

/** How the cash is counted: the float, a blind count, where the rest goes. */
export function cashCountingCard() {
  const c = S.data.drawer || {};
  const pots = S.data.pots.filter(p => p.active).map(p => p.name);
  return card(`<h2>Counting the cash</h2>
    <p class="sub">A float is left in the drawer at the end of each night, in small notes, so
      there is change from the first sale. After the count, Tonight offers to move everything
      above it out of ${esc(c.pot || 'the drawer')} in one click.</p>
    <div class="grid-form">
      ${field('Float left in the drawer (0 for none)', save('cash_settings', {}, 'float', c.float || 0,
        `type="number" min="0" step="${S.data.note}" inputmode="numeric"`))}
      ${field('The rest usually goes to', `<select data-save="cash_settings" data-args="${args({})}"
        data-field="rest_to">${options([{ value: '', label: 'choose each time' }, ...pots],
          c.rest_to || '')}</select>`)}
      ${field('While counting', `<select data-save="cash_settings" data-args="${args({})}"
        data-field="blind">${options([{ value: '0', label: 'show what the books expect' },
          { value: '1', label: 'count blind: show it once the count is saved' }],
          c.blind ? '1' : '0')}</select>`)}
    </div>
    <p class="note">A blind count is a well-known control: whoever counts types what they find
      before seeing what was expected, so nobody can count towards the answer.</p>`);
}

/** Each count's difference over the month, and who opened SambaPOS those nights. */
export function cashDifferences() {
  const d = S.data.differences;
  if (!d || !d.rows.length) return '';
  const max = Math.max(...d.rows.map(r => Math.abs(r.found)), 1);
  const bars = d.rows.map(r => {
    const h = Math.round(Math.abs(r.found) / max * 44);
    return `<div class="dday" title="${esc(r.on)}: ${r.found ? signed(r.found) : 'ties'}${
        r.opened_by ? ` · opened by ${esc(r.opened_by)}` : ''}">
      <span class="up">${r.found > 0 ? `<span class="good" style="height:${h}px"></span>` : ''}</span>
      <span class="down">${r.found < 0 ? `<span class="bad" style="height:${h}px"></span>` : ''}</span>
      <span class="quiet">${Number(r.on.slice(8))}</span></div>`;
  }).join('');
  const known = d.by_who.filter(g => g.who !== 'not known');
  const who = known.length ? table('<th>Opened SambaPOS</th><th class="num">Nights</th><th class="num">Short</th><th class="num">Over</th><th class="num">Net</th>',
    d.by_who.map(g => `<tr><td><bdi>${esc(g.who)}</bdi></td><td class="num">${g.nights}</td>
      <td class="num">${g.short || ''}</td><td class="num">${g.over || ''}</td>
      <td class="num ${cls(g.net)}">${g.net ? signed(g.net) : '0'}</td></tr>`).join('')) : '';
  return card(`<h2>Cash differences</h2>
    <p class="sub">What each night's count added to the difference with the books. A shortage
      nobody explained counts on the night it appeared, not again every night after. Small ups
      and downs are normal; a steady shortage on certain nights or shifts is not.</p>
    <div class="ddays">${bars}</div>
    <p class="note">${d.rows.length} count${d.rows.length === 1 ? '' : 's'}: ${money(-d.short)} short,
      ${money(d.over)} over, ${d.net ? signed(d.net) : 'nothing'} in all. A difference written off
      becomes a cost of its month.</p>${who}`);
}

const hhmm = t => String(t || '').slice(11, 16);

/** A time the database wrote in UTC, as the clock on the wall shows it. */
const localTime = at => {
  const d = new Date(String(at || '').replace(' ', 'T') + 'Z');
  return isNaN(d) ? String(at || '') : d.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

/** What SambaPOS kept for this night, and the one click that uses it. */
function posLine() {
  const pos = S.data.pos;
  if (!pos) return '';
  const night = pos.night;
  if (!night) {
    const on = S.data.day.on;
    const auto = pos.auto || {};
    const live = pos.can_read_live
      ? ' <button class="mini link" data-act="posLive">Read SambaPOS now</button>' : '';
    if (auto.on && (auto.waiting || auto.reading)) {
      return '<p class="note quiet">Reading SambaPOS’s backups…</p>';
    }
    if (auto.on) {
      return on >= S.data.today
        ? `<p class="note quiet">SambaPOS backs the night up when it is reset, and it
             comes in here by itself after that.${live}</p>`
        : `<p class="note">No SambaPOS backup has the night of ${esc(on)}.${live}</p>`;
    }
    if (live) return `<p class="note">SambaPOS has not been kept for ${esc(on)}.${live}</p>`;
    return `<p class="note quiet">Tell the app where SambaPOS puts its backups, and each
      night comes in by itself. <button class="mini link" data-go="setup">Open setup</button></p>`;
  }
  const same = night.takings === S.data.day.sales;
  return `<p class="note">SambaPOS kept <strong>${money(night.takings)}</strong> paid over
      ${night.tickets} tickets${night.unpaid
        ? `, and <span class="warnc">${money(night.unpaid)} still unpaid on
             ${night.open_tickets} open ticket${night.open_tickets === 1 ? '' : 's'}</span>` : ''}.
      ${night.ended ? '' : `<span class="quiet">(as it stood at ${esc(hhmm(night.seen_to))})</span>`}
      ${same ? '<span class="pos">The books match.</span>'
             : `<button class="mini link" data-act="usePos" data-amount="${night.takings}">
                  Use ${money(night.takings)}</button>`}</p>`;
}

/** A nudge when nights have been skipped, because the books are usually
    done the day after. */
function missingNights() {
  const last = S.data.last_sales;
  const d = S.data.day;
  if (!last || d.sales || d.on <= last) return '';
  const next = new Date(last + 'T00:00:00Z');
  next.setUTCDate(next.getUTCDate() + 1);
  const first = next.toISOString().slice(0, 10);
  if (first >= d.on) return '';
  return `<p class="note warnc">No sales are entered after ${esc(last)}.
    <button class="mini link" data-act="setDay" data-on="${first}">Go to ${esc(first)}</button></p>`;
}

export function todayFigures() {
  const d = S.data.day;
  const floats = S.data.people.float.length > 0;
  return tiles([
    tile("Tonight's sales", money(d.sales)),
    tile('Paid out', money(d.paid_out), 'everything that left a pot'),
    tile('Cash on hand', money(d.cash), 'your own pots, end of the day'),
    floats ? tile("In people's hands", money(d.floats), 'floats') : '',
  ]);
}

export function todayEntries() {
  const rows = S.data.day.entries;
  return card(`<h2>Everything entered for ${esc(S.data.day.on)}</h2>
    ${rows.length ? entryTable(rows, { date: false }) : empty('Nothing entered for this day yet.')}`);
}

/* ============================================================ entries table */

function whoList(kind) {
  const p = S.data.people;
  const names = list => list.map(a => a.name);
  if (kind === 'daily_expense') return S.data.lists.expense || [];
  if (kind === 'other_income') return S.data.lists.income || [];
  if (['staff_advance', 'staff_repayment', 'salary_payment'].includes(kind)) return names(p.staff);
  if (['supplier_payment', 'receipt_credit', 'receipt_cash'].includes(kind)) return names(p.supplier);
  if (['partner_draw', 'partner_in'].includes(kind)) return names(p.partner);
  if (kind === 'fixed_payment') return S.data.fixed_names || [];
  return null;
}

function entryRow(e, { date = true, lines = false } = {}) {
  const edit = S.draft.editing === e.id;
  if (edit) return editRow(e, { date });
  const where = e.kind === 'transfer' ? `${esc(e.pot)} → ${esc(e.pot_to)}` : esc(e.pot || '');
  return `<tr>
    ${date ? `<td class="nowrap">${esc(e.happened_on)}</td>` : ''}
    <td>${esc(e.label)}</td>
    <td>${['daily_sales', 'transfer'].includes(e.kind) ? '' : esc(e.detail || '')}
      ${e.tagged ? ` <span class="pill">for ${esc(monthName(e.period))}</span>` : ''}
      ${e.memo && e.kind !== 'transfer' ? ` <span class="quiet">${esc(e.memo)}</span>` : ''}</td>
    <td class="quiet">${where}</td>
    <td class="num ${e.cash > 0 ? 'pos' : ''}">${money(e.amount)}</td>
    <td class="actions">
      ${lines && e.receipt ? `<button class="mini" data-act="receiptLines" data-id="${e.receipt.id}"
          aria-expanded="${S.draft.rlines === e.receipt.id}">${e.lines.length
          ? `${e.lines.length} line${e.lines.length === 1 ? '' : 's'}` : 'What came in'}</button>` : ''}
      ${e.editable ? `<button class="mini" data-act="edit" data-id="${e.id}">Edit</button>` : ''}
      ${e.deletable ? `<button class="mini danger" data-act="void" data-id="${e.id}">Delete</button>` : ''}
    </td></tr>`;
}

function editRow(e, { date }) {
  const names = whoList(e.kind);
  const isReceipt = e.kind.startsWith('receipt_');
  const r = e.receipt || {};
  const closed = new Set((S.data.summary || []).filter(r => r.status === 'closed').map(r => r.month));
  const months = S.data.months.filter(m => m <= S.data.this_month && (!closed.has(m) || m === e.period));
  return `<tr class="editing" data-edit="${e.id}">
    <td colspan="${date ? 6 : 5}">
      <div class="grid-form">
        ${field('Date', `<input type="date" data-e="on" value="${esc(e.happened_on)}" max="${esc(S.data.today)}">`)}
        ${names ? field(isReceipt ? 'Supplier' : 'Who or what',
            `<select data-e="detail">${options(names.includes(e.detail) ? names : [e.detail, ...names], e.detail)}</select>`) : ''}
        ${e.kind === 'transfer'
          ? field('From', `<select data-e="pot">${potOptions(e.pot)}</select>`)
            + field('To', `<select data-e="pot_to">${potOptions(e.pot_to)}</select>`)
          : (e.pot ? field(e.cash > 0 ? 'Into' : 'Out of', `<select data-e="pot">${potOptions(e.pot)}</select>`) : '')}
        ${isReceipt ? field('For', `<input data-e="what" value="${esc(r.what || '')}">`)
                      + field('Terms', `<select data-e="terms">${options([
                          { value: 'credit', label: 'On credit' }, { value: 'cash', label: 'Paid cash' }],
                          r.terms || (e.kind === 'receipt_cash' ? 'cash' : 'credit'))}</select>`) : ''}
        ${field('Amount', `<input type="number" data-e="amount" step="${S.data.note}" min="0" value="${e.amount}" inputmode="numeric">`)}
        ${field('Counts for', `<select data-e="period" data-was="${esc(e.period)}">${options(
            months.map(m => ({ value: m, label: monthName(m) })), e.period)}</select>`)}
        <div class="row">
          <button class="btn primary" data-act="saveEdit" data-id="${e.id}" data-tagged="${e.tagged ? 1 : 0}">Save</button>
          <button class="btn" data-act="cancelEdit">Cancel</button>
        </div>
      </div>
      <p class="note">The original stays in the record as corrected, with the time it was changed.</p>
    </td></tr>`;
}

export function entryTable(rows, opts = {}) {
  const date = opts.date !== false;
  return table(`${date ? '<th>Date</th>' : ''}<th>What</th><th>Details</th><th>Pot</th>
                <th class="num">Amount</th><th></th>`,
    rows.map(e => entryRow(e, { date })).join(''));
}

/* =================================================================== month */

export function periodPicker() {
  const per = S.data.period;
  return card(`<div class="cardhead">
      <h2>${esc(monthName(S.data.month))}</h2>
      ${per.status === 'closed' ? '<span class="pill">closed</span>' : ''}
      ${S.data.month === S.data.this_month ? '<span class="pill">in progress</span>' : ''}
      <div class="right row">
        <select data-act="setMonth" style="width:auto">
          ${options(S.data.months.slice().reverse().map(m => ({ value: m, label: monthName(m) })), S.data.month)}
        </select>
        <button class="btn" data-act="printMonth">Print</button>
      </div>
    </div>`);
}

export function monthFigures() {
  const r = S.data.result;
  const sf = S.data.so_far;
  const dr = S.data.drawings;
  return tiles([
    tile('Sales', money(r.rev)),
    tile('Gross profit', money(r.gross), pct(r.grossPct), cls(r.gross)),
    sf ? tile(`Net profit so far`, money(sf.net), `${sf.days} of ${sf.days_in_month} days`, cls(sf.net))
       : tile('Net profit', money(r.net), pct(r.netPct), cls(r.net)),
    tile('Taken out by partners', money(dr.taken),
         dr.over ? `${money(dr.over)} more than the profit` : 'within the profit',
         dr.over ? 'neg' : ''),
  ]);
}

export function soFarCard() {
  const sf = S.data.so_far;
  if (!sf) return '';
  const line = (label, value, note, strong) => `<tr${strong ? ' class="tot"' : ''}>
      <td>${esc(label)}${note ? ` <span class="quiet">${esc(note)}</span>` : ''}</td>
      <td class="num ${strong ? cls(value) : ''}">${money(value)}</td></tr>`;
  return card(`<h2>So far: ${sf.days} of ${sf.days_in_month} days</h2>
    <p class="sub">Rent and salaries are charged for the whole month from the first
      day, so part-way through, the full result looks like a loss that is not real.
      This sets ${sf.days} days of them against ${sf.days} days of sales.</p>
    ${table('<th>Line</th><th class="num">Amount</th>',
      line('Sales', sf.rev, `to ${sf.through}`)
      + line('Cost of goods', -sf.cogs, sf.cogs_note)
      + line('Daily expenses & bills', -sf.daily)
      + (sf.elec ? line('Electricity', -sf.elec, sf.elec_estimated ? 'estimated from last month' : `${sf.days} days' worth`) : '')
      + line('Rent & fixed', -sf.fixed, `${sf.days} days' worth`)
      + line('Salaries', -sf.salaries, `${sf.days} days' worth`)
      + (sf.differences ? line('Cash written off', -sf.differences) : '')
      + line('Net so far', sf.net, '', true))}`);
}

export function resultCard() {
  const r = S.data.result;
  const line = (label, value, strong, note) => `<tr${strong ? ' class="tot"' : ''}>
      <td>${esc(label)}${note ? ` <span class="quiet">${esc(note)}</span>` : ''}</td>
      <td class="num ${strong ? cls(value) : ''}">${money(value)}</td></tr>`;
  const c = r.cogs || {};
  const inProgress = !!S.data.so_far;
  return card(`<h2>${inProgress ? 'Full month' : 'Result'}${r.frozen ? ' <span class="pill">frozen</span>' : ''}</h2>
    <p class="sub">${r.frozen
      ? 'This month is closed, so these are the figures recorded at the time.'
      : inProgress ? 'With the whole month’s rent and salaries already charged.'
                   : 'Rent and salaries are charged to the month whether or not they have been paid.'}</p>
    ${table(`<th>Line</th><th class="num">Amount</th>`,
      line('Sales', r.rev)
      + line('Cost of goods', -(c.value || 0))
      + line('Gross profit', r.gross, true)
      + line('Daily expenses & bills', -(r.daily || 0))
      + (r.elec ? line('Electricity used', -(r.elec || 0)) : '')
      + line('Rent & fixed', -(r.fixed || 0))
      + line('Salaries', -(r.salaries || 0))
      + (r.differences ? line('Cash written off', -(r.differences || 0)) : '')
      + line('Net profit', r.net, true))}
    <p class="sub" style="margin-top:10px">Stock ${money(c.opening)} at the start,
      ${money(c.purchases)} bought, ${money(c.closing)} left
      ${c.date ? `(counted ${esc(c.date)})` : ''}.</p>`);
}

export function electricityCard() {
  const e = S.data.electricity;
  if (S.data.period.status === 'closed') {
    return e.charged ? card(`<h2>Electricity</h2>
      <p class="sub">${money(e.charged)} was charged to this month.</p>`) : '';
  }
  const f = e.factors;
  return card(`<h2>Electricity</h2>
    <p class="sub">Charged to the month from the meter; paid whenever the bill is
      actually settled. ${e.charged ? `<strong>${money(e.charged)} charged to
      ${esc(monthName(S.data.month))}.</strong>` : 'Nothing charged to this month yet.'}
      ${e.unpaid > 0 ? ` ${money(e.unpaid)} in all is still unpaid.` : ''}</p>
    <div class="grid-form">
      ${field(`Private, price per amp (×${f.privateAmps})`,
        `<input type="number" id="elPP" value="${esc(e.private_price)}" min="0" inputmode="numeric">`)}
      ${field(`Elevator, price per amp (×${f.elevatorAmps} ÷ ${f.elevatorShare})`,
        `<input type="number" id="elPE" value="${esc(e.elevator_price)}" min="0" inputmode="numeric">`)}
      ${field('Public meter, last reading',
        `<input type="number" id="elLast" value="${esc(e.last_reading)}" min="0" inputmode="numeric">`)}
      ${field(`Public meter, now (×${f.publicRate} ÷ ${f.publicShare})`,
        `<input type="number" id="elNow" value="${esc(e.now_reading)}" min="0" inputmode="numeric">`)}
      <div><button class="btn primary" data-act="saveElectricity">Charge the month</button></div>
    </div>`);
}

export function settleCard() {
  if (S.data.period.status === 'closed') return '';
  const lines = S.data.settle;
  if (!lines.length) {
    return card(`<h2>Settle up</h2>
      <p class="sub">Nothing is waiting to be paid up to the end of ${esc(monthName(S.data.month))}.</p>`);
  }
  return card(`<h2>Settle up</h2>
    <p class="sub">Everything unpaid up to the end of <strong>${esc(monthName(S.data.month))}</strong>.
      A salary, rent or electricity paid from here counts for ${esc(monthName(S.data.month))}
      whatever today's date is — that is what stops a November payment counting
      against November.</p>
    ${table(`<th>What</th><th>Who</th><th class="num">Still to pay</th>
             <th style="width:150px">Amount</th><th>From</th><th></th>`,
      lines.map(l => `<tr data-line="${esc(l.action + '|' + l.who)}">
        <td>${esc(l.what)}</td>
        <td>${esc(l.who)}${l.note ? `<br><span class="quiet">${esc(l.note)}</span>` : ''}</td>
        <td class="num">${money(l.amount)}</td>
        <td><input type="number" data-s="amount" step="${S.data.note}" min="0" value="${l.amount}"
              inputmode="numeric"></td>
        <td><select data-s="pot" style="width:auto">${potOptions()}</select></td>
        <td><button class="btn primary" data-act="settle">Pay</button></td>
      </tr>`).join(''))}`);
}

export function payrollCard() {
  const pay = S.data.payroll;
  if (!pay.length) return '';
  const T = k => pay.reduce((a, p) => a + (p[k] || 0), 0);
  return card(`<h2>Staff</h2>
    <p class="sub">The salary is charged to the month in full. Advances come off
      it; what is left is handed over.</p>
    ${table(`<th>Who</th><th class="num">Salary</th><th class="num">Advances</th>
             <th class="num">Paid</th><th class="num">Still to pay</th>`,
      pay.map(p => `<tr>
        <td>${esc(p.name)}${p.active ? '' : ' <span class="pill">no longer here</span>'}</td>
        <td class="num">${money(p.gross)}</td>
        <td class="num">${money(p.advances)}</td>
        <td class="num">${money(p.paid)}</td>
        <td class="num">${p.overpaid
          ? `<span class="neg">${money(p.overpaid)} ahead</span>`
          : `<span class="${p.still_to_pay ? '' : 'pos'}">${money(p.still_to_pay)}</span>`}
          ${p.from_earlier ? `<br><span class="quiet">${money(p.from_earlier)} from earlier</span>` : ''}</td>
      </tr>`).join(''),
      `<tr class="tot"><td>Total</td><td class="num">${money(T('gross'))}</td>
        <td class="num">${money(T('advances'))}</td><td class="num">${money(T('paid'))}</td>
        <td class="num">${money(T('still_to_pay'))}</td></tr>`)}
    ${pay.some(p => p.overpaid) ? `<p class="note">“Ahead” means they have been given
      more than they have earned so far; it comes off their next salary.</p>` : ''}`);
}

export function partnersCard() {
  const prt = S.data.partners;
  if (!prt.length) return '';
  const dr = S.data.drawings;
  const basis = dr.basis === 'so far' ? 'so far this month' : 'this month';
  return card(`<h2>Partners</h2>
    <p class="sub">Taken out ${basis}: <strong>${money(dr.taken)}</strong>,
      against a profit ${basis} of <strong class="${cls(dr.profit)}">${money(dr.profit)}</strong>.
      ${dr.over ? `<br><span class="neg">That is ${money(dr.over)} more than the business has made.
        It is coming out of stock and supplier credit.</span>` : ''}</p>
    ${table(`<th>Partner</th><th class="num">Share</th>
             <th class="num">Share of profit${prt.some(p => p.so_far) ? ' so far' : ''}</th>
             <th class="num">Taken</th><th class="num">Put in</th><th class="num">Balance</th>`,
      prt.map(p => `<tr>
        <td>${esc(p.name)}</td>
        <td class="num">${(p.share * 100).toFixed(0)}%</td>
        <td class="num ${cls(p.profit)}">${money(p.profit)}</td>
        <td class="num">${money(p.taken)}</td>
        <td class="num">${money(p.put_in)}</td>
        <td class="num ${cls(p.balance)}">${money(p.balance)}${p.posted ? '' : ' <span class="quiet">before this month’s share</span>'}</td>
      </tr>`).join(''))}
    <p class="note">A share is added to the balance when the month is closed.</p>`);
}

export function suppliersCard() {
  const sup = S.data.suppliers;
  const total = sup.reduce((a, s) => a + Math.max(s.owed_now, 0), 0);
  const open = S.statement;
  return card(`<div class="cardhead"><h2>Suppliers</h2>
      <span class="pill">${money(S.data.owed)} owed</span>
      <div class="right"><button class="btn" data-act="printSuppliers">Print</button></div>
    </div>
    <p class="sub">A debt list, not an expense: the goods are already in the cost
      of goods, so paying a supplier does not change profit. Tap a name for the account.</p>
    ${sup.length ? table(
      `<th>Supplier</th><th class="num">Owed coming in</th><th class="num">Arrived</th>
       <th class="num">Paid</th><th class="num">Owed at the end</th><th style="width:110px"></th>`,
      sup.map(s => `<tr>
        <td><button class="mini link" data-act="statement" data-id="${s.id}">${esc(s.name)}</button></td>
        <td class="num">${money(s.brought_forward)}</td>
        <td class="num">${money(s.received)}</td>
        <td class="num">${money(s.paid)}</td>
        <td class="num ${s.closing > 0 ? 'neg' : ''}">${money(s.closing)}</td>
        <td><div class="bar"><span style="width:${total ? Math.max(0, s.owed_now) / total * 100 : 0}%"></span></div></td>
      </tr>${open && open.id === s.id ? statementRow(open) : ''}`).join(''))
      : empty('No supplier movement.')}`);
}

function statementRow(st) {
  return `<tr class="drill"><td colspan="6">
    <div class="cardhead"><strong>${esc(st.name)} — ${esc(monthName(st.month))}</strong>
      <div class="right"><button class="btn" data-act="printStatement">Print</button>
      <button class="mini" data-act="closeStatement">Close</button></div></div>
    ${table('<th>Date</th><th>What</th><th class="num">Amount</th><th class="num">Owed after</th>',
      (() => {
        let run = st.opening;
        return `<tr><td></td><td class="quiet">Owed coming in</td><td></td><td class="num">${money(run)}</td></tr>`
          + st.lines.map(l => { run += l.amount; return `<tr><td>${esc(l.on)}</td><td>${esc(l.what)}</td>
              <td class="num">${signed(l.amount)}</td><td class="num">${money(run)}</td></tr>`; }).join('');
      })(),
      `<tr class="tot"><td></td><td>Owed at the end of the month</td><td></td><td class="num">${money(st.closing)}</td></tr>`)}
    <p class="note">${money(st.received)} arrived and ${money(st.paid)} was paid this month.
      ${st.on_shelves ? ` Of what is owed, ${money(st.on_shelves)} worth of their goods
        was still on the shelves at the count on ${esc(st.count_date)}.` : ''}
      ${st.owed_now !== st.closing ? ` Owed today: ${money(st.owed_now)}.` : ''}</p>
  </td></tr>`;
}

export function moneyFlow() {
  const f = S.data.flow;
  if (!f.out.length && !f.in.length) return '';
  const group = (g, total) => `<details class="flow">
      <summary><span>${esc(g.label)}</span>
        <span class="track"><span class="fill" style="width:${total ? g.total / total * 100 : 0}%"></span></span>
        <span class="num">${money(g.total)}</span></summary>
      ${table('<th>Who or what</th><th class="num">Amount</th>',
        g.rows.map(([n, v]) => `<tr><td>${esc(n)}</td><td class="num">${money(v)}</td></tr>`).join(''))}
    </details>`;
  return card(`<h2>Where the cash went</h2>
    <p class="sub">Cash that physically left or came into a pot between
      ${esc(f.from)} and ${esc(f.to)}, by what it was for. Moving money between your
      own pots is left out. Open a line for the detail.</p>
    <h3 class="flowh">Out — ${money(f.out_total)}</h3>
    ${f.out.map(g => group(g, f.out_total)).join('')}
    <h3 class="flowh">In — ${money(f.in_total)}</h3>
    ${f.in.map(g => group(g, f.in_total)).join('')}`);
}

export function salesByDay() {
  const rows = S.data.sales_by_day;
  if (!rows.length) return '';
  const max = Math.max(...rows.map(r => r[1]));
  const avg = rows.reduce((a, r) => a + r[1], 0) / rows.length;
  const day = d => new Date(d + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short' });
  return card(`<h2>Sales by night</h2>
    <p class="sub">${rows.length} nights, ${money(avg)} on average.</p>
    ${table('<th>Night</th><th></th><th class="num">Sales</th>',
      rows.map(([d, v]) => `<tr><td class="nowrap">${esc(d)} <span class="quiet">${day(d)}</span></td>
        <td style="width:55%"><div class="bar"><span style="width:${max ? v / max * 100 : 0}%"></span></div></td>
        <td class="num">${money(v)}</td></tr>`).join(''))}`);
}

export function closeCard() {
  const per = S.data.period;
  if (per.status === 'closed') {
    return card(`<div class="row">
      <div><strong>Closed ${esc(String(per.closed_at || '').slice(0, 10))}</strong>
        <p class="sub" style="margin:2px 0 0">Stock counted ${esc(per.count_date || '—')}.
          Nothing in Setup can move these figures now.</p></div>
      <button class="btn" style="margin-left:auto" data-act="reopen">Reopen</button>
    </div>`);
  }
  if (S.data.month === S.data.this_month) return '';
  return card(`<div class="row">
      <div><strong>Close ${esc(monthName(S.data.month))}</strong>
        <p class="sub" style="margin:2px 0 0">Freezes the result, posts the cost of
          goods, splits the profit between the partners, and carries the stock into
          the next month.</p></div>
      <button class="btn primary" style="margin-left:auto" data-act="closeAsk">Close the month</button>
    </div>`);
}

export function everyMonth() {
  const rows = (S.data.summary || []).slice().reverse();
  if (rows.length < 2) return '';
  return card(`<h2>Every month</h2>
    ${table(`<th>Month</th><th class="num">Net profit</th><th></th>`,
      rows.map(r => `<tr>
        <td><button class="mini link" data-act="setMonth" data-m="${esc(r.month)}">${esc(monthName(r.month))}</button></td>
        <td class="num ${cls(r.net)}">${money(r.net)}</td>
        <td>${r.status === 'closed' ? '<span class="pill">closed</span>'
              : r.month === S.data.this_month ? '<span class="pill">in progress</span>'
              : '<span class="pill warn">not closed</span>'}</td>
      </tr>`).join(''))}`);
}

/* =================================================================== stock */

export function stockFigures() {
  const c = S.data.stock.cogs;
  return tiles([
    tile('Stock on the shelves', money(c.closing), c.date ? 'counted ' + c.date : 'no count'),
    tile('Stock at the start', money(c.opening), c.opening_date ? 'counted ' + c.opening_date : ''),
    tile('Bought', money(c.purchases), 'supplier receipts in the window'),
    tile('Cost of goods sold', money(c.value), 'start + bought − left', c.raw < 0 ? 'warnc' : ''),
  ]) + (c.raw < 0 ? `<div class="banner"><h2>The cost of goods came out negative</h2>
      <p style="margin:0">It works out at ${money(c.raw)}, which would mean the month
      ended with more stock than it started with plus everything bought. Either a
      delivery was never written down, or this count is setting the opening
      position rather than measuring a month.</p></div>` : '');
}

/* Filling a bucket: packs of sealed tobacco into one of the mixes. Nothing
   is saved until "Fill it"; the figures work themselves out as packs are
   typed or scanned. */
export function fillCard() {
  const st = S.data.stock;
  if (!st.mixes.length) return '';
  const f = S.draft.fill || {};
  const mix = st.mixes.find(m => m.id === f.mix);
  const items = Object.fromEntries(S.data.setup.items.map(i => [i.id, i]));
  const head = `<div class="cardhead"><h2>Fill a bucket</h2>
      <div class="right row"><select data-act="fillMix" style="width:auto">
        <option value="">Which mix?</option>
        ${options(st.mixes.map(m => ({ value: m.id, label: m.name })), f.mix)}</select></div></div>`;
  const recent = fillsList(st.fills);
  if (!mix) {
    return card(`${head}<p class="sub">Packs of tobacco into one of the mixes. No money
      moves: the packs come off their tobacco and go into the bucket at what they cost,
      and the mix’s price follows.</p>${recent}`);
  }
  const loose = it => ((it.levels || []).find(l => l.key === 'loose') || {}).label || '';
  const rows = (f.order || []).filter(id => items[id]).map(id => {
    const it = items[id];
    return `<tr data-fill="${id}"${S.draft.found === id ? ' class="found"' : ''}>
      <td>${esc(it.name)}<br><span class="quiet">${money(it.cost)} / kg</span></td>
      <td class="num"><input type="number" min="0" step="1" id="fill-${id}" data-fillpack="${id}"
          value="${esc(f.packs[id] ?? '')}" placeholder="0" inputmode="decimal">
        <span class="size">packs of ${esc(loose(it))}</span></td>
      <td class="num quiet" data-fillgrams="${id}"></td>
      <td class="num" data-fillvalue="${id}"></td>
      <td class="actions"><button class="mini" data-act="fillDrop" data-id="${id}" title="Leave it out">✕</button></td>
    </tr>`;
  }).join('');
  const sealed = S.data.setup.items.filter(i => i.letter === 'B' && i.active);
  return card(`${head}
    <p class="sub">${mix.usual.length ? `The usual for ${esc(mix.name)} is filled in; change any
      figure, or scan the packs as they go in.` : `No usual batch for ${esc(mix.name)} yet: add what
      goes in, or scan the packs as they go in, and keep it as the usual.`}
      Its price is ${money(mix.price)} a kilo.</p>
    ${rows ? table(`<th>Tobacco</th><th class="num">Packs</th><th class="num">Grams</th>
        <th class="num">Cost</th><th></th>`, rows,
        `<tr class="tot"><td>Into the bucket</td><td></td><td class="num" id="fillGrams"></td>
          <td class="num" id="fillValue"></td><td></td></tr>`) : ''}
    <div class="row" style="margin-top:10px">
      <input id="fillItem" list="sealedNames" placeholder="Tobacco or barcode" autocomplete="off"
        spellcheck="false" style="max-width:280px">
      <button class="btn" data-act="fillAdd">Add</button>
      ${mix.usual.length ? '<button class="mini" data-act="fillUsual">Back to the usual</button>' : ''}
    </div>
    <datalist id="sealedNames">${sealed.map(i => `<option value="${esc(i.name)}">`).join('')}</datalist>
    <div class="grid-form" style="margin-top:12px">
      ${field('Filled on', `<input type="date" id="fillOn" value="${esc(f.on || S.data.today)}" max="${esc(S.data.today)}">`)}
      ${field('Full bucket on the scales (g), if weighed', `<input type="number" min="0" id="fillGross"
          placeholder="not weighed" inputmode="numeric">`)}
      ${field('Bucket', `<select id="fillTare"><option value="">no bucket</option>
          ${options(S.data.stock.count.tares.map(t => ({ value: t.id, label: `${t.name} (${t.grams}g)` })))}</select>`)}
    </div>
    <label class="tick"><input type="checkbox" id="fillKeep"${mix.usual.length ? '' : ' checked'}>
      Keep this as the usual for ${esc(mix.name)}</label>
    <div class="row" style="margin-top:12px">
      <button class="btn primary" data-act="fillBucket">Fill it</button>
      <button class="btn" data-act="fillCancel">Cancel</button>
      <span class="quiet" id="fillPrice"></span>
    </div>
    ${recent}`);
}

function fillsList(fills) {
  if (!fills.length) return '';
  const rows = fills.map(f => `<tr>
      <td class="nowrap">${esc(f.filled_on)}</td>
      <td>${esc(f.mix)}<br><span class="quiet">${esc(f.lines.map(l =>
        `${+(l.packs_milli / 1000).toFixed(3)} × ${l.name}`).join(', '))}</span></td>
      <td class="num">${f.grams.toLocaleString('en-US')} g</td>
      <td class="num">${money(Math.round(f.value * 1000 / f.grams))}</td>
      <td class="num quiet">${money(f.price_before)} → ${money(f.price_after)}</td>
      <td class="actions">${f.locked ? '' : `<button class="mini danger" data-act="deleteFill"
          data-id="${f.id}">Delete</button>`}</td>
    </tr>`).join('');
  return `<details class="fold"><summary>Recent fills (${fills.length})</summary>
    ${table(`<th>Date</th><th>Mix</th><th class="num">Went in</th><th class="num">Cost a kilo</th>
      <th class="num">Mix price</th><th></th>`, rows)}</details>`;
}

export function countPicker() {
  const s = S.data.stock;
  const c = s.count;
  return card(`<div class="cardhead">
      <h2>Stock count</h2>
      ${c.locked ? '<span class="pill">locked — closed month</span>' : ''}
      <div class="right row">
        <select data-act="setCount" style="width:auto">
          ${options(s.count_dates.slice().reverse(), s.count_date)}
        </select>
        <input type="date" id="newCount" value="${esc(S.data.today)}" max="${esc(S.data.today)}" style="width:auto">
        <button class="btn" data-act="openCount">Start a count</button>
        ${c.locked || !c.date ? '' : `<button class="mini danger" data-act="deleteCount">Delete this count</button>`}
      </div>
    </div>
    <p class="sub">${c.locked
      ? 'This count is what a closed month was built on, so it is locked along with the prices it was valued at.'
      : c.source === 'carried'
        ? 'This figure was carried in from the Excel workbook, not counted item by item.'
        : 'Weigh the bucket and the tare comes off. Sealed tobacco is counted in the boxes it comes in, each size said under its box, and converts to kilos. Everything else is whole packages plus loose pieces. Each box saves as you leave it. Scanning a barcode goes straight to its item.'}
      ${c.date ? ` <strong>Valued at ${money(c.closing)}.</strong>` : ''}</p>`);
}

export function countSheet() {
  const c = S.data.stock.count;
  if (!c.date) return '';
  if (c.source === 'carried' && !c.groups.some(g => g.items.some(i => i.value))) return '';
  const ro = c.locked ? ' disabled' : '';
  const box = (k, v, step = '0.1') => `<input type="number" step="${step}" min="0" data-k="${k}"
      value="${v ? v / 1000 : ''}" placeholder="0"${ro} inputmode="decimal">`;
  // sealed tobacco: each box the size it comes in, said under it
  const sizes = i => ['packages', 'blocks', 'loose'].map(k => {
    const l = (i.levels || []).find(x => x.key === k);
    const v = i[`${k}_milli`];
    return l || v ? `<td class="num">${box(k, v)}${l ? `<span class="size">${esc(l.label)}</span>` : ''}</td>`
                  : '<td></td>';
  }).join('');
  const body = c.groups.map(g => {
    const weighed = g.letter === 'A';
    const sealed = g.letter === 'B';
    const head = weighed
      ? `<th>Item</th><th>Bucket</th><th class="num">On the scales (g)</th><th class="num">Net</th><th class="num">Value</th>`
      : sealed
        ? `<th>Item</th><th class="num">Cartons</th><th class="num">Blocks</th><th class="num">Packs</th><th class="num">Kilos</th><th class="num">Value</th>`
        : `<th>Item</th><th class="num">Packages</th><th class="num">Loose</th><th class="num">Comes to</th><th class="num">Value</th>`;
    const cols = sealed ? 6 : 5;
    let brand = null;
    const rows = g.items.map(i => {
      const under = i.parent_id && i.parent_id === brand;
      if (!i.parent_id) brand = i.id;
      const price = `<span class="quiet">${money(i.counted_at)} / ${esc(i.unit)}</span>`;
      // a brand counted by flavour is only their heading, unless this count has it
      if (i.flavours && i.qty_milli == null) {
        return `<tr class="brandh"><td colspan="${cols}"><strong>${esc(i.name)}</strong> ${price}</td></tr>`;
      }
      const q = (i.qty_milli || 0) / 1000;
      const unit = weighed || sealed ? 'kg' : '';
      return `<tr data-item="${i.id}" class="${[i.active ? '' : 'quiet', under ? 'flavour' : '',
                                                  S.draft.found === i.id ? 'found' : ''].join(' ').trim()}">
        <td>${esc(under ? i.flavour : i.name)}<br>${price}</td>
        ${weighed
          ? `<td><select data-k="tare_id"${ro} style="min-width:110px">
               <option value="">no bucket</option>
               ${options(c.tares.map(t => ({ value: t.id, label: `${t.name} (${t.grams}g)` })), i.tare_id)}</select></td>
             <td class="num"><input type="number" min="0" data-k="gross_grams" value="${i.gross_grams ?? ''}"
                  placeholder="0"${ro} inputmode="numeric"></td>`
          : sealed
            ? sizes(i)
            : `<td class="num">${box('packages', i.packages_milli)}</td>
               <td class="num">${box('loose', i.loose_milli)}</td>`}
        <td class="num quiet">${q ? q.toFixed(3).replace(/\.?0+$/, '') + (unit ? ' ' + unit : '') : ''}</td>
        <td class="num">${i.value ? money(i.value) : ''}</td>
      </tr>`;
    }).join('');
    return `<h3 class="grouph">${esc(g.name)}</h3>
      ${table(head, rows, `<tr class="tot"><td>Total</td>
        <td colspan="${cols - 2}"></td><td class="num">${money(g.value)}</td></tr>`)}`;
  }).join('');
  return card(`<h2>Count for ${esc(c.date)}</h2>
    <p class="sub">Quantities only — prices and pack sizes come from Setup.
      A count keeps the prices it was taken at.</p>
    ${body}
    <p class="sub" style="margin-top:14px"><strong>Counted value ${money(c.closing)}</strong>,
      rounded to the note.</p>`);
}

export function receiptForm() {
  const sup = S.data.people.supplier.filter(s => s.active);
  return card(`<h2>New receipt</h2>
    <p class="sub">The total is what moves money. Then list what came in, so the
      stock can follow it — that part can wait.</p>
    <div class="grid-form">
      ${field('Date', `<input type="date" id="rDate" value="${esc(S.data.today)}" max="${esc(S.data.today)}">`)}
      ${field('Supplier', `<select id="rSup">${options(sup.map(s => s.name))}</select>`)}
      ${field('Receipt no.', '<input id="rNo" placeholder="optional">')}
      ${field('For', '<input id="rWhat" placeholder="Several items">')}
      ${field('Total', amountInput('rAmt'))}
      ${field('Terms', `<select id="rTerms"><option value="credit">On credit</option>
                        <option value="cash">Paid cash</option></select>`)}
      ${field('Paid from', `<select id="rPot">${potOptions()}</select>`)}
      <div><button class="btn primary" data-act="receipt">Add</button></div>
    </div>`);
}

export function receiptList() {
  const rows = S.data.stock.receipts;
  const now = rows.filter(r => r.period === S.data.month);
  const older = rows.filter(r => r.period !== S.data.month);
  const open = S.draft.rlines;
  const isOpen = e => e.receipt && e.receipt.id === open;
  const list = rs => table(`<th>Date</th><th>What</th><th>Details</th><th>Pot</th>
      <th class="num">Amount</th><th></th>`,
    rs.map(e => entryRow(e, { lines: true }) + (isOpen(e) ? linesRow(e) : '')).join(''));
  const names = S.data.setup.items.filter(i => i.active && i.letter !== 'A');
  return card(`<h2>Receipts in ${esc(monthName(S.data.month))}</h2>
    ${now.length ? list(now) : empty('No receipts this month.')}
    ${older.length ? `<details class="fold"${older.some(isOpen) ? ' open' : ''}>
      <summary>Every other receipt (${older.length})</summary>${list(older)}</details>` : ''}
    <datalist id="stockNames">${names.map(i => `<option value="${esc(i.name)}">`).join('')}</datalist>`);
}

/* What came in on one receipt: a line per item, in the boxes it comes in,
   saved as you leave it, like the count sheet. */
function linesRow(e) {
  const rid = e.receipt.id;
  const closed = new Set((S.data.summary || []).filter(r => r.status === 'closed').map(r => r.month));
  const ro = closed.has(e.period) ? ' disabled' : '';
  const saved = e.lines;
  const pending = ((S.draft.rpending || {})[rid] || [])
    .filter(id => !saved.some(l => l.item === id))
    .map(id => S.data.setup.items.find(i => i.id === id)).filter(Boolean)
    .map(i => ({ item: i.id, name: i.name, letter: i.letter, levels: i.levels, pending: true }));
  const unit = l => (l.letter === 'B' ? ['kg', 'kg'] : l.letter === 'E' ? ['cartons', 'carton']
    : l.levels.length > 1 ? ['packages', 'package'] : ['pieces', 'piece']);
  const sizes = l => {
    const keys = l.levels.map(x => x.key);
    const extra = ['packages', 'blocks', 'loose'].filter(k => !keys.includes(k) && l[`${k}_milli`]);
    return `<div class="sizes">${[...l.levels, ...extra.map(k => ({ key: k, label: '' }))].map(x => {
      const v = l[`${x.key}_milli`];
      return `<label class="sizebox"><input type="number" step="0.1" min="0" data-k="${x.key}"
          value="${v ? v / 1000 : ''}" placeholder="0" inputmode="decimal"${ro}>
        <span class="size">${esc(x.label)}</span></label>`;
    }).join('')}</div>`;
  };
  const row = l => {
    const q = (l.qty_milli || 0) / 1000;
    const [many, one] = unit(l);
    return `<tr data-item="${l.item}" data-receipt="${rid}">
      <td>${esc(l.name)}</td>
      <td>${sizes(l)}</td>
      <td class="num quiet">${q ? `${+q.toFixed(3)} ${many}` : ''}
        ${q && l.amount ? `<br>${money(Math.round(l.amount / q))} / ${one}` : ''}</td>
      <td class="num"><input type="number" min="0" data-k="amount" value="${l.amount ?? ''}"
          placeholder="—" inputmode="numeric"${ro}></td>
      <td class="actions">${ro ? '' : l.pending
        ? `<button class="mini" data-act="dropRLine" data-id="${l.item}" title="Leave it out">✕</button>`
        : `<button class="mini" data-do="receipt_line" data-args="${args({ receipt: rid, item: l.item })}"
             title="Take this line off">✕</button>`}</td>
    </tr>`;
  };
  const priced = saved.filter(l => l.amount != null);
  const sum = priced.reduce((a, l) => a + l.amount, 0);
  const note = !saved.length
    ? 'Nothing listed yet. Only the total moves money; the lines are what came onto the shelves.'
    : priced.length < saved.length
      ? `${saved.length - priced.length} of ${saved.length} lines have no amount${priced.length
          ? `; the others come to ${money(sum)} of the receipt’s ${money(e.amount)}` : ''}.`
      : sum === e.amount
        ? `The lines come to ${money(sum)}, the receipt’s total.`
        : `The lines come to ${money(sum)}, ${money(Math.abs(e.amount - sum))}
           ${sum < e.amount ? 'less' : 'more'} than the receipt’s ${money(e.amount)}.`;
  return `<tr class="drill"><td colspan="6">
    <div class="cardhead"><strong>What came in</strong>
      <span class="quiet">${esc(e.detail || '')} · ${esc(e.happened_on)}</span>
      <div class="right"><button class="mini" data-act="receiptLines" data-id="${rid}">Close</button></div></div>
    ${saved.length || pending.length ? table(`<th>Item</th><th>How many</th><th class="num">Comes to</th>
        <th class="num">Amount</th><th></th>`, [...saved, ...pending].map(row).join('')) : ''}
    ${ro ? '' : `<div class="row" style="margin-top:10px">
      <input id="rlItem" list="stockNames" placeholder="Item or barcode" autocomplete="off"
        spellcheck="false" style="max-width:300px">
      <button class="btn" data-act="addRLine">Add</button></div>`}
    <p class="note">${note}</p>
  </td></tr>`;
}

export function countHistory() {
  const rows = S.data.stock.counts;
  return card(`<h2>Stock counts</h2>
    ${rows.length ? table(
      `<th>Count date</th><th class="num">Valued at</th><th>Where it came from</th>`,
      rows.map(r => `<tr><td>${esc(r.count_date)}</td>
        <td class="num">${money(r.closing)}</td>
        <td class="quiet">${r.source === 'counted' ? 'counted item by item' : 'carried in from the workbook'}</td></tr>`).join(''))
      : empty('No counts yet.')}`);
}

/* =================================================================== books */

const ENTRY_KINDS = [
  { value: 'expense', label: 'Daily expense' },
  { value: 'staff_advance', label: 'Staff advance' },
  { value: 'staff_repay', label: 'Staff paid money back' },
  { value: 'pay_salary', label: 'Salary payment' },
  { value: 'partner_draw', label: 'Partner took cash' },
  { value: 'partner_in', label: 'Partner put cash in' },
  { value: 'pay_supplier', label: 'Supplier payment' },
  { value: 'pay_fixed', label: 'Rent or monthly charge paid' },
  { value: 'pay_electricity', label: 'Electricity paid' },
  { value: 'income', label: 'Other income' },
  { value: 'transfer', label: 'Move between pots' },
];

export function newEntryCard() {
  const lists = S.data.lists;
  const people = S.data.people;
  const kind = S.draft.kind || 'expense';
  const active = list => list.filter(a => a.active).map(a => a.name);
  const detailsFor = {
    expense: lists.expense || [], income: lists.income || [],
    staff_advance: active(people.staff), staff_repay: active(people.staff),
    pay_salary: active(people.staff), pay_supplier: active(people.supplier),
    partner_draw: active(people.partner), partner_in: active(people.partner),
    pay_fixed: S.data.fixed_names || [],
  };
  const isTransfer = kind === 'transfer';
  const into = ['income', 'staff_repay', 'partner_in'].includes(kind);
  const closed = new Set((S.data.summary || []).filter(r => r.status === 'closed').map(r => r.month));
  const months = S.data.months.filter(m => m <= S.data.this_month && !closed.has(m));
  return card(`<h2>New entry</h2>
    <p class="sub">${isTransfer
      ? 'A transfer moves money between your pots. It never touches profit.'
      : 'For anything that is not part of closing up.'}</p>
    <div class="grid-form">
      ${field('Date', `<input type="date" id="eDate" value="${esc(S.data.today)}" max="${esc(S.data.today)}">`)}
      ${field('What', `<select id="eKind" data-act="pickKind">${options(ENTRY_KINDS, kind)}</select>`)}
      ${isTransfer
        ? field('From', `<select id="eFrom">${potOptions()}</select>`)
          + field('To', `<select id="eTo">${options(S.data.pots.filter(p => p.active).map(p => p.name),
              (S.data.pots.find(p => p.active && !p.main) || {}).name)}</select>`)
        : (detailsFor[kind] ? field('Who or what', `<select id="eDetail">${options(detailsFor[kind])}</select>`) : '')
          + field(into ? 'Into' : 'Out of', `<select id="ePot">${potOptions()}</select>`)}
      ${field('Amount', amountInput('eAmt'))}
      <div><button class="btn primary" data-act="addEntry">Add entry</button></div>
    </div>
    <details class="fold"><summary>Counts for another month</summary>
      <div class="row" style="margin-top:8px">
        <select id="ePeriod" style="max-width:200px">
          <option value="">the month of its date</option>
          ${options(months.slice().reverse().map(m => ({ value: m, label: monthName(m) })))}</select>
        <span class="quiet">Only when paying an older month's salary, rent or electricity.
          Settle up on Month does this for you.</span>
      </div>
    </details>`);
}

export function entryList() {
  const sr = S.search;
  const rows = sr ? sr.rows : S.data.entries;
  return card(`<div class="cardhead">
      <h2>${sr ? `Found ${sr.rows.length}${sr.rows.length >= 300 ? '+' : ''}` : esc(monthName(S.data.month))}</h2>
      ${sr ? '' : `<span class="pill">${rows.length} entr${rows.length === 1 ? 'y' : 'ies'}</span>`}
      <div class="right row">
        <input id="q" placeholder="Search every month: a name, an amount, a date" value="${esc(sr ? sr.q : '')}"
          style="width:300px">
        <button class="btn" data-act="search">Search</button>
        ${sr ? '<button class="mini" data-act="clearSearch">Back to the month</button>' : ''}
      </div>
    </div>
    ${rows.length ? entryTable(rows)
      : empty(sr ? 'Nothing matches.' : `Nothing recorded for ${monthName(S.data.month)}.`)}`);
}

export function recentChanges() {
  const rows = S.data.recent;
  if (!rows.length) return '';
  return card(`<h2>Recent changes</h2>
    <p class="sub">Everything done to the books lately, newest first. A deletion
      can be put back while its month is open.</p>
    ${table('<th>When</th><th>What happened</th><th></th>',
      rows.slice(0, 25).map(r => `<tr><td class="nowrap quiet">${esc(localTime(r.at))}</td>
        <td>${esc(r.summary)}</td>
        <td>${r.can_put_back ? `<button class="mini" data-act="putBack" data-id="${r.entry}">Put back</button>` : ''}</td>
      </tr>`).join(''))}`);
}

export function whereMoneyIs() {
  const pots = S.data.pots.filter(p => p.active && (p.in_use || p.balance));
  const floats = S.data.people.float.length > 0;
  return card(`<h2>Where the money is</h2>
    <p class="sub">Your own pots are the business's cash.${floats
      ? ' A float is money someone is holding for the business — still yours, just not in your hand.' : ''}</p>
    <div class="potgrid">${pots.map(p => `
      <div class="pot${p.kind === 'float' ? ' isfloat' : ''}">
        <div class="nm">${esc(p.name)}${p.main ? ' <span class="pill">main</span>' : ''}</div>
        <div class="bal ${cls(p.balance)}">${money(p.balance)}</div>
        <div class="sub">${p.kind === 'float' ? 'held by this person' : 'your cash'}</div>
      </div>`).join('')}</div>
    ${tiles([
      tile('Cash on hand', money(S.data.cash), 'own pots only'),
      floats ? tile("In people's hands", money(S.data.floats), 'floats') : '',
      floats ? tile('Total', money(S.data.cash + S.data.floats)) : '',
    ])}`);
}

export function cashCountsCard() {
  const rows = S.data.counts.slice().reverse();
  const open = rows.filter(r => r.diff !== 0);
  const head = `<th>Date</th><th class="num">Books said</th><th class="num">Counted</th>
       <th class="num">Out by</th><th>Where</th><th>Reason</th><th></th>`;
  const row = r => `<tr>
        <td class="nowrap">${esc(r.on)}</td>
        <td class="num">${money(r.expected)}</td>
        <td class="num">${money(r.counted)}</td>
        <td class="num ${r.found ? cls(r.found) : ''}">${r.found ? signed(r.found) : '—'}
          ${r.written_off ? `<br><span class="quiet">written off</span>` : ''}</td>
        <td class="quiet">${r.split
          ? esc(r.pots.filter(p => p.found).map(p => p.name + ' ' + signed(p.found)).join(', ') || 'all tie')
          : esc(r.pots.map(p => p.name).join(', '))}</td>
        <td class="quiet">${esc(r.reason || '')}</td>
        <td class="actions">
          ${r.diff ? `<button class="mini" data-act="writeOff" data-id="${r.id}">Write off</button>` : ''}
          ${r.written_off ? '' : `<button class="mini danger" data-act="deleteCashCount" data-id="${r.id}">Delete</button>`}
        </td>
      </tr>`;
  // anything that does not tie stays in view however old it is
  const recent = rows.filter((r, i) => i < 14 || r.diff !== 0);
  const older = rows.filter((r, i) => i >= 14 && r.diff === 0);
  return card(`<h2>Cash counts</h2>
    <p class="sub">Counting is done on Tonight; this is the history.
      ${open.length ? `<strong class="warnc">${open.length} of the last ${rows.length} do not tie.</strong>
        Find the missing entry if there is one; if the money really is gone, write it off,
        and it becomes a cost of that month instead of a hole in every count after it.`
        : `Every one of the last ${rows.length} ties.`}</p>
    ${rows.length ? table(head, recent.map(row).join('')) : empty('No counts yet.')}
    ${older.length ? `<details class="fold"><summary>Older counts (${older.length}), all tied</summary>
      ${table(head, older.map(row).join(''))}</details>` : ''}`);
}

/* =================================================================== setup */

const save = (action, a, fieldName, value, extra = '') =>
  `<input data-save="${action}" data-args="${args(a)}" data-field="${fieldName}"
     value="${esc(value ?? '')}" ${extra}>`;

const addRow = (action, fixed, fields, button = 'Add') =>
  `<div class="row addrow" style="margin-top:12px">
     ${fields.map(([f, placeholder, type, width]) =>
       `<input data-f="${f}" placeholder="${esc(placeholder)}" type="${type || 'text'}"
          style="max-width:${width || 200}px" ${type === 'number' ? 'min="0" inputmode="decimal"' : ''}>`).join('')}
     <button class="btn" data-add="${action}" data-args="${args(fixed)}">${button}</button>
   </div>`;

export function editAccounts(kind, title, note) {
  const list = S.data.people[kind] || [];
  const live = list.filter(a => a.active);
  const gone = list.filter(a => !a.active);
  const sal = S.data.setup.salaries;
  const extraHead = kind === 'staff' ? '<th class="num">Salary a month</th>'
    : kind === 'partner' ? '<th class="num">Share %</th>' : '';
  const balHead = { staff: 'Owed to them', supplier: 'Owed to them', partner: 'Balance',
                    cash: 'Holds', float: 'Holds' }[kind] || 'Balance';
  const bal = a => {
    if (kind === 'staff' && a.balance < 0) return `<span class="warnc">${money(-a.balance)} ahead</span>`;
    if (kind === 'supplier' && a.balance < 0) return `<span class="warnc">${money(-a.balance)} in credit</span>`;
    return `<span class="${a.balance < 0 ? 'neg' : ''}">${money(a.balance)}</span>`;
  };
  const row = a => `<tr>
      <td>${save('account_rename', { id: a.id }, 'name', a.name)}</td>
      ${kind === 'staff' ? `<td class="num">${save('set_salary', { id: a.id }, 'amount', sal[a.id] || '',
          `type="number" step="${S.data.note}" min="0" inputmode="numeric" style="max-width:140px"`)}</td>` : ''}
      ${kind === 'partner' ? `<td class="num">${save('set_share', { id: a.id }, 'share',
          Math.round((a.meta.share || 0) * 1000) / 10, 'type="number" step="1" min="0" max="100" style="max-width:90px"')}</td>` : ''}
      <td class="num">${bal(a)}</td>
      <td>${a.active
        ? `<button class="mini" data-do="account_active" data-args="${args({ id: a.id, active: 0 })}">
             ${kind === 'staff' ? 'Has left' : 'Retire'}</button>`
        : `<button class="mini" data-do="account_active" data-args="${args({ id: a.id, active: 1 })}">Bring back</button>`}</td>
    </tr>`;
  const fields = [['name', 'Name']];
  if (kind === 'staff') fields.push(['salary', 'Salary', 'number', 140]);
  if (kind === 'partner') fields.push(['share', 'Share %', 'number', 100]);
  const head = `<th>Name</th>${extraHead}<th class="num">${balHead}</th><th></th>`;
  const shares = kind === 'partner'
    ? Math.round(live.reduce((t, a) => t + (a.meta.share || 0), 0) * 1000) / 10 : 100;
  return card(`<h2>${esc(title)}</h2>${note ? `<p class="sub">${esc(note)}</p>` : ''}
    ${shares !== 100 ? `<p class="note warnc">The shares add up to ${shares}%, not 100%.
      A month closed like this would not hand out all of its profit.</p>` : ''}
    ${live.length ? table(head, live.map(row).join('')) : empty('None yet.')}
    ${gone.length ? `<details class="fold"><summary>Retired (${gone.length})</summary>
      ${table(head, gone.map(row).join(''))}</details>` : ''}
    ${addRow('account_add', { kind }, fields)}`);
}

export function floatsCard() {
  const list = S.data.people.float;
  if (list.length) return editAccounts('float', 'Floats', 'Money someone is holding for the business.');
  return card(`<details class="fold"><summary>Floats — money someone holds for the business (none)</summary>
    <p class="sub">A float is cash handed to someone to spend for the business — still
      yours, just not in your hand. Counted separately from cash on hand.</p>
    ${addRow('account_add', { kind: 'float' }, [['name', 'Who holds it']])}</details>`);
}

export function editFixed() {
  const rows = S.data.setup.fixed.filter(f => f.active).map(f => `<tr>
      <td>${esc(f.name)}</td>
      <td class="num">${save('fixed_set', { name: f.name }, 'amount', f.amount,
        `type="number" step="${S.data.note}" min="0" inputmode="numeric" style="max-width:150px"`)}</td>
      <td class="quiet">${f.from_month ? 'since ' + esc(monthName(f.from_month)) : ''}</td>
      <td><button class="mini" data-do="fixed_remove" data-args="${args({ name: f.name })}"
            data-confirm="Stop charging ${esc(f.name)}?"
            data-confirm-body="From ${esc(monthName(S.data.month))} on, ${esc(f.name)} is no longer charged. Months before keep what they were charged."
            data-yes="Stop charging">Stop charging</button></td>
    </tr>`).join('');
  return card(`<h2>Charged every month</h2>
    <p class="sub">Rent and anything else a month owes whether or not it has been
      paid. A change applies from ${esc(monthName(S.data.month))} on; earlier months
      keep what they were charged.</p>
    ${rows ? table('<th>What</th><th class="num">A month</th><th></th><th></th>', rows) : empty('Nothing.')}
    ${addRow('fixed_set', {}, [['name', 'What'], ['amount', 'Amount a month', 'number', 150]])}`);
}

export function editList(name, title, note) {
  const list = S.data.lists[name] || [];
  return card(`<h2>${esc(title)}</h2>${note ? `<p class="sub">${esc(note)}</p>` : ''}
    <div class="chips">${list.map(v => `<button data-do="list_remove" title="Remove"
        data-args="${args({ list: name, value: v })}">${esc(v)} ✕</button>`).join('')
        || '<span class="quiet">Nothing yet.</span>'}</div>
    ${addRow('list_add', { list: name }, [['value', 'Add one']])}`);
}

export function editItems() {
  const s = S.data.setup;
  const sups = S.data.people.supplier.map(a => ({ value: a.id, label: a.name }));
  const whole = 'type="number" min="0" inputmode="numeric"';
  const codes = i => `<div class="codes">${(i.barcodes || []).map(c => `<button class="mini"
        data-do="item_update" data-args="${args({ id: i.id, barcode_remove: c })}"
        title="Take this barcode off">${esc(c)} ✕</button>`).join('')}
      ${save('item_update', { id: i.id }, 'barcode_add', '',
        'placeholder="Scan or type" autocomplete="off" spellcheck="false" data-scan')}</div>`;
  const groups = s.categories.map(c => {
    const items = s.items.filter(i => i.letter === c.letter);
    if (!items.length) return '';
    const sealed = c.letter === 'B';
    const packs = !['A', 'B', 'E'].includes(c.letter);
    const unit = { A: 'kg', B: 'kg', E: 'cartons' }[c.letter] || 'packages';
    const byId = Object.fromEntries(items.map(i => [i.id, i]));
    const flavours = id => items.filter(f => f.parent_id === id && f.active).length;
    const rows = list => {
      let brand = null;                 // a flavour right under its brand says only its own name
      return list.map(i => {
        const under = i.parent_id && i.parent_id === brand;
        if (!i.parent_id) brand = i.id;
        const b = byId[i.parent_id];
        const u = { id: i.id };
        const n = flavours(i.id);
        return `<tr${under ? ' class="flavour"' : ''}>
          <td>${save('item_update', u, 'name', under ? i.flavour : i.name)}</td>
          <td class="num">${save('item_update', u, 'price', b && !i.price ? '' : i.price,
            `${whole} style="max-width:110px"${b ? ` placeholder="${esc(b.price)}"` : ''}`)}</td>
          ${sealed ? `<td>${save('item_update', u, 'packs', i.comes_as,
            `placeholder="${esc(i.comes_as_else)}" style="max-width:130px" spellcheck="false"`)}</td>` : ''}
          ${packs ? `<td class="num">${save('item_update', u, 'pack_size', i.pack_size || '',
            `${whole} style="max-width:90px"`)}</td>` : ''}
          <td class="num">${save('item_update', u, 'minimum', i.minimum ?? '',
            `type="number" min="0" step="0.1" inputmode="decimal" placeholder="${unit}" style="max-width:90px"`)}</td>
          <td>${codes(i)}</td>
          <td><select data-save="item_supplier" data-args="${args(u)}" data-field="supplier_id"
              style="min-width:140px">
            <option value="">${b ? 'as the brand' : '—'}</option>${options(sups, i.supplier_id)}</select></td>
          <td class="actions"><button class="mini" data-do="item_update" data-args="${args({ id: i.id, active: i.active ? 0 : 1 })}"
            ${i.active && n ? `data-confirm="${esc(`Stop stocking ${i.name} and its ${n} flavour${n === 1 ? '' : 's'}?`)}"
              data-yes="Stop stocking"` : ''}>
            ${i.active ? 'Stop stocking' : 'Bring back'}</button></td>
        </tr>`;
      }).join('');
    };
    const live = items.filter(i => i.active);
    const gone = items.filter(i => !i.active);
    const brands = live.filter(i => !i.parent_id).map(i => ({ value: i.id, label: i.name }));
    const head = `<th>Item</th><th class="num">Price</th>${sealed ? '<th>Comes as</th>' : ''}
      ${packs ? '<th class="num">Pieces a package</th>' : ''}<th class="num">Warn below</th>
      <th>Barcodes</th><th>From</th><th></th>`;
    return `<h3 class="grouph">${esc(c.name)}</h3>
      ${live.length ? table(head, rows(live)) : ''}
      ${sealed && brands.length ? `<div class="row addrow">
        <select data-f="brand" data-keep style="max-width:220px">${options(brands)}</select>
        <input data-f="name" placeholder="Flavour" style="max-width:200px">
        <button class="btn" data-add="item_add" data-args="{}">Add a flavour</button></div>` : ''}
      ${gone.length ? `<details class="fold"><summary>No longer stocked (${gone.length})</summary>
        ${table(head, rows(gone))}</details>` : ''}`;
  }).join('');
  return card(`<h2>Stock items</h2>
    <p class="sub">A new price values the next count; counts already taken keep the
      price they were counted at. “From” is the supplier, used on their statement.
      Sealed tobacco “comes as” the box says it: 12×10×50 g, 3×1 kg, 250 g.
      A flavour comes as its brand and costs what its brand does, unless it says otherwise.
      “Warn below” is for the shortage warnings to come.</p>
    ${groups}
    <div class="row addrow" style="margin-top:14px">
      <input data-f="name" placeholder="New item" style="max-width:200px">
      <select data-f="letter" style="max-width:220px">
        ${options(s.categories.map(c => ({ value: c.letter, label: c.name })))}</select>
      <input data-f="price" placeholder="Price" type="number" min="0" inputmode="numeric" style="max-width:120px">
      <input data-f="pack_size" placeholder="Pieces a package" type="number" min="0" inputmode="numeric" style="max-width:150px">
      <button class="btn" data-add="item_add" data-args="{}">Add</button>
    </div>`);
}

export function editTares() {
  const rows = S.data.setup.tares.map(t => `<tr><td>${esc(t.name)}</td>
      <td class="num">${save('tare_set', { id: t.id }, 'grams', t.grams,
        'type="number" min="0" inputmode="numeric" style="max-width:120px"')}</td></tr>`).join('');
  return card(`<h2>Buckets</h2>
    <p class="sub">What each empty bucket weighs, so it can come off the scales.</p>
    ${rows ? table('<th>Bucket</th><th class="num">Grams empty</th>', rows) : empty('None.')}
    ${addRow('tare_set', {}, [['name', 'Bucket name'], ['grams', 'Grams', 'number', 120]])}`);
}

export function editConversions() {
  const c = S.data.setup.conversions || {};
  const f = (key, label, def) => field(label, save('conversions_set', {}, key, c[key] ?? def,
    'type="number" min="1" inputmode="numeric"'));
  return card(`<details class="fold"><summary>How sealed tobacco and ice cream convert</summary>
    <p class="sub">Applies to lines counted from now on; lines already counted keep
      the quantity they had.</p>
    <div class="grid-form">
      ${f('gramsPerPack', 'Grams in a pack', 50)}
      ${f('packsPerBlock', 'Packs in a block', 10)}
      ${f('blocksPerCarton', 'Blocks in a carton', 12)}
      ${f('bucketsPerCarton', 'Ice cream buckets in a carton', 2)}
    </div></details>`);
}

export function editElecFactors() {
  const f = S.data.setup.elec_factors;
  const box = (key, label) => field(label, save('elec_factors_set', {}, key, f[key],
    'type="number" min="0" inputmode="numeric"'));
  return card(`<details class="fold"><summary>How the electricity bill is worked out</summary>
    <div class="grid-form">
      ${box('privateAmps', 'Private: amps the lounge takes')}
      ${box('elevatorAmps', 'Elevator: amps')}
      ${box('elevatorShare', 'Elevator: shops sharing it')}
      ${box('publicRate', 'Public: price per unit')}
      ${box('publicShare', 'Public: shops sharing the meter')}
    </div></details>`);
}

export function businessCard() {
  const b = S.data.business || {};
  return card(`<h2>The business</h2>
    <div class="grid-form">
      ${field('Name on slips', save('business_set', {}, 'name', b.name))}
      ${field('Smallest note (amounts round to it)', save('business_set', {}, 'note', b.note || S.data.note,
        'type="number" min="1" inputmode="numeric"'))}
    </div>`);
}

export function backupCard() {
  const b = S.data.backup;
  const last = b.last || {};
  const when = last.at ? last.at.replace('T', ' ') : 'never';
  return card(`<h2>Backups</h2>
    <p class="sub">A copy is made the first time the books are used each day and
      before anything risky. ${b.copies} cop${b.copies === 1 ? 'y is' : 'ies are'} on this PC.
      A copy on the same disk does nothing if the PC dies, so choose a second folder:
      a USB stick, or a folder Google Drive or OneDrive keeps in step.</p>
    <div class="grid-form">
      ${field('Second folder (the whole path)', save('backup_folder', {}, 'folder', b.second || '',
        'placeholder="for example G:\\My Drive\\Twilight" style="min-width:320px"'))}
      <div><button class="btn primary" data-act="backupNow">Back up now</button></div>
    </div>
    <p class="note">Last copy: ${esc(when)}${last.entries ? `, ${money(last.entries)} entries, checked` : ''}.
      ${b.second ? (b.second_ok ? `<span class="pos">Also copied to ${esc(b.second)}.</span>`
                                : `<span class="neg">Could not copy to ${esc(b.second)}${last.second_error ? ': ' + esc(last.second_error) : ''}.</span>`)
                 : '<span class="warnc">No second folder yet.</span>'}
      <br><span class="quiet">On this PC: ${esc(b.local_folder)}</span></p>`);
}

export function updateCard() {
  const u = S.draft.update;
  return card(`<h2>This app</h2>
    <p class="sub">Version ${esc(S.data.version)}. An update replaces the app and never
      the books: they are copied aside first, and the old version is kept so it can
      be put back.</p>
    <div class="row">
      <button class="btn" data-act="checkUpdate">Check for updates</button>
      ${u && u.newer ? `<button class="btn primary" data-act="installUpdate">Install ${esc(u.latest)}</button>` : ''}
      <button class="btn" data-act="health">Check the books</button>
    </div>
    ${u ? `<p class="note">${u.error ? `<span class="neg">${esc(u.error)}</span>`
      : u.newer ? `Version ${esc(u.latest)} is available.` : 'This is the newest version.'}</p>` : ''}`);
}

/* ================================================================ sambapos */

function soldTable(items, limit = 0) {
  const groups = new Map();
  for (const it of items) {
    if (!groups.has(it.group)) groups.set(it.group, []);
    groups.get(it.group).push(it);
  }
  const qty = q => (Number.isInteger(q) ? String(q) : q.toFixed(2).replace(/\.?0+$/, ''));
  const row = it => `<tr><td><bdi>${esc(it.item)}</bdi>${it.portion && it.portion !== 'Normal'
      ? ` <span class="quiet"><bdi>${esc(it.portion)}</bdi></span>` : ''}</td>
    <td class="num">${qty(it.qty)}${it.free ? ` <span class="quiet">+${qty(it.free)} free</span>` : ''}</td>
    <td class="num">${money(it.value)}</td></tr>`;
  const head = '<th>Item</th><th class="num">How many</th><th class="num">Came to</th>';
  const blocks = [...groups.entries()]
    .map(([g, list]) => [g, list, list.reduce((t, i) => t + i.value, 0)])
    .sort((a, b) => b[2] - a[2])
    .map(([g, list, total]) => {
      const shown = limit ? list.slice(0, limit) : list;
      const rest = list.slice(shown.length);
      return `<h3 class="grouph"><bdi>${esc(g || 'Other')}</bdi>
          <span class="quiet">· ${money(total)}</span></h3>
        ${table(head, shown.map(row).join(''))}
        ${rest.length ? `<details class="fold"><summary>${rest.length} more</summary>
          ${table(head, rest.map(row).join(''))}</details>` : ''}`;
    });
  // the biggest groups open, the rest folded away
  return blocks.slice(0, 3).join('') + (blocks.length > 3
    ? `<details class="fold"><summary>${blocks.length - 3} more groups</summary>
         ${blocks.slice(3).join('')}</details>` : '');
}

/** What sold on the night on screen, as SambaPOS recorded it. */
export function nightSold() {
  const n = S.data.pos && S.data.pos.night;
  if (!n || !n.tickets) return '';
  const max = Math.max(...n.hours.map(h => h[1]), 1);
  return card(`<h2>What sold on ${esc(n.night)}</h2>
    <p class="sub">From SambaPOS: ${n.tickets} tickets between ${esc(hhmm(n.first_at))} and
      ${esc(hhmm(n.last_at))}, ${money(n.total)} in all${n.discounts ? `, after ${money(n.discounts)} of discounts` : ''}.
      ${n.by_kind.length > 1 ? 'Paid as ' + n.by_kind.map(([k, v]) => `${esc(k)} ${money(v)}`).join(', ') + '.' : ''}</p>
    <div class="sold">${soldTable(n.items, 8)}</div>
    <h3 class="grouph">Through the night</h3>
    <div class="hours">${n.hours.map(([h, c, t]) => `<div class="hour" title="${c} tickets, ${money(t)}">
        <span class="bar v"><span style="height:${c / max * 100}%"></span></span>
        <span class="quiet">${String(h).padStart(2, '0')}</span></div>`).join('')}</div>`);
}

/** The month as SambaPOS saw it, night by night against the books. */
export function monthSold() {
  const m = S.data.pos && S.data.pos.month;
  if (!m) return '';
  const books = new Map(S.data.sales_by_day);
  const rows = m.nights.map(n => {
    const b = books.get(n.night) || 0;
    const diff = b - n.takings;
    return `<tr><td class="nowrap">${esc(n.night)}</td>
      <td class="num">${n.tickets}</td>
      <td class="num">${money(n.takings)}${n.unpaid ? ` <span class="warnc">+${money(n.unpaid)} unpaid</span>` : ''}</td>
      <td class="num">${b ? money(b) : '<span class="quiet">not entered</span>'}</td>
      <td class="num ${diff ? 'warnc' : 'quiet'}">${b ? (diff ? signed(diff) : 'same') : ''}</td></tr>`;
  }).join('');
  return card(`<h2>SambaPOS this month</h2>
    <p class="sub">${m.nights.length} night${m.nights.length === 1 ? '' : 's'} kept from SambaPOS,
      ${m.tickets} tickets, ${money(m.takings)} paid. Each night beside what the books say it took.</p>
    ${table('<th>Night</th><th class="num">Tickets</th><th class="num">SambaPOS paid</th><th class="num">In the books</th><th class="num">Difference</th>', rows)}
    <details class="fold"><summary>What sold across the month</summary>
      <div class="sold">${soldTable(m.items, 12)}</div></details>`);
}

/** What else is kept from SambaPOS, for later steps: its own lists. */
function keptLists(c) {
  if (!c) return '';
  const bits = [['menu_item', 'menu item'], ['menu_price', 'price'], ['recipe', 'recipe'],
                ['inventory_item', 'inventory item'], ['payment_type', 'payment type']]
    .filter(([k]) => c[k]).map(([k, w]) => `${c[k]} ${w}${c[k] === 1 ? '' : 's'}`);
  return bits.length ? `Also kept, as SambaPOS has them now: ${bits.join(', ')}.` : '';
}

/** Where SambaPOS is read from. */
export function sambaposCard() {
  const p = S.data.pos;
  const s = p.settings;
  const st = p.status;
  const who = p.windows_user || 'YOUR-PC\\you';
  const grant = `CREATE LOGIN [${who}] FROM WINDOWS;\nUSE [${s.database || 'twilight'}];\n`
    + `CREATE USER [${who}] FOR LOGIN [${who}];\nALTER ROLE db_datareader ADD MEMBER [${who}];`;
  const a = p.auto || {};
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const reading = !a.on ? '' : a.error
    ? `<p class="note warnc">${esc(a.error)}</p>`
    : `<p class="note">${a.newest
        ? `${plural(a.read, 'backup')} read so far. The newest, <bdi>${esc(a.newest.name)}</bdi>,
           was made ${esc(a.newest_when)}.`
        : a.in_folder ? 'No backup read yet.' : 'There are no SambaPOS backups in this folder yet.'}
        ${a.waiting ? ` Reading ${plural(a.waiting, 'more backup')}…` : ''}</p>
      ${a.failed && a.failed.length ? `<details class="fold"><summary>${plural(a.failed.length, 'backup')}
          could not be read</summary><ul>${a.failed.map(f => `<li><bdi>${esc(f.name)}</bdi>
          — ${esc(f.note)}</li>`).join('')}</ul></details>` : ''}`;
  return card(`<h2>SambaPOS</h2>
    <p class="sub">The nightly reset deletes the night's tickets from SambaPOS, but SambaPOS
      makes a backup just before it. Tell the app which folder those backups go to, and every
      night comes in by itself: when the app starts, every few minutes while it is open, and
      when Tonight is opened. Nothing is ever written to SambaPOS.</p>
    <div class="grid-form">
      ${field('Folder SambaPOS backs up to', save('pos_settings', {}, 'folder', s.folder,
        'placeholder="for example C:\\Users\\you\\Documents\\SambaPOS5\\Backups"'))}
      ${p.can_read_live ? field('SQL Server', save('pos_settings', {}, 'server', s.server))
        + field('SambaPOS database', save('pos_settings', {}, 'database', s.database)) : ''}
    </div>
    ${reading}
    <div class="row" style="margin-top:12px">
      ${s.folder ? `<button class="btn primary" data-act="posAuto">Look in the folder now</button>
        <button class="btn" data-act="posFolder">Read every backup there again</button>` : ''}
      ${p.can_read_live ? `<button class="btn" data-act="posLive">Read SambaPOS now</button>
        <button class="btn" data-act="posTest">Test the connection</button>` : ''}
    </div>
    <p class="note">${st.nights
      ? `${st.nights} night${st.nights === 1 ? '' : 's'} kept, from ${esc(st.first)} to ${esc(st.last)}.
         ${keptLists(p.catalog)}
         Last kept ${esc(localTime(st.kept_at))} from ${esc(String(st.source || '').replace(/^\w+:/, ''))}.`
      : 'Nothing kept yet.'}
      ${p.can_read_live ? '<br>Read SambaPOS now shows tonight before the reset, straight from its database.'
        : '<br>Reading SambaPOS’s database directly works on the Windows PC it runs on; here, its backups are read.'}</p>
    ${p.can_read_live ? `<details class="fold"><summary>If SQL Server will not let this PC in</summary>
      <p class="note">Sign in to SQL Server as <code>sa</code> once — in SQL Server Management Studio,
        or anything else that runs SQL — and run these lines. They let this Windows account
        read SambaPOS's database, and nothing more.</p>
      <pre class="code">${esc(grant)}</pre></details>` : ''}`);
}

/** What a SambaPOS account is in the books: a picker, with the plain
    suggestion first, saved the moment it is changed. */
function linkPicker(posId, posName, link, suggest) {
  const p = S.data.pos;
  const groups = (p.targets || []).map(g => ({ ...g, options: [...g.options] }));
  const label = v => {
    for (const g of groups) {
      const o = g.options.find(x => x[0] === v);
      if (o) return `${g.group} · ${o[1]}`;
    }
    return v === 'ignore' ? 'Leave it out' : v;
  };
  const current = link ? link.value : '';
  const known = new Set(groups.flatMap(g => g.options.map(o => o[0])));
  // the chosen one says what kind it is too, as a closed picker shows only it
  const opt = (v, text) => (v === current
    ? `<option value="${esc(v)}" selected>${esc(link.label)}</option>`
    : `<option value="${esc(v)}">${esc(text)}</option>`);
  const exp = groups.find(g => g.group === 'Expense');
  if (exp) exp.options.push(['new-expense', `New expense named “${posName}”`]);
  return `<select class="link" data-save="pos_link" data-args="${args({ pos_id: posId })}"
      data-field="to" title="What this SambaPOS account is in the books">
    ${current ? '' : '<option value="" selected disabled>What is this in the books?</option>'}
    ${current && !known.has(current) && current !== 'ignore' ? opt(current, link.label) : ''}
    ${!current && suggest ? `<optgroup label="Suggested">${opt(suggest, label(suggest))}</optgroup>` : ''}
    ${groups.filter(g => g.options.length).map(g => `<optgroup label="${esc(g.group)}">
        ${g.options.map(o => opt(o[0], o[1])).join('')}</optgroup>`).join('')}
    <optgroup label="Neither">${opt('ignore', 'Leave it out')}</optgroup>
  </select>`;
}

/* What each line of a SambaPOS night is, beside the books. */
const POS_STATUS = {
  new: ['to add', ''],
  added: ['in the books', 'pos'],
  typed: ['typed by hand', 'pos'],
  check: ['check', 'warn'],
  deleted: ['deleted in the books', ''],
  held: ['link it first', 'warn'],
  manual: ['enter by hand', 'warn'],
  skip: ['not added', ''],
};

/** A SambaPOS account on a night: its name, a picker the first time it is
    seen, and a word if it belongs to someone who has left. */
function posAccount(a) {
  const name = `<bdi>${esc(a.name)}</bdi>${a.type ? ` <span class="quiet"><bdi>${esc(a.type)}</bdi></span>` : ''}`;
  if (!a.link) return `${name}<br>${linkPicker(a.pos_id, a.name, null, a.suggest)}`;
  return a.link.left && !a.link.told
    ? `${name}<br><span class="warnc">${esc(a.link.name)} has left — remove the account from SambaPOS</span>
       <button class="mini link" data-act="posTold" data-pos="${a.pos_id}">Done</button>`
    : name;
}

/** The night as SambaPOS recorded it — the takings, and every expense,
    advance and owner withdrawal — each line as the entry it becomes in the
    books, and the one click that adds them. */
export function nightDrawer() {
  const pos = S.data.pos;
  const n = pos && pos.night;
  const p = pos && pos.adding;
  if (!n || !p) return '';
  const rows = p.lines.map(l => {
    const [word, kls] = POS_STATUS[l.status] || [l.status, ''];
    const acct = l.account ? posAccount(l.account)
      : `<span class="quiet">${n.tickets} ticket${n.tickets === 1 ? '' : 's'}</span>`;
    const note = l.note || (l.status === 'new' && l.replaces
      ? `replaces ${money(l.replaces)} entered by hand` : '');
    return `<tr${l.status === 'skip' ? ' class="quiet"' : ''}>
      <td class="nowrap">${l.at ? esc(hhmm(l.at)) : ''}</td>
      <td><bdi>${esc(l.what || '')}</bdi></td>
      <td>${acct}</td>
      <td class="num">${money(l.amount)}</td>
      <td>${esc(l.words || '')}<br><span class="pill ${kls}">${word}</span>
        ${note ? `<span class="quiet">${esc(note)}</span>` : ''}</td></tr>`;
  }).join('');
  const odd = p.lines.filter(l => l.status === 'check' || l.status === 'manual').length;
  const oddWords = odd
    ? `${odd} line${odd === 1 ? '' : 's'} marked “check” or “enter by hand” ${odd === 1 ? 'is' : 'are'}
       not added: put ${odd === 1 ? 'it' : 'them'} right by hand, on Books or in step 1.` : '';
  const foot = p.held
    ? `<p class="note warnc">Say what the ${p.held === 1 ? 'account' : 'accounts'} marked
         “link it first” ${p.held === 1 ? 'is' : 'are'} in the books, and the night can be added.</p>`
    : p.to_add
      ? `<div class="row" style="margin-top:12px">
           <button class="btn primary" data-act="posAddNight">Add the night</button>
           <span class="quiet">adds ${p.to_add} entr${p.to_add === 1 ? 'y' : 'ies'} to the books</span></div>
         ${odd ? `<p class="note warnc">${oddWords}</p>` : ''}`
      : odd ? `<p class="note warnc">Nothing more to add. ${oddWords}</p>`
        : '<p class="note">Everything SambaPOS recorded that night is in the books.</p>';
  const only = p.books_only.length
    ? `<p class="note">Entered by hand and not in SambaPOS: ${p.books_only.map(b =>
        `${esc(b.label)} · <bdi>${esc(b.detail || '')}</bdi> ${money(b.amount)}`).join('; ')}.</p>` : '';
  return card(`<h2>The night in SambaPOS</h2>
    <p class="sub">Everything SambaPOS recorded on ${esc(n.night)}, each line as the entry it
      becomes in the books. Out of the drawer: <strong>${money(n.drawer_out)}</strong>${n.drawer_in
        ? `; into it: <strong>${money(n.drawer_in)}</strong>` : ''}.${n.opened_by
        ? ` Opened by <bdi>${esc(n.opened_by)}</bdi>${n.closed_by
          ? `, closed by <bdi>${esc(n.closed_by)}</bdi>` : ', not closed yet'}.` : ''}</p>
    ${table('<th>Time</th><th>SambaPOS</th><th>Account</th><th class="num">Amount</th><th>In the books</th>', rows)}
    ${foot}${only}`);
}

/** The menu as SambaPOS has it: names and prices are set there, where the
    customer is charged, and only read here. */
/* SambaPOS's recipes say what each menu item takes from its own inventory
   items; this says which stock item each of those is here, once. */
export function sambaposStock() {
  const r = S.data.pos && S.data.pos.recipes;
  if (!r || !r.inventory.length) return '';
  const all = S.data.setup.items;
  const byId = Object.fromEntries(all.map(i => [i.id, i]));
  const pick = chosen => `<option value="">— not here</option>`
    + S.data.setup.categories.map(c => {
      const list = all.filter(i => i.letter === c.letter && (i.active || i.id === chosen));
      return list.length ? `<optgroup label="${esc(c.name)}">${options(
        list.map(i => ({ value: i.id, label: i.name })), chosen)}</optgroup>` : '';
    }).join('');
  const ours = it => (['A', 'B'].includes(it.letter) ? 'kilo' : it.letter === 'E' ? 'carton'
    : (it.pack_size || 1) > 1 ? `package of ${it.pack_size}` : 'piece');
  const rows = r.inventory.map(x => {
    const it = byId[x.item_id];
    return `<tr>
      <td><bdi>${esc(x.name)}</bdi><br><span class="quiet"><bdi>${esc(x.unit)}</bdi>${x.group
        ? ` · <bdi>${esc(x.group)}</bdi>` : ''}${x.recipes ? ` · in ${x.recipes} recipe${x.recipes === 1 ? '' : 's'}` : ''}</span></td>
      <td><select data-save="pos_stock_link" data-args="${args({ pos_id: x.pos_id })}" data-field="item_id"
          style="min-width:200px">${pick(x.item_id)}</select></td>
      <td class="num">${it ? save('pos_stock_link', { pos_id: x.pos_id }, 'per', x.per ?? '',
        `type="number" min="1" inputmode="numeric" placeholder="${x.per_default ?? 'how many?'}"
         style="max-width:100px"`) : ''}</td>
      <td class="quiet">${it ? `<bdi>${esc(x.unit)}</bdi> make one ${esc(ours(it))}${!x.per && !x.per_default
        ? ' <span class="warnc">— say how many</span>' : ''}` : ''}</td>
    </tr>`;
  }).join('');
  const amount = t => {
    const it = byId[t.item];
    if (['A', 'B'].includes(t.letter)) return t.qty < 1 ? `${Math.round(t.qty * 1000)} g` : `${+t.qty.toFixed(2)} kg`;
    if (it && (it.pack_size || 1) > 1) {
      const n = +(t.qty * it.pack_size).toFixed(1);
      return `${n} piece${n === 1 ? '' : 's'}`;
    }
    return `${+t.qty.toFixed(2)} ${t.letter === 'E' ? 'cartons' : 'packages'}`;
  };
  const linked = r.inventory.filter(x => x.item_id).length;
  return card(`<h2>What SambaPOS’s recipes take</h2>
    <p class="sub">SambaPOS’s recipes say what each menu item takes from its own inventory
      items. Say which stock item each one is here, once, and every night kept takes what was
      sold off the shelves: a gift takes stock, a void does not. ${linked} of ${r.inventory.length}
      are linked.</p>
    <div class="grid-form" style="max-width:420px">
      ${field('Grams in a head, the same for every flavour', save('head_grams', {}, 'grams',
        r.head_grams ?? '', 'type="number" min="1" inputmode="numeric" placeholder="as each SambaPOS recipe says"'))}
    </div>
    ${r.took.length ? `<p class="note">The night of ${esc(r.last_night)} took ${r.took.map(t =>
      `${esc(amount(t))} of <bdi>${esc(t.name)}</bdi>`).join(', ')}.</p>` : ''}
    <details class="fold"${linked ? '' : ' open'}><summary>SambaPOS’s inventory items
      (${linked} of ${r.inventory.length} linked)</summary>
      ${table(`<th>In SambaPOS</th><th>Here</th><th class="num">How many</th><th></th>`, rows)}</details>
    ${r.no_recipe.length ? `<details class="fold"><summary>Menu items with no recipe in SambaPOS
        (${r.no_recipe.length})</summary><p class="note">They take nothing off the shelves until
        SambaPOS has a recipe for them.</p><ul class="note">${r.no_recipe.map(n =>
        `<li><bdi>${esc(n)}</bdi></li>`).join('')}</ul></details>` : ''}`);
}

export function sambaposMenu() {
  const m = S.data.pos && S.data.pos.menu;
  if (!m || !m.items) return '';
  const odd = m.odd.length
    ? `<p class="note warnc">${m.odd.length} price${m.odd.length === 1 ? ' is' : 's are'} not a
        multiple of ${money(S.data.note)}, so ${m.odd.length === 1 ? 'it needs' : 'they need'} change
        nobody has:</p><ul class="note">${m.odd.map(o => `<li><bdi>${esc(o.item)}</bdi>${o.portion
          && o.portion !== 'Normal' ? ` · <bdi>${esc(o.portion)}</bdi>` : ''}: ${money(o.price)}</li>`).join('')}</ul>`
    : `<p class="note">Every price is a multiple of ${money(S.data.note)}, so change is always possible.</p>`;
  const groups = m.groups.map(g => `<details class="fold"><summary><bdi>${esc(g.name || 'No group')}</bdi>
      <span class="quiet">${g.items.length} item${g.items.length === 1 ? '' : 's'}</span></summary>
      ${table(`<th>Item</th><th>Portion</th><th class="num">Price</th><th class="num">Sold, last ${m.nights} nights</th>`,
        g.items.map(i => i.portions.map((p, n) => `<tr>
          <td>${n ? '' : `<bdi>${esc(i.name)}</bdi>`}</td>
          <td class="quiet"><bdi>${esc(p.name || '')}</bdi>${p.tag ? ` · <bdi>${esc(p.tag)}</bdi>` : ''}</td>
          <td class="num ${p.price && p.price % S.data.note ? 'warnc' : ''}">${p.price === null ? '—' : money(p.price)}</td>
          <td class="num">${n ? '' : (i.sold ? Number(i.sold).toLocaleString('en') : '<span class="quiet">0</span>')}</td>
        </tr>`).join('')).join(''))}</details>`).join('');
  return card(`<h2>The menu, as SambaPOS has it</h2>
    <p class="sub">${m.items} items in ${m.groups.length} groups. Names and prices are set in
      SambaPOS, where the customer is charged; the app reads them each time SambaPOS is read,
      ready for the TV and the QR menu later.</p>${odd}${groups}`);
}

/** Every SambaPOS account money moves through, and what it is in the books. */
export function sambaposAccounts() {
  const p = S.data.pos;
  const rows = p.accounts || [];
  const intro = `<h2>SambaPOS accounts</h2>
    <p class="sub">An expense, a staff advance and an owner taking cash all look the same in
      SambaPOS: money moved from the drawer to one of its accounts. So each account is linked
      once to what it is in the books. The link is by SambaPOS's number for the account, so
      renaming it in SambaPOS changes nothing.</p>`;
  if (!rows.length) {
    return card(intro + empty('Once a night is kept, the accounts it used show here.'));
  }
  let type = null;
  const body = rows.map(r => {
    const head = r.type !== type
      ? `<tr class="typeh"><td colspan="4"><strong><bdi>${esc(r.type || 'Other')}</bdi></strong></td></tr>` : '';
    type = r.type;
    const person = r.link && ['staff', 'partner', 'supplier'].includes(r.link.as);
    const gone = r.gone
      ? (person && !r.link.left
        ? ` <span class="pill warn">gone from SambaPOS</span><br>Has ${esc(r.link.name)} left?
            <button class="mini link" data-act="posLeft" data-pos="${r.pos_id}"
              data-name="${esc(r.link.name)}">Mark as left</button>`
        : ' <span class="pill">gone from SambaPOS</span>') : '';
    return `${head}<tr>
      <td><bdi>${esc(r.name)}</bdi>${r.drawer ? ' <span class="pill">drawer</span>' : ''}${gone}
        ${r.link && r.link.name_then !== r.name
          ? `<br><span class="quiet">was <bdi>${esc(r.link.name_then)}</bdi> when linked</span>` : ''}</td>
      <td class="num">${r.used || '<span class="quiet">—</span>'}</td>
      <td class="nowrap quiet">${esc(String(r.last_at || '').slice(0, 10))}</td>
      <td>${linkPicker(r.pos_id, r.name, r.link, r.suggest)}</td></tr>`;
  }).join('');
  const todo = rows.filter(r => !r.link && !r.gone).length;
  return card(intro + table('<th>SambaPOS account</th><th class="num">Used</th><th>Last</th><th>In the books</th>', body)
    + `<p class="note">${todo ? `${todo} not linked yet.` : 'Every account is linked.'}</p>`);
}

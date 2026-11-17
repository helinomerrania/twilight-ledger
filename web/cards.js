/* One function per card. A card reads the state and returns markup; it never
   fetches and never computes a figure the server already worked out. That is
   deliberate: in the old app the cards did their own arithmetic, and the cards
   disagreed. */

import {
  S, args, card, cls, empty, en, esc, field, money, monthName, monthWords,
  options, pct, potOptions, signed, t, table, th, tile, tiles,
} from './lib.js';

/** The months that are closed, as a set. */
const closedMonths = () =>
  new Set((S.data.summary || []).filter(m => m.status === 'closed').map(m => m.month));

// c.go is a screen, or a page of one ('books/cash'); the button names the screen
const go = c => (c.go ? ` <button class="mini link" data-go="${esc(c.go)}">${th(`go.${c.go.split('/')[0]}`)}</button>` : '');
/* A box for an amount of money shows its commas as it is typed (1,250,000);
   the screens read it without them. */
const MONEY = 'type="text" inputmode="numeric" autocomplete="off" data-money';
const commas = v => (v === null || v === undefined || v === '' ? ''
  : String(v).replace(/[^\d]/g, '').replace(/\B(?=(\d{3})+(?!\d))/g, ','));
const amountInput = (id, value = '', extra = '') =>
  `<input ${MONEY} id="${id}" value="${esc(commas(value))}" placeholder="0" ${extra}>`;

/* A box that keeps only the rows whose name has what is typed in it. A
   brand stays with its flavours, and a flavour with its brand. */
const findAttrs = (name, brand, of) => ` data-name="${esc(String(name || '').toLowerCase())}"`
  + (brand ? ` data-brand="${brand}"` : '') + (of ? ` data-of="${of}"` : '');
const findBox = key => `<input type="search" class="find" id="find-${key}" data-find="${key}"
    value="${esc((S.draft.find || {})[key] || '')}" placeholder="${th('find.item')}" autocomplete="off"
    spellcheck="false">`;

/* ============================================================ needs a look */

export function needsALook() {
  const bad = S.data.checks.filter(c => !c.ok);
  if (!bad.length) return '';
  const show = bad.slice(0, 4);
  // one line until it is opened, so it does not push tonight's job down the page
  return `<details class="banner${bad.some(b => b.serious) ? ' bad' : ''}"${S.draft.lookOpen ? ' open' : ''}>
    <summary data-act="lookToggle">${bad.length === 1 ? th('look.one', 1) : th('look.many', bad.length)}</summary>
    <ul>${show.map(c => `<li><strong>${esc(c.label)}</strong>${c.detail ? ' — ' + esc(c.detail) : ''}
      <br><span class="quiet">${esc(c.fix || '')}</span>${go(c)}</li>`).join('')}</ul>
    ${bad.length > show.length
      ? `<p style="margin:8px 0 0"><button class="btn" data-go="month/close">${th('look.see_all', bad.length)}</button></p>` : ''}
  </details>`;
}

export function allChecks() {
  return card(`<h2>${th('checks.title')}</h2><p class="sub">${th('checks.sub')}</p>
    ${S.data.checks.map(c => `<div class="check ${c.ok ? 'ok' : 'no'}">
      <span class="mark">${c.ok ? '✓' : '!'}</span>
      <span><span class="label">${esc(c.label)}</span>
        ${c.detail ? ` <span class="detail">— ${esc(c.detail)}</span>` : ''}
        ${!c.ok && c.fix ? `<br><span class="fix">${esc(c.fix)}</span>${go(c)}` : ''}</span>
    </div>`).join('')}`);
}

/* ================================================================== tonight */

/* What can leave or come back to the box at night, in the order they are
   most used. Each says what it does to the books (night_kind.*_note in the
   words), because the difference between an expense and an advance is the
   whole difference to profit. */
export const NIGHT = ['expense', 'staff_advance', 'partner_draw', 'pay_salary', 'pay_supplier',
                      'pay_fixed', 'staff_repay'];

/** Who can still be paid, or hand money back: everyone here now, and anyone
    who has left or been retired with the account not yet square. `sign` is
    the side of the balance that matters: 1 owed to them, -1 owed by them. */
const unsettled = (list, sign) => list
  .filter(a => a.active || a.balance * sign > 0).map(a => a.name);

function nightNames(kind) {
  const p = S.data.people;
  const active = list => list.filter(a => a.active).map(a => a.name);
  return {
    expense: S.data.lists.expense || [],
    staff_advance: active(p.staff), pay_salary: unsettled(p.staff, 1),
    staff_repay: unsettled(p.staff, -1),
    partner_draw: active(p.partner), pay_supplier: unsettled(p.supplier, 1),
    pay_fixed: S.data.fixed_names || [],
  }[kind] || [];
}

export function closingUp() {
  const d = S.data.day;
  const kind = S.draft.nKind || 'expense';
  const names = nightNames(kind);
  const pick = names.includes(S.draft.nWho) ? S.draft.nWho : (names[0] || '');
  const counted = {};
  const left = {};                     // what each counted pot is still out by
  const lastCount = d.count;
  if (lastCount) lastCount.pots.forEach(p => { counted[p.name] = p.counted; left[p.name] = p.diff; });
  const pots = d.pots.filter(p => p.active && (p.in_use || p.name in counted));
  const chips = kind === 'expense' ? names.slice(0, 12) : names;

  // a blind count shows what was expected only once the count is saved
  const dr = S.data.drawer || {};
  const blind = dr.blind && !lastCount;
  const potCards = pots.map(p => {
    const got = counted[p.name];
    // the count's own difference, and the books as they stood at the count:
    // the rest moved out of the drawer afterwards is not part of either
    const diff = got === undefined ? null : left[p.name];
    const books = got === undefined ? p.balance : got - diff;
    const pos = p.name === dr.pot && dr.pos && !blind ? dr.pos : null;
    return `<div class="pot">
      <div class="nm">${esc(p.name)}</div>
      ${blind ? `<div class="bal quiet">?</div><div class="sub">${th('closing.count_it_first')}</div>`
        : `<div class="bal">${money(books)}</div><div class="sub">${th('closing.books_say')}</div>`}
      <input ${MONEY} placeholder="${th('closing.count_it')}"
             data-pot="${esc(p.name)}" value="${got === undefined ? '' : esc(commas(got))}">
      ${diff === null ? '' : `<div class="sub ${cls(diff)}" style="margin-top:6px">
         ${diff === 0 ? th('closing.ties_exactly') : signed(diff)}</div>`}
      ${pos ? `<div class="sub" style="margin-top:6px" title="${th('closing.pos_title')}">${th('closing.pos_cash', money(pos.cash))}${pos.out
          ? th('closing.pos_out', money(pos.out)) : ''}${pos.in ? th('closing.pos_in', money(pos.in)) : ''}${pos.expected
          !== undefined ? `<br>${th('closing.pos_float', money(pos.expected))}` : ''}</div>` : ''}
    </div>`;
  }).join('');
  const sd = dr.sales_differ;
  const hidden = sd && !blind
    ? `<p class="note warnc">${sd.gap > 0
        ? th('closing.hidden_shortage', money(sd.books), money(sd.pos), money(Math.abs(sd.gap)))
        : th('closing.hidden_surplus', money(sd.books), money(sd.pos), money(Math.abs(sd.gap)))}</p>` : '';
  const there = counted[dr.pot];
  const rest = there === undefined ? 0 : there - (dr.float || 0);
  const move = !dr.float || !lastCount || there === undefined ? ''
    : dr.moved ? `<p class="note">${th('closing.moved_today', money(dr.moved), esc(dr.pot))}</p>`
      : rest > 0 ? `<div class="row" style="margin-top:12px">
          <span>${th('closing.leave_float', money(dr.float), esc(dr.pot), `<strong>${money(rest)}</strong>`)}</span>
          <select id="restTo" style="max-width:180px">${options(
            S.data.pots.filter(p => p.active && p.name !== dr.pot).map(p => p.name), dr.rest_to)}</select>
          <button class="btn" data-act="moveRest" data-amount="${rest}">${th('closing.move_it')}</button></div>` : '';

  return card(`
    <div class="cardhead">
      <h2>${th('closing.title')}</h2>
      <div class="right"><input type="date" id="nightDate" value="${esc(d.on)}"
           max="${esc(S.data.today)}" data-act="setDay" style="width:auto"></div>
    </div>
    <div class="steps">

      <div class="step"><div class="no">1</div><div>
        <h3>${th('tonight.sales')}</h3>
        <p>${th('closing.sales_help')}</p>
        <div class="row">
          ${amountInput('nSales', d.sales || '', 'class="big" style="max-width:220px"')}
          <button class="btn primary" data-act="sales">${d.sales ? th('common.replace') : th('common.save')}</button>
          ${d.sales ? `<span class="quiet">${th('closing.recorded', money(d.sales))}</span>` : ''}
        </div>
        ${posLine()}${missingNights()}</div></div>

      <div class="step"><div class="no">2</div><div>
        <h3>${th('closing.step_out')}</h3>
        <div class="chips kinds">
          ${NIGHT.map(k => `<button data-act="nKind" data-k="${k}"
             aria-pressed="${k === kind}">${th(`night_kind.${k}`)}</button>`).join('')}
        </div>
        <div class="chips">
          ${chips.map(c => `<button data-act="nWho" data-who="${esc(c)}"
             aria-pressed="${c === pick}">${esc(c)}</button>`).join('')
            || `<span class="quiet">${th('closing.nothing_set_up')}</span>`}
        </div>
        <div class="row">
          <select id="nWho" style="max-width:220px">${options(names, pick)}</select>
          ${amountInput('nAmt', '', 'style="max-width:140px"')}
          <select id="nPot" style="max-width:150px" title="${kind === 'staff_repay' ? th('closing.into') : th('closing.paid_from')}">
            ${potOptions(S.draft.nPot)}</select>
          <button class="btn primary" data-act="nAdd">${th('common.add')}</button>
          ${d.paid_out ? `<span class="quiet">${th('closing.out_so_far', money(d.paid_out))}</span>` : ''}
        </div>
        <p class="note">${NIGHT.includes(kind) ? th(`night_kind.${kind}_note`) : ''}</p>
        </div></div>

      <div class="step"><div class="no">3</div><div>
        <h3>${th('closing.step_count')}</h3>
        <p>${th('closing.count_help')}</p>
        ${blind ? `<p class="note">${th('closing.blind_note')}</p>` : ''}
        <div class="potgrid">${potCards || empty(t('closing.no_pots'))}</div>
        ${hidden}
        <div class="row" style="margin-top:12px">
          <select id="nReason" style="max-width:260px">
            <option value="">${th('closing.no_reason')}</option>
            ${options(S.data.lists.reason, lastCount ? lastCount.reason : '')}</select>
          <button class="btn primary" data-act="saveCount">
            ${lastCount ? th('closing.update_count') : th('closing.save_count')}</button>
        </div>${move}</div></div>
    </div>`);
}

/** How the cash is counted: the float, a blind count, where the rest goes. */
export function cashCountingCard() {
  const c = S.data.drawer || {};
  const pots = S.data.pots.filter(p => p.active).map(p => p.name);
  return card(`<h2>${th('counting.title')}</h2>
    <p class="sub">${th('counting.sub', esc(c.pot || t('counting.the_drawer')))}</p>
    <div class="grid-form">
      ${field(t('counting.float_left'), save('cash_settings', {}, 'float', commas(c.float || 0),
        MONEY))}
      ${field(t('counting.rest_goes_to'), `<select data-save="cash_settings" data-args="${args({})}"
        data-field="rest_to">${options([{ value: '', label: t('counting.choose_each_time') }, ...pots],
          c.rest_to || '')}</select>`)}
      ${field(t('counting.while_counting'), `<select data-save="cash_settings" data-args="${args({})}"
        data-field="blind">${options([{ value: '0', label: t('counting.show_expected') },
          { value: '1', label: t('counting.count_blind') }],
          c.blind ? '1' : '0')}</select>`)}
    </div>
    <p class="note">${th('counting.blind_control')}</p>`);
}

/** Each count's difference over the month, and who opened SambaPOS those nights. */
export function cashDifferences() {
  const d = S.data.differences;
  if (!d || !d.rows.length) return '';
  const max = Math.max(...d.rows.map(r => Math.abs(r.found)), 1);
  const bars = d.rows.map(r => {
    const h = Math.round(Math.abs(r.found) / max * 44);
    return `<div class="dday" title="${esc(r.on)}: ${r.found ? signed(r.found) : th('diffs.ties')}${
        r.opened_by ? th('diffs.opened_by', esc(r.opened_by)) : ''}">
      <span class="up">${r.found > 0 ? `<span class="good" style="height:${h}px"></span>` : ''}</span>
      <span class="down">${r.found < 0 ? `<span class="bad" style="height:${h}px"></span>` : ''}</span>
      <span class="quiet">${Number(r.on.slice(8))}</span></div>`;
  }).join('');
  const known = d.by_who.filter(g => g.who !== en('cash.not_known'));
  const who = known.length ? table(`<th>${th('diffs.opened_sambapos')}</th><th class="num">${th('diffs.nights')}</th>
      <th class="num">${th('diffs.short')}</th><th class="num">${th('diffs.over')}</th>
      <th class="num">${th('diffs.net')}</th>`,
    d.by_who.map(g => `<tr><td><bdi>${esc(g.who)}</bdi></td><td class="num">${g.nights}</td>
      <td class="num">${g.short || ''}</td><td class="num">${g.over || ''}</td>
      <td class="num ${cls(g.net)}">${g.net ? signed(g.net) : '0'}</td></tr>`).join('')) : '';
  return card(`<h2>${th('diffs.title')}</h2>
    <p class="sub">${th('diffs.sub')}</p>
    <div class="ddays">${bars}</div>
    <p class="note">${d.rows.length === 1
      ? th('diffs.note_one', 1, money(-d.short), money(d.over), d.net ? signed(d.net) : th('diffs.nothing'))
      : th('diffs.note_many', d.rows.length, money(-d.short), money(d.over),
           d.net ? signed(d.net) : th('diffs.nothing'))}</p>${who}`);
}

const hhmm = at => String(at || '').slice(11, 16);

/** A time the database wrote in UTC, as the clock on the wall shows it:
    "17 Nov, 07:26", the month in the words whatever the PC's own language. */
export const localTime = at => {
  const d = new Date(String(at || '').replace(' ', 'T') + 'Z');
  if (isNaN(d)) return String(at || '');
  const two = n => String(n).padStart(2, '0');
  return `${d.getDate()} ${t(`month.short.${two(d.getMonth() + 1)}`)}, ${two(d.getHours())}:${two(d.getMinutes())}`;
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
      ? ` <button class="mini link" data-act="posLive">${th('tonight_pos.read_now')}</button>` : '';
    if (auto.on && (auto.waiting || auto.reading)) {
      return `<p class="note quiet">${th('tonight_pos.reading')}</p>`;
    }
    if (auto.on) {
      return on >= S.data.tonight
        ? `<p class="note quiet">${th('tonight_pos.auto_tonight')}${live}</p>`
        : `<p class="note">${th('tonight_pos.no_backup', esc(on))}${live}</p>`;
    }
    if (live) return `<p class="note">${th('tonight_pos.not_kept', esc(on))}${live}</p>`;
    return `<p class="note quiet">${th('tonight_pos.tell_folder')} <button class="mini link" data-go="setup/sambapos">${th('go.setup')}</button></p>`;
  }
  const same = night.takings === S.data.day.sales;
  return `<p class="note">${th('tonight_pos.kept', `<strong>${money(night.takings)}</strong>`, night.tickets)}${night.unpaid
        ? th('tonight_pos.and_unpaid', `<span class="warnc">${night.open_tickets === 1
          ? th('tonight_pos.unpaid_one', money(night.unpaid), 1)
          : th('tonight_pos.unpaid_many', money(night.unpaid), night.open_tickets)}</span>`) : ''}.
      ${night.ended ? '' : `<span class="quiet">${th('tonight_pos.as_it_stood', esc(hhmm(night.seen_to)))}</span>`}
      ${same ? `<span class="pos">${th('tonight_pos.books_match')}</span>`
             : `<button class="mini link" data-act="usePos" data-amount="${night.takings}">
                  ${th('tonight_pos.use', money(night.takings))}</button>`}</p>`;
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
  return `<p class="note warnc">${th('tonight.no_sales_after', esc(last))}
    <button class="mini link" data-act="setDay" data-on="${first}">${th('tonight.go_to', esc(first))}</button></p>`;
}

export function todayFigures() {
  const d = S.data.day;
  const floats = S.data.people.float.length > 0;
  return tiles([
    tile(t('tonight.sales'), money(d.sales)),
    tile(t('tonight.paid_out'), money(d.paid_out), t('tonight.paid_out_note')),
    tile(t('common.cash_on_hand'), money(d.cash), t('tonight.cash_on_hand_note')),
    floats ? tile(t('common.in_hands'), money(d.floats), t('common.floats')) : '',
  ]);
}

export function todayEntries() {
  const rows = S.data.day.entries;
  return card(`<h2>${th('tonight.everything_entered', esc(S.data.day.on))}</h2>
    ${rows.length ? entryTable(rows, { date: false }) : empty(t('tonight.nothing_entered'))}`);
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
      ${e.tagged ? ` <span class="pill">${th('entries.for_month', ...monthWords(e.period))}</span>` : ''}
      ${e.memo && e.kind !== 'transfer' ? ` <span class="quiet">${esc(e.memo)}</span>` : ''}</td>
    <td class="quiet">${where}</td>
    <td class="num ${e.cash > 0 ? 'pos' : ''}">${money(e.amount)}</td>
    <td class="actions">
      ${lines && e.receipt ? `<button class="mini" data-act="receiptLines" data-id="${e.receipt.id}"
          aria-expanded="${S.draft.rlines === e.receipt.id}">${e.lines.length === 1 ? th('entries.lines_one', 1)
          : e.lines.length ? th('entries.lines_many', e.lines.length) : th('entries.what_came_in')}</button>` : ''}
      ${e.editable ? `<button class="mini" data-act="edit" data-id="${e.id}">${th('common.edit')}</button>` : ''}
      ${e.deletable ? `<button class="mini danger" data-act="void" data-id="${e.id}">${th('common.delete')}</button>` : ''}
    </td></tr>`;
}

function editRow(e, { date }) {
  const names = whoList(e.kind);
  // a person as they are called now, not the name written on the entry
  const who = (names && e.who) || e.detail;
  const isReceipt = e.kind.startsWith('receipt_');
  const r = e.receipt || {};
  const closed = closedMonths();
  const months = S.data.months.filter(m => m <= S.data.this_month && (!closed.has(m) || m === e.period));
  return `<tr class="editing" data-edit="${e.id}">
    <td colspan="${date ? 6 : 5}">
      <div class="grid-form">
        ${field(t('common.date'), `<input type="date" data-e="on" value="${esc(e.happened_on)}" max="${esc(S.data.today)}">`)}
        ${names ? field(isReceipt ? t('entries.supplier') : t('common.who_or_what'),
            `<select data-e="detail">${options(names.includes(who) ? names : [who, ...names], who)}</select>`) : ''}
        ${e.kind === 'transfer'
          ? field(t('common.from'), `<select data-e="pot">${potOptions(e.pot)}</select>`)
            + field(t('common.to'), `<select data-e="pot_to">${potOptions(e.pot_to)}</select>`)
          : (e.pot ? field(e.cash > 0 ? t('common.into') : t('common.out_of'), `<select data-e="pot">${potOptions(e.pot)}</select>`) : '')}
        ${isReceipt ? field(t('common.for'), `<input data-e="what" value="${esc(r.what || '')}">`)
                      + field(t('common.terms'), `<select data-e="terms">${options([
                          { value: 'credit', label: t('entries.on_credit') }, { value: 'cash', label: t('entries.paid_cash') }],
                          r.terms || (e.kind === 'receipt_cash' ? 'cash' : 'credit'))}</select>`) : ''}
        ${field(t('common.amount'), `<input ${MONEY} data-e="amount" value="${esc(commas(e.amount))}">`)}
        ${field(t('entries.counts_for'), `<select data-e="period" data-was="${esc(e.period)}">${options(
            months.map(m => ({ value: m, label: monthName(m) })), e.period)}</select>`)}
        <div class="row">
          <button class="btn primary" data-act="saveEdit" data-id="${e.id}" data-tagged="${e.tagged ? 1 : 0}">${th('common.save')}</button>
          <button class="btn" data-act="cancelEdit">${th('common.cancel')}</button>
        </div>
      </div>
      <p class="note">${th('entries.edit_note')}</p>
    </td></tr>`;
}

function entryTable(rows, opts = {}) {
  const date = opts.date !== false;
  return table(`${date ? `<th>${th('common.date')}</th>` : ''}<th>${th('common.what')}</th><th>${th('common.details')}</th><th>${th('common.pot')}</th>
                <th class="num">${th('common.amount')}</th><th></th>`,
    rows.map(e => entryRow(e, { date })).join(''));
}

/* =================================================================== month */

/* The month every page of Month is about, on the same row as the pages. */
export function periodPicker() {
  const per = S.data.period;
  return `<div class="tools">
      ${per.status === 'closed' ? `<span class="pill">${th('period.closed')}</span>` : ''}
      ${S.data.month === S.data.this_month ? `<span class="pill">${th('period.in_progress')}</span>` : ''}
      <select data-act="setMonth" style="width:auto" aria-label="${th('period.month')}">
        ${options(S.data.months.slice().reverse().map(m => ({ value: m, label: monthName(m) })), S.data.month)}
      </select>
      <button class="btn" data-act="printMonth">${th('common.print')}</button>
      <button class="btn" data-act="printSummary"
        title="${th('period.summary_title')}">${th('period.summary')}</button>
    </div>`;
}

export function monthFigures() {
  const r = S.data.result;
  const sf = S.data.so_far;
  const dr = S.data.drawings;
  return tiles([
    tile(t('result.sales'), money(r.rev)),
    tile(t('result.gross_profit'), money(r.gross), pct(r.grossPct), cls(r.gross)),
    sf ? tile(t('figures.net_so_far'), money(sf.net), t('common.days_of', sf.days, sf.days_in_month), cls(sf.net))
       : tile(t('result.net_profit'), money(r.net), pct(r.netPct), cls(r.net)),
    tile(t('figures.taken'), money(dr.taken),
         dr.over ? t('figures.over_profit', money(dr.over)) : t('figures.within_profit'),
         dr.over ? 'neg' : ''),
  ]);
}

export function soFarCard() {
  const sf = S.data.so_far;
  if (!sf) return '';
  const line = (label, value, note, strong) => `<tr${strong ? ' class="tot"' : ''}>
      <td>${esc(label)}${note ? ` <span class="quiet">${esc(note)}</span>` : ''}</td>
      <td class="num ${strong ? cls(value) : ''}">${money(value)}</td></tr>`;
  return card(`<h2>${th('so_far.title', sf.days, sf.days_in_month)}</h2>
    <p class="sub">${th('so_far.sub', sf.days, sf.days)}</p>
    ${table(`<th>${th('result.line')}</th><th class="num">${th('common.amount')}</th>`,
      line(t('result.sales'), sf.rev, t('result.through', sf.through))
      + line(t('result.cogs'), -sf.cogs, sf.cogs_note)
      + line(t('result.daily'), -sf.daily)
      + (sf.elec ? line(t('result.electricity'), -sf.elec, sf.elec_estimated ? t('result.elec_estimated') : t('result.days_worth', sf.days)) : '')
      + line(t('result.rent'), -sf.fixed, t('result.days_worth', sf.days))
      + line(t('result.salaries'), -sf.salaries, t('result.days_worth', sf.days))
      + (sf.differences ? line(t('result.written_off'), -sf.differences) : '')
      + line(t('result.net_so_far'), sf.net, '', true))}`);
}

export function resultCard() {
  const r = S.data.result;
  const line = (label, value, strong, note) => `<tr${strong ? ' class="tot"' : ''}>
      <td>${esc(label)}${note ? ` <span class="quiet">${esc(note)}</span>` : ''}</td>
      <td class="num ${strong ? cls(value) : ''}">${money(value)}</td></tr>`;
  const c = r.cogs || {};
  const inProgress = !!S.data.so_far;
  return card(`<h2>${inProgress ? th('result.full_month') : th('result.title')}${r.frozen ? ` <span class="pill">${th('result.frozen')}</span>` : ''}</h2>
    <p class="sub">${r.frozen
      ? th('result.closed_note')
      : inProgress ? th('result.in_progress_note')
                   : th('result.charged_note')}</p>
    ${table(`<th>${th('result.line')}</th><th class="num">${th('common.amount')}</th>`,
      line(t('result.sales'), r.rev)
      + line(t('result.cogs'), -(c.value || 0))
      + line(t('result.gross_profit'), r.gross, true)
      + line(t('result.daily'), -(r.daily || 0))
      + (r.elec ? line(t('result.elec_used'), -(r.elec || 0)) : '')
      + line(t('result.rent'), -(r.fixed || 0))
      + line(t('result.salaries'), -(r.salaries || 0))
      + (r.differences ? line(t('result.written_off'), -(r.differences || 0)) : '')
      + line(t('result.net_profit'), r.net, true))}
    <p class="sub" style="margin-top:10px">${c.date
      ? th('result.stock_counted', money(c.opening), money(c.purchases), money(c.closing), esc(c.date))
      : th('result.stock', money(c.opening), money(c.purchases), money(c.closing))}</p>`);
}

export function electricityCard() {
  const e = S.data.electricity;
  if (S.data.period.status === 'closed') {
    return e.charged ? card(`<h2>${th('elec.title')}</h2>
      <p class="sub">${th('elec.charged_closed', money(e.charged))}</p>`) : '';
  }
  const f = e.factors;
  return card(`<h2>${th('elec.title')}</h2>
    <p class="sub">${th('elec.sub')} ${e.charged
        ? `<strong>${th('elec.charged_to', money(e.charged), ...monthWords(S.data.month))}</strong>`
        : th('elec.nothing_charged')}
      ${e.unpaid > 0 ? th('elec.unpaid', money(e.unpaid)) : ''}</p>
    <div class="grid-form">
      ${field(t('elec.private', f.privateAmps),
        `<input ${MONEY} id="elPP" value="${esc(commas(e.private_price))}">`)}
      ${field(t('elec.elevator', f.elevatorAmps, f.elevatorShare),
        `<input ${MONEY} id="elPE" value="${esc(commas(e.elevator_price))}">`)}
      ${field(t('elec.public_last'),
        `<input type="number" id="elLast" value="${esc(e.last_reading)}" min="0" inputmode="numeric">`)}
      ${field(t('elec.public_now', f.publicRate, f.publicShare),
        `<input type="number" id="elNow" value="${esc(e.now_reading)}" min="0" inputmode="numeric">`)}
      <div><button class="btn primary" data-act="saveElectricity">${th('elec.charge')}</button></div>
    </div>`);
}

export function settleCard() {
  if (S.data.period.status === 'closed') return '';
  const lines = S.data.settle;
  if (!lines.length) {
    return card(`<h2>${th('settle_up.title')}</h2>
      <p class="sub">${th('settle_up.nothing', ...monthWords(S.data.month))}</p>`);
  }
  return card(`<h2>${th('settle_up.title')}</h2>
    <p class="sub">${th('settle_up.everything', `<strong>${esc(monthName(S.data.month))}</strong>`,
      ...monthWords(S.data.month))}</p>
    <p class="sub">${th('settle_up.supplier_note')}</p>
    ${table(`<th>${th('common.what')}</th><th>${th('common.who')}</th><th class="num">${th('settle_up.still_to_pay')}</th>
             <th style="width:150px">${th('common.amount')}</th><th>${th('common.from')}</th><th></th>`,
      lines.map(l => l.done ? `<tr>
        <td>${esc(l.what)}</td>
        <td>${esc(l.who)}${l.note ? `<br><span class="quiet">${esc(l.note)}</span>` : ''}</td>
        <td class="num">${money(0)}</td>
        <td colspan="3" class="quiet">${esc(l.done)}</td>
      </tr>` : `<tr data-line="${esc(l.action + '|' + l.who)}">
        <td>${esc(l.what)}</td>
        <td>${esc(l.who)}${l.note ? `<br><span class="quiet">${esc(l.note)}</span>` : ''}</td>
        <td class="num">${money(l.amount)}</td>
        <td><input ${MONEY} data-s="amount" value="${esc(commas(l.amount))}"></td>
        <td><select data-s="pot" style="width:auto">${potOptions()}</select></td>
        <td><button class="btn primary" data-act="settle">${th('settle_up.pay')}</button></td>
      </tr>`).join(''))}`);
}

export function payrollCard() {
  const pay = S.data.payroll;
  if (!pay.length) return '';
  const T = k => pay.reduce((a, p) => a + (p[k] || 0), 0);
  return card(`<h2>${th('payroll.title')}</h2>
    <p class="sub">${th('payroll.sub')}</p>
    ${table(`<th>${th('common.who')}</th><th class="num">${th('payroll.salary')}</th><th class="num">${th('payroll.advances')}</th>
             <th class="num">${th('common.paid')}</th><th class="num">${th('settle_up.still_to_pay')}</th>`,
      pay.map(p => `<tr>
        <td>${esc(p.name)}${p.started_on ? ` <span class="pill">${th('payroll.started', esc(p.started_on))}</span>` : ''}${
          p.active ? '' : p.left_on
            ? ` <span class="pill">${th('payroll.left', esc(p.left_on))}</span>` : ` <span class="pill">${th('payroll.no_longer')}</span>`}</td>
        <td class="num">${money(p.gross)}${p.part
          ? `<br><span class="quiet">${th('common.days_of', p.part.days, p.part.of)}</span>` : ''}</td>
        <td class="num">${money(p.advances)}</td>
        <td class="num">${money(p.paid)}</td>
        <td class="num">${p.overpaid
          ? `<span class="neg">${th('payroll.ahead', money(p.overpaid))}</span>`
          : `<span class="${p.still_to_pay ? '' : 'pos'}">${money(p.still_to_pay)}</span>`}
          ${p.from_earlier ? `<br><span class="quiet">${th('payroll.from_earlier', money(p.from_earlier))}</span>` : ''}</td>
      </tr>`).join(''),
      `<tr class="tot"><td>${th('common.total')}</td><td class="num">${money(T('gross'))}</td>
        <td class="num">${money(T('advances'))}</td><td class="num">${money(T('paid'))}</td>
        <td class="num">${money(T('still_to_pay'))}</td></tr>`)}
    ${pay.some(p => p.overpaid) ? `<p class="note">${th('payroll.ahead_note')}</p>` : ''}`);
}

export function partnersCard() {
  const prt = S.data.partners;
  if (!prt.length) return '';
  const dr = S.data.drawings;
  const taken = `<strong>${money(dr.taken)}</strong>`;
  const profit = `<strong class="${cls(dr.profit)}">${money(dr.profit)}</strong>`;
  return card(`<h2>${th('partners.title')}</h2>
    <p class="sub">${dr.basis === 'so_far' ? th('partners.taken_so_far', taken, profit)
                                           : th('partners.taken_month', taken, profit)}
      ${dr.over ? `<br><span class="neg">${th('partners.over', money(dr.over))}</span>` : ''}</p>
    ${table(`<th>${th('partners.partner')}</th><th class="num">${th('partners.share')}</th>
             <th class="num">${prt.some(p => p.so_far) ? th('partners.share_so_far') : th('partners.share_of_profit')}</th>
             <th class="num">${th('partners.taken')}</th><th class="num">${th('partners.put_in')}</th><th class="num">${th('partners.balance')}</th>`,
      prt.map(p => `<tr>
        <td>${esc(p.name)}</td>
        <td class="num">${(p.share * 100).toFixed(0)}%</td>
        <td class="num ${cls(p.profit)}">${money(p.profit)}</td>
        <td class="num">${money(p.taken)}</td>
        <td class="num">${money(p.put_in)}</td>
        <td class="num ${cls(p.balance)}">${money(p.balance)}${p.posted ? '' : ` <span class="quiet">${th('partners.before_share')}</span>`}</td>
      </tr>`).join(''))}
    <p class="note">${th('partners.note')}</p>`);
}

export function suppliersCard() {
  const sup = S.data.suppliers;
  const total = sup.reduce((a, s) => a + Math.max(s.owed_now, 0), 0);
  const open = S.statement;
  return card(`<div class="cardhead"><h2>${th('suppliers.title')}</h2>
      <span class="pill">${th('suppliers.owed', money(S.data.owed))}</span>
      <div class="right"><button class="btn" data-act="printSuppliers">${th('common.print')}</button></div>
    </div>
    <p class="sub">${th('suppliers.sub')}</p>
    ${sup.length ? table(
      `<th>${th('entries.supplier')}</th><th class="num">${th('suppliers.coming_in')}</th><th class="num">${th('suppliers.arrived')}</th>
       <th class="num">${th('common.paid')}</th><th class="num">${th('suppliers.at_end')}</th><th style="width:110px"></th>`,
      sup.map(s => `<tr>
        <td><button class="mini link" data-act="statement" data-id="${s.id}">${esc(s.name)}</button></td>
        <td class="num">${money(s.brought_forward)}</td>
        <td class="num">${money(s.received)}</td>
        <td class="num">${money(s.paid)}</td>
        <td class="num ${s.closing > 0 ? 'neg' : ''}">${money(s.closing)}</td>
        <td><div class="bar"><span style="width:${total ? Math.max(0, s.owed_now) / total * 100 : 0}%"></span></div></td>
      </tr>${open && open.id === s.id ? statementRow(open) : ''}`).join(''))
      : empty(t('suppliers.none'))}`);
}

function statementRow(st) {
  return `<tr class="drill"><td colspan="6">
    <div class="cardhead"><strong>${esc(st.name)} — ${esc(monthName(st.month))}</strong>
      <div class="right"><button class="btn" data-act="printStatement">${th('common.print')}</button>
      <button class="mini" data-act="closeStatement">${th('common.close')}</button></div></div>
    ${table(`<th>${th('common.date')}</th><th>${th('common.what')}</th><th class="num">${th('common.amount')}</th>
        <th class="num">${th('suppliers.owed_after')}</th>`,
      (() => {
        let run = st.opening;
        return `<tr><td></td><td class="quiet">${th('suppliers.coming_in')}</td><td></td><td class="num">${money(run)}</td></tr>`
          + st.lines.map(l => { run += l.amount; return `<tr><td>${esc(l.on)}</td><td>${esc(l.what)}</td>
              <td class="num">${signed(l.amount)}</td><td class="num">${money(run)}</td></tr>`; }).join('');
      })(),
      `<tr class="tot"><td></td><td>${th('suppliers.end_of_month')}</td><td></td><td class="num">${money(st.closing)}</td></tr>`)}
    <p class="note">${th('stmt.arrived_paid', money(st.received), money(st.paid))}
      ${st.on_shelves ? th('stmt.on_shelves', money(st.on_shelves), esc(st.count_date)) : ''}
      ${st.owed_now !== st.closing ? th('stmt.owed_today', money(st.owed_now)) : ''}</p>
  </td></tr>`;
}

export function moneyFlow() {
  const f = S.data.flow;
  if (!f.out.length && !f.in.length) return '';
  const pick = S.draft.flow || {};
  const group = (g, total, side) => {
    const open = pick.kind === g.kind && pick.side === side;
    return `<details class="flow"${open ? ' open' : ''}>
      <summary><span>${esc(g.label)}</span>
        <span class="track"><span class="fill" style="width:${total ? g.total / total * 100 : 0}%"></span></span>
        <span class="num">${money(g.total)}</span></summary>
      <div class="row" style="justify-content:flex-end"><button class="mini" data-act="printKind"
        data-k="${esc(g.kind)}" data-side="${side}">${th('common.print')}</button></div>
      ${table(`<th>${th('common.who_or_what')}</th><th class="num">${th('common.amount')}</th>`,
        g.rows.map(([n, v]) => {
          const shown = open && pick.name === n;
          return `<tr><td><button class="mini link" data-act="flowName" data-k="${esc(g.kind)}"
              data-side="${side}" data-n="${esc(n)}" aria-expanded="${shown}">${esc(n)}</button></td>
            <td class="num">${money(v)}</td></tr>${shown ? nameLines(n) : ''}`;
        }).join(''))}
    </details>`;
  };
  return card(`<div class="cardhead"><h2>${th('flow.title')}</h2>
      <div class="right"><button class="btn" data-act="printFlow">${th('flow.print_all')}</button></div></div>
    <p class="sub">${th('flow.sub', esc(f.from), esc(f.to))}</p>
    ${forEarlier(f)}
    <h3 class="flowh">${th('flow.out', money(f.out_total))}</h3>
    ${f.out.map(g => group(g, f.out_total, 'out')).join('')}
    <h3 class="flowh">${th('flow.in', money(f.in_total))}</h3>
    ${f.in.map(g => group(g, f.in_total, 'in')).join('')}`);
}

/** What went out this month for an earlier month: a salary or the rent paid
    late, what a supplier was owed from before. It is part of Out; each
    payment says which month it is for when it is made. */
function forEarlier(f) {
  if (!f.earlier_total) return '';
  const names = rows => rows.map(([n, v]) => `<bdi>${esc(n)}</bdi> ${money(v)}`).join(' · ');
  return `<details class="flow">
      <summary><span>${th('earlier.title')}</span>
        <span class="track"><span class="fill"
          style="width:${f.out_total ? f.earlier_total / f.out_total * 100 : 0}%"></span></span>
        <span class="num">${money(f.earlier_total)}</span></summary>
      <div class="row" style="justify-content:flex-end"><button class="mini"
        data-act="printEarlier">${th('common.print')}</button></div>
      ${table(`<th>${th('common.for')}</th><th>${th('common.what')}</th><th class="num">${th('common.amount')}</th>`,
        f.earlier.map(m => m.kinds.map((k, i) => `<tr>
          <td class="nowrap">${i ? '' : esc(monthName(m.month))}</td>
          <td><span>${esc(k.label)}</span><br><span class="quiet">${names(k.rows)}</span></td>
          <td class="num">${money(k.total)}</td></tr>`).join('')).join(''),
        `<tr class="tot"><td colspan="2">${th('common.total')}</td><td class="num">${money(f.earlier_total)}</td></tr>`)}
      <p class="note">${th('earlier.note')}</p>
    </details>`;
}

/** Every entry under one name this month, whatever it was for, with the time
    of each where the books know it. */
function nameLines(name) {
  const lines = S.data.flow.lines.filter(l => l.name === name);
  const sum = side => lines.filter(l => l.out === side).reduce((a, l) => a + l.amount, 0);
  return `<tr class="drill"><td colspan="2">
    <div class="cardhead"><strong>${esc(name)} — ${esc(monthName(S.data.month))}</strong>
      <div class="right"><button class="btn" data-act="printName" data-n="${esc(name)}">${th('common.print')}</button></div></div>
    ${table(`<th>${th('common.date')}</th><th>${th('common.time')}</th><th>${th('common.what')}</th>
        <th class="num">${th('common.out')}</th><th class="num">${th('common.in')}</th>`,
      lines.map(l => `<tr><td class="nowrap">${esc(l.on)}</td><td class="quiet">${esc(l.time || '')}</td>
        <td><span>${esc(l.label)}</span>${(l.earlier || []).map(([m, v]) => ` <span class="pill">${v === l.amount
          ? th('entries.for_month', ...monthWords(m)) : th('flow.amount_for', money(v), ...monthWords(m))}</span>`).join('')}</td>
        <td class="num">${l.out ? money(l.amount) : ''}</td>
        <td class="num">${l.out ? '' : money(l.amount)}</td></tr>`).join(''),
      `<tr class="tot"><td colspan="3">${lines.length === 1 ? th('flow.entries_one', 1) : th('flow.entries_many', lines.length)}</td>
        <td class="num">${sum(true) ? money(sum(true)) : ''}</td>
        <td class="num">${sum(false) ? money(sum(false)) : ''}</td></tr>`)}
  </td></tr>`;
}

export function salesByDay() {
  const rows = S.data.sales_by_day;
  if (!rows.length) return '';
  const max = Math.max(...rows.map(r => r[1]));
  const avg = rows.reduce((a, r) => a + r[1], 0) / rows.length;
  const day = d => t(`day.short.${new Date(d + 'T12:00:00').getDay() || 7}`);
  return card(`<h2>${th('sales_night.title')}</h2>
    <p class="sub">${th('sales_night.sub', rows.length, money(avg))}</p>
    ${table(`<th>${th('sales_night.night')}</th><th></th><th class="num">${th('result.sales')}</th>`,
      rows.map(([d, v]) => `<tr><td class="nowrap">${esc(d)} <span class="quiet">${day(d)}</span></td>
        <td style="width:55%"><div class="bar"><span style="width:${max ? v / max * 100 : 0}%"></span></div></td>
        <td class="num">${money(v)}</td></tr>`).join(''))}`);
}

export function closeCard() {
  const per = S.data.period;
  if (per.status === 'closed') {
    return card(`<div class="row">
      <div><strong>${th('close_card.closed', esc(String(per.closed_at || '').slice(0, 10)))}</strong>
        <p class="sub" style="margin:2px 0 0">${th('close_card.counted', esc(per.count_date || '—'))}</p></div>
      <button class="btn" style="margin-inline-start:auto" data-act="reopen">${th('close_card.reopen')}</button>
    </div>`);
  }
  if (S.data.month === S.data.this_month) return '';
  return card(`<div class="row">
      <div><strong>${th('close_card.close_month', ...monthWords(S.data.month))}</strong>
        <p class="sub" style="margin:2px 0 0">${th('close_card.sub')}</p></div>
      <button class="btn primary" style="margin-inline-start:auto" data-act="closeAsk">${th('close_card.close')}</button>
    </div>`);
}

export function everyMonth() {
  const rows = (S.data.summary || []).slice().reverse();
  if (rows.length < 2) return '';
  return card(`<h2>${th('every_month.title')}</h2>
    ${table(`<th>${th('period.month')}</th><th class="num">${th('result.net_profit')}</th><th></th>`,
      rows.map(r => `<tr>
        <td><button class="mini link" data-act="setMonth" data-m="${esc(r.month)}">${esc(monthName(r.month))}</button></td>
        <td class="num ${cls(r.net)}">${money(r.net)}</td>
        <td>${r.status === 'closed' ? `<span class="pill">${th('period.closed')}</span>`
              : r.month === S.data.this_month ? `<span class="pill">${th('period.in_progress')}</span>`
              : `<span class="pill warn">${th('period.not_closed')}</span>`}</td>
      </tr>`).join(''))}`);
}

/* =================================================================== stock */

export function stockFigures() {
  const c = S.data.stock.cogs;
  return tiles([
    tile(t('stock.on_shelves'), money(c.closing), c.date ? t('stock.counted', c.date) : t('stock.no_count')),
    tile(t('stock.at_start'), money(c.opening), c.opening_date ? t('stock.counted', c.opening_date) : ''),
    tile(t('stock.bought'), money(c.purchases), t('stock.receipts_window')),
    tile(t('stock.cogs_sold'), money(c.value), t('stock.cogs_sum'), c.raw < 0 ? 'warnc' : ''),
  ]) + (c.raw < 0 ? `<div class="banner"><h2>${th('stock.negative_title')}</h2>
      <p style="margin:0">${th('stock.negative', money(c.raw))}</p></div>` : '');
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
  const head = `<div class="cardhead"><h2>${th('fill.title')}</h2>
      <div class="right row"><select data-act="fillMix" style="width:auto">
        <option value="">${th('fill.which_mix')}</option>
        ${options(st.mixes.map(m => ({ value: m.id, label: m.name })), f.mix)}</select></div></div>`;
  const recent = fillsList(st.fills);
  if (!mix) {
    return card(`${head}<p class="sub">${th('fill.sub')}</p>${recent}`);
  }
  const loose = it => ((it.levels || []).find(l => l.key === 'loose') || {}).label || '';
  const rows = (f.order || []).filter(id => items[id]).map(id => {
    const it = items[id];
    return `<tr data-fill="${id}"${S.draft.found === id ? ' class="found"' : ''}>
      <td>${esc(it.name)}<br><span class="quiet">${th('fill.per_kg', money(it.cost))}</span></td>
      <td class="num"><input type="number" min="0" step="1" id="fill-${id}" data-fillpack="${id}"
          value="${esc(f.packs[id] ?? '')}" placeholder="0" inputmode="decimal">
        <span class="size">${th('fill.packs_of', esc(loose(it)))}</span></td>
      <td class="num quiet" data-fillgrams="${id}"></td>
      <td class="num" data-fillvalue="${id}"></td>
      <td class="actions"><button class="mini" data-act="fillDrop" data-id="${id}" title="${th('fill.leave_out')}">✕</button></td>
    </tr>`;
  }).join('');
  const sealed = S.data.setup.items.filter(i => i.letter === 'B' && i.active);
  return card(`${head}
    <p class="sub">${mix.usual.length ? th('fill.usual_filled', esc(mix.name)) : th('fill.no_usual', esc(mix.name))}
      ${th('fill.price', money(mix.price))}</p>
    ${rows ? table(`<th>${th('fill.tobacco')}</th><th class="num">${th('fill.packs')}</th><th class="num">${th('fill.grams')}</th>
        <th class="num">${th('fill.cost')}</th><th></th>`, rows,
        `<tr class="tot"><td>${th('fill.into_bucket')}</td><td></td><td class="num" id="fillGrams"></td>
          <td class="num" id="fillValue"></td><td></td></tr>`) : ''}
    <div class="row" style="margin-top:10px">
      <input id="fillItem" list="sealedNames" placeholder="${th('fill.tobacco_or_barcode')}" autocomplete="off"
        spellcheck="false" style="max-width:280px">
      <button class="btn" data-act="fillAdd">${th('common.add')}</button>
      ${mix.usual.length ? `<button class="mini" data-act="fillUsual">${th('fill.back_to_usual')}</button>` : ''}
    </div>
    <datalist id="sealedNames">${sealed.map(i => `<option value="${esc(i.name)}">`).join('')}</datalist>
    <div class="grid-form" style="margin-top:12px">
      ${field(t('fill.filled_on'), `<input type="date" id="fillOn" value="${esc(f.on || S.data.tonight)}" max="${esc(S.data.today)}">`)}
      ${field(t('fill.full_bucket'), `<input type="number" min="0" id="fillGross"
          placeholder="${th('fill.not_weighed')}" inputmode="numeric">`)}
      ${field(t('fill.bucket'), `<select id="fillTare"><option value="">${th('fill.no_bucket')}</option>
          ${options(S.data.stock.count.tares.map(x => ({ value: x.id, label: t('fill.tare', x.name, x.grams) })))}</select>`)}
    </div>
    <label class="tick"><input type="checkbox" id="fillKeep"${mix.usual.length ? '' : ' checked'}>
      ${th('fill.keep_usual', esc(mix.name))}</label>
    <div class="row" style="margin-top:12px">
      <button class="btn primary" data-act="fillBucket">${th('fill.fill_it')}</button>
      <button class="btn" data-act="fillCancel">${th('common.cancel')}</button>
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
      <td class="num">${th('unit.g', f.grams.toLocaleString('en-US'))}</td>
      <td class="num">${money(Math.round(f.value * 1000 / f.grams))}</td>
      <td class="num quiet">${money(f.price_before)} → ${money(f.price_after)}</td>
      <td class="actions">${f.locked ? '' : `<button class="mini danger" data-act="deleteFill"
          data-id="${f.id}">${th('common.delete')}</button>`}</td>
    </tr>`).join('');
  return `<details class="fold"><summary>${th('fills.recent', fills.length)}</summary>
    ${table(`<th>${th('common.date')}</th><th>${th('fills.mix')}</th><th class="num">${th('fills.went_in')}</th><th class="num">${th('fills.cost_kilo')}</th>
      <th class="num">${th('fills.mix_price')}</th><th></th>`, rows)}</details>`;
}

export function countPicker() {
  const s = S.data.stock;
  const c = s.count;
  return card(`<div class="cardhead">
      <h2>${th('count.title')}</h2>
      ${c.locked ? `<span class="pill">${th('count.locked')}</span>` : ''}
      <div class="right row">
        <select data-act="setCount" style="width:auto">
          ${options(s.count_dates.slice().reverse(), s.count_date)}
        </select>
        <input type="date" id="newCount" value="${esc(S.data.tonight)}" max="${esc(S.data.today)}" style="width:auto">
        <button class="btn" data-act="openCount">${th('count.start')}</button>
        ${c.locked || !c.date ? '' : `<button class="mini danger" data-act="deleteCount">${th('count.delete')}</button>`}
      </div>
    </div>
    <p class="sub">${c.locked
      ? th('count.locked_note')
      : c.source === 'carried'
        ? th('count.carried_note')
        : th('count.how')}
      ${c.date ? ` <strong>${th('count.valued', money(c.closing))}</strong>` : ''}</p>`);
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
      ? `<th>${th('count.item')}</th><th>${th('fill.bucket')}</th><th class="num">${th('count.on_scales')}</th>
          <th class="num">${th('count.net')}</th><th class="num">${th('count.value')}</th>`
      : sealed
        ? `<th>${th('count.item')}</th><th class="num">${th('count.cartons')}</th>
            <th class="num">${th('count.blocks')}</th><th class="num">${th('fill.packs')}</th>
            <th class="num">${th('count.kilos')}</th><th class="num">${th('count.value')}</th>`
        : `<th>${th('count.item')}</th><th class="num">${th('count.packages')}</th>
            <th class="num">${th('count.loose')}</th><th class="num">${th('count.comes_to')}</th>
            <th class="num">${th('count.value')}</th>`;
    const cols = sealed ? 6 : 5;
    let brand = null;
    const rows = g.items.map(i => {
      const under = i.parent_id && i.parent_id === brand;
      if (!i.parent_id) brand = i.id;
      const price = `<span class="quiet">${money(i.counted_at)} / ${esc(i.unit)}</span>`;
      const find = findAttrs(i.name, i.parent_id ? null : i.id, i.parent_id);
      // a brand counted by flavour is only their heading, unless this count has it
      if (i.flavours && i.qty_milli == null) {
        return `<tr class="brandh"${find}><td colspan="${cols}"><strong>${esc(i.name)}</strong> ${price}</td></tr>`;
      }
      const q = (i.qty_milli || 0) / 1000;
      const kilos = weighed || sealed;
      return `<tr data-item="${i.id}"${find} class="${[i.active ? '' : 'quiet', under ? 'flavour' : '',
                                                  S.draft.found === i.id ? 'found' : ''].join(' ').trim()}">
        <td>${esc(under ? i.flavour : i.name)}<br>${price}</td>
        ${weighed
          ? `<td><select data-k="tare_id"${ro} style="min-width:110px">
               <option value="">${th('fill.no_bucket')}</option>
               ${options(c.tares.map(x => ({ value: x.id, label: t('fill.tare', x.name, x.grams) })), i.tare_id)}</select></td>
             <td class="num"><input type="number" min="0" data-k="gross_grams" value="${i.gross_grams ?? ''}"
                  placeholder="0"${ro} inputmode="numeric"></td>`
          : sealed
            ? sizes(i)
            : `<td class="num">${box('packages', i.packages_milli)}</td>
               <td class="num">${box('loose', i.loose_milli)}</td>`}
        <td class="num quiet">${!q ? '' : kilos ? th('unit.kg', q.toFixed(3).replace(/\.?0+$/, ''))
          : q.toFixed(3).replace(/\.?0+$/, '')}</td>
        <td class="num">${i.value ? money(i.value) : ''}</td>
      </tr>`;
    }).join('');
    return `<div class="findgroup"><h3 class="grouph">${esc(g.name)}</h3>
      ${table(head, rows, `<tr class="tot"><td>${th('common.total')}</td>
        <td colspan="${cols - 2}"></td><td class="num">${money(g.value)}</td></tr>`)}</div>`;
  }).join('');
  return card(`<div class="cardhead"><h2>${th('count.for', esc(c.date))}</h2>
      <div class="right">${findBox('count')}</div></div>
    <p class="sub">${th('count.quantities')}</p>
    ${body}
    <p class="sub" style="margin-top:14px">${th('count.rounded', `<strong>${th('count.counted_value', money(c.closing))}</strong>`)}</p>`);
}

/* What should be on the shelf, from the count before: receipts in, buckets
   filled, and what the nights sold by what each menu item takes; and the gap
   at this count. */
export function expectedCard() {
  const v = S.data.stock.expected;
  if (!v) return '';
  const cats = Object.fromEntries(S.data.setup.categories.map(c => [c.letter, c.name]));
  const qty = (r, x, withSign) => {
    if (x === null || x === undefined) return '';
    if (Math.abs(x) < 0.0005) return withSign ? '' : '0';
    const sign = x < 0 ? '−' : withSign ? '+' : '';
    const a = Math.abs(x);
    return sign + (['A', 'B'].includes(r.letter)
      ? (a < 1 ? t('unit.g', Math.round(a * 1000)) : t('unit.kg', +a.toFixed(3))) : `${+a.toFixed(2)}`);
  };
  const row = (r, lit) => `<tr${lit && r.flag ? ' class="found"' : ''}${findAttrs(r.name, r.parent_id ? null : r.item, r.parent_id)}>
      <td>${esc(r.name)}${r.minimum !== null && r.should < r.minimum
        ? `<br><span class="warnc">${th('shelf.below_minimum', qty(r, r.minimum))}</span>` : ''}</td>
      <td class="num quiet">${qty(r, r.was)}</td>
      <td class="num quiet">${qty(r, r.in, true)}</td>
      <td class="num quiet">${qty(r, r.buckets, true)}</td>
      <td class="num quiet">${qty(r, -r.sold, true)}</td>
      <td class="num">${qty(r, r.should)}</td>
      <td class="num">${r.counted === null ? `<span class="quiet">${th('shelf.not_counted')}</span>` : qty(r, r.counted)}</td>
      <td class="num ${r.flag ? (r.gap < 0 ? 'neg' : 'warnc') : 'quiet'}">${r.gap === null ? ''
        : `${qty(r, r.gap, true) || '—'}${r.flag && r.worth ? `<br>${money(r.worth)}` : ''}`}</td>
    </tr>`;
  const head = `<th>${th('count.item')}</th><th class="num">${th('shelf.at', esc(v.from))}</th><th class="num">${th('common.in')}</th>
    <th class="num">${th('shelf.buckets')}</th><th class="num">${th('shelf.sold')}</th><th class="num">${th('shelf.should_be')}</th>
    <th class="num">${th('shelf.counted')}</th><th class="num">${th('shelf.gap')}</th>`;
  const grouped = (list, lit) => {
    let last = null;
    return list.map(r => {
      const h = r.letter !== last ? `<tr class="typeh"><td colspan="8">${esc(cats[r.letter] || r.letter)}</td></tr>` : '';
      last = r.letter;
      return h + row(r, lit);
    }).join('');
  };
  const off = v.rows.filter(r => r.flag);
  const says = v.counted
    ? (off.length
      ? (off.length === 1 ? th('shelf.off_one', 1, money(-v.short), money(v.over))
        : th('shelf.off_many', off.length, money(-v.short), money(v.over)))
      : th('shelf.all_well'))
    : th('shelf.no_count', esc(v.to));
  const caveats = [
    v.not_set.length === 1
      ? th('shelf.not_set_one', 1, v.not_set.map(n => `<bdi>${esc(n)}</bdi>`).join(', '))
      : v.not_set.length
        ? th('shelf.not_set_many', v.not_set.length, v.not_set.map(n => `<bdi>${esc(n)}</bdi>`).join(', ')) : '',
    v.heads_unknown ? th('shelf.heads_unknown', +v.heads_unknown.toFixed(1)) : '',
  ].filter(Boolean);
  return card(`<div class="cardhead"><h2>${th('shelf.title')}</h2>
      <div class="right">${findBox('shelf')}</div></div>
    <p class="sub">${th('shelf.from_count', esc(v.from), esc(v.to), `<strong>${says}</strong>`)}</p>
    ${off.length ? table(head, grouped(off)) : ''}
    <details class="fold"><summary>${th('shelf.every_item', v.rows.length)}</summary>
      ${table(head, grouped(v.rows, true))}</details>
    ${caveats.map(c => `<p class="note">${c}</p>`).join('')}
    <div class="row" style="margin-top:10px;align-items:center">
      <label style="margin:0">${th('shelf.may_dry')}</label>
      ${save('drying_pct', {}, 'pct', v.drying || '', 'type="number" min="0" max="50" step="0.5" inputmode="decimal" placeholder="0" style="max-width:80px"')}
      <span class="quiet">${th('shelf.between_counts')}</span>
    </div>`);
}

/* Foil, coal and the like: hookahs to each one, learnt between counts. */
export function ratiosCard() {
  const r = S.data.stock.ratios;
  const taken = new Set(r.items.map(x => x.item));
  const candidates = S.data.setup.items.filter(i => i.active && !['A', 'B'].includes(i.letter)
                                                 && !taken.has(i.id));
  if (!r.items.length && !candidates.length) return '';
  const fmt = x => (x === null || x === undefined ? '—'
    : (+x.toFixed(x < 10 ? 1 : 0)).toLocaleString('en-US'));
  const rows = r.items.map(x => `<tr>
      <td>${esc(x.name)}${x.dropped ? `<br><span class="neg">${th('ratios.going')}</span>` : ''}</td>
      <td class="num">${x.ratio ? fmt(x.ratio) : `<span class="quiet">${th('ratios.not_yet')}</span>`}</td>
      <td class="num">${x.a_night ? fmt(x.a_night) : ''}</td>
      <td class="quiet">${x.pairs.map(p => `${esc(p.to.slice(5))}: ${p.ratio ? fmt(p.ratio) : '—'}`).join(' · ')}</td>
      <td class="actions"><button class="mini" data-do="per_hookah"
          data-args="${args({ id: x.item, on: 0 })}">${th('ratios.stop')}</button></td>
    </tr>`).join('');
  return card(`<h2>${th('ratios.title')}</h2>
    <p class="sub">${th('ratios.sub')}${r.a_night ? th('ratios.lately', fmt(r.a_night)) : ''}</p>
    ${r.hookahs_known ? '' : `<p class="note warnc">${th('ratios.give_tobacco')}</p>`}
    ${rows ? table(`<th>${th('count.item')}</th><th class="num">${th('ratios.to_each')}</th><th class="num">${th('ratios.a_night')}</th>
      <th>${th('ratios.by_count')}</th><th></th>`, rows) : ''}
    ${candidates.length ? `<div class="row addrow">
      <select data-f="id" style="max-width:260px">${options(candidates.map(i => ({ value: i.id, label: i.name })))}</select>
      <button class="btn" data-add="per_hookah" data-args="${args({ on: 1 })}">${th('ratios.goes_with')}</button>
    </div>` : ''}`);
}

export function receiptForm() {
  const sup = S.data.people.supplier.filter(s => s.active);
  return card(`<h2>${th('receipt_form.title')}</h2>
    <p class="sub">${th('receipt_form.sub')}</p>
    <div class="grid-form">
      ${field(t('common.date'), `<input type="date" id="rDate" value="${esc(S.data.tonight)}" max="${esc(S.data.today)}">`)}
      ${field(t('entries.supplier'), `<select id="rSup">${options(sup.map(s => s.name))}</select>`)}
      ${field(t('receipt_form.number'), `<input id="rNo" placeholder="${th('receipt_form.optional')}">`)}
      ${field(t('common.for'), `<input id="rWhat" placeholder="${th('receipt.several')}">`)}
      ${field(t('common.total'), amountInput('rAmt'))}
      ${field(t('common.terms'), `<select id="rTerms"><option value="credit">${th('entries.on_credit')}</option>
                        <option value="cash">${th('entries.paid_cash')}</option></select>`)}
      ${field(t('receipt_form.paid_from'), `<select id="rPot">${potOptions()}</select>`)}
      <div><button class="btn primary" data-act="receipt">${th('common.add')}</button></div>
    </div>`);
}

export function receiptList() {
  const rows = S.data.stock.receipts;
  const now = rows.filter(r => r.period === S.data.month);
  const older = rows.filter(r => r.period !== S.data.month);
  const open = S.draft.rlines;
  const isOpen = e => e.receipt && e.receipt.id === open;
  const list = rs => table(`<th>${th('common.date')}</th><th>${th('common.what')}</th><th>${th('common.details')}</th><th>${th('common.pot')}</th>
      <th class="num">${th('common.amount')}</th><th></th>`,
    rs.map(e => entryRow(e, { lines: true }) + (isOpen(e) ? linesRow(e) : '')).join(''));
  const names = S.data.setup.items.filter(i => i.active && i.letter !== 'A');
  return card(`<h2>${th('receipts.in_month', ...monthWords(S.data.month))}</h2>
    ${now.length ? list(now) : empty(t('receipts.none'))}
    ${older.length ? `<details class="fold"${older.some(isOpen) ? ' open' : ''}>
      <summary>${th('receipts.every_other', older.length)}</summary>${list(older)}</details>` : ''}
    <datalist id="stockNames">${names.map(i => `<option value="${esc(i.name)}">`).join('')}</datalist>`);
}

/* What came in on one receipt: a line per item, in the boxes it comes in,
   saved as you leave it, like the count sheet. */
function linesRow(e) {
  const rid = e.receipt.id;
  const closed = closedMonths();
  const ro = closed.has(e.period) ? ' disabled' : '';
  const saved = e.lines;
  const pending = ((S.draft.rpending || {})[rid] || [])
    .filter(id => !saved.some(l => l.item === id))
    .map(id => S.data.setup.items.find(i => i.id === id)).filter(Boolean)
    .map(i => ({ item: i.id, name: i.name, letter: i.letter, levels: i.levels, pending: true }));
  // what one line is counted in: rline.many_<it> and rline.one_<it> in the words
  const unit = l => (l.letter === 'B' ? 'kg' : l.letter === 'E' ? 'carton'
    : l.levels.length > 1 ? 'package' : 'piece');
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
    const u = unit(l);
    return `<tr data-item="${l.item}" data-receipt="${rid}">
      <td>${esc(l.name)}</td>
      <td>${sizes(l)}</td>
      <td class="num quiet">${q ? th(`rline.many_${u}`, +q.toFixed(3)) : ''}
        ${q && l.amount ? `<br>${th(`rline.one_${u}`, money(Math.round(l.amount / q)))}` : ''}</td>
      <td class="num"><input ${MONEY} data-k="amount" value="${esc(commas(l.amount))}"
          placeholder="—"${ro}></td>
      <td class="actions">${ro ? '' : l.pending
        ? `<button class="mini" data-act="dropRLine" data-id="${l.item}" title="${th('fill.leave_out')}">✕</button>`
        : `<button class="mini" data-do="receipt_line" data-args="${args({ receipt: rid, item: l.item })}"
             title="${th('rline.take_off')}">✕</button>`}</td>
    </tr>`;
  };
  const priced = saved.filter(l => l.amount != null);
  const sum = priced.reduce((a, l) => a + l.amount, 0);
  const note = !saved.length ? th('rline.nothing')
    : priced.length < saved.length
      ? (priced.length
        ? th('rline.no_amount_others', saved.length - priced.length, saved.length, money(sum), money(e.amount))
        : th('rline.no_amount', saved.length - priced.length, saved.length))
      : sum === e.amount ? th('rline.total', money(sum))
        : sum < e.amount ? th('rline.less', money(sum), money(e.amount - sum), money(e.amount))
          : th('rline.more', money(sum), money(sum - e.amount), money(e.amount));
  return `<tr class="drill"><td colspan="6">
    <div class="cardhead"><strong>${th('entries.what_came_in')}</strong>
      <span class="quiet">${esc(e.detail || '')} · ${esc(e.happened_on)}</span>
      <div class="right"><button class="mini" data-act="receiptLines" data-id="${rid}">${th('common.close')}</button></div></div>
    ${saved.length || pending.length ? table(`<th>${th('count.item')}</th><th>${th('rline.how_many')}</th><th class="num">${th('count.comes_to')}</th>
        <th class="num">${th('common.amount')}</th><th></th>`, [...saved, ...pending].map(row).join('')) : ''}
    ${ro ? '' : `<div class="row" style="margin-top:10px">
      <input id="rlItem" list="stockNames" placeholder="${th('rline.item_or_barcode')}" autocomplete="off"
        spellcheck="false" style="max-width:300px">
      <button class="btn" data-act="addRLine">${th('common.add')}</button></div>`}
    <p class="note">${note}</p>
  </td></tr>`;
}

export function countHistory() {
  const rows = S.data.stock.counts;
  return card(`<h2>${th('counts.title')}</h2>
    ${rows.length ? table(
      `<th>${th('counts.date')}</th><th class="num">${th('counts.valued_at')}</th><th>${th('counts.where_from')}</th>`,
      rows.map(r => `<tr><td>${esc(r.count_date)}</td>
        <td class="num">${money(r.closing)}</td>
        <td class="quiet">${r.source !== 'counted' ? th('counts.carried')
          : r.has_lines || r.closing ? th('counts.item_by_item')
            : th('counts.started')}</td></tr>`).join(''))
      : empty(t('counts.none'))}`);
}

/* =================================================================== books */

// what a new entry can be; each is called entry_kind.<it> in the words
const ENTRY_KINDS = ['expense', 'staff_advance', 'staff_repay', 'pay_salary', 'partner_draw', 'partner_in',
                     'pay_supplier', 'pay_fixed', 'pay_electricity', 'income', 'transfer'];

export function newEntryCard() {
  const lists = S.data.lists;
  const people = S.data.people;
  const kind = S.draft.kind || 'expense';
  const active = list => list.filter(a => a.active).map(a => a.name);
  const detailsFor = {
    expense: lists.expense || [], income: lists.income || [],
    staff_advance: active(people.staff), staff_repay: unsettled(people.staff, -1),
    pay_salary: unsettled(people.staff, 1), pay_supplier: unsettled(people.supplier, 1),
    partner_draw: active(people.partner), partner_in: active(people.partner),
    pay_fixed: S.data.fixed_names || [],
  };
  const isTransfer = kind === 'transfer';
  const into = ['income', 'staff_repay', 'partner_in'].includes(kind);
  const closed = closedMonths();
  const months = S.data.months.filter(m => m <= S.data.this_month && !closed.has(m));
  return card(`<h2>${th('new_entry.title')}</h2>
    <p class="sub">${isTransfer
      ? th('new_entry.transfer_note')
      : th('new_entry.note')}</p>
    <div class="grid-form">
      ${field(t('common.date'), `<input type="date" id="eDate" value="${esc(S.data.tonight)}" max="${esc(S.data.today)}">`)}
      ${field(t('common.what'), `<select id="eKind" data-act="pickKind">${options(
        ENTRY_KINDS.map(k => ({ value: k, label: t(`entry_kind.${k}`) })), kind)}</select>`)}
      ${isTransfer
        ? field(t('common.from'), `<select id="eFrom">${potOptions()}</select>`)
          + field(t('common.to'), `<select id="eTo">${options(S.data.pots.filter(p => p.active).map(p => p.name),
              (S.data.pots.find(p => p.active && !p.main) || {}).name)}</select>`)
        : (detailsFor[kind] ? field(t('common.who_or_what'), `<select id="eDetail">${options(detailsFor[kind])}</select>`) : '')
          + field(into ? t('common.into') : t('common.out_of'), `<select id="ePot">${potOptions()}</select>`)}
      ${field(t('common.amount'), amountInput('eAmt'))}
      <div><button class="btn primary" data-act="addEntry">${th('new_entry.add')}</button></div>
    </div>
    <details class="fold"><summary>${th('new_entry.another_month')}</summary>
      <div class="row" style="margin-top:8px">
        <select id="ePeriod" style="max-width:200px">
          <option value="">${th('new_entry.its_date')}</option>
          ${options(months.slice().reverse().map(m => ({ value: m, label: monthName(m) })))}</select>
        <span class="quiet">${th('new_entry.older_month')}</span>
      </div>
    </details>`);
}

export function entryList() {
  const sr = S.search;
  const rows = sr ? sr.rows : S.data.entries;
  return card(`<div class="cardhead">
      <h2>${!sr ? esc(monthName(S.data.month))
        : sr.rows.length >= 300 ? th('entries.found_more', sr.rows.length) : th('entries.found', sr.rows.length)}</h2>
      ${sr ? '' : `<span class="pill">${rows.length === 1 ? th('flow.entries_one', 1)
        : th('flow.entries_many', rows.length)}</span>`}
      <div class="right row">
        <input id="q" placeholder="${th('entries.search_hint')}" value="${esc(sr ? sr.q : '')}"
          style="width:300px">
        <button class="btn" data-act="search">${th('entries.search')}</button>
        ${sr ? `<button class="mini" data-act="clearSearch">${th('entries.back_to_month')}</button>` : ''}
      </div>
    </div>
    ${rows.length ? entryTable(rows)
      : empty(sr ? t('entries.nothing_matches') : t('entries.nothing_for', ...monthWords(S.data.month)))}`);
}

export function recentChanges() {
  const rows = S.data.recent;
  if (!rows.length) return '';
  return card(`<div class="cardhead"><h2>${th('recent.title')}</h2>
      <div class="right"><button class="btn" data-act="printChanges">${th('common.print')}</button></div></div>
    <p class="sub">${th('recent.sub')}</p>
    ${table(`<th>${th('recent.when')}</th><th>${th('recent.what_happened')}</th><th></th>`,
      rows.slice(0, 25).map(r => `<tr><td class="nowrap quiet">${esc(localTime(r.at))}</td>
        <td>${esc(r.summary)}</td>
        <td>${r.can_put_back ? `<button class="mini" data-act="putBack" data-id="${r.entry}">${th('recent.put_back')}</button>` : ''}</td>
      </tr>`).join(''))}`);
}

export function whereMoneyIs() {
  const pots = S.data.pots.filter(p => p.active && (p.in_use || p.balance));
  const floats = S.data.people.float.length > 0;
  return card(`<h2>${th('pots.title')}</h2>
    <p class="sub">${th('pots.own')}${floats
      ? th('pots.float_note') : ''}</p>
    <div class="potgrid">${pots.map(p => `
      <div class="pot${p.kind === 'float' ? ' isfloat' : ''}">
        <div class="nm">${esc(p.name)}${p.main ? ` <span class="pill">${th('pots.main')}</span>` : ''}</div>
        <div class="bal ${cls(p.balance)}">${money(p.balance)}</div>
        <div class="sub">${p.kind === 'float' ? th('pots.held') : th('pots.your_cash')}</div>
      </div>`).join('')}</div>
    ${tiles([
      tile(t('common.cash_on_hand'), money(S.data.cash), t('pots.own_only')),
      floats ? tile(t('common.in_hands'), money(S.data.floats), t('common.floats')) : '',
      floats ? tile(t('common.total'), money(S.data.cash + S.data.floats)) : '',
    ])}`);
}

export function cashCountsCard() {
  const rows = S.data.counts.slice().reverse();
  const open = rows.filter(r => r.diff !== 0);
  const head = `<th>${th('common.date')}</th><th class="num">${th('cash_counts.books_said')}</th><th class="num">${th('shelf.counted')}</th>
       <th class="num">${th('cash_counts.out_by')}</th><th>${th('cash_counts.where')}</th><th>${th('cash_counts.reason')}</th><th></th>`;
  const row = r => `<tr>
        <td class="nowrap">${esc(r.on)}</td>
        <td class="num">${money(r.expected)}</td>
        <td class="num">${money(r.counted)}</td>
        <td class="num ${r.found ? cls(r.found) : ''}">${r.found ? signed(r.found) : '—'}
          ${r.written_off ? `<br><span class="quiet">${th('cash_counts.written_off')}</span>` : ''}</td>
        <td class="quiet">${r.split
          ? esc(r.pots.filter(p => p.found).map(p => p.name + ' ' + signed(p.found)).join(', ') || t('cash_counts.all_tie'))
          : esc(r.pots.map(p => p.name).join(', '))}</td>
        <td class="quiet">${esc(r.reason || '')}</td>
        <td class="actions">
          ${r.diff ? `<button class="mini" data-act="writeOff" data-id="${r.id}">${th('cash_counts.write_off')}</button>` : ''}
          ${r.written_off ? '' : `<button class="mini danger" data-act="deleteCashCount" data-id="${r.id}">${th('common.delete')}</button>`}
        </td>
      </tr>`;
  // anything that does not tie stays in view however old it is
  const recent = rows.filter((r, i) => i < 14 || r.diff !== 0);
  const older = rows.filter((r, i) => i >= 14 && r.diff === 0);
  return card(`<h2>${th('cash_counts.title')}</h2>
    <p class="sub">${th('cash_counts.sub')}
      ${open.length ? `<strong class="warnc">${th('cash_counts.do_not_tie', open.length, rows.length)}</strong>
        ${th('cash_counts.find_missing')}`
        : th('cash_counts.all_tied', rows.length)}</p>
    ${rows.length ? table(head, recent.map(row).join('')) : empty(t('counts.none'))}
    ${older.length ? `<details class="fold"><summary>${th('cash_counts.older', older.length)}</summary>
      ${table(head, older.map(row).join(''))}</details>` : ''}`);
}

/* =================================================================== setup */

const save = (action, a, fieldName, value, extra = '') =>
  `<input data-save="${action}" data-args="${args(a)}" data-field="${fieldName}"
     value="${esc(value ?? '')}" ${extra}>`;

const addRow = (action, fixed, fields, button = t('common.add')) =>
  `<div class="row addrow" style="margin-top:12px">
     ${fields.map(([f, placeholder, type, width]) =>
       `<input data-f="${f}" placeholder="${esc(placeholder)}" ${type === 'money' ? MONEY : `type="${type || 'text'}"`}
          style="max-width:${width || 200}px" ${type === 'number' ? 'min="0" inputmode="decimal"' : ''}>`).join('')}
     <button class="btn" data-add="${action}" data-args="${args(fixed)}">${button}</button>
   </div>`;

export function editAccounts(kind, title, note) {
  const list = S.data.people[kind] || [];
  const live = list.filter(a => a.active);
  const gone = list.filter(a => !a.active);
  const sal = S.data.setup.salaries;
  const extraHead = kind === 'staff' ? `<th class="num">${th('accounts.salary_month')}</th>`
    : kind === 'partner' ? `<th class="num">${th('accounts.share_pct')}</th>` : '';
  const balHead = { staff: th('accounts.owed_to_them'), supplier: th('accounts.owed_to_them'),
                    cash: th('accounts.holds'), float: th('accounts.holds') }[kind] || th('common.balance');
  const bal = a => {
    if (kind === 'staff' && a.balance < 0) return `<span class="warnc">${th('payroll.ahead', money(-a.balance))}</span>`;
    if (kind === 'supplier' && a.balance < 0) return `<span class="warnc">${th('accounts.in_credit', money(-a.balance))}</span>`;
    return `<span class="${a.balance < 0 ? 'neg' : ''}">${money(a.balance)}</span>`;
  };
  // the days someone on the staff started and left decide their first and last
  // months; each can be put right while it still changes something
  const leftDay = a => (kind !== 'staff' ? '' : (a.start_open
    ? `<br><button class="mini link" data-act="started" data-id="${a.id}" data-name="${esc(a.name)}"
         data-on="${esc(a.meta.started_on)}">${th('payroll.started', esc(a.meta.started_on))}</button>` : '')
    + (!a.active && !a.meta.former
      ? `<br><button class="mini link" data-act="hasLeft" data-id="${a.id}" data-name="${esc(a.name)}"
           data-on="${esc(a.meta.left_on || '')}">${a.meta.left_on
             ? th('payroll.left', esc(a.meta.left_on)) : th('accounts.which_day')}</button>` : ''));
  const row = a => `<tr>
      <td>${save('account_rename', { id: a.id }, 'name', a.name)}${leftDay(a)}</td>
      ${kind === 'staff' ? `<td class="num">${save('set_salary', { id: a.id }, 'amount', commas(sal[a.id] || ''),
          `${MONEY} style="max-width:140px"`)}</td>` : ''}
      ${kind === 'partner' ? `<td class="num">${save('set_share', { id: a.id }, 'share',
          Math.round((a.meta.share || 0) * 1000) / 10, 'type="number" step="1" min="0" max="100" style="max-width:90px"')}</td>` : ''}
      <td class="num">${bal(a)}</td>
      <td>${a.active
        ? (kind === 'staff'
          ? `<button class="mini" data-act="hasLeft" data-id="${a.id}" data-name="${esc(a.name)}">${th('accounts.has_left')}</button>`
          : `<button class="mini" data-do="account_active" data-args="${args({ id: a.id, active: 0 })}">${th('accounts.retire')}</button>`)
        : (kind === 'staff' && a.meta.left_on
          ? `<button class="mini" data-act="cameBack" data-id="${a.id}" data-name="${esc(a.name)}"
               data-on="${esc(a.meta.left_on)}">${th('accounts.bring_back')}</button>`
          : `<button class="mini" data-do="account_active" data-args="${args({ id: a.id, active: 1 })}">${th('accounts.bring_back')}</button>`)}</td>
    </tr>`;
  const fields = [['name', t('accounts.name')]];
  if (kind === 'staff') fields.push(['salary', t('payroll.salary'), 'money', 140]);
  if (kind === 'partner') fields.push(['share', t('accounts.share_pct'), 'number', 100]);
  const head = `<th>${th('accounts.name')}</th>${extraHead}<th class="num">${balHead}</th><th></th>`;
  const shares = kind === 'partner'
    ? Math.round(live.reduce((n, a) => n + (a.meta.share || 0), 0) * 1000) / 10 : 100;
  return card(`<h2>${esc(title)}</h2>${note ? `<p class="sub">${esc(note)}</p>` : ''}
    ${shares !== 100 ? `<p class="note warnc">${th('accounts.shares_off', shares)}</p>` : ''}
    ${live.length ? table(head, live.map(row).join('')) : empty(t('accounts.none_yet'))}
    ${gone.length ? `<details class="fold"><summary>${kind === 'staff' ? th('accounts.have_left', gone.length) : th('accounts.retired', gone.length)}</summary>
      ${table(head, gone.map(row).join(''))}</details>` : ''}
    ${addRow('account_add', { kind }, fields)}`);
}

export function floatsCard() {
  const list = S.data.people.float;
  if (list.length) return editAccounts('float', t('floats.title'), t('floats.note'));
  return card(`<details class="fold"><summary>${th('floats.none')}</summary>
    <p class="sub">${th('floats.sub')}</p>
    ${addRow('account_add', { kind: 'float' }, [['name', t('floats.who_holds')]])}</details>`);
}

export function editFixed() {
  const rows = S.data.setup.fixed.filter(f => f.active).map(f => `<tr>
      <td>${esc(f.name)}</td>
      <td class="num">${save('fixed_set', { name: f.name }, 'amount', commas(f.amount),
        `${MONEY} style="max-width:150px"`)}</td>
      <td class="quiet">${f.from_month ? th('fixed.since', ...monthWords(f.from_month)) : ''}</td>
      <td><button class="mini" data-do="fixed_remove" data-args="${args({ name: f.name })}"
            data-confirm="${th('fixed.stop_ask', esc(f.name))}"
            data-confirm-body="${th('fixed.stop_body', ...monthWords(S.data.month), esc(f.name))}"
            data-yes="${th('fixed.stop')}">${th('fixed.stop')}</button></td>
    </tr>`).join('');
  return card(`<h2>${th('fixed.title')}</h2>
    <p class="sub">${th('fixed.sub', ...monthWords(S.data.month))}</p>
    ${rows ? table(`<th>${th('common.what')}</th><th class="num">${th('fixed.a_month')}</th><th></th><th></th>`, rows) : empty(t('fixed.nothing'))}
    ${addRow('fixed_set', {}, [['name', t('common.what')], ['amount', t('fixed.amount_month'), 'money', 150]])}`);
}

export function editList(name, title, note) {
  const list = S.data.lists[name] || [];
  return card(`<h2>${esc(title)}</h2>${note ? `<p class="sub">${esc(note)}</p>` : ''}
    <div class="chips">${list.map(v => `<button data-do="list_remove" title="${th('lists.remove')}"
        data-args="${args({ list: name, value: v })}">${esc(v)} ✕</button>`).join('')
        || `<span class="quiet">${th('lists.nothing_yet')}</span>`}</div>
    ${addRow('list_add', { list: name }, [['value', t('lists.add_one')]])}`);
}

export function editItems() {
  const s = S.data.setup;
  const sups = S.data.people.supplier.map(a => ({ value: a.id, label: a.name }));
  const whole = 'type="number" min="0" inputmode="numeric"';
  const codes = i => `<div class="codes">${(i.barcodes || []).map(c => `<button class="mini"
        data-do="item_update" data-args="${args({ id: i.id, barcode_remove: c })}"
        title="${th('items.barcode_off')}">${esc(c)} ✕</button>`).join('')}
      ${save('item_update', { id: i.id }, 'barcode_add', '',
        `placeholder="${th('items.scan_or_type')}" autocomplete="off" spellcheck="false" data-scan`)}</div>`;
  const groups = s.categories.map(c => {
    const items = s.items.filter(i => i.letter === c.letter);
    if (!items.length) return '';
    const sealed = c.letter === 'B';
    const packs = !['A', 'B', 'E'].includes(c.letter);
    const unit = { A: th('items.kg'), B: th('items.kg'), E: th('items.cartons') }[c.letter] || th('items.packages');
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
        return `<tr${under ? ' class="flavour"' : ''}${findAttrs(i.name, i.parent_id ? null : i.id, i.parent_id)}>
          <td>${save('item_update', u, 'name', under ? i.flavour : i.name)}</td>
          <td class="num">${save('item_update', u, 'price', b && !i.price ? '' : commas(i.price),
            `${MONEY} style="max-width:110px"${b ? ` placeholder="${esc(commas(b.price))}"` : ''}`)}</td>
          ${sealed ? `<td>${save('item_update', u, 'packs', i.comes_as,
            `placeholder="${esc(i.comes_as_else)}" style="max-width:130px" spellcheck="false"`)}</td>` : ''}
          ${packs ? `<td class="num">${save('item_update', u, 'pack_size', i.pack_size || '',
            `${whole} style="max-width:90px"`)}</td>` : ''}
          <td class="num">${save('item_update', u, 'minimum', i.minimum ?? '',
            `type="number" min="0" step="0.1" inputmode="decimal" placeholder="${unit}" style="max-width:90px"`)}</td>
          <td>${codes(i)}</td>
          <td><select data-save="item_supplier" data-args="${args(u)}" data-field="supplier_id"
              style="min-width:140px">
            <option value="">${b ? th('items.as_brand') : '—'}</option>${options(sups, i.supplier_id)}</select></td>
          <td class="actions"><button class="mini" data-do="item_update" data-args="${args({ id: i.id, active: i.active ? 0 : 1 })}"
            ${i.active && n ? `data-confirm="${esc(n === 1 ? t('items.stop_one', i.name, 1) : t('items.stop_many', i.name, n))}"
              data-yes="${th('items.stop')}"` : ''}>
            ${i.active ? th('items.stop') : th('accounts.bring_back')}</button></td>
        </tr>`;
      }).join('');
    };
    const live = items.filter(i => i.active);
    const gone = items.filter(i => !i.active);
    const brands = live.filter(i => !i.parent_id).map(i => ({ value: i.id, label: i.name }));
    const head = `<th>${th('count.item')}</th><th class="num">${th('items.price')}</th>${sealed ? `<th>${th('items.comes_as')}</th>` : ''}
      ${packs ? `<th class="num">${th('items.pieces')}</th>` : ''}<th class="num">${th('items.warn_below')}</th>
      <th>${th('items.barcodes')}</th><th>${th('common.from')}</th><th></th>`;
    return `<div class="findgroup"><h3 class="grouph">${esc(c.name)}</h3>
      ${live.length ? table(head, rows(live)) : ''}
      ${sealed && brands.length ? `<div class="row addrow">
        <select data-f="brand" data-keep style="max-width:220px">${options(brands)}</select>
        <input data-f="name" placeholder="${th('items.flavour')}" style="max-width:200px">
        <button class="btn" data-add="item_add" data-args="{}">${th('items.add_flavour')}</button></div>` : ''}
      ${gone.length ? `<details class="fold"><summary>${th('items.no_longer', gone.length)}</summary>
        ${table(head, rows(gone))}</details>` : ''}</div>`;
  }).join('');
  return card(`<div class="cardhead"><h2>${th('items.title')}</h2>
      <div class="right">${findBox('items')}</div></div>
    <p class="sub">${th('items.sub')}</p>
    ${groups}
    <div class="row addrow" style="margin-top:14px">
      <input data-f="name" placeholder="${th('items.new')}" style="max-width:200px">
      <select data-f="letter" style="max-width:220px">
        ${options(s.categories.map(c => ({ value: c.letter, label: c.name })))}</select>
      <input data-f="price" placeholder="${th('items.price')}" ${MONEY} style="max-width:120px">
      <input data-f="pack_size" placeholder="${th('items.pieces')}" type="number" min="0" inputmode="numeric" style="max-width:150px">
      <button class="btn" data-add="item_add" data-args="{}">${th('common.add')}</button>
    </div>`);
}

export function editTares() {
  const rows = S.data.setup.tares.map(x => `<tr><td>${esc(x.name)}</td>
      <td class="num">${save('tare_set', { id: x.id }, 'grams', x.grams,
        'type="number" min="0" inputmode="numeric" style="max-width:120px"')}</td></tr>`).join('');
  return card(`<h2>${th('tares.title')}</h2>
    <p class="sub">${th('tares.sub')}</p>
    ${rows ? table(`<th>${th('fill.bucket')}</th><th class="num">${th('tares.grams_empty')}</th>`, rows) : empty(t('tares.none'))}
    ${addRow('tare_set', {}, [['name', t('tares.name')], ['grams', t('tares.grams'), 'number', 120]])}`);
}

export function editConversions() {
  const c = S.data.setup.conversions || {};
  const f = (key, label, def) => field(label, save('conversions_set', {}, key, c[key] ?? def,
    'type="number" min="1" inputmode="numeric"'));
  return card(`<details class="fold"><summary>${th('conversions.title')}</summary>
    <p class="sub">${th('conversions.sub')}</p>
    <div class="grid-form">
      ${f('gramsPerPack', t('conversions.pack'), 50)}
      ${f('packsPerBlock', t('conversions.block'), 10)}
      ${f('blocksPerCarton', t('conversions.carton'), 12)}
      ${f('bucketsPerCarton', t('conversions.ice_cream'), 2)}
    </div></details>`);
}

export function editElecFactors() {
  const f = S.data.setup.elec_factors;
  const box = (key, label) => field(label, save('elec_factors_set', {}, key, f[key],
    'type="number" min="0" inputmode="numeric"'));
  return card(`<details class="fold"><summary>${th('factors.title')}</summary>
    <div class="grid-form">
      ${box('privateAmps', t('factors.private'))}
      ${box('elevatorAmps', t('factors.elevator'))}
      ${box('elevatorShare', t('factors.elevator_share'))}
      ${box('publicRate', t('factors.public_rate'))}
      ${box('publicShare', t('factors.public_share'))}
    </div></details>`);
}

export function businessCard() {
  const b = S.data.business || {};
  return card(`<h2>${th('business.title')}</h2>
    <div class="grid-form">
      ${field(t('business.name'), save('business_set', {}, 'name', b.name))}
      ${field(t('business.smallest_note'), save('business_set', {}, 'note', b.note || S.data.note,
        'type="number" min="1" inputmode="numeric"'))}
    </div>`);
}

/** English or Kurdish, and how much of the app has its Kurdish yet: it comes
    with the app, in lang/ckb.json. */
export function languageCard() {
  const L = S.data.lang;
  const names = L.languages || { en: t('language.en'), ckb: t('language.ckb') };
  return card(`<h2>${th('lang.title')}</h2>
    <p class="sub">${th('lang.sub')}</p>
    <div class="chips" translate="no">${Object.entries(names).map(([k, label]) =>
      `<button data-act="langPick" data-lang="${esc(k)}" aria-pressed="${L.language === k}">${esc(label)}</button>`).join('')}</div>
    <p class="note">${th('lang.done', money(L.done), money(L.total))}${L.done < L.total ? ` ${th('lang.stays_english')}` : ''}</p>`);
}

export function backupCard() {
  const b = S.data.backup;
  const last = b.last || {};
  const when = last.at ? last.at.replace('T', ' ') : t('backup_card.never');
  return card(`<h2>${th('backup_card.title')}</h2>
    <p class="sub">${b.copies === 1 ? th('backup_card.sub_one', 1) : th('backup_card.sub_many', b.copies)}</p>
    <div class="grid-form">
      ${field(t('backup_card.second'), save('backup_folder', {}, 'folder', b.second || '',
        `placeholder="${th('backup_card.example', esc(t('backup.example_path')))}" style="min-width:320px"`))}
      <div><button class="btn primary" data-act="backupNow">${th('backup_card.now')}</button></div>
    </div>
    <p class="note">${last.entries ? th('backup_card.last_entries', esc(when), money(last.entries))
      : th('backup_card.last', esc(when))}
      ${b.second ? (b.second_ok ? `<span class="pos">${th('backup_card.also', esc(b.second))}</span>`
                                : `<span class="neg">${last.second_error
                                  ? th('backup_card.failed_why', esc(b.second), esc(last.second_error))
                                  : th('backup_card.failed', esc(b.second))}</span>`)
                 : `<span class="warnc">${th('backup_card.no_second')}</span>`}
      <br><span class="quiet">${th('backup_card.on_this_pc', esc(b.local_folder))}</span></p>`);
}

export function updateCard() {
  const u = S.draft.update;
  return card(`<h2>${th('update_card.title')}</h2>
    <p class="sub">${th('update_card.sub', esc(S.data.version))}</p>
    <div class="row">
      <button class="btn" data-act="checkUpdate">${th('update_card.check')}</button>
      ${u && u.newer ? `<button class="btn primary" data-act="installUpdate">${th('update_card.install', esc(u.latest))}</button>` : ''}
      <button class="btn" data-act="health">${th('update_card.health')}</button>
    </div>
    ${u ? `<p class="note">${u.error ? `<span class="neg">${esc(u.error)}</span>`
      : u.newer ? th('update_card.available', esc(u.latest)) : th('update_card.newest')}</p>` : ''}`);
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
    <td class="num">${qty(it.qty)}${it.free ? ` <span class="quiet">${th('sold.free', '+' + qty(it.free))}</span>` : ''}</td>
    <td class="num">${money(it.value)}</td></tr>`;
  const head = `<th>${th('count.item')}</th><th class="num">${th('rline.how_many')}</th><th class="num">${th('sold.came_to')}</th>`;
  const blocks = [...groups.entries()]
    .map(([g, list]) => [g, list, list.reduce((n, i) => n + i.value, 0)])
    .sort((a, b) => b[2] - a[2])
    .map(([g, list, total]) => {
      const shown = limit ? list.slice(0, limit) : list;
      const rest = list.slice(shown.length);
      return `<h3 class="grouph"><bdi>${esc(g || t('sold.other'))}</bdi>
          <span class="quiet">· ${money(total)}</span></h3>
        ${table(head, shown.map(row).join(''))}
        ${rest.length ? `<details class="fold"><summary>${th('common.more', rest.length)}</summary>
          ${table(head, rest.map(row).join(''))}</details>` : ''}`;
    });
  // the biggest groups open, the rest folded away
  return blocks.slice(0, 3).join('') + (blocks.length > 3
    ? `<details class="fold"><summary>${th('sold.more_groups', blocks.length - 3)}</summary>
         ${blocks.slice(3).join('')}</details>` : '');
}

/** What sold on the night on screen, as SambaPOS recorded it. */
export function nightSold() {
  const n = S.data.pos && S.data.pos.night;
  if (!n || !n.tickets) return '';
  const max = Math.max(...n.hours.map(h => h[1]), 1);
  return card(`<h2>${th('sold.what_sold', esc(n.night))}</h2>
    <p class="sub">${th('sold.from_pos', n.tickets, esc(hhmm(n.first_at)), esc(hhmm(n.last_at)), money(n.total))}${
      n.discounts ? th('sold.after_discounts', money(n.discounts)) : ''}.
      ${n.by_kind.length > 1 ? th('sold.paid_as', n.by_kind.map(([k, v]) => `${esc(k)} ${money(v)}`).join(', ')) : ''}</p>
    <div class="sold">${soldTable(n.items, 8)}</div>
    <h3 class="grouph">${th('sold.through_night')}</h3>
    <div class="hours">${n.hours.map(([h, c, v]) => `<div class="hour" title="${th('sold.hour', c, money(v))}">
        <span class="bar v"><span style="height:${c / max * 100}%"></span></span>
        <span class="quiet">${String(h).padStart(2, '0')}</span></div>`).join('')}</div>`);
}

/** The month as SambaPOS saw it, night by night against the books. */
/** When the month sold: through the night, the nights of the week, and the
    tables — from every night kept, which SambaPOS itself cannot keep. */
export function monthWhen() {
  const m = S.data.pos && S.data.pos.month;
  const w = m && m.when;
  if (!w || !w.hours.length) return '';
  const max = Math.max(...w.hours.map(h => h[1]));
  const hours = `<div class="hours">${w.hours.map(([h, c, v]) => `<div class="hour"
      title="${th('sold.hour', c, money(v))}"><span class="bar v"><span style="height:${c / max * 100}%"></span></span>
      <span class="quiet">${String(h).padStart(2, '0')}</span></div>`).join('')}</div>`;
  const best = Math.max(...w.days.map(d => d.average), 1);
  const days = table(`<th>${th('sales_night.night')}</th><th class="num">${th('diffs.nights')}</th><th class="num">${th('when.takings_average')}</th><th></th>`,
    w.days.map(d => `<tr><td>${esc(d.day)}</td><td class="num">${d.nights}</td>
      <td class="num">${money(d.average)}</td><td style="width:38%"><div class="track"><span class="fill"
      style="width:${d.average / best * 100}%"></span></div></td></tr>`).join(''));
  const row = x => `<tr><td><bdi>${esc(x.place)}</bdi></td><td class="num">${x.tickets}</td>
      <td class="num">${money(x.total)}</td>
      <td class="num quiet">${x.minutes === null ? '' : th('when.minutes', x.minutes)}</td></tr>`;
  const head = `<th>${th('when.table')}</th><th class="num">${th('when.tickets')}</th>
      <th class="num">${th('sold.came_to')}</th><th class="num">${th('when.stayed')}</th>`;
  const n = m.nights.length;
  return card(`<h2>${th('when.title')}</h2>
    <p class="sub">${n === 1 ? th('when.tickets_one', m.tickets, 1, Math.round(m.tickets / n))
      : th('when.tickets_many', m.tickets, n, Math.round(m.tickets / n))}${
      w.minutes ? th('when.staying', w.minutes) : ''}.</p>
    <h3 class="grouph">${th('when.opened')}</h3>${hours}
    <h3 class="grouph">${th('when.week')}</h3>${days}
    <h3 class="grouph">${th('when.tables')}</h3>${table(head, w.tables.slice(0, 10).map(row).join(''))}
    ${w.tables.length > 10 ? `<details class="fold"><summary>${th('common.more', w.tables.length - 10)}</summary>
      ${table(head, w.tables.slice(10).map(row).join(''))}</details>` : ''}`);
}

export function monthMakes() {
  const m = S.data.pos && S.data.pos.month;
  if (!m || !m.items.length) return '';
  const moved = m.items.filter(i => i.qty || i.took);           // not only voided
  const known = moved.filter(i => i.makes !== null && i.makes !== undefined)
    .sort((a, b) => b.makes - a.makes);
  const unknown = moved.filter(i => i.makes === null || i.makes === undefined);
  if (!known.length) {
    return card(`<h2>${th('makes.title')}</h2>
      <p class="sub">${th('makes.once_given')}</p>`);
  }
  const qty = q => (Number.isInteger(q) ? String(q) : q.toFixed(2).replace(/\.?0+$/, ''));
  const name = i => `<bdi>${esc(i.item)}</bdi>${i.portion ? ` <span class="quiet"><bdi>${esc(i.portion)}</bdi></span>` : ''}`;
  const row = i => `<tr><td>${name(i)}</td>
      <td class="num">${qty(i.qty)}${i.took > i.qty ? ` <span class="quiet">${th('makes.given', '+' + qty(i.took - i.qty))}</span>` : ''}</td>
      <td class="num">${money(i.value)}</td>
      <td class="num quiet">${money(i.cost)}</td>
      <td class="num ${cls(i.makes)}">${money(i.makes)}</td>
      <td class="num quiet">${i.value ? `${Math.round(i.makes / i.value * 100)}%` : ''}</td></tr>`;
  const head = `<th>${th('count.item')}</th><th class="num">${th('shelf.sold')}</th>
      <th class="num">${th('sold.came_to')}</th><th class="num">${th('makes.stock_took')}</th>
    <th class="num">${th('makes.made')}</th><th class="num">${th('makes.of_price')}</th>`;
  const sum = k => known.reduce((n, i) => n + i[k], 0);
  const names = list => list.map(name).join(', ');
  return card(`<h2>${th('makes.title')}</h2>
    <p class="sub">${known.length === 1
      ? th('makes.sum_one', 1, money(sum('value')), money(sum('cost')), money(sum('makes')), names(known.slice(0, 3)))
      : th('makes.sum_many', known.length, money(sum('value')), money(sum('cost')), money(sum('makes')),
           names(known.slice(0, 3)))}${known.length > 3 ? th('makes.least', names(known.slice(-3).reverse())) : ''}</p>
    ${table(head, known.slice(0, 10).map(row).join(''))}
    ${known.length > 10 ? `<details class="fold"><summary>${th('common.more', known.length - 10)}</summary>
      ${table(head, known.slice(10).map(row).join(''))}</details>` : ''}
    ${unknown.length ? `<details class="fold"><summary>${unknown.length === 1 ? th('makes.no_cost_one', 1)
      : th('makes.no_cost_many', unknown.length)}</summary>
      <p class="note">${th('makes.not_given')}</p>
      <ul class="note">${unknown.map(i => `<li>${name(i)}</li>`).join('')}</ul></details>` : ''}`);
}

export function monthSold() {
  const m = S.data.pos && S.data.pos.month;
  if (!m) return '';
  const books = new Map(S.data.sales_by_day);
  const rows = m.nights.map(n => {
    const b = books.get(n.night) || 0;
    const diff = b - n.takings;
    return `<tr><td class="nowrap">${esc(n.night)}</td>
      <td class="num">${n.tickets}</td>
      <td class="num">${money(n.takings)}${n.unpaid ? ` <span class="warnc">${th('pos_month.unpaid', '+' + money(n.unpaid))}</span>` : ''}</td>
      <td class="num">${b ? money(b) : `<span class="quiet">${th('pos_month.not_entered')}</span>`}</td>
      <td class="num ${diff ? 'warnc' : 'quiet'}">${b ? (diff ? signed(diff) : th('pos_month.same')) : ''}</td></tr>`;
  }).join('');
  return card(`<h2>${th('pos_month.title')}</h2>
    <p class="sub">${m.nights.length === 1 ? th('pos_month.sub_one', 1, m.tickets, money(m.takings))
      : th('pos_month.sub_many', m.nights.length, m.tickets, money(m.takings))}</p>
    ${table(`<th>${th('sales_night.night')}</th><th class="num">${th('when.tickets')}</th>
        <th class="num">${th('pos_month.pos_paid')}</th><th class="num">${th('pos_month.in_books')}</th>
        <th class="num">${th('pos_month.difference')}</th>`, rows)}
    <details class="fold"><summary>${th('pos_month.across')}</summary>
      <div class="sold">${soldTable(m.items, 12)}</div></details>`);
}

/** What else is kept from SambaPOS, for later steps: its own lists. */
function keptLists(c) {
  if (!c) return '';
  // each is kept.<it>_one or kept.<it>_many in the words
  const bits = ['menu_item', 'menu_price', 'payment_type'].filter(k => c[k])
    .map(k => (c[k] === 1 ? t(`kept.${k}_one`, 1) : t(`kept.${k}_many`, c[k])));
  return bits.length ? th('kept.also', bits.join(', ')) : '';
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
  const kept = [esc(st.first), esc(st.last), keptLists(p.catalog), esc(localTime(st.kept_at)),
                esc(String(st.source || '').replace(/^\w+:/, ''))];
  const reading = !a.on ? '' : a.error
    ? `<p class="note warnc">${esc(a.error)}</p>`
    : `<p class="note">${a.newest
        ? (a.read === 1 ? th('auto.read_one', 1, `<bdi>${esc(a.newest.name)}</bdi>`, esc(a.newest_when))
          : th('auto.read_many', a.read, `<bdi>${esc(a.newest.name)}</bdi>`, esc(a.newest_when)))
        : a.in_folder ? th('auto.none_read') : th('auto.none_in_folder')}
        ${!a.waiting ? '' : a.waiting === 1 ? th('auto.reading_one', 1) : th('auto.reading_many', a.waiting)}</p>
      ${a.failed && a.failed.length ? `<details class="fold"><summary>${a.failed.length === 1 ? th('auto.failed_one', 1)
          : th('auto.failed_many', a.failed.length)}</summary><ul>${a.failed.map(f => `<li><bdi>${esc(f.name)}</bdi>
          — ${esc(f.note)}</li>`).join('')}</ul></details>` : ''}`;
  return card(`<h2>${th('sambapos_card.title')}</h2>
    <p class="sub">${th('sambapos_card.sub')}</p>
    <div class="grid-form">
      ${field(t('sambapos_card.folder'), save('pos_settings', {}, 'folder', s.folder,
        `placeholder="${th('backup_card.example', esc(t('pos.example_path')))}"`))}
      ${p.can_read_live ? field(t('sambapos_card.server'), save('pos_settings', {}, 'server', s.server))
        + field(t('sambapos_card.database'), save('pos_settings', {}, 'database', s.database)) : ''}
    </div>
    ${reading}
    <div class="row" style="margin-top:12px">
      ${s.folder ? `<button class="btn primary" data-act="posAuto">${th('sambapos_card.look_now')}</button>
        <button class="btn" data-act="posFolder">${th('sambapos_card.read_again')}</button>` : ''}
      ${p.can_read_live ? `<button class="btn" data-act="posLive">${th('tonight_pos.read_now')}</button>
        <button class="btn" data-act="posTest">${th('sambapos_card.test')}</button>` : ''}
    </div>
    <p class="note">${st.nights
      ? (st.nights === 1 ? th('sambapos_card.kept_one', 1, ...kept) : th('sambapos_card.kept_many', st.nights, ...kept))
      : th('sambapos_card.nothing_kept')}
      ${p.can_read_live ? `<br>${th('sambapos_card.live_note')}`
        : `<br>${th('sambapos_card.windows_note')}`}</p>
    ${p.can_read_live ? `<details class="fold"><summary>${th('sambapos_card.sql_help')}</summary>
      <p class="note">${th('sambapos_card.sql_lines', `<code>sa</code>`)}</p>
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
    return v === 'ignore' ? t('fill.leave_out') : v;
  };
  const current = link ? link.value : '';
  const known = new Set(groups.flatMap(g => g.options.map(o => o[0])));
  // the chosen one says what kind it is too, as a closed picker shows only it
  const opt = (v, text) => (v === current
    ? `<option value="${esc(v)}" selected>${esc(link.label)}</option>`
    : `<option value="${esc(v)}">${esc(text)}</option>`);
  const exp = groups.find(g => g.group === en('link.expense'));
  if (exp) exp.options.push(['new-expense', t('link_picker.new_expense', posName)]);
  return `<select class="link" data-save="pos_link" data-args="${args({ pos_id: posId })}"
      data-field="to" title="${th('link_picker.title')}">
    ${current ? '' : `<option value="" selected disabled>${th('link_picker.what_is')}</option>`}
    ${current && !known.has(current) && current !== 'ignore' ? opt(current, link.label) : ''}
    ${!current && suggest ? `<optgroup label="${th('link_picker.suggested')}">${opt(suggest, label(suggest))}</optgroup>` : ''}
    ${groups.filter(g => g.options.length).map(g => `<optgroup label="${esc(g.group)}">
        ${g.options.map(o => opt(o[0], o[1])).join('')}</optgroup>`).join('')}
    <optgroup label="${th('link_picker.neither')}">${opt('ignore', t('fill.leave_out'))}</optgroup>
  </select>`;
}

/* What each line of a SambaPOS night is, beside the books: the look of its
   pill here, its word pos_status.<it> in the words. */
const POS_STATUS = {
  new: '', added: 'pos', typed: 'pos', check: 'warn', deleted: '', held: 'warn', manual: 'warn', skip: '',
};

/** A SambaPOS account on a night: its name, a picker the first time it is
    seen, and a word if it belongs to someone who has left. */
function posAccount(a) {
  const name = `<bdi>${esc(a.name)}</bdi>${a.type ? ` <span class="quiet"><bdi>${esc(a.type)}</bdi></span>` : ''}`;
  if (!a.link) return `${name}<br>${linkPicker(a.pos_id, a.name, null, a.suggest)}`;
  return a.link.left && !a.link.told
    ? `${name}<br><span class="warnc">${th('pos_account.has_left', esc(a.link.name))}</span>
       <button class="mini link" data-act="posTold" data-pos="${a.pos_id}">${th('pos_account.done')}</button>`
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
    const known = l.status in POS_STATUS;
    const kls = known ? POS_STATUS[l.status] : '';
    const word = known ? th(`pos_status.${l.status}`) : l.status;
    const acct = l.account ? posAccount(l.account)
      : `<span class="quiet">${n.tickets === 1 ? th('drawer.tickets_one', 1) : th('drawer.tickets_many', n.tickets)}</span>`;
    const note = l.note || (l.status === 'new' && l.replaces
      ? t('drawer.replaces', money(l.replaces)) : '');
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
    ? (odd === 1 ? th('drawer.odd_one', 1) : th('drawer.odd_many', odd)) : '';
  const foot = p.held
    ? `<p class="note warnc">${p.held === 1 ? th('drawer.held_one') : th('drawer.held_many')}</p>`
    : p.to_add
      ? `<div class="row" style="margin-top:12px">
           <button class="btn primary" data-act="posAddNight">${th('drawer.add_night')}</button>
           <span class="quiet">${p.to_add === 1 ? th('drawer.adds_one', 1) : th('drawer.adds_many', p.to_add)}</span></div>
         ${odd ? `<p class="note warnc">${oddWords}</p>` : ''}`
      : odd ? `<p class="note warnc">${th('drawer.nothing_more', oddWords)}</p>`
        : `<p class="note">${th('drawer.all_in')}</p>`;
  const only = p.books_only.length
    ? `<p class="note">${th('drawer.only', p.books_only.map(b =>
        `${esc(b.label)} · <bdi>${esc(b.detail || '')}</bdi> ${money(b.amount)}`).join('; '))}</p>` : '';
  return card(`<h2>${th('drawer.title')}</h2>
    <p class="sub">${th('drawer.sub', esc(n.night), `<strong>${money(n.drawer_out)}</strong>`)}${n.drawer_in
        ? th('drawer.into_it', `<strong>${money(n.drawer_in)}</strong>`) : ''}.${!n.opened_by ? ''
        : n.closed_by ? th('drawer.opened_closed', `<bdi>${esc(n.opened_by)}</bdi>`, `<bdi>${esc(n.closed_by)}</bdi>`)
          : th('drawer.opened_open', `<bdi>${esc(n.opened_by)}</bdi>`)}</p>
    ${table(`<th>${th('common.time')}</th><th>${th('drawer.sambapos')}</th><th>${th('drawer.account')}</th>
        <th class="num">${th('common.amount')}</th><th>${th('pos_month.in_books')}</th>`, rows)}
    ${foot}${only}`);
}

/** The menu as SambaPOS has it: names and prices are set there, where the
    customer is charged, and only read here. */
/* What each menu item takes off the shelves, set here once: a hookah a head
   from its bucket, a drink one of itself. */
export function menuUses() {
  const u = S.data.pos && S.data.pos.uses;
  if (!u || !u.menu.length) return '';
  const all = S.data.setup.items;
  const byId = Object.fromEntries(all.map(i => [i.id, i]));
  const pick = r => `<option value=""${r.set ? '' : ' selected'}>${th('uses.not_set')}</option>
      <option value="0"${r.set && !r.item_id ? ' selected' : ''}>${th('uses.nothing')}</option>`
    + S.data.setup.categories.map(c => {
      const list = all.filter(i => i.letter === c.letter && (i.active || i.id === r.item_id));
      return list.length ? `<optgroup label="${esc(c.name)}">${options(
        list.map(i => ({ value: i.id, label: i.name })), r.item_id)}</optgroup>` : '';
    }).join('');
  const row = r => {
    const it = byId[r.item_id];
    const [one, many] = r.unit || ['', ''];
    return `<tr>
      <td><bdi>${esc(r.name)}</bdi></td>
      <td><select data-save="menu_use" data-args="${args({ menu_id: r.menu_id })}" data-field="item_id"
          style="min-width:220px">${pick(r)}</select></td>
      <td class="num">${it ? save('menu_use', { menu_id: r.menu_id }, 'amount', r.amount,
        'type="number" min="0" step="0.5" inputmode="decimal" style="max-width:80px"') : ''}</td>
      <td class="quiet">${it ? esc(r.amount === 1 ? one : many) : ''}</td>
    </tr>`;
  };
  const groups = new Map();
  u.menu.forEach(r => {
    if (!groups.has(r.group)) groups.set(r.group, []);
    groups.get(r.group).push(r);
  });
  const blocks = [...groups.entries()].map(([g, list]) => {
    const unset = list.filter(r => !r.set).length;
    return `<details class="fold"${unset ? ' open' : ''}><summary><bdi>${esc(g || t('uses.no_group'))}</bdi>
        <span class="quiet">${th('uses.how_many_set', list.length - unset, list.length)}</span></summary>
      ${table(`<th>${th('uses.menu_item')}</th><th>${th('uses.takes')}</th><th class="num">${th('uses.how_much')}</th><th></th>`,
        list.map(row).join(''))}</details>`;
  }).join('');
  const amount = x => {
    const it = byId[x.item];
    if (['A', 'B'].includes(x.letter)) return x.qty < 1 ? t('unit.g', Math.round(x.qty * 1000)) : t('unit.kg', +x.qty.toFixed(2));
    if (it && (it.pack_size || 1) > 1) {
      const n = +(x.qty * it.pack_size).toFixed(1);
      return n === 1 ? t('uses.piece_one', 1) : t('uses.piece_many', n);
    }
    return x.letter === 'E' ? t('rline.many_carton', +x.qty.toFixed(2)) : t('rline.many_package', +x.qty.toFixed(2));
  };
  return card(`<h2>${th('uses.title')}</h2>
    <p class="sub">${th('uses.sub', u.set, u.menu.length)}</p>
    <div class="grid-form" style="max-width:420px">
      ${field(t('uses.head_grams'), save('head_grams', {}, 'grams',
        u.head_grams ?? '', 'type="number" min="1" inputmode="numeric"'))}
    </div>
    ${u.took.length ? `<p class="note">${th('uses.took', esc(u.last_night), u.took.map(x =>
      th('uses.amount_of', esc(amount(x)), `<bdi>${esc(x.name)}</bdi>`)).join(', '))}</p>` : ''}
    ${blocks}`);
}

export function sambaposMenu() {
  const m = S.data.pos && S.data.pos.menu;
  if (!m || !m.items) return '';
  const odd = m.odd.length
    ? `<p class="note warnc">${m.odd.length === 1 ? th('menu_card.odd_one', 1, money(S.data.note))
      : th('menu_card.odd_many', m.odd.length, money(S.data.note))}</p><ul class="note">${m.odd.map(o => `<li><bdi>${esc(o.item)}</bdi>${o.portion
          && o.portion !== 'Normal' ? ` · <bdi>${esc(o.portion)}</bdi>` : ''}: ${money(o.price)}</li>`).join('')}</ul>`
    : `<p class="note">${th('menu_card.all_round', money(S.data.note))}</p>`;
  const groups = m.groups.map(g => `<details class="fold"><summary><bdi>${esc(g.name || t('uses.no_group'))}</bdi>
      <span class="quiet">${g.items.length === 1 ? th('menu_card.items_one', 1) : th('menu_card.items_many', g.items.length)}</span></summary>
      ${table(`<th>${th('count.item')}</th><th>${th('menu_card.portion')}</th>
          <th class="num">${th('items.price')}</th><th class="num">${th('menu_card.costs')}</th>
          <th class="num">${th('menu_card.sold_last', m.nights)}</th>`,
        g.items.map(i => i.portions.map((p, n) => `<tr>
          <td>${n ? '' : `<bdi>${esc(i.name)}</bdi>`}</td>
          <td class="quiet"><bdi>${esc(p.name || '')}</bdi>${p.tag ? ` · <bdi>${esc(p.tag)}</bdi>` : ''}</td>
          <td class="num ${p.price && p.price % S.data.note ? 'warnc' : ''}">${p.price === null ? '—' : money(p.price)}</td>
          <td class="num quiet">${p.cost === null || p.cost === undefined ? '' : money(p.cost)}${p.cost
            && p.price ? ` · ${Math.round(p.cost / p.price * 100)}%` : ''}</td>
          <td class="num">${n ? '' : (i.sold ? Number(i.sold).toLocaleString('en') : '<span class="quiet">0</span>')}</td>
        </tr>`).join('')).join(''))}</details>`).join('');
  return card(`<h2>${th('menu_card.title')}</h2>
    <p class="sub">${th('menu_card.sub', m.items, m.groups.length)}</p>${odd}${groups}`);
}

/** Every SambaPOS account money moves through, and what it is in the books. */
export function sambaposAccounts() {
  const p = S.data.pos;
  const rows = p.accounts || [];
  const intro = `<h2>${th('pos_accounts.title')}</h2>
    <p class="sub">${th('pos_accounts.sub')}</p>`;
  if (!rows.length) {
    return card(intro + empty(t('pos_accounts.none')));
  }
  let type = null;
  const body = rows.map(r => {
    const head = r.type !== type
      ? `<tr class="typeh"><td colspan="4"><strong><bdi>${esc(r.type || t('sold.other'))}</bdi></strong></td></tr>` : '';
    type = r.type;
    const person = r.link && ['staff', 'partner', 'supplier'].includes(r.link.as);
    const gone = r.gone
      ? (person && !r.link.left
        ? ` <span class="pill warn">${th('pos_accounts.gone')}</span><br>${th('pos_accounts.has_left', esc(r.link.name))}
            <button class="mini link" data-act="posLeft" data-pos="${r.pos_id}"
              data-name="${esc(r.link.name)}"${r.link.as === 'staff' ? ' data-staff="1"' : ''}>${th('pos_accounts.mark_left')}</button>`
        : ` <span class="pill">${th('pos_accounts.gone')}</span>`) : '';
    return `${head}<tr>
      <td><bdi>${esc(r.name)}</bdi>${r.drawer ? ` <span class="pill">${th('pos_accounts.drawer')}</span>` : ''}${gone}
        ${r.link && r.link.name_then !== r.name
          ? `<br><span class="quiet">${th('pos_accounts.was', `<bdi>${esc(r.link.name_then)}</bdi>`)}</span>` : ''}</td>
      <td class="num">${r.used || '<span class="quiet">—</span>'}</td>
      <td class="nowrap quiet">${esc(String(r.last_at || '').slice(0, 10))}</td>
      <td>${linkPicker(r.pos_id, r.name, r.link, r.suggest)}</td></tr>`;
  }).join('');
  const todo = rows.filter(r => !r.link && !r.gone).length;
  return card(intro + table(`<th>${th('pos_accounts.account')}</th><th class="num">${th('pos_accounts.used')}</th>
      <th>${th('pos_accounts.last')}</th><th>${th('pos_month.in_books')}</th>`, body)
    + `<p class="note">${todo ? th('pos_accounts.not_linked', todo) : th('pos_accounts.all_linked')}</p>`);
}

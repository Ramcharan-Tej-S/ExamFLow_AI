// pages/optimizer.js — LEVEL 5: generate the timetable, run it, track readiness.
import { sprite } from '../sprites.js';
import { api } from '../api.js';
import {
  esc, el, els, badge, tile, empty, panel, dialogue, pageTitle,
  tabs, mountTabs, statBlock, heartMeter, toast, withLoader, fmtDate,
  collapsible, radarChart,
} from '../ui.js';

let subjects = [];

export function renderOptimizer() {
  return `<div class="page"><div class="wrap">
    ${pageTitle(5, 'OPTIMIZER', 'The AI builds the run. You play it, one session at a time.', 'bolt')}
    <div id="opt-stats" class="grid grid-4" style="margin-bottom:26px"></div>
    ${tabs('opt-tabs', ['TIMETABLE', 'READINESS', 'GENERATE'])}
    <div id="opt-body"></div>
  </div></div>`;
}

export async function mountOptimizer() {
  subjects = await api.subjects().catch(() => []);
  if (!subjects.length) {
    el('#opt-body').innerHTML = empty('NO SUBJECTS', 'Register subjects in Data Setup first.');
    el('#opt-stats').innerHTML = '';
    return;
  }
  mountTabs('opt-tabs', show);
  show(0);
}

async function refreshStats() {
  const sessions = await api.sessions().catch(() => []);
  const done = sessions.filter((s) => s.status === 'completed').length;
  const planned = sessions.filter((s) => s.status === 'planned').length;
  const skipped = sessions.filter((s) => s.status === 'skipped').length;
  const pct = sessions.length ? Math.round((done / sessions.length) * 100) : 0;
  el('#opt-stats').innerHTML =
    tile('Total sessions', sessions.length, '', 'blue', 'calendar') +
    tile('Completed', done, pct + '% of the run', 'green', 'trophy') +
    tile('Planned', planned, '', 'teal', 'clock') +
    tile('Skipped', skipped, '', 'red', 'ghost');
  return sessions;
}

async function show(idx) {
  const host = el('#opt-body');
  host.innerHTML = '<div class="empty">LOADING...</div>';
  const sessions = await refreshStats();
  if (idx === 0) tabTimetable(host, sessions);
  else if (idx === 1) await tabReadiness(host, sessions);
  else await tabGenerate(host, sessions);
}

/* ─── Tab 1: the timetable ───────────────────────────────────────── */
function tabTimetable(host, sessions) {
  if (!sessions.length) {
    host.innerHTML = empty('NO PLAN YET', 'Nothing scheduled. Head to the Generate tab and let the optimizer build your run.', 'qblock');
    return;
  }

  const dates = [...new Set(sessions.map((s) => s.session_date))].sort();
  const todayStr = new Date().toISOString().slice(0, 10);
  const skipped = sessions.filter((s) => s.status === 'skipped').length;

  host.innerHTML = `<div class="stack">
    ${panel('WORLD MAP', dayMap(dates, sessions), 'blue', 'flag')}

    ${
      skipped
        ? panel(
            `${skipped} SKIPPED SESSION${skipped > 1 ? 'S' : ''}`,
            `<div class="stack">
              <p class="muted" style="margin:0">Let the optimizer re-book those topics into slots you still have free.</p>
              <button class="btn go block" id="recalc-top">${sprite('bolt', 20)} RECALCULATE PLAN</button>
            </div>`,
            'yellow',
            'ghost'
          )
        : ''
    }

    <p class="muted tiny" style="margin:0">Days are collapsed by default — open the one you're working on.</p>

    ${dates
      .map((d) => {
        const day = sessions.filter((s) => s.session_date === d);
        const done = day.filter((s) => s.status === 'completed').length;
        // Only today's schedule is worth opening on arrival.
        return collapsible(
          fmtDate(d),
          day.map(sessionRow).join(''),
          {
            open: d === todayStr,
            icon: 'calendar',
            color: done === day.length ? 'green' : '',
            note: `${done}/${day.length} CLEARED`,
          }
        );
      })
      .join('')}
  </div>`;

  el('#recalc-top')?.addEventListener('click', runRecalculate);

  els('[data-mark]', host).forEach((btn) =>
    btn.addEventListener('click', async () => {
      try {
        await api.setSessionStatus(btn.dataset.mark, btn.dataset.status);
        toast('ok', btn.dataset.status === 'completed' ? 'SESSION CLEARED' : 'SESSION SKIPPED', '');
        show(0);
      } catch (err) {
        toast('err', 'FAILED', err.message);
      }
    })
  );
}

/** Ask the optimizer to re-book skipped topics into remaining free slots. */
async function runRecalculate() {
  const res = await withLoader('REDISTRIBUTING SKIPPED WORK', () => api.recalculatePlan());
  if (!res) return;
  if (res.added > 0) {
    const tail = res.unplaced ? ` ${res.unplaced} could not fit — your grid is full.` : '';
    toast('ok', 'PLAN RECALCULATED', `${res.added} of ${res.skipped} skipped topic${res.skipped > 1 ? 's' : ''} re-booked.${tail}`);
  } else {
    toast(
      'info',
      'NO ROOM LEFT',
      'Every slot in your availability grid is already booked, so there is nowhere to move the skipped work. Add hours in Schedule → Availability, or push an exam date.'
    );
  }
  show(0);
}

function sessionRow(s) {
  const status = s.status || 'planned';
  const icon = status === 'completed' ? 'trophy' : status === 'skipped' ? 'ghost' : 'qblock';
  const prio = s.priority || 'medium';
  return `<div class="list-row" style="${status !== 'planned' ? 'opacity:.72' : ''}">
    ${sprite(icon, 26, status === 'planned' ? 'bob' : '')}
    <span class="rk">${esc(s.start_time || '--:--')}</span>
    <div class="grow">
      <div class="rt">${esc(s.subject_name || '')}</div>
      <div class="rs">${esc(s.topic_name || 'General review')}</div>
    </div>
    <span class="rs">${esc(s.duration_min ?? 60)} min</span>
    ${badge(prio, prio === 'high' ? 'hard' : prio === 'low' ? 'easy' : 'medium')}
    ${badge(status, status)}
    ${
      status === 'planned'
        ? `<button class="ibtn ok" data-mark="${s.id}" data-status="completed" title="Mark complete">✓</button>
           <button class="ibtn skip" data-mark="${s.id}" data-status="skipped" title="Skip">»</button>`
        : ''
    }
  </div>`;
}

/** A row of level-map tiles, one per scheduled day. */
function dayMap(dates, sessions) {
  const tiles = dates
    .map((d) => {
      const day = sessions.filter((s) => s.session_date === d);
      const done = day.filter((s) => s.status === 'completed').length;
      const all = done === day.length;
      const icon = all ? 'flag' : done > 0 ? 'coin' : 'qblock';
      return `<div style="text-align:center;min-width:74px">
        ${sprite(icon, 38, all ? '' : 'bob')}
        <div class="tiny muted" style="margin-top:4px">${esc(d.slice(5))}</div>
        <div class="tiny mono-num" style="font-size:9px">${done}/${day.length}</div>
      </div>`;
    })
    .join('<div style="align-self:center;color:#9A9AB0">&middot;&middot;&middot;</div>');
  return `<div class="scroll-x"><div class="row" style="flex-wrap:nowrap;gap:10px;padding-bottom:8px">${tiles}</div></div>`;
}

/* ─── Tab 2: readiness ───────────────────────────────────────────── */
async function tabReadiness(host, sessions) {
  if (!sessions.length) {
    host.innerHTML = empty('NO PLAN YET', 'Generate a study plan to unlock readiness tracking.');
    return;
  }

  const rows = [];
  for (const s of subjects) {
    const mine = sessions.filter((x) => x.subject_name === s.name);
    const done = mine.filter((x) => x.status === 'completed');
    const completion = mine.length ? (done.length / mine.length) * 100 : 0;

    const topics = await api.subjectTopics(s.id).catch(() => []);
    const covered = new Set(done.map((x) => x.topic_name).filter(Boolean)).size;
    const coverage = topics.length ? (covered / topics.length) * 100 : 0;

    rows.push({
      label: s.name,
      value: completion * 0.6 + coverage * 0.4,
      sub: `${done.length}/${mine.length} sessions · ${covered}/${topics.length} topics covered`,
    });
  }

  const overall = rows.length ? rows.reduce((t, r) => t + r.value, 0) / rows.length : 0;

  host.innerHTML = `<div class="stack">
    ${panel(
      'OVERALL READINESS',
      `<div class="stack">${heartMeter(overall)}
        <p class="muted" style="margin:0">Weighted 60% session completion, 40% topic coverage.</p></div>`,
      overall >= 60 ? 'green' : overall >= 30 ? 'yellow' : 'red',
      'heart'
    )}
    ${
      rows.length >= 3
        ? panel(
            'READINESS RADAR',
            `<div class="scroll-x">${radarChart(rows, { max: 100, color: 'blue', unit: '%' })}</div>`,
            'blue',
            'target'
          )
        : ''
    }
    ${panel('PER-SUBJECT STATS', statBlock(rows), 'blue', 'chart')}
    <button class="btn primary block" id="run-predict">${sprite('brain', 22)} RUN AI READINESS PREDICTION</button>
    <div id="predict-out"></div>
  </div>`;

  el('#run-predict').addEventListener('click', async () => {
    const preds = await withLoader('PREDICTING READINESS', () => api.predictReadiness());
    if (!preds) return;
    toast('ok', 'PREDICTION LOGGED', 'Results saved to the feedback loop.');
    el('#predict-out').innerHTML = preds
      .map((p) => {
        const score = Math.round(p.readiness_score || 0);
        return panel(
          p.subject || 'Subject',
          `<div class="stack">
            ${heartMeter(score)}
            <div class="row-tight">
              ${badge(`readiness ${score}%`, score >= 60 ? 'easy' : score >= 30 ? 'medium' : 'hard')}
              ${badge(`coverage ${Math.round(p.coverage_pct || 0)}%`, 'info')}
              ${badge(`confidence ${Math.round((p.confidence || 0) * 100)}%`, 'purple')}
            </div>
            ${p.reasoning ? dialogue('AI REASONING', p.reasoning) : ''}
            ${chipList('Critical gaps', p.critical_gaps, 'hard')}
            ${chipList('Strengths', p.strengths, 'easy')}
            ${p.prediction ? `<p class="muted" style="margin:0">${esc(p.prediction)}</p>` : ''}
          </div>`,
          score >= 60 ? 'green' : score >= 30 ? 'yellow' : 'red',
          'target'
        );
      })
      .join('');
  });
}

function chipList(title, items, kind) {
  if (!items || !items.length) return '';
  return `<div>
    <div class="tiny muted" style="margin-bottom:6px">${esc(title.toUpperCase())}</div>
    <div class="row-tight">${items.map((i) => badge(i, kind)).join('')}</div>
  </div>`;
}

/* ─── Tab 3: generate ────────────────────────────────────────────── */
async function tabGenerate(host, sessions) {
  const [avail, exams] = await Promise.all([
    api.availability().catch(() => []),
    api.exams(true).catch(() => []),
  ]);

  const skippedCount = sessions.filter((s) => s.status === 'skipped').length;

  const blockers = [];
  if (!avail.length) blockers.push('Set your weekly availability in Schedule → Availability.');
  if (!exams.length) blockers.push('Schedule at least one upcoming exam in Schedule → Exam Dates.');

  host.innerHTML = `<div class="stack">
    ${panel(
      'WHAT THE OPTIMIZER CONSIDERS',
      `<div class="grid grid-2">
        ${[
          ['skull', 'Topic difficulty from the LLM-as-Judge scores'],
          ['bolt', 'Your peak focus windows for the hardest material'],
          ['calendar', 'Exam dates and how little time is left'],
          ['brain', 'Spaced repetition so it actually sticks'],
          ['chart', 'Test scores, to push weak subjects up the queue'],
          ['clock', 'Hard limits — nothing lands outside your free hours'],
        ]
          .map(([icon, text]) => `<div class="row-tight">${sprite(icon, 26)}<span class="grow">${esc(text)}</span></div>`)
          .join('')}
      </div>`,
      'purple',
      'bolt'
    )}

    ${
      blockers.length
        ? panel(
            'MISSING PREREQUISITES',
            blockers.map((b) => `<div class="list-row">${sprite('skull', 22)}<span class="grow">${esc(b)}</span></div>`).join(''),
            'red',
            'skull'
          )
        : ''
    }

    <button class="btn go block" id="gen-plan" ${blockers.length ? 'disabled' : ''} style="font-size:13px;padding:18px">
      ${sprite('bolt', 24)} GENERATE OPTIMIZED PLAN
    </button>

    ${panel(
      'KEEP IT DYNAMIC',
      `<div class="stack">
        <p class="muted" style="margin:0">
          Generating replaces the whole plan. Recalculating keeps what you've done and only
          re-books the topics from sessions you skipped, into slots you still have free.
        </p>
        <button class="btn block" id="recalc-plan" ${skippedCount ? '' : 'disabled'}>
          ${sprite('ghost', 20)} RECALCULATE ${skippedCount ? `(${skippedCount} SKIPPED)` : '— NOTHING SKIPPED'}
        </button>
      </div>`,
      'teal',
      'bolt'
    )}

    ${sessions.length ? `<button class="btn danger block" id="clear-plan">${sprite('skull', 20)} CLEAR CURRENT PLAN (${sessions.length} SESSIONS)</button>` : ''}
    <div id="gen-out"></div>
  </div>`;

  el('#recalc-plan')?.addEventListener('click', runRecalculate);

  el('#gen-plan')?.addEventListener('click', async () => {
    const res = await withLoader('BUILDING YOUR RUN', () => api.generatePlan());
    if (!res) return;
    toast('ok', 'PLAN GENERATED', `${res.saved} study sessions scheduled.`);
    el('#gen-out').innerHTML = `<div class="stack">
      ${panel(`${res.saved} SESSIONS SCHEDULED`, `<p class="muted" style="margin:0">Switch to the Timetable tab to play through them.</p>`, 'green', 'trophy')}
      ${res.strategy ? dialogue('STRATEGY', res.strategy, 'target') : ''}
      ${res.reasoning ? dialogue('AI REASONING', res.reasoning) : ''}
    </div>`;
    refreshStats();
  });

  el('#clear-plan')?.addEventListener('click', async () => {
    if (!confirm(`Delete all ${sessions.length} scheduled sessions? This cannot be undone.`)) return;
    try {
      await api.clearSessions();
      toast('ok', 'PLAN CLEARED', 'Generate a fresh one whenever you are ready.');
      show(2);
    } catch (err) {
      toast('err', 'FAILED', err.message);
    }
  });
}

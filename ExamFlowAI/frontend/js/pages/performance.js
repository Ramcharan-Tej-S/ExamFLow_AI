// pages/performance.js — LEVEL 4: test scores + AI priority re-calibration.
import { sprite } from '../sprites.js';
import { api } from '../api.js';
import {
  esc, el, els, badge, tile, empty, panel, dialogue, pageTitle,
  tabs, mountTabs, dualBarChart, toast, withLoader, todayISO, collapsible,
} from '../ui.js';

let subjects = [];

export function renderPerformance() {
  return `<div class="page"><div class="wrap">
    ${pageTitle(4, 'PERFORMANCE', 'Log what you actually scored and let the analyzer re-weight the plan.', 'chart')}
    ${tabs('perf-tabs', ['ENTER SCORES', 'AI ANALYSIS'])}
    <div id="perf-body"></div>
  </div></div>`;
}

export async function mountPerformance() {
  subjects = await api.subjects().catch(() => []);
  mountTabs('perf-tabs', show);
  show(0);
}

async function show(idx) {
  const host = el('#perf-body');
  if (!subjects.length) {
    host.innerHTML = empty('NO SUBJECTS', 'Register subjects in Data Setup first.');
    return;
  }
  host.innerHTML = '<div class="empty">LOADING...</div>';
  if (idx === 0) await tabEnter(host);
  else await tabAnalysis(host);
}

/* ─── Tab 1: enter scores ────────────────────────────────────────── */
async function tabEnter(host) {
  const scores = await api.scores().catch(() => []);

  host.innerHTML = `<div class="stack">
    ${panel(
      'RECORD A SCORE',
      `<form id="score-form" class="stack">
        <div class="grid grid-2">
          <label class="field"><span>Subject</span>
            <select name="subject_id">${subjects.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></label>
          <label class="field"><span>Test type</span>
            <select name="test_type">
              ${['cie1', 'cie2', 'cie3', 'quiz', 'assignment', 'midterm', 'mock']
                .map((t) => `<option value="${t}">${t.toUpperCase()}</option>`).join('')}
            </select></label>
          <label class="field"><span>Score obtained</span>
            <input type="number" name="score" min="0" max="500" step="0.5" value="0" required></label>
          <label class="field"><span>Maximum score</span>
            <input type="number" name="max_score" min="1" max="500" step="0.5" value="50" required></label>
          <label class="field"><span>Test date</span>
            <input type="date" name="test_date" value="${todayISO()}"></label>
          <label class="field"><span>Notes</span>
            <input type="text" name="notes" placeholder="Ran out of time on section B"></label>
        </div>
        <button class="btn primary block" type="submit">${sprite('floppy', 20)} SAVE SCORE</button>
      </form>`,
      'orange',
      'chart'
    )}

    ${
      scores.length
        ? collapsible(
            'SCORE HISTORY',
            scores
              .map((sc) => {
                const pct = sc.max_score > 0 ? (sc.score / sc.max_score) * 100 : 0;
                const kind = pct >= 70 ? 'easy' : pct >= 50 ? 'medium' : 'hard';
                const icon = pct >= 70 ? 'trophy' : pct >= 50 ? 'coin' : 'skull';
                return `<div class="list-row">
                  ${sprite(icon, 26)}
                  <div class="grow">
                    <div class="rt">${esc(sc.subject_name)}</div>
                    <div class="rs">${esc(sc.test_date || '')} ${sc.notes ? '&middot; ' + esc(sc.notes) : ''}</div>
                  </div>
                  ${badge(sc.test_type, 'blue')}
                  <span class="rs">${esc(sc.score)}/${esc(sc.max_score)}</span>
                  ${badge(pct.toFixed(0) + '%', kind)}
                </div>`;
              })
              .join(''),
            { icon: 'trophy', note: `${scores.length} RECORDED` }
          )
        : empty('NO SCORES YET', 'Record a CIE, quiz or mock result above to unlock the analysis tab.')
    }
  </div>`;

  el('#score-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const score = Number(fd.get('score'));
    const max = Number(fd.get('max_score'));
    if (!(score > 0)) return toast('err', 'INVALID', 'Enter a score greater than zero.');
    if (score > max) return toast('err', 'INVALID', 'The score cannot exceed the maximum.');
    try {
      await api.addScore({
        subject_id: Number(fd.get('subject_id')),
        score,
        max_score: max,
        test_type: fd.get('test_type'),
        test_date: fd.get('test_date') || null,
        notes: fd.get('notes') || '',
      });
      toast('ok', 'SCORE SAVED', `${((score / max) * 100).toFixed(0)}% recorded.`);
      show(0);
    } catch (err) {
      toast('err', 'FAILED', err.message);
    }
  });
}

/* ─── Tab 2: AI analysis ─────────────────────────────────────────── */
async function tabAnalysis(host) {
  const scores = await api.scores().catch(() => []);
  if (!scores.length) {
    host.innerHTML = empty('NOTHING TO ANALYSE', 'Record at least one test score first.');
    return;
  }

  // Expected (from self-rating) vs actual average, per subject.
  const rows = [];
  new Set(scores.map((s) => s.subject_name)).forEach((name) => {
    const mine = scores.filter((s) => s.subject_name === name);
    const actual = mine.reduce((t, s) => t + (s.score / s.max_score) * 100, 0) / mine.length;
    const subj = subjects.find((s) => s.name === name);
    rows.push({ label: name, a: subj ? subj.self_rating * 10 : 50, b: actual });
  });

  host.innerHTML = `<div class="stack">
    ${panel('EXPECTED VS ACTUAL', `<div class="scroll-x">${dualBarChart(rows, 'You predicted (self-rating)', 'You actually scored')}</div>`, 'purple', 'target')}
    <button class="btn primary block" id="run-analysis">${sprite('brain', 22)} RUN AI PERFORMANCE ANALYSIS</button>
    <div id="analysis-out"></div>
  </div>`;

  el('#run-analysis').addEventListener('click', async () => {
    const a = await withLoader('ANALYSING PATTERNS', () => api.analyzePerformance());
    if (!a) return;
    toast('ok', 'ANALYSIS DONE', 'Priorities re-calibrated and logged.');
    el('#analysis-out').innerHTML = `<div class="stack">
      ${a.reasoning ? dialogue('AI REASONING', a.reasoning) : ''}
      ${(a.subject_analysis || [])
        .map((sa) => {
          const shift = sa.priority_shift || 'maintain';
          const kind = shift === 'increase' ? 'hard' : shift === 'decrease' ? 'easy' : 'info';
          return panel(
            sa.subject || 'Subject',
            `<div class="stack">
              <div class="row">
                ${badge(`${Math.round(sa.score_pct || 0)}%`, (sa.score_pct || 0) >= 70 ? 'easy' : (sa.score_pct || 0) >= 50 ? 'medium' : 'hard')}
                ${badge(`priority ${shift}`, kind)}
                ${badge(String(sa.performance_level || '').replace(/_/g, ' ') || 'unrated', 'blue')}
              </div>
              ${sa.focus_recommendation ? `<p class="muted" style="margin:0">${esc(sa.focus_recommendation)}</p>` : ''}
              ${listBlock('Weak areas', sa.weak_areas, 'hard')}
              ${listBlock('Strong areas', sa.strong_areas, 'easy')}
            </div>`,
            kind === 'hard' ? 'red' : kind === 'easy' ? 'green' : 'teal',
            'cartridge'
          );
        })
        .join('')}
      ${
        (a.recommendations || []).length
          ? panel(
              'RECOMMENDATIONS',
              a.recommendations
                .map((r) => `<div class="list-row">${sprite('star', 22)}<span class="grow">${esc(r)}</span></div>`)
                .join(''),
              'yellow',
              'scroll'
            )
          : ''
      }
    </div>`;
  });
}

function listBlock(title, items, kind = '') {
  if (!items || !items.length) return '';
  return `<div>
    <div class="tiny muted" style="margin-bottom:6px">${esc(title.toUpperCase())}</div>
    <div class="row-tight">${items.map((i) => badge(i, kind)).join('')}</div>
  </div>`;
}

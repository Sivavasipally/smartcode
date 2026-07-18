/* smartcode renderer: parameter form, live pipeline flow, event ledger,
   node detail, result view, HITL approval modal.
   Runs against the Electron preload bridge (window.smartcode) or, when opened
   in a plain browser, against a canned DemoBridge for UI development. */
'use strict';

/* ============================ pipeline model ============================ */
const NODES = [
  { id: 'classify_intent', title: 'Classify', sub: 'intent · skills',  x: 10 },
  { id: 'retriever',       title: 'Retrieve', sub: 'symbols · budget', x: 152 },
  { id: 'planner',         title: 'Plan',     sub: 'bounded steps',    x: 294 },
  { id: 'coder',           title: 'Code',     sub: 'structured edits', x: 436 },
  { id: 'verifier',        title: 'Verify',   sub: 'AST · lint · tests', x: 578 },
  { id: 'critic',          title: 'Critique', sub: 'LLM judge',        x: 720 },
  { id: 'hitl_gate',       title: 'Gate',     sub: 'write approval',   x: 862 },
  { id: 'finalize',        title: 'Finalize', sub: 'write · evidence', x: 1004 },
];
const REPAIR = { id: 'repair', title: 'Repair', sub: 'feedback loop', x: 507, y: 168 };
const NODE_W = 126, NODE_H = 62, NODE_Y = 46;

const NODE_COLORS = {
  classify_intent: '#6ea8e8', retriever: '#5db0d0', planner: '#a58fe0',
  coder: '#7bc47b', verifier: '#d9b04a', critic: '#e08a8a',
  repair: '#e0a35d', hitl_gate: '#d3c25b', finalize: '#69c9a1',
};

const STATE_TEXT = { idle: '○ PENDING', active: '● RUNNING', done: '✓ DONE',
                     fail: '✕ FAILED', skip: '– SKIPPED' };

/* ============================ state ============================ */
const S = {
  mode: 'generate',
  targets: [],
  acceptance: [],
  providers: {},
  running: false,
  runId: null,
  runStart: 0,
  clockTimer: null,
  events: [],
  selectedEvent: null,
  result: null,
  intent: 'new',
};

const $ = (sel) => document.querySelector(sel);

/* ============================ flow SVG ============================ */
function buildFlow() {
  const midY = NODE_Y + NODE_H / 2;
  const right = (n) => n.x + NODE_W;
  const edges = [];
  for (let i = 0; i < NODES.length - 1; i++) {
    edges.push({ id: `e-${NODES[i].id}`, d: `M ${right(NODES[i])} ${midY} L ${NODES[i + 1].x} ${midY}` });
  }
  // loop-back edges through repair
  const vx = NODES[4].x + NODE_W / 2, cx = NODES[5].x + NODE_W / 2;
  const rx = REPAIR.x + NODE_W / 2, ryTop = REPAIR.y, ryMid = REPAIR.y + NODE_H / 2;
  const codeX = NODES[3].x + NODE_W / 2, bot = NODE_Y + NODE_H;
  const loops = [
    { id: 'e-verify-repair', d: `M ${vx} ${bot} C ${vx} ${ryMid}, ${rx + 40} ${ryMid}, ${REPAIR.x + NODE_W} ${ryMid}`, cls: 'loop' },
    { id: 'e-critic-repair', d: `M ${cx} ${bot} C ${cx} ${REPAIR.y + 30}, ${rx + 90} ${ryTop + 10}, ${REPAIR.x + NODE_W} ${ryMid - 14}`, cls: 'loop' },
    { id: 'e-repair-code',   d: `M ${REPAIR.x} ${ryMid} C ${codeX} ${ryMid}, ${codeX} ${ryMid}, ${codeX} ${bot}`, cls: 'loop' },
  ];

  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', '0 0 1140 246');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

  const defs = document.createElementNS(svgNS, 'defs');
  defs.innerHTML = `<marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4"
      markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L8 4 L0 8 z" fill="#454540"></path></marker>`;
  svg.appendChild(defs);

  for (const e of [...edges, ...loops]) {
    const p = document.createElementNS(svgNS, 'path');
    p.setAttribute('d', e.d);
    p.setAttribute('id', e.id);
    p.setAttribute('class', 'edge' + (e.cls ? ` ${e.cls}` : ''));
    p.setAttribute('marker-end', 'url(#arrow)');
    svg.appendChild(p);
  }

  const mkNode = (n, y) => {
    const g = document.createElementNS(svgNS, 'g');
    g.setAttribute('class', 'node idle');
    g.setAttribute('id', `node-${n.id}`);
    g.innerHTML = `
      <rect x="${n.x}" y="${y}" width="${NODE_W}" height="${NODE_H}" rx="10"></rect>
      <circle cx="${n.x + 15}" cy="${y + 17}" r="4" fill="${NODE_COLORS[n.id]}"></circle>
      <text class="n-title" x="${n.x + 26}" y="${y + 21}">${n.title}</text>
      <text class="n-sub" x="${n.x + 12}" y="${y + 38}">${n.sub}</text>
      <text class="n-state" x="${n.x + 12}" y="${y + 53}">${STATE_TEXT.idle}</text>
      <text class="n-badge" x="${n.x + NODE_W - 26}" y="${y + 21}" id="badge-${n.id}"></text>`;
    svg.appendChild(g);
  };
  NODES.forEach((n) => mkNode(n, NODE_Y));
  mkNode(REPAIR, REPAIR.y);

  $('#flow-wrap').replaceChildren(svg);
}

function setNodeState(id, state) {
  const g = $(`#node-${id}`);
  if (!g) return;
  g.setAttribute('class', `node ${state}`);
  g.querySelector('.n-state').textContent = STATE_TEXT[state] || state;
}

function setBadge(id, txt) {
  const b = $(`#badge-${id}`);
  if (b) b.textContent = txt;
}

function setActiveEdge(edgeId) {
  document.querySelectorAll('.edge.active').forEach((e) => e.classList.remove('active'));
  if (edgeId) $(`#${edgeId}`)?.classList.add('active');
}

function resetFlow() {
  NODES.forEach((n) => setNodeState(n.id, 'idle'));
  setNodeState('repair', 'idle');
  setBadge('repair', '');
  setActiveEdge(null);
}

/* Predict the next node from a completed event → keeps the "running" pulse honest. */
function advanceFlow(ev) {
  const d = ev;
  const node = ev.node;
  setNodeState(node, 'done');

  const activate = (next, edgeId) => { setNodeState(next, 'active'); setActiveEdge(edgeId); };

  switch (node) {
    case 'classify_intent': {
      const m = /intent=(\w+)/.exec(ev.message || '');
      S.intent = m ? m[1] : 'new';
      if (S.intent === 'new') {
        setNodeState('retriever', 'skip');
        activate('planner', 'e-retriever');
      } else {
        activate('retriever', 'e-classify_intent');
      }
      break;
    }
    case 'retriever':
      if (S.intent === 'review') activate('critic', 'e-verifier');
      else activate('planner', 'e-retriever');
      break;
    case 'planner': activate('coder', 'e-planner'); break;
    case 'coder': activate('verifier', 'e-coder'); break;
    case 'verifier':
      if (d.ok === false) { setNodeState('verifier', 'fail'); activate('repair', 'e-verify-repair'); }
      else activate('critic', 'e-verifier');
      break;
    case 'repair': {
      const m = /revision (\d+)/.exec(ev.message || '');
      if (m) setBadge('repair', `×${m[1]}`);
      activate('coder', 'e-repair-code');
      break;
    }
    case 'critic':
      if (S.intent === 'review') activate('finalize', 'e-hitl_gate');
      else if (d.revise) activate('repair', 'e-critic-repair');
      else activate('hitl_gate', 'e-critic');
      break;
    case 'hitl_gate':
      if (/rejected/.test(ev.message || '')) setNodeState('hitl_gate', 'fail');
      activate('finalize', 'e-hitl_gate');
      break;
    case 'finalize':
      setActiveEdge(null);
      if (/rejected/.test(ev.message || '')) setNodeState('finalize', 'fail');
      break;
  }
}

/* ============================ timeline & detail ============================ */
function addTimelineEntry(ev, idx) {
  const li = document.createElement('li');
  li.dataset.idx = idx;
  const color = NODE_COLORS[ev.node] || '#888';
  li.innerHTML = `
    <span class="t">${(ev.elapsed_s ?? 0).toFixed(1)}s</span>
    <span class="n"><span class="node-chip" style="color:${color}">${ev.node}</span></span>
    <span class="m"></span>`;
  li.querySelector('.m').textContent = ev.message || '';
  li.addEventListener('click', () => selectEvent(idx));
  const ol = $('#timeline');
  ol.appendChild(li);
  ol.scrollTop = ol.scrollHeight;
  $('#event-count').textContent = `${S.events.length} events`;
}

function selectEvent(idx) {
  S.selectedEvent = idx;
  document.querySelectorAll('#timeline li').forEach((li) =>
    li.classList.toggle('selected', Number(li.dataset.idx) === idx));
  showTab('detail');
  renderDetail(S.events[idx]);
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function section(title) {
  const s = el('div', 'd-section');
  s.appendChild(el('h3', null, title));
  return s;
}

function renderDetail(ev) {
  const root = $('#tab-detail');
  root.replaceChildren();
  root.appendChild(el('div', 'd-title', `${ev.node}  ·  ${(ev.elapsed_s ?? 0).toFixed(1)}s`));
  root.appendChild(el('div', 'd-msg', ev.message || ''));

  if (ev.node === 'planner') {
    if (ev.approach) { const s = section('Approach'); s.appendChild(el('div', 'd-msg', ev.approach)); root.appendChild(s); }
    if (ev.steps?.length) {
      const s = section('Steps'); const ol = el('ol', 'd-steps');
      ev.steps.forEach((st) => ol.appendChild(el('li', null, st)));
      s.appendChild(ol); root.appendChild(s);
    }
    if (ev.open_questions?.length) {
      const s = section('Open questions'); const ul = el('ul', 'd-steps');
      ev.open_questions.forEach((q) => ul.appendChild(el('li', null, q)));
      s.appendChild(ul); root.appendChild(s);
    }
  } else if (ev.node === 'verifier' && ev.checks) {
    const s = section('Deterministic checks');
    ev.checks.forEach((c) => {
      const row = el('div', 'check-row');
      row.appendChild(el('span', `check-ic ${c.passed ? 'ok' : 'bad'}`, c.passed ? '✓' : '✕'));
      row.appendChild(el('span', null, c.name + (c.detail ? ` — ${c.detail}` : '')));
      s.appendChild(row);
    });
    root.appendChild(s);
    const kv = el('dl', 'kv');
    const add = (k, v) => { kv.appendChild(el('dt', null, k)); kv.appendChild(el('dd', null, v)); };
    if (ev.lint_ok !== null && ev.lint_ok !== undefined) add('linters', ev.lint_ok ? 'passed' : 'FAILED');
    if (ev.tests_ok !== null && ev.tests_ok !== undefined) add('tests', ev.tests_ok ? 'passed' : 'FAILED');
    root.appendChild(kv);
  } else if (ev.node === 'critic' && ev.score !== undefined) {
    const row = el('div', 'score-row');
    row.appendChild(el('span', null, `score ${Number(ev.score).toFixed(2)}`));
    const bar = el('div', 'score-bar'); const fill = el('div', 'score-fill');
    fill.style.width = `${Math.round(ev.score * 100)}%`;
    fill.style.background = ev.score >= 0.7 ? 'var(--good)' : ev.score >= 0.4 ? 'var(--warning)' : 'var(--critical)';
    bar.appendChild(fill); row.appendChild(bar); root.appendChild(row);
    if (ev.rationale) root.appendChild(el('div', 'd-msg', ev.rationale));
    if (ev.findings?.length) {
      const s = section(`Findings (${ev.findings.length})`);
      ev.findings.forEach((f) => {
        const fd = el('div', `finding ${f.severity}`);
        const head = el('div');
        head.appendChild(el('span', 'sev', f.severity));
        head.appendChild(el('span', null, f.message + (f.location ? `  (${f.location})` : '')));
        fd.appendChild(head);
        if (f.suggestion) fd.appendChild(el('div', 'sugg', `→ ${f.suggestion}`));
        s.appendChild(fd);
      });
      root.appendChild(s);
    }
  } else if (ev.node === 'coder' && ev.edits?.length) {
    const s = section('Edits');
    ev.edits.forEach((e2) => s.appendChild(el('div', 'check-row', e2)));
    root.appendChild(s);
  } else if (ev.node === 'retriever' && ev.paths?.length) {
    const s = section('Evidence sources');
    ev.paths.forEach((p) => s.appendChild(el('div', 'check-row', p)));
    root.appendChild(s);
  } else if (ev.node === 'finalize' && ev.applied?.length) {
    const s = section('Applied');
    ev.applied.forEach((a) => {
      const row = el('div', 'check-row');
      row.appendChild(el('span', `check-ic ${a.applied ? 'ok' : 'bad'}`, a.applied ? '✓' : '✕'));
      row.appendChild(el('span', null, `${a.path}${a.error ? ` — ${a.error}` : ` (${a.bytes_written} bytes)`}`));
      s.appendChild(row);
    });
    root.appendChild(s);
  }

  const raw = el('span', 'raw-toggle', 'show raw event');
  const pre = el('pre', 'code'); pre.hidden = true;
  pre.textContent = JSON.stringify(ev, null, 2);
  raw.addEventListener('click', () => { pre.hidden = !pre.hidden; });
  root.appendChild(raw); root.appendChild(pre);
}

/* ============================ result view ============================ */
const STATUS_META = {
  success:     { ic: '✓', label: 'Success — verified, approved, written' },
  best_effort: { ic: '△', label: 'Best effort — written, but not all gates passed' },
  rejected:    { ic: '✕', label: 'Rejected — nothing was written' },
  review_only: { ic: '◎', label: 'Review complete — findings only, no writes' },
};

function renderResult(evidence, writtenFiles) {
  const root = $('#tab-result');
  root.replaceChildren();
  const meta = STATUS_META[evidence.status] || { ic: '?', label: evidence.status };

  const banner = el('div', `status-banner ${evidence.status}`);
  banner.appendChild(el('span', 'ic', meta.ic));
  banner.appendChild(el('span', null, `${meta.label}  ·  ${evidence.revisions} revision(s)`));
  root.appendChild(banner);

  if (evidence.critique?.findings?.length) {
    const s = section(`Findings (${evidence.critique.findings.length})`);
    evidence.critique.findings.forEach((f) => {
      const fd = el('div', `finding ${f.severity}`);
      fd.appendChild(el('span', 'sev', f.severity));
      fd.appendChild(el('span', null, f.message + (f.location ? ` (${f.location})` : '')));
      if (f.suggestion) fd.appendChild(el('div', 'sugg', `→ ${f.suggestion}`));
      s.appendChild(fd);
    });
    root.appendChild(s);
  }

  const files = Object.entries(writtenFiles || {});
  if (files.length) {
    const s = section('Written files');
    const tabs = el('div', 'file-tabs');
    const pre = el('pre', 'code');
    const show = (i) => {
      tabs.querySelectorAll('button').forEach((b, j) => b.classList.toggle('active', i === j));
      pre.textContent = files[i][1];
    };
    files.forEach(([p], i) => {
      const b = el('button', null, p.split(/[\\/]/).pop());
      b.title = p;
      b.addEventListener('click', () => show(i));
      tabs.appendChild(b);
    });
    s.appendChild(tabs); s.appendChild(pre); root.appendChild(s);
    show(0);
  } else if (evidence.status !== 'review_only') {
    root.appendChild(el('div', 'placeholder', 'No files were written.'));
  }

  const dl = el('div', 'dl-row');
  const btn = el('button', 'ghost-btn', 'Download evidence package (JSON)');
  btn.addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(evidence, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'evidence.json';
    a.click();
    URL.revokeObjectURL(a.href);
  });
  dl.appendChild(btn); root.appendChild(dl);
}

function showTab(name) {
  document.querySelectorAll('#detail-tabs button').forEach((b) =>
    b.classList.toggle('active', b.dataset.tab === name));
  $('#tab-detail').hidden = name !== 'detail';
  $('#tab-result').hidden = name !== 'result';
}

/* ============================ bridge ============================ */
function makeDemoBridge() {
  // Browser-only development mode: replays a canned run so the UI can be
  // designed/tested without Electron or Python.
  let onMsg = () => {};
  const evs = [
    { node: 'classify_intent', message: 'intent=modify lang=python framework=fastapi', elapsed_s: 0.2 },
    { node: 'retriever', message: '6/14 evidence item(s) within budget', paths: ['src/api.py :: create_user', 'src/api.py :: UserService'], elapsed_s: 0.9 },
    { node: 'planner', message: '3 step(s)', approach: 'Add validation via a pydantic model, then wire it into the route handler.', steps: ['Add UserIn model with email validation', 'Update create_user to use UserIn', 'Return 422 on invalid payloads'], open_questions: [], elapsed_s: 2.4 },
    { node: 'coder', message: '2 edit(s)', edits: ['replace src/api.py @create_user', 'insert src/api.py @UserIn'], elapsed_s: 5.1 },
    { node: 'verifier', message: 'FAIL: lint failures: F821 undefined name UserIn', ok: false, summary: 'lint failures: F821', lint_ok: false, checks: [{ name: 'api.py: tree-sitter parse (python)', passed: true, detail: '' }, { name: 'api.py: py-compile', passed: true, detail: '' }], elapsed_s: 6.0 },
    { node: 'repair', message: 'revision 1: 1 issue(s) fed back', elapsed_s: 6.1 },
    { node: 'coder', message: '2 edit(s)', edits: ['replace src/api.py @create_user', 'insert src/api.py @imports'], elapsed_s: 8.9 },
    { node: 'verifier', message: 'PASS', ok: true, summary: 'all structural checks passed', lint_ok: true, checks: [{ name: 'api.py: tree-sitter parse (python)', passed: true, detail: '' }, { name: 'api.py: py-compile', passed: true, detail: '' }], elapsed_s: 9.6 },
    { node: 'critic', message: 'score=0.92 revise=False findings=1', score: 0.92, revise: false, satisfies: true, rationale: 'Validation is correct and idiomatic.', findings: [{ severity: 'nit', message: 'Consider a 409 for duplicate emails', location: 'src/api.py', suggestion: 'raise HTTPException(409) on unique violation' }], elapsed_s: 11.8 },
  ];
  const finish = [
    { node: 'hitl_gate', message: 'tier=medium -> approved', elapsed_s: 13.0 },
    { node: 'finalize', message: 'status=success written=1', status: 'success', applied: [{ path: 'src/api.py', applied: true, bytes_written: 1423, error: null, action: 'replace' }], elapsed_s: 13.2 },
  ];
  return {
    demo: true,
    onMessage: (cb) => { onMsg = cb; },
    pickFiles: async () => ['src/api.py'],
    pickSave: async () => 'generated/solution.py',
    restart: async () => {},
    send: async (obj) => {
      if (obj.cmd === 'init') {
        setTimeout(() => onMsg({
          type: 'init',
          providers: {
            local: { ok: true, reason: 'model at D:/models/Qwen2.5-1.5B-Instruct', model: 'Qwen2.5-1.5B-Instruct' },
            groq: { ok: true, reason: 'ok', model: 'llama-3.3-70b-versatile' },
            anthropic: { ok: false, reason: 'missing ANTHROPIC_API_KEY', model: 'claude-sonnet-4-5' },
            openai: { ok: true, reason: 'ok', model: 'gpt-4.1' },
            google: { ok: false, reason: 'missing GOOGLE_API_KEY', model: 'gemini-2.0-flash' },
            mock: { ok: true, reason: 'offline stub', model: 'mock' },
          },
          languages: ['c', 'cpp', 'csharp', 'go', 'java', 'javascript', 'php', 'python', 'ruby', 'rust', 'typescript'],
          frameworks: ['express', 'fastapi', 'flask', 'react', 'spring'],
          defaults: { provider: 'groq', risk: 'medium', max_revisions: 3 },
        }), 250);
      }
      if (obj.cmd === 'run') {
        const runId = obj.id;
        let t = 0;
        evs.forEach((e, i) => {
          t += 550;
          setTimeout(() => onMsg({ type: 'event', runId, event: e }), t);
        });
        setTimeout(() => onMsg({ type: 'approval_request', runId, risk: 'medium',
          edits: [{ action: 'replace', path: 'src/api.py', anchor: 'create_user', summary: 'validated create_user with UserIn model' }] }), t + 600);
        makeDemoBridge._finish = (approved) => {
          let t2 = 0;
          const seq = approved ? finish : [
            { node: 'hitl_gate', message: 'tier=medium -> rejected', elapsed_s: 13.0 },
            { node: 'finalize', message: 'status=rejected written=0', status: 'rejected', applied: [], elapsed_s: 13.1 },
          ];
          seq.forEach((e) => { t2 += 450; setTimeout(() => onMsg({ type: 'event', runId, event: e }), t2); });
          setTimeout(() => onMsg({ type: 'result', runId,
            evidence: { status: approved ? 'success' : 'rejected', revisions: 1,
              critique: { findings: [{ severity: 'nit', message: 'Consider a 409 for duplicate emails', location: 'src/api.py', suggestion: 'raise HTTPException(409)' }] } },
            written_files: approved ? { 'src/api.py': 'from fastapi import APIRouter, HTTPException\nfrom pydantic import BaseModel, EmailStr\n\nrouter = APIRouter()\n\nclass UserIn(BaseModel):\n    name: str\n    email: EmailStr\n\n@router.post("/users", status_code=201)\ndef create_user(user: UserIn):\n    return user\n' } : {},
          }), t2 + 500);
        };
      }
      if (obj.cmd === 'approval_response') makeDemoBridge._finish?.(obj.approved);
      return true;
    },
  };
}

const bridge = window.smartcode || makeDemoBridge();

/* ============================ run control ============================ */
function collectParams() {
  return {
    mode: S.mode,
    objective: $('#objective').value.trim(),
    provider: $('#provider').value,
    language: $('#language').value,
    framework: $('#framework').value,
    out_path: $('#out-path').value.trim(),
    paths: S.targets,
    acceptance: S.acceptance,
    risk: $('#risk').value,
    max_revisions: Number($('#max-revisions').value),
    test_command: $('#test-command').value.trim(),
    run_linters: $('#run-linters').checked,
    run_tests: $('#run-tests').checked,
  };
}

function validate(p) {
  if (!p.objective && S.mode !== 'review') return 'Describe the objective first.';
  if ((S.mode === 'modify' || S.mode === 'review') && !p.paths.length) return 'Add at least one target file.';
  return null;
}

function startRun() {
  const p = collectParams();
  const err = validate(p);
  const errBox = $('#form-error');
  if (err) { errBox.textContent = err; errBox.hidden = false; return; }
  errBox.hidden = true;

  S.running = true;
  S.runId = `run-${Date.now()}`;
  S.events = [];
  S.result = null;
  S.runStart = performance.now();
  $('#timeline').replaceChildren();
  $('#event-count').textContent = '';
  $('#tab-detail').replaceChildren(el('div', 'placeholder', 'Waiting for events…'));
  $('#tab-result').replaceChildren(el('div', 'placeholder', 'Run in progress…'));
  showTab('detail');
  resetFlow();
  setNodeState('classify_intent', 'active');

  const btn = $('#btn-run');
  btn.disabled = true; btn.classList.add('running');
  btn.querySelector('.run-label').textContent = 'Running…';
  const clock = $('#run-clock'); clock.hidden = false;
  S.clockTimer = setInterval(() => {
    clock.textContent = `${((performance.now() - S.runStart) / 1000).toFixed(1)}s`;
  }, 100);

  bridge.send({ id: S.runId, cmd: 'run', params: p });
}

function endRun() {
  S.running = false;
  clearInterval(S.clockTimer);
  const btn = $('#btn-run');
  btn.disabled = false; btn.classList.remove('running');
  btn.querySelector('.run-label').textContent = 'Run pipeline';
}

/* ============================ bridge messages ============================ */
bridge.onMessage((msg) => {
  switch (msg.type) {
    case 'ready':
      setBridgeStatus('ok', bridge.demo ? 'demo mode (no Electron)' : 'agent ready');
      bridge.send({ id: 'init', cmd: 'init' });
      break;
    case 'init': applyInit(msg); break;
    case 'run_started': break;
    case 'event': {
      if (msg.runId !== S.runId) break;
      const ev = msg.event;
      S.events.push(ev);
      addTimelineEntry(ev, S.events.length - 1);
      advanceFlow(ev);
      break;
    }
    case 'approval_request': {
      if (msg.runId !== S.runId) break;
      openApprovalModal(msg);
      break;
    }
    case 'result': {
      if (msg.runId !== S.runId) break;
      S.result = msg;
      endRun();
      renderResult(msg.evidence, msg.written_files);
      showTab('result');
      break;
    }
    case 'error': {
      if (msg.runId && msg.runId !== S.runId) break;
      endRun();
      const root = $('#tab-result');
      root.replaceChildren();
      const banner = el('div', 'status-banner rejected');
      banner.appendChild(el('span', 'ic', '✕'));
      banner.appendChild(el('span', null, `Run failed: ${msg.message}`));
      root.appendChild(banner);
      showTab('result');
      break;
    }
    case 'bridge_exit':
      setBridgeStatus('err', `agent exited (${msg.code})`);
      if (S.running) endRun();
      break;
  }
});

function setBridgeStatus(cls, txt) {
  const b = $('#bridge-status');
  b.className = `bridge-status ${cls}`;
  b.querySelector('.txt').textContent = txt;
}

function applyInit(msg) {
  S.providers = msg.providers || {};
  const sel = $('#provider');
  sel.replaceChildren();
  for (const [pid, info] of Object.entries(S.providers)) {
    const opt = document.createElement('option');
    opt.value = pid;
    opt.textContent = `${info.ok ? '●' : '○'} ${pid}${info.model ? ` — ${info.model}` : ''}`;
    opt.disabled = !info.ok;
    sel.appendChild(opt);
  }
  const def = msg.defaults?.provider;
  if (def && S.providers[def]?.ok) sel.value = def;
  else {
    const firstOk = Object.keys(S.providers).find((p) => S.providers[p].ok);
    if (firstOk) sel.value = firstOk;
  }
  updateProviderHint();

  const fillSelect = (sel, firstLabel, values) => {
    sel.replaceChildren();
    const first = document.createElement('option');
    first.value = ''; first.textContent = firstLabel;
    sel.appendChild(first);
    values.forEach((v) => {
      const o = document.createElement('option'); o.value = v; o.textContent = v;
      sel.appendChild(o);
    });
  };
  fillSelect($('#language'), 'auto', msg.languages || []);
  fillSelect($('#framework'), 'none', msg.frameworks || []);
  if (msg.defaults?.risk) $('#risk').value = msg.defaults.risk;
  if (msg.defaults?.max_revisions) $('#max-revisions').value = msg.defaults.max_revisions;

  $('#btn-run').disabled = false;
}

function updateProviderHint() {
  const info = S.providers[$('#provider').value];
  $('#provider-hint').textContent = info ? info.reason : '';
}

/* ============================ approval modal ============================ */
function openApprovalModal(msg) {
  $('#modal-risk').textContent = msg.risk || 'medium';
  const box = $('#modal-edits');
  box.replaceChildren();
  (msg.edits || []).forEach((e) => {
    const row = el('div', 'edit-row');
    row.appendChild(el('span', `edit-action ${e.action}`, e.action));
    row.appendChild(el('span', 'edit-path', e.path + (e.anchor ? `  @ ${e.anchor}` : '')));
    if (e.summary) row.appendChild(el('span', 'edit-sum', e.summary));
    box.appendChild(row);
  });
  $('#modal-backdrop').hidden = false;

  const close = (approved) => {
    $('#modal-backdrop').hidden = true;
    bridge.send({ id: msg.runId, cmd: 'approval_response', approved });
    $('#btn-approve').onclick = $('#btn-reject').onclick = null;
  };
  $('#btn-approve').onclick = () => close(true);
  $('#btn-reject').onclick = () => close(false);
}

/* ============================ form wiring ============================ */
const MODE_COPY = {
  generate: { label: 'What should be built?', ph: 'e.g. FastAPI endpoint POST /users with a pydantic model' },
  modify: { label: 'What should change?', ph: 'e.g. add rate limiting to all routes' },
  review: { label: 'Review focus (optional)', ph: 'e.g. security issues, error handling' },
};

$('#mode-tabs').addEventListener('click', (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  S.mode = btn.dataset.mode;
  document.querySelectorAll('#mode-tabs button').forEach((b) =>
    b.classList.toggle('active', b === btn));
  $('#objective-label').textContent = MODE_COPY[S.mode].label;
  $('#objective').placeholder = MODE_COPY[S.mode].ph;
  $('#out-path-field').hidden = S.mode !== 'generate';
  $('#targets-field').hidden = S.mode === 'generate';
});

function renderChips(listEl, items, onRemove) {
  listEl.replaceChildren();
  items.forEach((item, i) => {
    const c = el('span', 'chip');
    const t = el('span', 'txt', item);
    t.title = item;
    const x = el('button', null, '×');
    x.addEventListener('click', () => onRemove(i));
    c.appendChild(t); c.appendChild(x);
    listEl.appendChild(c);
  });
}

function refreshTargets() {
  renderChips($('#targets-list'), S.targets, (i) => {
    S.targets.splice(i, 1);
    refreshTargets();
  });
}

function refreshAcceptance() {
  renderChips($('#acceptance-list'), S.acceptance, (i) => {
    S.acceptance.splice(i, 1);
    refreshAcceptance();
  });
}

$('#btn-add-targets').addEventListener('click', async () => {
  const files = await bridge.pickFiles();
  for (const f of files) if (!S.targets.includes(f)) S.targets.push(f);
  refreshTargets();
});

$('#btn-pick-out').addEventListener('click', async () => {
  const f = await bridge.pickSave($('#out-path').value);
  if (f) $('#out-path').value = f;
});

$('#acceptance-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.value.trim()) {
    S.acceptance.push(e.target.value.trim());
    e.target.value = '';
    refreshAcceptance();
  }
});

$('#detail-tabs').addEventListener('click', (e) => {
  const btn = e.target.closest('button');
  if (btn) showTab(btn.dataset.tab);
});

$('#btn-run').addEventListener('click', startRun);
$('#btn-restart').addEventListener('click', async () => {
  await bridge.restart();
  setBridgeStatus('', 'restarting…');
});

/* ============================ boot ============================ */
buildFlow();
$('#provider').addEventListener('change', updateProviderHint);
if (bridge.demo) setBridgeStatus('ok', 'demo mode (no Electron)');
// The bridge's "ready" line may have been forwarded before this window loaded,
// so always send init once at boot; applyInit is idempotent.
bridge.send({ id: 'init', cmd: 'init' });

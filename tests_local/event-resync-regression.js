'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const app = fs.readFileSync(path.join(__dirname, '../geological_agent/team/web/app.js'), 'utf8');
const handleSource = app.slice(app.indexOf('function handleEvent('), app.indexOf('function attachRunHistory('));
const subscribeSource = app.slice(app.indexOf('function subscribe('), app.indexOf("$('composer').addEventListener"));
assert(handleSource.includes('function handleEvent'));
assert(subscribeSource.includes('function subscribe'));

class Node {
  constructor(text = '') { this._text = String(text); this.children = []; }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value); }
}
const connection = new Node(), messages = {scrollHeight: 100, scrollTop: 0, clientHeight: 100};
const notices = [];
const state = {cid: 'c', view: 1, busy: null, runs: new Map(), sources: new Map()};
let experienceFailure = false, markdownFailure = false, closed = 0, busyCleared = 0, hitlRefresh = 0;
const sandbox = {
  state, notices,
  $: id => id === 'connection' ? connection : messages,
  AGENT_NAME: 'OreBOGAO',
  setRunMessageTimes() {}, setRunElapsed() {}, scrollEnd() {},
  busy(value) { state.busy = value; busyCleared++; },
  notice(message) { notices.push(message); },
  markdown() { if (markdownFailure) throw new Error('markdown'); },
  refreshActiveTasks: async () => {}, loadFiles: async () => {}, loadConversations: async () => {},
  window: {
    GeoAgentExperience: {event() { if (experienceFailure) { experienceFailure = false; throw new Error('render'); } }},
    GeoAgentRecovery: {event() {}}, GeoAgentTimeline: {event() {}}, GeoAgentPresentation: {event() {}},
    GeoToolHITL: {refresh() { hitlRefresh++; }},
  },
};
vm.runInNewContext(handleSource, sandbox);

const ui = {
  lastEventSequence: 4, finished: false, status: 'running', mode: 'ask',
  overview: {preview: {hidden: true}}, modeReceipt: {dataset: {}, hidden: true},
  turn: {querySelector: () => new Node()}, answer: new Node(), answerText: '',
  summary: new Node(), reason: new Node(), replyActions: {hidden: true}, artifactContext: {},
};
state.runs.set('r', ui);
experienceFailure = true;
assert.throws(() => sandbox.handleEvent('r', {kind: 'status'}, '5'), /render/);
assert.equal(ui.lastEventSequence, 4, 'A failed render must not consume the event sequence');
sandbox.handleEvent('r', {kind: 'status'}, '5');
assert.equal(ui.lastEventSequence, 5, 'The same event can be replayed after a failed render');

markdownFailure = true;
const source = {close() { closed++; }};
state.sources.set('r', source); state.busy = 'r';
sandbox.handleEvent('r', {kind: 'finished', status: 'completed', answer: '原始答复', reason: ''}, '6');
assert.equal(ui.finished, true);
assert.equal(ui.answer.textContent, '原始答复');
assert.equal(closed, 1);
assert.equal(state.sources.has('r'), false);
assert.equal(state.busy, null);
assert.equal(busyCleared, 1);
assert.equal(hitlRefresh, 1);
assert.equal(ui.lastEventSequence, 6);
assert(notices.some(message => message.includes('答复富文本显示失败')));
markdownFailure = false;

class FakeSource {
  constructor(url) { this.url = url; this.readyState = FakeSource.CONNECTING; this.closed = false; }
  close() { this.readyState = FakeSource.CLOSED; this.closed = true; }
}
FakeSource.CONNECTING = 1; FakeSource.CLOSED = 3;
let handled = [], attached = [], scheduled = null, apiRun = {status: 'completed', answer: 'done'};
Object.assign(sandbox, {
  EventSource: FakeSource,
  api: async () => apiRun,
  runIsWorking: status => ['running', 'queued', 'stopping'].includes(status),
  handleEvent: (...args) => { handled.push(args); },
  attachRunHistory: (...args) => { attached.push(args); },
  setTimeout: (fn, ms) => { scheduled = {fn, ms}; },
});
vm.runInNewContext(subscribeSource, sandbox);

state.runs.set('terminal', {status: 'completed', finished: true, lastEventSequence: 7});
sandbox.subscribe('terminal', 7);
const terminalSource = state.sources.get('terminal');
terminalSource.readyState = FakeSource.CONNECTING;
(async () => {
  await terminalSource.onerror();
  assert.equal(terminalSource.closed, true, 'A terminal snapshot must close a reconnecting stream');
  assert.equal(state.sources.has('terminal'), false);
  assert.equal(handled.length, 1);
  assert.equal(handled[0][1].kind, 'finished');
  assert.equal(attached.length, 1, 'Terminal fallback must offer saved history backfill');

  const live = {status: 'running', finished: false, lastEventSequence: 4};
  state.runs.set('live', live);
  sandbox.handleEvent = () => { throw new Error('render'); };
  sandbox.subscribe('live', 4);
  const liveSource = state.sources.get('live');
  liveSource.onmessage({data: JSON.stringify({kind: 'tool_result', id: 'x'}), lastEventId: '5'});
  assert.equal(liveSource.closed, true);
  assert.equal(state.sources.has('live'), false);
  assert.equal(live.lastEventSequence, 4);
  assert(scheduled && scheduled.ms === 0, 'A failed live render must resync from the last successful sequence');
  console.log('Event resync: failed renders keep sequence, terminal fallback closes reconnecting SSE, markdown failure preserves answer, and live failures reschedule from last receipt passed');

})();
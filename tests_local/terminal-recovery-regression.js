'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
class Node {
  constructor(tag, text = '', cls = '') {
    this.tag = tag; this.text = String(text ?? ''); this.className = cls || ''; this.children = [];
    this.dataset = {}; this.attributes = {}; this.events = {}; this.hidden = false; this.parent = null;
  }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.replaceChildren(); this.text = String(value); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const child of this.children) child.parent = null; this.children = []; this.text = ''; this.append(...nodes); }
  before(node) { this.parent.insert(node, this.parent.children.indexOf(this)); }
  after(node) { this.parent.insert(node, this.parent.children.indexOf(this) + 1); }
  insert(node, index) { node.remove(); node.parent = this; this.children.splice(index, 0, node); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(name, callback) { this.events[name] = callback; }
  querySelectorAll(selector) { return all(this).slice(1).filter(node => selector.startsWith('.') ? node.className.split(' ').includes(selector.slice(1)) : node.tag === selector); }
}
const all = node => [node, ...node.children.flatMap(all)];
const document = {createElement:tag => new Node(tag)};
const sandbox = {document, window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../geological_agent/team/web/recovery.js'), 'utf8'), sandbox);
const recovery = sandbox.window.GeoAgentRecovery;
let blocked = false, composed = [], inspected = 0, composeResult = true;
const hooks = {blocked:() => blocked, compose:async (rid, action) => { composed.push([rid, action]); return composeResult; },
  inspect:() => { inspected++; }};
function fixture(status, overview) {
  const turn = new Node('article'), reason = new Node('div'), reply = new Node('div');
  turn.append(reason, reply);
  const ui = {status, finished:!['running', 'stopping'].includes(status), reason, replyActions:reply, overview};
  recovery.attach('run-a', ui, hooks); recovery.attach('run-a', ui, hooks);
  assert.equal(turn.querySelectorAll('.run-recovery').length, 1);
  return {ui, box:ui.recovery.box};
}
function actions(box) { return box.querySelectorAll('button').map(button => button.dataset.action); }
(async () => {
  const working = fixture('running');
  assert(working.box.hidden);
  working.ui.finished = true; working.ui.status = 'completed'; recovery.event('run-a');
  assert(!working.box.hidden);
  assert.deepEqual(actions(working.box), ['follow_up', 'derive']);
  assert(working.box.textContent.includes('原运行和成果版本保留'));
  await working.box.querySelectorAll('button')[0].events.click();
  assert.deepEqual(composed, [['run-a', 'follow_up']]);
  assert(working.box.textContent.includes('草稿已准备'));

  blocked = true; recovery.sync();
  assert(working.box.querySelectorAll('button').every(button => button.disabled));
  blocked = false; recovery.sync();
  assert(working.box.querySelectorAll('button').every(button => !button.disabled));

  recovery.reset();
  const stopped = fixture('stopped');
  assert.deepEqual(actions(stopped.box), ['resume']);
  assert(stopped.box.textContent.includes('任务已停止'));
  stopped.ui.status = 'failed'; recovery.event('run-a');
  assert.deepEqual(actions(stopped.box), ['retry']);
  assert(stopped.box.textContent.includes('执行失败'));

  recovery.reset();
  const cancelled = fixture('cancelled');
  assert.deepEqual(actions(cancelled.box), ['resume']);
  assert(cancelled.box.textContent.includes('任务已停止'));

  const overview = {openItems:{hidden:true, open:false}, openSummary:{textContent:'未完成事项 · 0'}};
  const partial = fixture('incomplete', overview);
  assert.deepEqual(actions(partial.box), ['inspect', 'resume']);
  assert(partial.box.textContent.includes('部分完成'));
  assert(partial.box.textContent.includes('尚未加载的记录不作推断'));
  await partial.box.querySelectorAll('button')[0].events.click();
  assert.equal(inspected, 1);
  overview.openItems.hidden = false; overview.openSummary.textContent = '未完成事项 · 3'; recovery.event('run-a');
  assert(partial.box.textContent.includes('未完成事项 · 3'));

  for (const [status, title] of [['budget_exhausted', '预算已耗尽'], ['interrupted', '执行中断']]) {
    recovery.reset();
    const variant = fixture(status, overview);
    assert.deepEqual(actions(variant.box), ['inspect', 'resume']);
    assert(variant.box.textContent.includes(title));
    assert(variant.box.textContent.includes('未完成事项 · 3'));
  }

  composeResult = false;
  await partial.box.querySelectorAll('button')[1].events.click();
  assert(partial.box.textContent.includes('对话已切换，未填入草稿'));
  composeResult = true;
  const waiting = fixture('needs_input');
  assert(waiting.box.hidden);
  recovery.reset();
  console.log('terminal recovery regression passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

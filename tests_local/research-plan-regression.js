'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

class Node {
  constructor(tag) {
    this.tag = tag; this.value = ''; this.children = []; this.parent = null; this.dataset = {};
    this.className = ''; this.open = false; this.events = {}; this.focused = false; this._text = '';
    this.classList = {add: name => { if (!this.className.split(' ').includes(name)) this.className = (this.className + ' ' + name).trim(); }};
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  set innerHTML(value) { throw new Error('Research plan must never assign HTML: ' + value); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this._text = ''; this.append(...nodes); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
  addEventListener(name, callback) { this.events[name] = callback; }
  dispatch(name) { const event = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }}; this.events[name]?.(event); return event; }
  focus() { for (const item of elements) item.focused = false; this.focused = true; document.activeElement = this; }
  showModal() { assert.equal(this.open, false, 'A native modal cannot be opened twice'); this.open = true; }
  close() { if (!this.open) return false; this.open = false; this.events.close?.(); return true; }
  requestSubmit() { composerSubmissions++; this.dispatch('submit'); }
}
const elements = new Map(), all = node => [node, ...node.children.flatMap(all)];
const add = id => { const node = new Node('div'); node.id = id; elements.set(id, node); return node; };
for (const field of ['objective', 'scope', 'materials', 'tools', 'deliverables', 'acceptance']) add('plan-' + field);
const dialog = add('plan-dialog'), form = add('plan-form'), error = add('plan-error'), composer = add('composer');
add('plan-cancel'); add('plan-confirm');
let composerSubmissions = 0, timerSequence = 0;
const timers = new Map(), storage = new Map();
const window = {addEventListener() {}};
const document = {
  activeElement: null,
  getElementById: id => elements.get(id) || null,
  createElement: tag => new Node(tag),
  createTextNode: text => { const node = new Node('#text'); node.textContent = text; return node; }
};
const sandbox = {
  window, document, console, JSON, Map, Set,
  setTimeout: callback => { const id = ++timerSequence; timers.set(id, callback); return id; },
  clearTimeout: id => timers.delete(id),
  localStorage: {
    getItem: key => storage.has(key) ? storage.get(key) : null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key)
  }
};
const web = path.join(__dirname, '../geological_agent/team/web');
vm.runInNewContext(fs.readFileSync(path.join(web, 'drafts.js'), 'utf8'), sandbox);
vm.runInNewContext(fs.readFileSync(path.join(web, 'research-plan.js'), 'utf8'), sandbox);
const drafts = window.OreSageDrafts, plan = window.GeoAgentPlan;
const field = name => elements.get('plan-' + name);
const input = (name, value) => { field(name).value = value; field(name).dispatch('input'); drafts.flush(); };
const reopen = (query = '分析区域地质', skill = null) => {
  assert.equal(plan.open(query, skill), true);
  assert.equal(dialog.open, true);
  assert.equal(document.activeElement, field('objective'));
};
const saved = (scope = 'plan:a') => JSON.parse(drafts.text(scope, 'plan') || 'null');

drafts.identity('owner-a');
plan.reset();
reopen('分析区域地质', 'skill-lithology');
assert.equal(field('objective').value, '分析区域地质');
assert.equal(field('scope').value, '围绕研究问题确定；无额外限制');
assert.equal(field('materials').value, '可使用已上传文件、知识库与公开资料');
assert.equal(field('tools').value, '已选技能：skill-lithology；可按需使用其他工具');
assert.equal(field('deliverables').value, '给出结论、关键证据与结果文件（如适用）');
assert.deepEqual(Array.from(field('acceptance').value.split('\n')), ['结论回应研究问题', '关键判断引用可追溯来源', '说明数据或方法局限']);
assert.equal(plan.open('另一个问题', 'other-skill'), true);
assert.equal(field('objective').value, '分析区域地质', 'An already-open modal is not replaced');
dialog.close();

plan.selectConversation('a');
reopen('确认前校验');
field('objective').value = '   ';
form.dispatch('submit');
assert.match(error.textContent, /请填写研究目标/);
assert.equal(document.activeElement, field('objective'));
assert.equal(composerSubmissions, 0, 'Invalid confirmation cannot submit the composer');
input('objective', '确认前校验');
field('acceptance').value = ' \n\n ';
form.dispatch('submit');
assert.match(error.textContent, /至少填写一条验收标准/);
field('acceptance').value = '1\n2\n3\n4\n5\n6';
form.dispatch('submit');
assert.match(error.textContent, /5 条以内/);
assert.equal(composerSubmissions, 0);
dialog.close();

plan.reset(); plan.selectConversation('a'); reopen('保留取消草稿');
input('objective', '用户修改后的目标');
input('scope', '仅使用已授权资料');
input('materials', '区域地质图与钻孔资料');
input('tools', '资料检索与表格分析');
input('deliverables', '结论与证据表');
input('acceptance', '  结论有来源  \n\n 局限已说明  ');
elements.get('plan-cancel').dispatch('click');
assert.equal(dialog.open, false);
assert.equal(composerSubmissions, 0);
assert.equal(plan.consume('保留取消草稿', null), null);
assert.equal(saved('plan:a').objectiveEdited, true);
reopen('保留取消草稿');
assert.equal(field('objective').value, '用户修改后的目标');
assert.equal(field('scope').value, '仅使用已授权资料');
assert.equal(field('materials').value, '区域地质图与钻孔资料');
assert.equal(field('tools').value, '资料检索与表格分析');
assert.equal(field('deliverables').value, '结论与证据表');
assert.equal(field('acceptance').value, '结论有来源\n局限已说明');
dialog.close();

plan.selectConversation('b'); reopen('另一段对话');
assert.equal(field('objective').value, '另一段对话');
assert.equal(field('scope').value, '围绕研究问题确定；无额外限制', 'Drafts are conversation scoped');
dialog.close();
plan.selectConversation('a'); reopen('保留取消草稿');
assert.equal(field('objective').value, '用户修改后的目标', 'Switching back restores the original conversation draft');
dialog.close();
drafts.identity('owner-b'); plan.selectConversation('a'); reopen('保留取消草稿');
assert.equal(field('objective').value, '保留取消草稿', 'Another account cannot read the first account draft');
assert.equal(field('scope').value, '围绕研究问题确定；无额外限制');
dialog.close();
drafts.identity('owner-a'); plan.selectConversation('a'); reopen('保留取消草稿');
assert.equal(field('objective').value, '用户修改后的目标', 'The owning account still has its draft');
dialog.close();

plan.selectConversation('a'); reopen('待确认计划', 'skill-a');
field('objective').value = '可执行的研究目标';
field('acceptance').value = '输出证据表';
form.dispatch('submit');
assert.equal(dialog.open, false);
assert.equal(composerSubmissions, 1);
const confirmed = plan.consume('待确认计划', 'skill-a');
assert.equal(confirmed.objective, '可执行的研究目标');
assert.deepEqual(Array.from(confirmed.acceptance), ['输出证据表']);
assert.equal(plan.consume('待确认计划', 'skill-b'), null, 'A different skill cannot consume the pending plan');
assert.equal(plan.consume('待确认计划', 'skill-a'), null, 'A mismatch invalidates the pending plan');
reopen('待确认计划', 'skill-a'); form.dispatch('submit');
plan.selectConversation('b');
assert.equal(plan.consume('待确认计划', 'skill-a'), null, 'Changing conversation invalidates a conversation-scoped pending plan');
plan.selectConversation('a'); reopen('待确认计划', 'skill-a'); form.dispatch('submit');
plan.consume('待确认计划', 'skill-a'); plan.committed();
assert.equal(drafts.text('plan:a', 'plan'), '', 'Commit clears the plan draft');
assert.equal(plan.consume('待确认计划', 'skill-a'), null);

plan.reset(); reopen('首次提交计划');
input('acceptance', '首次验收');
form.dispatch('submit');
plan.selectConversation('new-conversation');
assert.equal(plan.consume('首次提交计划', null).objective, '首次提交计划', 'A pending new-conversation plan survives conversation creation');
plan.committed();
assert.equal(drafts.text('plan:new', 'plan'), '');
assert.equal(drafts.text('plan:new-conversation', 'plan'), '');
plan.selectConversation('saved'); reopen('重置前计划');
input('objective', '重置后仍保留的草稿');
elements.get('plan-cancel').dispatch('click');
reopen('重置前计划');
assert.equal(plan.consume('重置前计划', null), null);
plan.reset();
assert.equal(dialog.open, false, 'Reset closes an open dialog');
assert.equal(plan.consume('重置前计划', null), null);
assert.equal(saved('plan:saved').plan.objective, '重置后仍保留的草稿', 'Reset does not erase durable account drafts');

const hostile = '<img src=x onerror="window.__planXss=1"><script>window.__planXss=2</script>';
const receiptPlan = {objective: hostile, scope: hostile, materials: '资料', tools: '检索', deliverables: '证据表',
  acceptance: [hostile, '说明局限']};
const before = JSON.stringify(receiptPlan);
const receipt = plan.receipt(receiptPlan);
assert(receipt && receipt.tag === 'details');
assert(receipt.dataset.planReceipt === '');
assert(receipt.textContent.includes(hostile), 'Unsafe-looking plan text is retained literally');
assert(receipt.textContent.includes('验收 2 项'), 'Receipt reports the confirmed acceptance count');
assert.equal(all(receipt).filter(node => ['img', 'script'].includes(node.tag)).length, 0, 'Receipt text cannot create elements');
assert.equal(window.__planXss, undefined);
assert.equal(JSON.stringify(receiptPlan), before, 'Receipt rendering does not mutate the confirmed plan');
assert.equal(plan.receipt(null), null);
assert.equal(plan.receipt({acceptance: 'not-an-array'}), null);
console.log('Research plan: defaults, validation, cancel drafts, account/conversation scope, pending consume, commit/reset, literal receipt text and immutable evidence passed');

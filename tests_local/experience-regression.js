'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
class Node {
  constructor(tag, text = '', cls = '') {
    this.tag = tag; this._text = String(text ?? ''); this.className = cls || ''; this.children = [];
    this.attributes = {}; this.dataset = {}; this.events = {}; this.hidden = false;
    this.classList = {
      add: name => { this.className = [...new Set(this.className.split(' ').filter(Boolean).concat(name))].join(' '); },
      toggle: (name, enabled) => {
        const has = this.className.split(' ').includes(name); enabled = enabled ?? !has;
        this.className = this.className.split(' ').filter(x => x && x !== name).concat(enabled ? [name] : []).join(' ');
        return enabled;
      }
    };
  }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  get isConnected() { return this.tag === 'body' || Boolean(this.parent?.isConnected); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const node of [...this.children]) node.remove(); this._text = ''; this.append(...nodes); }
  insert(node, index) { node.remove(); node.parent = this; this.children.splice(index, 0, node); }
  after(node) { this.parent.insert(node, this.parent.children.indexOf(this) + 1); }
  before(node) { this.parent.insert(node, this.parent.children.indexOf(this)); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter(x => x !== this); this.parent = null; } }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, callback) { this.events[name] = callback; }
  querySelectorAll(selector) { return all(this).slice(1).filter(node => selector.startsWith('.') ? node.className.split(' ').includes(selector.slice(1)) : node.tag === selector); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
}
const all = node => [node, ...node.children.flatMap(all)];
const body = new Node('body'), picker = new Node('section', '', 'model-profile-picker'); body.append(picker);
const element = (tag, text, cls) => new Node(tag, text, cls);
const document = {body, getElementById:id => all(body).find(node => node.id === id),
  querySelector:selector => body.querySelector(selector), createTextNode:text => new Node('#text', text)};
const state = {me:{id:'owner-a'}, cid:'conversation-a', runs:new Map()};
let zoomed, opened;
const sandbox = {state, element, document, window:{GeoAgentArtifacts:{preview:(...args)=>{zoomed=args;},openFile:(...args)=>{opened=args;}}},
  statusText:{'Checking the result':'正在检查结果'}, Map, Set};
const web = path.join(__dirname, '../geological_agent/team/web');
const source = fs.readFileSync(path.join(web, 'images.js'), 'utf8');
const start = source.indexOf('// Compact research experience:');
assert(start >= 0);
vm.runInNewContext(source.slice(start), sandbox);
const experience = sandbox.window.GeoAgentExperience;
const turn = new Node('article'), answer = new Node('div'), activity = new Node('details');
turn.append(activity, answer); body.append(turn);
const richRoot = new Node('section'), toolbar = new Node('div', '', 'rich-toolbar'), panel = new Node('div');
richRoot.append(toolbar, panel); turn.append(richRoot);
const ui = {turn, answer, activity, status:'running', finished:false, rich:{root:richRoot,panel}};
state.runs.set('run-a', ui);
experience.attach('run-a', ui); experience.attach('run-a', ui);
assert.equal(turn.querySelectorAll('.run-overview').length, 1, 'One overview per run');
experience.event('run-a', {kind:'tool_start',id:'call-a',name:'GeoRasterIndexAnalysis'});
experience.event('run-a', {kind:'tool_result',id:'call-a',result:{status:'ok'}});
experience.event('run-a', {kind:'tool_start',id:'call-a',name:'GeoRasterIndexAnalysis'});
experience.event('run-a', {kind:'tool_result',id:'call-a',result:{status:'ok'}});
assert(ui.overview.counts.textContent.includes('1 次工具调用'));
assert(ui.overview.counts.textContent.includes('1 成功'));
assert(!ui.overview.counts.textContent.includes('执行中'), 'Replayed start must not downgrade the receipt');
experience.event('run-a', {kind:'tool_start',id:'call-b',name:'OtherTool'});
experience.event('run-a', {kind:'tool_result',id:'call-b',result:{status:'error'}});
assert(ui.overview.counts.textContent.includes('1 失败'));
experience.event('run-a', {kind:'tool_result',id:'call-c',cached:true,result:{status:'ok'}});
assert(ui.overview.counts.textContent.includes('1 复用'));
experience.event('run-a', {kind:'status',message:'Checking the result',turn:3});
assert.equal(ui.overview.heading.textContent, '正在检查执行结果');
const profile = {model:'historical-model', context_window_tokens:32000,max_output_tokens:4096,api_token:'must-never-render'};
experience.event('run-a', {kind:'model_config',profile});
assert(ui.overview.body.textContent.includes('32,000 Tokens'));
assert(!ui.overview.body.textContent.includes(profile.api_token));
experience.model({model:'next-model',context_window_tokens:1000000,max_output_tokens:128000,source:'custom',storage:'account_encrypted'});
assert(document.getElementById('effective-model-summary').textContent.includes('1,000,000 Tokens'));
assert(document.getElementById('effective-model-summary').textContent.includes('128,000 Tokens'));
assert(ui.overview.body.textContent.includes('historical-model'), 'Current connection must not rewrite historical settings');
experience.event('run-a', {kind:'model_config',profile:{model:'older-model'}});
assert(ui.overview.body.textContent.includes('未记录'));
assert(!ui.overview.body.textContent.includes('1,000,000'));
assert.equal(ui.overview.openItems.open, false);
assert(ui.overview.openList.textContent.includes('OtherTool · 1 次未完成'), 'Observed failures are aggregated by tool');
assert(!ui.overview.openList.textContent.includes('GeoRasterIndexAnalysis'), 'Successful calls are not outstanding');
experience.event('run-a', {kind:'stage_timing',active:'tools',totals_seconds:{tools:4}});
assert.equal(ui.overview.currentStage.textContent, '当前阶段 · 执行工具');
experience.event('run-a', {kind:'knowledge_sources',status:'unavailable',references:[]});
assert(ui.overview.openList.textContent.includes('知识库检索未成功'));
experience.event('run-a', {kind:'stream_end',request_id:'interrupted-review',phase:'review',complete:false});
assert(ui.overview.openList.textContent.includes('模型响应中断 · 核对结果'));
experience.event('run-a', {kind:'diagnostic',category:'review_evidence',blocking:false});
experience.event('run-a', {kind:'knowledge_sources',status:'ok',references:[{title:'Source',source:'https://example.org'}]});
experience.event('run-a', {kind:'review_result',passed:true});
assert(!ui.overview.openList.textContent.includes('知识库检索未成功'), 'Successful retry clears the outstanding issue');
assert(!ui.overview.openList.textContent.includes('运行检查仍需处理'), 'Passed review clears the diagnostic');
assert.equal(ui.overview.milestoneCount.textContent, '关键里程碑 · 2');
experience.event('run-a', {kind:'stage_timing',active:'review_wait',totals_seconds:{tools:4,review_wait:1}});
assert.equal(ui.overview.currentStage.textContent, '当前阶段 · 等待结果审核');
const ctx = {run_id:'run-a',conversation_id:'conversation-a',generation:'generation-a',blocks:[],files:[
  {name:'result.png',bytes:2048,sha256:'a'.repeat(64)},
  {name:'ndvi/values.tif',bytes:4096,sha256:'b'.repeat(64)},
  {name:'sources.json',bytes:200,sha256:'c'.repeat(64)},
  {name:'../escape.png',bytes:50,sha256:'d'.repeat(64)},
  {name:'https://remote.example/map.png',sha256:'e'.repeat(64)}
]};
const before = JSON.stringify(ctx);
const image1 = new Node('span', '', 'answer-image'), image2 = new Node('span', '', 'answer-image');
answer.append(image1, image2);
experience.results('run-a', ui, ctx);
assert(!image1.className.includes('is-secondary'));
assert(image2.className.includes('is-secondary'), 'Keep only the first inline image expanded');
assert(ui.rich.compact.textContent.includes('3 个文件'));
assert.equal(ui.rich.compact.querySelectorAll('img').length, 0, 'No duplicate cover when the answer already contains images');
experience.open('run-a', ui);
assert.equal(opened[0].generation, 'generation-a');
assert.equal(opened[0].files.length, 3, 'Only safe versioned manifest entries reach the artifact viewer');
assert(!JSON.stringify(opened).includes('../escape'));
assert(!JSON.stringify(opened).includes('https://remote'));
experience.files(ctx, 'ndvi/values.tif');
assert.equal(opened[1], 'ndvi/values.tif');
const openedBeforeIsolation = opened;
state.cid = 'conversation-b';
experience.files(ctx);
assert.equal(opened, openedBeforeIsolation, 'Old conversation snapshots must not open in a new conversation');
state.cid = 'conversation-a';
experience.files({...ctx,generation:''});
assert.equal(opened, openedBeforeIsolation, 'No unversioned file preview');
ui.resultContext = {...ctx,files:[],blocks:[{id:'block-a',component:'table'}]};
experience.open('run-a', ui);
const drawer = body.querySelector('.results-drawer');
assert(drawer?.open);
assert.equal(panel.parent.className, 'results-drawer-body');
experience.clear();
assert(!body.querySelector('.results-drawer'));
assert.equal(panel.parent, richRoot, 'Closing restores interactive evidence without cloning or discarding controls');
assert.equal(JSON.stringify(ctx), before, 'Rendering must not mutate manifests or scientific evidence');
ui.finished = true; ui.status = 'completed';
experience.event('run-a', {kind:'status',message:'Checking the result',turn:2});
assert.equal(ui.overview.heading.textContent, '已完成', 'Historical status replay must not restart a finished task');
assert.equal(ui.overview.currentStage.textContent, '当前阶段 · 本轮已结束');
assert.equal(ui.overview.openItems.hidden, true, 'Completed runs do not present recovered historical issues as outstanding');
const nativeArgs=JSON.stringify({index:'NDVI',path:'jilin-inputs/jiapigou-sentinel-rgbnir.tif'});
const objectAction=experience.describeTool('GeoRasterIndexAnalysis',JSON.parse(nativeArgs));
assert.equal(JSON.stringify(experience.describeTool('GeoRasterIndexAnalysis',nativeArgs)),JSON.stringify(objectAction),'Historical JSON-string arguments must describe the same action as object arguments');
assert(!experience.describeTool('GeoRasterIndexAnalysis','{broken').title.includes('undefined'));
assert(!experience.describeTool('GeoRasterIndexAnalysis','[1,2]').title.includes('undefined'));
console.log('Research experience: event replay, actual model provenance, compact images, immutable downloads, drawer lifecycle, conversation isolation and JSON-string action labels passed');

const progressTurn = new Node('article'), progressDetails = new Node('details'), progressAnswer = new Node('div');
progressTurn.append(progressAnswer);
const progressSummary = new Node('summary'), progressElapsed = new Node('p', 'Working for 1m 2s', 'run-elapsed');
progressElapsed.setAttribute('role', 'timer'); progressElapsed.setAttribute('aria-live', 'off');
progressDetails.append(progressSummary); progressTurn.append(progressElapsed, progressDetails); body.append(progressTurn);
const progress = {turn:progressTurn, answer:progressAnswer, activity:progressDetails, summary:progressSummary, mode:'agent', hasExtendedProgress:false,
  elapsed:progressElapsed, status:'running', finished:false};
state.runs.set('progress', progress); experience.attach('progress', progress);
assert.equal(progressSummary.textContent, '查看执行详情');
assert(progress.overview.box.querySelector('.run-elapsed') === progressElapsed, 'Preserve the existing elapsed clock node');
assert.equal(progressElapsed.attributes.role, 'timer');
assert.equal(progressElapsed.attributes['aria-live'], 'off');
assert(progressDetails.querySelector('.run-technical-details'), 'Technical metadata belongs inside expandable details');
const update = (data, seq) => experience.event('progress', data, String(seq));
update({kind:'status', message:'Model is working',phase:'intent',turn:1}, 1);
assert.equal(progress.overview.heading.textContent, '正在理解任务要求');
assert(!progress.overview.box.textContent.includes('执行轮次'), 'Do not show model counters as the main activity');
update({kind:'tool_start',id:'ndvi',name:'GeoRasterIndexAnalysis',arguments:{index:'NDVI',path:'inputs/sentinel.tif',api_token:'never-display-this'}},2);
assert.equal(progress.overview.heading.textContent, '正在计算 NDVI 植被指数');
assert.equal(progress.overview.target.textContent, 'inputs/sentinel.tif');
assert(!progress.overview.box.textContent.includes('never-display-this'));
update({kind:'tool_start',id:'ndwi',name:'GeoRasterIndexAnalysis',arguments:{index:'NDWI',path:'inputs/water.tif'}},3);
assert(progress.overview.heading.textContent.includes('NDWI'));
assert(progress.overview.counts.textContent.includes('2 执行中'));
update({kind:'tool_result',id:'ndwi',result:{status:'ok'}},4);
assert(progress.overview.heading.textContent.includes('NDVI'), 'Keep showing the tool still running');
update({kind:'tool_result',id:'ndvi',result:{status:'ok'}},5);
assert.equal(progress.overview.heading.textContent, '工具处理完成，准备下一步');
update({kind:'status',message:'Model is working',phase:'intent'},1);
assert.equal(progress.overview.heading.textContent, '工具处理完成，准备下一步', 'Ignore out-of-order SSE events');
experience.event('progress',{kind:'connection_lost'});
assert.equal(progress.overview.box.dataset.state, 'reconnecting');
experience.event('progress',{kind:'connection_failed'});
assert(progress.overview.heading.textContent.includes('中断'));
update({kind:'status',message:'Checking the result',phase:'final_answer'},6);
assert.equal(progress.overview.heading.textContent, '正在核对答复与原始证据');
update({kind:'tool_start',id:'failure',name:'execute_python',arguments:{code:'private-code',api_token:'private-token'}},7);
assert.equal(progress.overview.heading.textContent, '正在运行计算程序');
assert(!progress.overview.box.textContent.includes('private-'));
update({kind:'tool_result',id:'failure',result:{status:'error',error:{message:'Temporary failure',retryable:true}}},8);
assert.equal(progress.overview.heading.textContent, '这一步未完成，正在判断下一步');
update({kind:'tool_start',id:'context',name:'context_search',arguments:{query:'智能体'}},9);
assert.equal(progress.overview.heading.textContent, '正在检索历史上下文');
assert.equal(progress.overview.target.textContent, '智能体');
update({kind:'finished',status:'needs_input',turns:3},10);
assert.equal(progress.overview.heading.textContent, '等待补充信息');
assert(progress.overview.openList.textContent.includes('execute_python · 1 次未完成 · 可重试'));
assert(progress.overview.openList.textContent.includes('context_search · 1 次结果未记录'));
assert(!progress.overview.counts.textContent.includes('执行中'), 'Terminal state must not keep a retrieval spinner');
assert(progress.overview.counts.textContent.includes('1 结果未记录'));
assert(progress.overview.openList.textContent.includes('本轮尚未交付完整结果'));
assert.equal(progress.overview.currentStage.textContent, '当前阶段 · 本轮已结束');
update({kind:'status',message:'Model is working',phase:'execution'},11);
assert.equal(progress.overview.heading.textContent, '等待补充信息', 'Terminal state cannot be restarted by replay');
console.log('Activity status: real targets, parallel calls, SSE ordering, disconnection, errors, HITL, elapsed-node preservation and secret exclusion passed');

const evidenceReason = 'Invalid source review blocks: ' + JSON.stringify({b1:'Compared term needs its exact quoted source evidence'});
assert.equal(experience.classifyIssue(evidenceReason), 'review_evidence');
assert.equal(experience.classifyIssue('Invalid source review blocks: {"b1":"Missing requested block"}'), 'review_format');
assert.equal(experience.classifyIssue('Model provider error: unavailable'), 'model_service');
assert.equal(experience.classifyIssue('A paper mentioned Invalid source review blocks: {}'), null);
const blockedTurn = new Node('article'), blockedActivity = new Node('details'), blockedAnswer = new Node('div'); blockedTurn.append(blockedActivity, blockedAnswer); body.append(blockedTurn);
const blocked = {turn:blockedTurn,answer:blockedAnswer,activity:blockedActivity,status:'needs_input',finished:true,reason:new Node('p',evidenceReason)};
state.runs.set('blocked', blocked); experience.attach('blocked', blocked);
assert.equal(blocked.overview.heading.textContent, '审核受阻，等待恢复');
assert(blocked.overview.target.textContent.includes('不需要补充研究资料'));
blocked.status='running'; blocked.finished=false;
experience.event('blocked',{kind:'diagnostic',category:'review_evidence'},'1');
experience.event('blocked',{kind:'status',message:'Retrying the completion check'},'2');
assert.equal(blocked.overview.heading.textContent,'正在补齐审核证据');
assert(!blocked.overview.box.textContent.includes('响应格式'));
experience.event('blocked',{kind:'review_result',passed:true},'3');
experience.event('blocked',{kind:'run_outcome',business_state:'completed',task_completed:true},'4');
experience.event('blocked',{kind:'finished',status:'completed'},'5');
assert.equal(blocked.overview.heading.textContent,'已完成');
experience.event('blocked',{kind:'diagnostic',category:'model_service'},'2');
assert.equal(blocked.overview.heading.textContent,'已完成','Old faults must not restart a completed run');
console.log('Business status: evidence repair, review format, service errors, historical paused tasks and completed recovery passed');

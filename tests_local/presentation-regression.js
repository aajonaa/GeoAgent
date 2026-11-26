'use strict';
const assert = require('node:assert/strict');
const { latestRequest } = require('../geological_agent/team/web/presentation-state.js');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Node {
  constructor(tag, text = '') {
    this.tag = tag; this.textContent = text; this.children = [];
    this.attributes = {}; this.dataset = {}; this.events = {};
  }
  append(...nodes) { this.children.push(...nodes); }
  after(node) { this.afterNode = node; }
  replaceChildren(...nodes) { this.children = nodes; }
  insertBefore(node, before) { this.children.splice(this.children.indexOf(before), 0, node); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, callback) { this.events[name] = callback; }
}
const descendants = node => [node, ...node.children.flatMap(descendants)];
const flush = () => new Promise(resolve => setImmediate(resolve));

async function testRenderer() {
  const ui = { answer: new Node('div') };
  const context = { version:1, run_id:'test-run', conversation_id:'test-conversation',
    generation:'fixed-generation', status:'completed', blocks:[{
      id:'file:synthetic.csv', version:1, component:'table', title:'synthetic.csv',
      props:{file:{name:'synthetic.csv', sha256:'fixed-hash'}}
    }] };
  const page = {columns:['Magnitude','Energy'], rows:[['5','1.995e12'],['6','6.310e13']],
    offset:0, total:2, sha256:'fixed-hash'};
  const sandbox = {
    state:{cid:context.conversation_id,view:1,me:{id:'owner'},runs:new Map([['test-run',ui]])},
    element:(tag,text,cls)=>Object.assign(new Node(tag,text),{className:cls}),
    document:{createElementNS:(_,tag)=>new Node(tag),createTextNode:text=>new Node('#text',text),body:new Node('body')},
    window:{GeoPresentationState:{latestRequest}},
    localStorage:{getItem:()=>null,setItem:()=>{}},
    api:async url=>url.includes('/table?')?page:context,
    URL, setTimeout:callback=>{queueMicrotask(callback); return 1;}, clearTimeout:()=>{}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../geological_agent/team/web/presentation.js'),'utf8'),sandbox);
  await flush();
  const card = ui.rich.blocks.children[0];
  const findButton = text => descendants(card).find(n=>n.tag==='button' && n.textContent===text);
  await findButton('查看数据与图表').events.click();
  findButton('图表').events.click();
  let selects = descendants(card).filter(n=>n.tag==='select');
  assert.deepEqual(selects.map(n=>n.attributes['aria-label']),['横轴','纵轴','图形']);
  selects[0].value='0'; selects[0].events.change();
  selects[1].value='1'; selects[1].events.change();
  selects[2].value='bar'; selects[2].events.change();
  assert.equal(descendants(card).filter(n=>n.tag==='rect').length,2);
  const before = descendants(card).find(n=>n.tag==='svg');
  sandbox.window.GeoAgentPresentation.event('test-run',{kind:'finished'});
  await flush();
  assert.equal(ui.rich.blocks.children[0],card,'An identical event must preserve the card');
  assert.equal(descendants(card).find(n=>n.tag==='svg'),before,'An identical event must preserve chart state');
  assert.deepEqual(descendants(card).filter(n=>n.tag==='select').map(n=>n.value),['0','1','bar']);
  console.log('Actual renderer: accessible controls, chart axes, and stable event replay passed');
}

(async () => {
  const gate = latestRequest();
  let displayed;
  let oldResolve, newResolve;
  const oldData = new Promise(resolve => { oldResolve = resolve; });
  const newData = new Promise(resolve => { newResolve = resolve; });
  async function render(promise) {
    const token = gate.begin();
    const incoming = await promise;
    if (!gate.current(token)) return;
    displayed = incoming;
  }
  const oldRequest = render(oldData);
  const newRequest = render(newData);
  newResolve('new sorted page');
  await newRequest;
  oldResolve('stale page');
  await oldRequest;
  assert.equal(displayed, 'new sorted page');
  const independent = latestRequest();
  const token = independent.begin();
  gate.begin();
  assert.equal(independent.current(token), true);
  console.log('Presentation request ordering and independent card state passed');
  await testRenderer();
})().catch(error => { console.error(error); process.exitCode = 1; });

'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Node {
  constructor(tag,text='',cls=''){this.tag=tag;this._text=text??'';this.className=cls;this.children=[];this.events={};this.attributes={};this.dataset={};this.open=false;this.classList={add:x=>{this.className+=' '+x;}};}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  set textContent(x){this._text=String(x);this.children=[];}
  append(...xs){this.children.push(...xs);}
  after(x){this.sibling=x;}
  replaceChildren(...xs){this._text='';this.children=xs;}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(k,v){this.events[k]=v;}
}
const element=(...x)=>new Node(...x), state={runs:new Map(),cid:'c1',view:1};
const sandbox={element,state,URL,Map,Set,performance:{now:()=>1000},document:{createElementNS:(_,tag)=>new Node(tag)},window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../geological_agent/team/web/timeline.js'),'utf8'),sandbox);
const ui={activity:element('details'),summary:element('summary'),list:element('div'),tools:new Map(),finished:false,overview:{box:element('section')}};
state.runs.set('r1',ui);
const timeline=sandbox.window.GeoAgentTimeline;let seq=0;
const send=data=>timeline.event('r1',data,String(++seq));
send({kind:'status',message:'Model is working',phase:'execution',turn:1});
send({kind:'stream_open',request_id:'s1',phase:'execution',turn:1,transport:'native_stream',queue_seconds:.5});
send({kind:'stream_delta',request_id:'s1',phase:'execution',turn:1,channel:'text',offset:0,text:'<script>not HTML</script>',verified:false});
const row=ui.timeline.streams.get('s1');
assert(row.channels.text.content.textContent.includes('<script>'));
assert(row.body.textContent.includes('未审核'));
const text=row.channels.text.content.textContent;
send({kind:'stream_delta',request_id:'s1',channel:'text',offset:0,text:'duplicate',verified:false});
assert.equal(row.channels.text.content.textContent,text);
send({kind:'stream_end',request_id:'s1',complete:true,duration_seconds:2.5,first_text_seconds:1});
assert(row.status.textContent.includes('2.5s'));
send({kind:'stage_timing',active:null,totals_seconds:{queue:.5,model_wait:1,model_stream:1.5,tools:2,review_wait:3}});
assert(ui.timing.summary.textContent.includes('审核 3.0s'));
send({kind:'tool_result',id:'t',name:'GeoX',result:{status:'ok',data:{x:'full raw data'}}});
assert.equal(ui.tools.get('t').output.textContent,'','Raw JSON is not formatted while collapsed');
ui.tools.get('t').raw.open=true;ui.tools.get('t').raw.events.toggle();
assert(ui.tools.get('t').output.textContent.includes('full raw data'));

for (const channel of ['text','reasoning']) {
  const request_id='unicode-'+channel;
  send({kind:'stream_open',request_id,phase:'execution',turn:2,transport:'native_stream',queue_seconds:0});
  const pieces=['\u5730\u8d28 ', '\u{1f30d}', ' e\u0301', '\u{20000}', '\u{1f469}\u200d\u{1f52c}', '\u{1f1e8}\u{1f1f3}', '\ncomplete'];
  let offset=0,expected='';
  for(const text of pieces) {
    send({kind:'stream_delta',request_id,channel,offset,text,verified:false});
    expected+=text;offset+=Array.from(text).length;
  }
  const actual=ui.timeline.streams.get(request_id).channels[channel];
  assert.equal(actual.content.textContent,expected,'Astral, combining and ZWJ characters must not drop following fragments');
  assert.equal(actual.length,offset,'UI offsets match Python Unicode code-point counts');
  send({kind:'stream_delta',request_id,channel,offset:0,text:'replayed',verified:false});
  assert.equal(actual.content.textContent,expected,'Unicode replay stays idempotent');
}
const app=fs.readFileSync(path.join(__dirname,'../geological_agent/team/web/app.js'),'utf8');
const history=app.slice(app.indexOf('function attachRunHistory('),app.indexOf('function subscribe('));
let requests=0, received=[], resolve;
const page={run_id:'r1',events:[{id:1,data:{kind:'status'}}],next:1,through:1,has_more:false};
Object.assign(sandbox,{api:async()=>{requests++;return await new Promise(r=>{resolve=r;});},handleEvent:(...x)=>received.push(x)});
vm.runInNewContext(history,sandbox);
sandbox.attachRunHistory('r1',ui);
assert.equal(requests,0,'Closed history makes no requests');
ui.activity.open=true;ui.activity.events.toggle();ui.activity.events.toggle();
assert.equal(requests,1,'Opening twice coalesces requests');
resolve(page);
setImmediate(()=>{
  assert.equal(received.length,1);assert.equal(received[0][3],true);
  ui.activity.events.toggle();assert.equal(requests,1,'Cached details are not fetched again');
  assert(app.includes("if (runIsWorking(run.status)) { subscribe(run.id)"),'Only active history uses SSE');
  console.log('Live UI: unreviewed literal streaming, offsets, timings, lazy raw receipts, lazy history, request coalescing and no historical SSE passed');
});

'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
class Node {
  constructor(tag,text='',cls=''){this.tag=tag;this._text=String(text??'');this.className=cls;this.children=[];this.attributes={};this.dataset={};this.events={};this.open=false;
    this.classList={add:name=>{this.className+=' '+name;}};}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
  set textContent(text){this.replaceChildren();this._text=String(text);}
  append(...nodes){for(const n of nodes){n.remove();n.parent=this;this.children.push(n);}}
  remove(){if(this.parent){this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null;}}
  replaceChildren(...nodes){for(const n of [...this.children])n.remove();this._text='';this.append(...nodes);}
  setAttribute(key,value){this.attributes[key]=String(value);}
  addEventListener(name,callback){this.events[name]=callback;}
}
const all=n=>[n,...n.children.flatMap(all)];
const element=(...args)=>new Node(...args), state={runs:new Map()};
const sandbox={state,element,URL,Map,Set,document:{createElementNS:(_,tag)=>new Node(tag)},window:{GeoAgentExperience:{describeTool:(name,args)=>({title:name==='GeoRasterIndexAnalysis'?'正在计算 '+args.index:name,detail:args.path||name})}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../geological_agent/team/web/timeline.js'),'utf8'),sandbox);
const timeline=sandbox.window.GeoAgentTimeline;
function make(id,finished=false){const activity=element('details'),summary=element('summary'),list=element('div');activity.append(summary,list);const ui={activity,summary,list,tools:new Map(),finished};state.runs.set(id,ui);timeline.attach(id,ui);return ui;}
const ui=make('run');let seq=0;const send=data=>timeline.event('run',data,String(++seq));
assert.equal(ui.activity.open,true);
send({kind:'status',message:'Model is working',phase:'execution',turn:1});
assert.equal(ui.list.children.length,1);
send({kind:'model_process',phase:'execution',turn:1,source:'provider_reasoning_content',verified:false,text:'<script>unsafe()</script> Provider text, not proof.'});
assert.equal(ui.list.children.length,1,'Process text belongs to its actual model phase');
assert(ui.list.textContent.includes('未经结果审核'));
assert(!all(ui.list).some(n=>n.tag==='script'),'Process text is never interpreted as HTML');
const process=ui.list.children[0];process.open=true;
send({kind:'tool_start',id:'search-a',name:'web_search',arguments:{query:'Sentinel-2 documentation',api_token:'do-not-display'}});
const search=ui.tools.get('search-a');search.details.open=true;
send({kind:'tool_result',id:'search-a',name:'web_search',result:{status:'ok',data:{query:'Sentinel-2 documentation',results:[
  {title:'Public source',url:'https://www.usgs.gov/',snippet:'<img onerror="unsafe()">'},
  {title:'Unsafe URL',url:'javascript:unsafe()',snippet:'not clickable'},
  {title:'Credential URL',url:'https://example.org/?api_key=private',snippet:'not clickable'}
]}}});
assert.equal(ui.tools.size,1);assert.equal(search.status.textContent,'3 条来源');
assert.equal(search.details.open,true);assert.equal(process.open,true,'Incoming events preserve user-expanded rows');
assert(!search.details.textContent.includes('do-not-display'));
const links=all(search.details).filter(n=>n.tag==='a');
assert.equal(links.length,2,'Only one safe source and the authenticated receipt link');
assert.equal(links[0].href,'https://www.usgs.gov/');assert.equal(links[0].rel,'noopener noreferrer');
assert(links[1].href.startsWith('/api/runs/run/receipts/'));
assert(!all(search.details).some(n=>n.tag==='img'),'External source markup is literal text');
const before=ui.list.children.length;
timeline.event('run',{kind:'status',message:'Model is working',phase:'execution',turn:1},'1');
assert.equal(ui.list.children.length,before,'Old SSE events are ignored');
send({kind:'tool_start',id:'index',name:'GeoRasterIndexAnalysis',arguments:{index:'NDVI',path:'image.tif'}});
send({kind:'tool_result',id:'index',name:'GeoRasterIndexAnalysis',result:{status:'ok',data:{mean_ndvi:0.84},artifacts:[{path:'ndvi/values.tif'}]}});
assert(ui.tools.get('index').details.textContent.includes('mean_ndvi'));
assert(ui.tools.get('index').details.textContent.includes('0.84'));
assert(ui.tools.get('index').details.textContent.includes('ndvi/values.tif'));
send({kind:'tool_start',id:'index',name:'GeoRasterIndexAnalysis',arguments:{index:'NDVI',path:'image.tif'}});
assert.equal(ui.tools.get('index').status.textContent,'已完成','Replayed starts never downgrade a result');
send({kind:'tool_result',id:'failed',name:'OtherTool',result:{status:'error',error:{message:'Missing dataset'}}});
assert.equal(ui.tools.get('failed').status.textContent,'未完成');assert(ui.tools.get('failed').details.textContent.includes('Missing dataset'));
ui.summary.events.click();ui.activity.open=true;
send({kind:'finished',status:'completed'});
assert.equal(ui.activity.open,true,'Completion must not override an explicit disclosure choice');
const second=make('second');timeline.event('second',{kind:'finished',status:'completed'},'1');
assert.equal(second.activity.open,false,'Untouched activity collapses on completion');
const historical=make('history',true);timeline.event('history',{kind:'status',message:'Model is working',phase:'execution',turn:1},'1');
assert.equal(historical.activity.open,false);assert(historical.list.textContent.includes('已结束'));
assert(!historical.list.textContent.includes('进行中'));
const preserved=ui.list.textContent;timeline.event('missing',{kind:'tool_start',id:'other',name:'OtherTool'},'1');assert.equal(ui.list.textContent,preserved);
const nativeUI=make('native-strings');let nativeSeq=0;
const nativeSend=data=>timeline.event('native-strings',data,String(++nativeSeq));
const nativeEvent={kind:'tool_start',id:'native-index',name:'GeoRasterIndexAnalysis',arguments:JSON.stringify({path:'jilin-inputs/jiapigou-sentinel-rgbnir.tif',bands:{red:1,green:2,blue:3,nir:4},index:'NDVI',valid_mask_path:'jilin-inputs/jiapigou-clear-mask.tif',output_dir:'jilin-ndvi',api_token:'native-secret',nested:{authorization:'nested-secret'}})};
const nativeBefore=JSON.stringify(nativeEvent);
nativeSend(nativeEvent);
const nativeRow=nativeUI.tools.get('native-index');
assert.equal(nativeRow.label.textContent,'计算 NDVI');
assert(nativeRow.description.textContent.includes('jiapigou-sentinel-rgbnir.tif'));
assert(all(nativeRow.content).filter(n=>n.tag==='dt').some(n=>n.textContent==='index'));
assert(!all(nativeRow.content).filter(n=>n.tag==='dt').some(n=>/^\d+$/.test(n.textContent)),'JSON arguments must not become character fields');
assert(!nativeRow.body.textContent.includes('native-secret'));
assert(!nativeRow.body.textContent.includes('nested-secret'));
assert(nativeRow.input.textContent.includes('JSON 字符串参数已展开显示'));
nativeRow.details.open=true;
nativeSend({kind:'tool_result',id:'native-index',result:{name:'GeoRasterIndexAnalysis',status:'ok',data:{analysis_type:'raster_index',manifest_path:'jilin-ndvi/analysis.geoanalysis.json'},artifacts:[{path:'jilin-ndvi/values.tif'}]}});
assert.equal(nativeRow.status.textContent,'已完成');assert(nativeRow.details.open);
assert(nativeRow.content.textContent.includes('jilin-ndvi/values.tif'));
assert.equal(JSON.stringify(nativeEvent),nativeBefore,'Display decoding must not mutate native evidence');
nativeSend({kind:'tool_start',id:'native-search',name:'web_search',arguments:'{"query":"Sentinel-2 sources","api_key":"search-secret"}'});
assert.equal(nativeUI.tools.get('native-search').label.textContent,'搜索资料 · Sentinel-2 sources');
assert(!nativeUI.tools.get('native-search').body.textContent.includes('search-secret'));
nativeSend({kind:'tool_start',id:'native-fetch',name:'web_fetch',arguments:'{"url":"https://www.usgs.gov/"}'});
assert.equal(nativeUI.tools.get('native-fetch').label.textContent,'读取网页 · www.usgs.gov');
for(const [i,args] of ['{"api_token":"malformed-secret"', '[1,2]', 'null', '7', '"text"', '', null, [], 7].entries()) {
  nativeSend({kind:'tool_start',id:'invalid-'+i,name:'UnknownTool',arguments:args});
  const row=nativeUI.tools.get('invalid-'+i);
  assert(row.content.textContent.includes('参数无法结构化显示'));
  assert.equal(all(row.content).filter(n=>n.tag==='dt').length,0);
  assert(!row.body.textContent.includes('malformed-secret'),'Malformed unparsed arguments must not leak credentials');
}
console.log('Timeline: ordering, expandable provider text, safe source cards, native receipts, errors, event replay, independent disclosure state, run isolation and immutable JSON-string arguments passed');

const repairUI=make('review-repair');let repairSeq=0;
const repairSend=data=>timeline.event('review-repair',data,String(++repairSeq));
repairSend({kind:'status',message:'Checking the result',turn:1});
const repairEvent={kind:'diagnostic',category:'review_evidence',phase:'knowledge_semantics',turn:1,blocking:false};
const repairBefore=JSON.stringify(repairEvent);repairSend(repairEvent);
assert(repairUI.list.textContent.includes('补齐审核证据'));
assert(!repairUI.list.textContent.includes('响应异常'));
const issueRow=repairUI.list.children[1];assert.equal(issueRow.dataset.state,'attention');
repairSend({kind:'status',message:'Retrying the completion check',turn:2});
assert(!repairUI.list.textContent.includes('修正响应格式'));
repairSend({kind:'review_result',passed:true,turn:2});
assert(issueRow.textContent.includes('已纠正'));
assert.equal(JSON.stringify(repairEvent),repairBefore,'Issue presentation never mutates evidence');
repairSend({kind:'finished',status:'completed'});
assert.equal(repairUI.activity.open,false);
console.log('Typed diagnostic timeline: evidence repairs, retained recovered errors and native ordering passed');

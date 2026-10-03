'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const ids = new Map();
class Node {
  constructor(tag='div') { this.tagName=tag;this.children=[];this.events={};this.attrs={};this.dataset={};this.value='';this.hidden=false;this.disabled=false;this.open=false;this.classes=new Set();this._text='';this.className='';this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x)}; }
  set id(id) {this._id=id;ids.set(id,this);} get id(){return this._id;}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join(' ');}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this._text='';this.children=nodes;}
  get firstChild(){return this.children[0];}
  get options(){return this.children;}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k];}
  addEventListener(k,fn){(this.events[k] ||= []).push(fn);}
  async fire(k,event={}){for(const fn of this.events[k]||[])await fn(event);await new Promise(setImmediate);}
  focus(){focused=this;}
  closest(){return main;}
  showModal(){this.open=true;}
  close(){this.open=false;for(const fn of this.events.close||[])fn();}
}
let focused=null;
const main=new Node();
const names=['library-view','library-detail','library-open','library-open-top','library-back','library-stats',
 'library-skills-count','library-tools-count','library-disclaimer','library-revision','library-category',
 'library-status','library-search','library-results','library-match-count','library-reset','library-detail-back',
 'library-detail-close','library-detail-body','library-use-note','library-use','library-skills-tab',
 'library-tools-tab','files-panel','sidebar','prompt'];
for(const name of names){const n=new Node();n.id=name;}
const $=id=>ids.get(id), tabs=[$('library-skills-tab'),$('library-tools-tab')];
tabs[0].dataset.libraryKind='skills';tabs[1].dataset.libraryKind='tools';
const element=(tag,text,cls)=>{const n=new Node(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const rows={
 skills:[
  {id:'energy',name:'Energy skill',kind:'skills',scope:'professional',description:'Energy analysis',category:'earthquake',tags:['energy'],status:'registered',tool_count:1,available_tool_count:1,tool_preview:['EnergyTool']},
  {id:'blocked',name:'Blocked method',kind:'skills',description:'Missing data',category:'Other',tags:[],status:'blocked',tool_count:1,available_tool_count:0,tool_preview:['MissingTool']},
 ],
 tools:[
  {id:'EnergyTool',name:'EnergyTool',native_name:'EnergyTool',kind:'tools',scope:'professional',description:'Estimate energy <img src=x onerror=alert(1)>',category:'earthquake',status:'registered',tags:['energy']},
  {id:'MissingTool',name:'MissingTool',kind:'tools',scope:'professional',description:'Not implemented',category:'Other',status:'blocked',tags:[]},
 ],
 counts:{skills:2,tools:2,professional_tools:2,registered_tools:1,runtime_tools:0},
 revision:'test-revision',release:'test-release',notice:'Registration is not validation.',
};
const details={
 'skills/energy':{...rows.skills[0],required_inputs:['Mw'],expected_outputs:['Energy J'],constraints:['Empirical'],instructions:'# Energy instructions',document_kind:'Runtime skill',tools:[{id:'EnergyTool',name:'EnergyTool',status:'registered'}],example_prompt:'Estimate energy for Mw=6.'},
 'skills/blocked':{...rows.skills[1],required_inputs:[],expected_outputs:[],constraints:[],instructions:'Unavailable',document_kind:'Registered only',tools:[],example_prompt:'',reason:'Missing backend'},
 'tools/EnergyTool':{...rows.tools[0],input_schema:{type:'object',properties:{Mw:{type:'number',minimum:0,maximum:10,description:'Moment magnitude'}},required:['Mw'],additionalProperties:false},output_schema:{type:'object',properties:{energy:{type:'number'}},required:['energy']},example_arguments:{Mw:6},path_fields:[],limitations:['Empirical'],skills:[{id:'energy',name:'Energy skill',status:'registered'}],version:'v1',validation:'Not certified',example_prompt:'Estimate energy for Mw=6.'},
};
let fail=false,hold=null,heldResolve=null;
const calls=[], state={me:{username:'test'},busy:null}, window={GeoToolHITL:{blocksComposer:()=>false}};
async function api(path,options){calls.push({path,options});if(fail)throw Error('offline');if(path===hold)return new Promise(resolve=>{heldResolve=resolve;});return structuredClone(path==='/api/library'?rows:details[path.replace('/api/library/','')]);}
let noticeText='';
const context={document:{getElementById:$,querySelectorAll:()=>tabs},window,state,element,api,
 markdown:(target,text)=>target.append(element('p',text)),notice:text=>{noticeText=text;},
 Option:function(text,value){const n=element('option',text);n.value=value;return n;},Set,Map,console};
context.$=$;
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
function descendants(n){return [n,...n.children.flatMap(descendants)];}
function buttonWith(n,text){return descendants(n).find(x=>x.tagName==='button'&&x.textContent.includes(text));}
async function mainTest(){
 await $('library-open').fire('click');
 assert.equal($('library-results').children.length,2);
 assert.equal($('library-view').hidden,false);
 assert.equal(calls.length,1);
 await $('library-tools-tab').fire('click');
 $('library-search').value='EnergyTool';await $('library-search').fire('input');
 assert.equal($('library-results').children.length,1);
 assert.match($('library-results').textContent,/<img/);
 assert(!descendants($('library-results')).some(x=>x.tagName==='img'));
 $('library-search').value='no-such-asset';await $('library-search').fire('input');
 assert($('library-results').textContent.includes('no-such-asset')===false);
 assert.equal($('library-results').children.length,1);
 await $('library-reset').fire('click');
 await $('library-skills-tab').fire('click');
 await $('library-results').children[0].fire('click');
 assert.equal($('library-detail-title').textContent,'Energy skill');
 await buttonWith($('library-detail-body'),'EnergyTool').fire('click');
 assert.equal($('library-detail-title').textContent,'EnergyTool');
 assert.equal($('library-detail-back').hidden,false);
 await $('library-detail-back').fire('click');
 assert.equal($('library-detail-title').textContent,'Energy skill');
 assert.equal($('library-detail-back').hidden,true);
 $('prompt').value='Existing draft';
 await $('library-use').fire('click');
 assert.equal($('prompt').value,'Existing draft\n\nEstimate energy for Mw=6.');
 assert.equal($('library-detail').open,false);
 assert.equal($('library-view').hidden,true);
 assert.equal(focused,$('prompt'));
 assert(noticeText.length>0);
 assert(calls.every(c=>c.options===undefined));
 await $('library-open').fire('click');
 await $('library-results').children[1].fire('click');
 assert.equal($('library-use').disabled,true);
 const draft=$('prompt').value;
 await $('library-use').fire('click');
 assert.equal($('prompt').value,draft);
 await $('library-detail-close').fire('click');
 state.busy='other-task';
 await $('library-results').children[0].fire('click');
 assert.equal($('library-use').disabled,true);
 await $('library-use').fire('click');assert.equal($('prompt').value,draft);
 state.busy=null;await $('library-detail-close').fire('click');
 hold='/api/library/skills/energy';
 const pending=$('library-results').children[0].fire('click');
 await $('library-results').children[1].fire('click');
 heldResolve(structuredClone(details['skills/energy']));await pending;
 assert.equal($('library-detail-title').textContent,'Blocked method');
 hold=null;await $('library-detail-close').fire('click');
 await $('library-tools-tab').fire('click');window.GeoToolLibrary.reset();
 assert.equal($('library-skills-tab').attrs['aria-selected'],'true');
 assert.equal($('library-tools-tab').attrs['aria-selected'],'false');
 fail=true;await $('library-open').fire('click');
 assert.match($('library-results').textContent,/offline/);
 fail=false;await descendants($('library-results')).find(n=>n.tagName==='button').fire('click');
 assert.equal($('library-results').children.length,2);
 window.GeoToolHITL.blocksComposer=()=>true;
 await $('library-results').children[0].fire('click');
 assert.equal($('library-use').disabled,true);
 await $('library-use').fire('click');assert.equal($('prompt').value,draft);
 assert(calls.every(c=>c.options===undefined));
 console.log('library UI checks passed: filters, links/back, safe text, drafts, no execution, busy/HITL, stale responses, reset, retry');
}
mainTest().catch(error=>{console.error(error);process.exitCode=1;});

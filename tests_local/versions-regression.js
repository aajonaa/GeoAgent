'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
class Node {
  constructor(tag, text = '', cls = '') { this.tag=tag; this.text=String(text ?? ''); this.className=cls||''; this.children=[]; this.events={}; this.attributes={}; this.hidden=false; this.isConnected=true; this.parent=null; }
  get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  set textContent(v){this.replaceChildren();this.text=String(v);}
  append(...nodes){for(const n of nodes){n.remove();n.parent=this;this.children.push(n);}}
  replaceChildren(...nodes){for(const n of this.children)n.parent=null;this.text='';this.append(...nodes);}
  remove(){if(this.parent){this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}}
  setAttribute(k,v){this.attributes[k]=String(v);}
  addEventListener(k,fn){this.events[k]=fn;}
}
const all=n=>[n,...n.children.flatMap(all)], find=(root,predicate)=>all(root).find(predicate), buttons=root=>all(root).filter(n=>n.tag==='button');
const host=new Node('div'), document={createElement:tag=>new Node(tag),getElementById:id=>id==='versions-panel'?host:null};
const state={me:{id:'alice'},cid:'cid-a'}, calls=[], window={confirm:()=>true,loadFiles:async()=>{calls.push(['reload']);}};
const generationA='a'.repeat(32), generationB='b'.repeat(32), restored='c'.repeat(32);
let rejectOldDetail = null;
const api=async url=>{
  calls.push([url]);
  if(url.endsWith('/generations'))return {items:[
    {generation:generationB,current:true,created:2,file_count:1,bytes:10},
    {generation:generationA,current:false,created:1,file_count:1,bytes:10}]};
  if(url.includes('/generation-evidence'))return {note:'仅展示实际引用',items:[{run_id:'run-a',answer:'结论 [citation]',items:[{title:'来源 A',text:'原文片段',pages:[4],sha256:'d'.repeat(64)}],unavailable_ids:[]}]};
  if(url.includes('/generation-compare'))return {changes:[{name:'figure.png',status:'modified',left_sha256:'1'.repeat(64),right_sha256:'2'.repeat(64)}],counts:{added:0,removed:0,modified:1,unchanged:0}};
  if(url.includes('/generation?') && rejectOldDetail && url.includes('id='+generationA))return new Promise((_,reject)=>{rejectOldDetail=reject;});
  if(url.includes('/generation?'))return {file_count:1,bytes:10,files:[{name:'figure.png',bytes:10,sha256:'2'.repeat(64)}],figures:[{name:'figure.png',width:20,height:10,source:null,coordinate_reference:null,source_coordinate_reference:null,transform:null,units:null,band_units:['m','s'],cartographic_scale:null,manifest:null}]};
  if(url.includes('/generation-restore'))return {generation:restored};
  throw new Error('Unexpected URL '+url);
};
const sandbox={document,window,state,api};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../geological_agent/team/web/versions.js'),'utf8'),sandbox);
(async()=>{
  await sandbox.window.GeoAgentVersions.render({},'cid-a');
  assert(host.textContent.includes('成果版本'));
  assert(host.textContent.includes('结论与证据定位'));
  assert(host.textContent.includes('结论 [citation]'));
  assert(host.textContent.includes('原文片段'));
  assert.equal(all(host).filter(n=>n.tag==='dd'&&n.text==='未记录').length,7);
  assert(host.textContent.includes('波段单位'));
  assert(host.textContent.includes('1: m；2: s'));
  await find(host,n=>n.tag==='button'&&n.text==='比较版本').events.click();
  assert(host.textContent.includes('版本差异'));
  assert(host.textContent.includes('修改 1'));
  await find(host,n=>n.tag==='button'&&n.text==='恢复此版本为新版本').events.click();
  assert(calls.some(([url])=>url.includes('/generation-restore?generation='+generationB)));
  assert(calls.some(([name])=>name==='reload'));
  assert(host.textContent.includes('比例尺'));
  rejectOldDetail = true;
  const current = find(host,n=>n.tag==='select'&&n.attributes['aria-label']==='查看版本');
  current.value=generationA; current.events.change();
  current.value=generationB; current.events.change();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(typeof rejectOldDetail,'function');
  rejectOldDetail(new Error('stale failure'));
  rejectOldDetail = null; await Promise.resolve(); await Promise.resolve();
  assert(!host.textContent.includes('stale failure'));
  assert(host.textContent.includes('1 个文件'));
  console.log('evidence and generation versions regression passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

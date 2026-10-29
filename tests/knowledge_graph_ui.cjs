// DOM regression only: no browser, service, model or GPU access.
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const assert = require('node:assert/strict');
const {JSDOM} = require(process.env.KG_JSDOM_PATH || 'jsdom');
const script = readFileSync(join(__dirname,'../geological_agent/team/web/knowledge-graph.js'),'utf8');
const wait = () => new Promise(resolve=>setTimeout(resolve,30));
(async()=>{
  const dom = new JSDOM('<main id="app"><section id="knowledge-view"><section id="knowledge-panel-graph"></section></section><button id="logout">Logout</button></main>',{runScripts:'outside-only',url:'https://graph-fixture.invalid'});
  const w=dom.window, doc=w.document, calls=[];
  let updated='first';
  const entity={id:'a'.repeat(24),label:'黄铁矿',kind:'mineral',mentions:1,documents:1};
  const quote='🙂未发现黄铁矿。<script>globalThis.injected=true</script>';
  const item={...entity,entity_id:entity.id,document_id:'test-doc',title:'<img src=x onerror=alert(1)> 测试文献',text:quote,groups:['高相关'],pages:[2,3],quality_status:'manual_review_required',start_char:0,end_char:Array.from(quote).length,mention_start:4,mention_end:7};
  w.api=async(path,options={})=>{
    calls.push({path,options});
    const u=new URL(path,'https://graph-fixture.invalid');
    if(u.pathname==='/api/knowledge-graph/build'){updated='second';return {accepted:true};}
    if(u.pathname==='/api/knowledge-graph')return {counts:{documents:1,built_documents:1,entities:1,mentions:1,connected_documents:1,missing_or_stale_documents:0,failed_documents:0},types:{mineral:'矿物'},groups:['高相关','低相关'],vocabulary_size:106,job:{status:'completed',updated_at:updated}};
    if(u.pathname==='/api/knowledge-graph/entities')return {items:[entity],total:1,offset:0,limit:24};
    if(u.pathname==='/api/knowledge-graph/entities/'+entity.id)return {items:[item],total:1,offset:0,limit:8};
    if(u.pathname==='/api/knowledge-graph/documents')return {items:[{id:'test-doc',title:item.title,current:true,mentions:1,diagnostics:{}}]};
    throw new Error('Unexpected API path '+path);
  };
  w.eval(script);await wait();await wait();
  assert.equal(doc.querySelectorAll('.kgraph-metric').length,4);
  assert.equal(doc.querySelectorAll('.kgraph-svg [role="button"]').length,1);
  assert.equal(doc.querySelector('mark').textContent,'黄铁矿');
  assert(doc.querySelector('blockquote').textContent.includes('未发现'));
  assert.equal(doc.querySelector('.kgraph-evidence').querySelectorAll('img,script').length,0);
  assert(doc.querySelector('.kgraph-meta').textContent.includes('需复核'));
  let source;
  doc.addEventListener('geoagent:graph-source',e=>source=e.detail);
  doc.querySelector('.kgraph-evidence-item button').click();
  assert.equal(source.document_id,'test-doc');assert.equal(source.hit.text,quote);
  const group=doc.querySelector('[aria-label="原始资料分类"]');group.value='低相关';group.dispatchEvent(new w.Event('change'));await wait();
  assert(calls.some(c=>decodeURIComponent(c.path).includes('group=低相关')));
  doc.querySelector('.kgraph-head button').click();await wait();await wait();
  assert(calls.some(c=>c.path.endsWith('/build')&&c.options.method==='POST'));
  assert(!doc.querySelector('.kgraph-notice').textContent.includes('正在读取真实进度'));
  // Session expiry hides and clears private content without requiring logout.
  doc.getElementById('app').hidden=true;await wait();
  assert.equal(doc.querySelectorAll('.kgraph-evidence-item').length,0);
  assert.equal(doc.querySelectorAll('.kgraph-entity').length,0);
  assert.equal(doc.querySelectorAll('.kgraph-metric').length,0);
  dom.window.close();console.log('PASS: graph DOM, escaped content, source events, filters, fast build completion and session clearing');
})().catch(error=>{console.error(error);process.exitCode=1;});

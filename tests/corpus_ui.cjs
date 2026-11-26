const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom');
const dom=new JSDOM('<button id="logout">退出</button><section id="knowledge-panel-corpus" hidden></section>',{url:'http://localhost/',runScripts:'outside-only'});
const w=dom.window,d=w.document,requests=[];
let summaryResolve=null;
w.fetch=async path=>{
  requests.push(path);const url=new URL(path,'http://localhost');
  let value;
  if(url.pathname==='/api/knowledge-corpus'){
    if(summaryResolve===true)return new Promise(resolve=>summaryResolve=resolve);
    value={collections:[{imported_documents:349818,expected_documents:349818,metadata:{categories:{'ES01.01':{label:'矿物学',deduplicated:20564}}}}],states:{pending:349800,ready:18},account_capacity:500000,legacy_documents:257};
  }else if(url.pathname==='/api/knowledge-corpus/papers'){
    value={documents:[{id:'a'.repeat(32),title:'<script>not executable</script>',year:'2020',l1_labels:['地学'],l2_labels:['矿物学'],index_state:'pending'}],next_cursor:url.searchParams.get('after')?null:'cursor2'};
  }else value={id:'a'.repeat(32),title:'文献',body:url.searchParams.has('start')?'后一段':'前一段',total_characters:50000,index_state:'pending',next_start:url.searchParams.has('start')?null:24000};
  return {ok:true,json:async()=>value};
};
w.eval(fs.readFileSync('geological_agent/team/web/knowledge-corpus.js','utf8'));
const settle=()=>new Promise(r=>setTimeout(r,0));
const click=text=>[...d.querySelectorAll('button')].find(n=>n.textContent===text).click();
(async()=>{
 const p=d.getElementById('knowledge-panel-corpus');p.hidden=false;await settle();await settle();
 assert(d.querySelector('.kc-metrics').textContent.includes('500,000'));
 assert.equal(d.querySelectorAll('.kc-paper').length,1);assert.equal(d.querySelectorAll('.kc-paper script').length,0);
 click('下一页');await settle();assert(requests.at(-1).includes('after=cursor2'));assert(d.querySelector('.kc-pager').textContent.includes('第 2 页'));
 click('上一页');await settle();assert(d.querySelector('.kc-pager').textContent.includes('第 1 页'));
 const category=d.querySelector('[aria-label="学科分类"]');category.value='ES01.01';category.dispatchEvent(new w.Event('change'));await settle();assert(requests.at(-1).includes('category=ES01.01'));
 click('清除筛选');await settle();assert.equal(category.value,'');
 d.querySelector('.kc-title').click();await settle();assert.equal(d.querySelector('.kc-body').textContent,'前一段');
 click('继续阅读');await settle();assert.equal(d.querySelector('.kc-body').textContent,'前一段后一段');assert(d.querySelector('.kc-detail a').href.endsWith('/source'));
 click('← 返回文献列表');assert(d.querySelector('.kc-detail').hidden);
 p.hidden=true;await settle();p.hidden=false;await settle();await settle();assert.equal(d.querySelectorAll('.kc-paper').length,1);
 summaryResolve=true;click('刷新统计');await settle();d.getElementById('logout').click();
 summaryResolve({ok:true,json:async()=>({collections:[{imported_documents:999,expected_documents:999,metadata:{}}],states:{},account_capacity:500000,legacy_documents:257})});await settle();
 assert.equal(d.querySelector('.kc-metrics').textContent,'');assert.equal(d.querySelector('.kc-list').textContent,'');
 console.log(JSON.stringify({passed:13,scope:'paging, filters, text escaping, source reading, logout isolation'}));dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1;});

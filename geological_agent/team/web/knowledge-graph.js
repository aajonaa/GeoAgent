'use strict';
(() => {
  const $ = id => document.getElementById(id), panel = $('knowledge-panel-graph');
  if (!panel) return;
  const number = new Intl.NumberFormat('zh-CN');
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const button = (text, action, cls = 'k-button') => { const n = node('button',cls,text); n.type='button'; n.addEventListener('click',action); return n; };
  let version = 0, listTicket = 0, evidenceTicket = 0, timer = null, metadata = null, selected = null, entityOffset = 0, evidenceOffset = 0, documentOffset = 0, pendingBuild = false, previousBuild = null;
  const visible = () => !panel.hidden && !$('knowledge-view').hidden && !$('app')?.hidden;
  const head = node('header','kgraph-head'), title = node('div');
  title.append(node('p','k-eyebrow','LITERATURE CONNECTIONS'),node('h2','','从一条线索，读到它的出处。'),node('p','','连接当前账号的全部知识资料，保留原来的分类。点击地质术语，查看原文提及、关联文献和来源页码。'));
  const build = button('建立／更新图谱',startBuild,'k-button k-primary'); head.append(title,build);
  const status = node('p','kgraph-notice'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
  const metrics = node('div','kgraph-metrics'); metrics.setAttribute('aria-label','知识图谱统计');
  const toolbar = node('form','kgraph-toolbar');
  function field(label, element) { const box = node('label','kgraph-field'); box.append(node('span','',label),element); return box; }
  const query = node('input'); query.type='search'; query.maxLength=200; query.placeholder='例如：黄铁矿、李坝、三叠纪'; query.setAttribute('aria-label','搜索图谱术语');
  const kind = node('select'), group = node('select'); kind.setAttribute('aria-label','实体类别'); group.setAttribute('aria-label','原始资料分类');
  kind.append(new Option('全部类别','')); group.append(new Option('全部分类',''));
  toolbar.append(field('地质术语',query),field('实体类别',kind),field('原始分类',group),button('查找',()=>loadEntities(0)));
  toolbar.addEventListener('submit',event=>{event.preventDefault();loadEntities(0);});
  kind.addEventListener('change',()=>loadEntities(0)); group.addEventListener('change',()=>loadEntities(0));
  const layout = node('div','kgraph-layout'), map = node('section','kgraph-map'), detail = node('section','kgraph-evidence');
  const mapHead = node('div','kgraph-panel-head'), mapTitle = node('h3','','文献关联'), mapCount = node('span'); mapHead.append(mapTitle,mapCount);
  const canvas = node('div'), legend = node('p','kgraph-legend','连线表示资料中有该术语的原文提及，不表示两个地质实体之间存在因果或成矿关系。图上显示当前页前 12 项，下方列表可翻页查看全部。');
  const entities = node('div','kgraph-entities'), entityPages = node('div','kgraph-pages');
  map.append(mapHead,canvas,legend,entities,entityPages);
  const detailHead = node('div','kgraph-panel-head'), detailTitle = node('h3','','原文证据'), detailCount = node('span'); detailHead.append(detailTitle,detailCount);
  const evidence = node('div','kgraph-evidence-list'), evidencePages = node('div','kgraph-pages'); evidence.append(node('p','kgraph-empty','选择左侧术语，打开文献中的真实表述。'));
  detail.append(detailHead,evidence,evidencePages); layout.append(map,detail);
  const documents = node('details','kgraph-documents'); documents.append(node('summary','','全部资料覆盖情况'));
  const documentRows = node('div'), documentPages = node('div','kgraph-pages'); documents.append(documentRows,documentPages);
  documents.addEventListener('toggle',()=>{if(documents.open) loadDocuments(0);});
  const note = node('p','kgraph-notice','首版采用可审计的地学术语表；未识别到术语的文献仍保留在覆盖列表中。原文提及不等于事实验证，否定、不同观点和解析质量状态会随证据一起保留。');
  panel.append(head,metrics,status,toolbar,layout,documents,note);

  function say(text,error=false){status.textContent=text;status.classList.toggle('is-error',error);}
  function resetDetail(){selected=null;evidenceTicket++;detailTitle.textContent='原文证据';detailCount.textContent='';evidencePages.replaceChildren();evidence.replaceChildren(node('p','kgraph-empty','选择左侧术语，打开文献中的真实表述。'));}
  function openEvidence(item) {
    // The PDF reader independently verifies the body hash, exact range and block
    // provenance. Forward the original block IDs; never jump from page hints alone.
    const hit = {...item, metadata: {...item.metadata,
      block_ids: Array.isArray(item.block_ids) ? [...item.block_ids] : []}};
    document.dispatchEvent(new CustomEvent('geoagent:graph-source', {
      detail: {document_id: item.document_id, hit}
    }));
  }
  function paging(target,offset,limit,total,action){target.replaceChildren();const prev=button('上一页',()=>action(Math.max(0,offset-limit)),''),next=button('下一页',()=>action(offset+limit),'');prev.disabled=offset===0;next.disabled=offset+limit>=total;target.append(prev,node('span','',total?`${number.format(offset+1)}–${number.format(Math.min(offset+limit,total))} / ${number.format(total)}`:'0 项'),next);}
  function options(select,items,first){const old=select.value;select.replaceChildren(new Option(first,''));for(const [value,label] of items) select.append(new Option(label,value));if([...select.options].some(o=>o.value===old)) select.value=old;}
  async function refresh(){
    const ticket=version;
    try{
      const data=await api('/api/knowledge-graph');if(ticket!==version||!visible())return;metadata=data;
      const c=data.counts;metrics.replaceChildren();for(const [value,label] of [[c.documents,'当前账号资料记录'],[c.built_documents,'已扫描记录'],[c.entities,'已识别地质术语'],[c.mentions,'原文提及']]){const card=node('div','kgraph-metric');card.append(node('strong','',number.format(value)),node('span','',label));metrics.append(card);}
      options(kind,Object.entries(data.types),'全部类别');options(group,data.groups.map(g=>[g,g]),'全部分类');
      const job=data.job,running=job?.status==='running';build.disabled=running;
      if(pendingBuild&&job?.updated_at!==previousBuild&&job?.status!=='running')pendingBuild=false;
      if(running){pendingBuild=false;say(`正在建立图谱 · 已处理 ${number.format(job.completed)} / ${number.format(job.total)} 条资料。已有结果可以继续浏览。`);}
      else if(job?.status==='failed'||job?.status==='interrupted'){pendingBuild=false;say('上次构建中断，已完成资料保留。点击「建立／更新图谱」可继续。',true);}
      else if(pendingBuild){say('构建请求已提交，正在读取真实进度…');}
      else if(c.missing_or_stale_documents){say(`${number.format(c.missing_or_stale_documents)} 条资料尚待更新；被修改或删除的原文证据不会继续展示。`);}
      else if(job){say(`已覆盖 ${number.format(c.built_documents)} 条资料；其中 ${number.format(c.connected_documents)} 条识别到术语。${c.failed_documents?c.failed_documents+' 条来源校验失败，请查看覆盖列表。':''} ${number.format(data.vocabulary_size)} 个受控术语，支持后续扩充。`,!!c.failed_documents);}
      else say('图谱尚未建立。点击右上角按钮扫描当前账号全部已入库资料，不调用聊天模型。');
      clearTimeout(timer);if(running||pendingBuild)timer=setTimeout(async()=>{await refresh();if(metadata?.job?.status!=='running'&&!pendingBuild)loadEntities(entityOffset);},2000);
    }catch(error){if(ticket===version&&visible())say(error.message,true);build.disabled=false;}
  }
  async function startBuild(){build.disabled=true;pendingBuild=true;previousBuild=metadata?.job?.updated_at;say('正在提交构建任务…');try{await api('/api/knowledge-graph/build',{method:'POST',body:{}});await refresh();}catch(error){pendingBuild=false;say(error.message,true);build.disabled=false;}}
  function svgElement(tag,attrs,text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;}
  function draw(items){
    const svg=svgElement('svg',{viewBox:'0 0 620 430',class:'kgraph-svg',role:'group','aria-label':'文献与术语原文提及关联图'});
    if(!items.length){canvas.replaceChildren(node('p','kgraph-empty','没有匹配的术语。调整筛选条件，或先建立图谱。'));return;}
    const shown=items.slice(0,12);
    shown.forEach((item,i)=>{const angle=2*Math.PI*i/shown.length-Math.PI/2,x=310+224*Math.cos(angle),y=209+148*Math.sin(angle);svg.append(svgElement('line',{x1:310,y1:209,x2:x,y2:y,class:'kg-edge'}));const g=svgElement('g',{class:'kg-node-control',tabindex:0,role:'button','aria-label':`${item.label}，${item.documents} 条文献记录，查看证据`,'data-entity':item.id});g.append(svgElement('circle',{cx:x,cy:y,r:26,class:'kg-node'}),svgElement('text',{x,y:y+4},item.label.length>6?item.label.slice(0,5)+'…':item.label),svgElement('text',{x,y:y+44},`${item.documents} 条资料`));g.addEventListener('click',()=>choose(item));g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(item);}});svg.append(g);});
    svg.append(svgElement('circle',{cx:310,cy:209,r:53,class:'kg-center'}),svgElement('text',{x:310,y:205,class:'kg-center-text'},group.value||'当前知识资料'),svgElement('text',{x:310,y:226,class:'kg-center-text'},'原文提及'));
    canvas.replaceChildren(svg);
  }
  function choose(item){selected=item;evidenceOffset=0;entities.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.entity===item.id)));canvas.querySelectorAll('.kg-node-control').forEach(n=>n.classList.toggle('kg-selected',n.dataset.entity===item.id));loadEvidence(0);}
  async function loadEntities(offset=0){
    entityOffset=offset;const ticket=++listTicket,turn=version;resetDetail();
    try{const params=new URLSearchParams({q:query.value.trim(),kind:kind.value,group:group.value,offset:String(offset),limit:'24'}),data=await api('/api/knowledge-graph/entities?'+params);if(turn!==version||ticket!==listTicket||!visible())return;mapCount.textContent=`${number.format(data.total)} 个术语`;draw(data.items);entities.replaceChildren();for(const item of data.items){const b=button('',()=>choose(item),'kgraph-entity');b.dataset.entity=item.id;b.setAttribute('aria-pressed','false');b.append(node('span','',item.label),node('span','',`${item.documents} 条资料`));entities.append(b);}paging(entityPages,offset,24,data.total,loadEntities);if(data.items.length)choose(data.items[0]);}
    catch(error){if(turn===version&&ticket===listTicket)say(error.message,true);}
  }
  async function loadEvidence(offset){
    if(!selected)return;evidenceOffset=offset;const ticket=++evidenceTicket,turn=version,id=selected.id;detailTitle.textContent=selected.label+' · 原文提及';evidence.setAttribute('aria-busy','true');
    try{const params=new URLSearchParams({group:group.value,offset:String(offset),limit:'8'}),data=await api('/api/knowledge-graph/entities/'+id+'?'+params);if(turn!==version||ticket!==evidenceTicket||!visible())return;detailCount.textContent=number.format(data.total)+' 处';evidence.replaceChildren();for(const item of data.items){const article=node('article','kgraph-evidence-item');article.append(node('h4','',item.title));const meta=node('div','kgraph-meta');for(const text of [...item.groups,item.pages.length?`证据所在片段：第 ${item.pages.join('、')} 页`:'原始页码未记录',item.quality_status==='manual_review_required'?'解析标记：需复核':`解析状态：${item.quality_status}`])meta.append(node('span','',text));article.append(meta);const quote=node('blockquote'),chars=Array.from(item.text),left=item.mention_start-item.start_char,right=item.mention_end-item.start_char;quote.append(document.createTextNode(chars.slice(0,left).join('')),node('mark','',chars.slice(left,right).join('')),document.createTextNode(chars.slice(right).join('')));article.append(quote,button('打开原文并定位',()=>openEvidence(item),''));evidence.append(article);}if(!data.items.length)evidence.append(node('p','kgraph-empty','当前筛选下没有有效原文证据。'));paging(evidencePages,offset,8,data.total,loadEvidence);}
    catch(error){if(turn===version&&ticket===evidenceTicket)say(error.message,true);}finally{if(ticket===evidenceTicket)evidence.removeAttribute('aria-busy');}
  }
  async function loadDocuments(offset){documentOffset=offset;const turn=version;try{const data=await api('/api/knowledge-graph/documents?offset='+offset+'&limit=30');if(turn!==version||!visible()||offset!==documentOffset)return;documentRows.replaceChildren();for(const doc of data.items){const row=node('div','kgraph-document'),d=doc.diagnostics||{};let label=doc.current?(d.error?'来源校验未通过':doc.mentions?`${number.format(doc.mentions)} 处提及`:'已扫描 · 未识别到术语'):'待更新';if(d.invalid_chunks)label+=` · ${d.invalid_chunks} 个片段位置未通过`;if(d.chunks===0)label+=' · 没有可定位片段';row.append(button(doc.title,()=>document.dispatchEvent(new CustomEvent('geoagent:graph-source',{detail:{document_id:doc.id}})),''),node('span','',label));documentRows.append(row);}paging(documentPages,offset,30,metadata?.counts.documents||0,loadDocuments);}catch(error){if(turn===version)say(error.message,true);}}
  async function enter(){version++;await refresh();if(visible())loadEntities(0);}
  function clearPrivateView(){version++;clearTimeout(timer);pendingBuild=false;metadata=null;query.value='';options(kind,[],'全部类别');options(group,[],'全部分类');metrics.replaceChildren();entities.replaceChildren();canvas.replaceChildren();documentRows.replaceChildren();entityPages.replaceChildren();documentPages.replaceChildren();resetDetail();say('');}
  const observer=new MutationObserver(()=>{clearTimeout(timer);if($('app')?.hidden)clearPrivateView();else if(visible())enter();else{version++;listTicket++;evidenceTicket++;}});observer.observe(panel,{attributes:true,attributeFilter:['hidden']});observer.observe($('knowledge-view'),{attributes:true,attributeFilter:['hidden']});if($('app'))observer.observe($('app'),{attributes:true,attributeFilter:['hidden']});
  $('logout')?.addEventListener('click',clearPrivateView);
  if(visible())enter();
})();

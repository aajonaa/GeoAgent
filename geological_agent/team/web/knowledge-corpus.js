'use strict';
(() => {
  const panel=document.getElementById('knowledge-panel-corpus');
  if(!panel)return;
  const numbers=new Intl.NumberFormat('zh-CN');
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  let generation=0, sessionEpoch=0, history=[''], next=null, loaded=false;
  const workspace=document.getElementById('knowledge-view');
  let summaryGeneration=0, summaryPending=false, timer=null;
  const workspaceVisible=()=>workspace?!workspace.hidden:!panel.hidden;
  const headerIds=['knowledge-count','knowledge-indexed-count','knowledge-chunk-count'];
  const headerLabels=['资料总数','可检索资料','索引片段'];
  const summaryNote=el('p','统计正在读取…','kc-note');
  summaryNote.id='knowledge-summary-status';summaryNote.setAttribute('role','status');
  const header=document.getElementById('knowledge-count')?.closest('dl');
  if(header){header.setAttribute('aria-label','当前账号全部知识资料统计');header.parentElement.classList.add('has-corpus-summary');header.after(summaryNote);summaryNote.style.gridColumn='1 / -1';summaryNote.style.margin='0';headerState('…');
    headerIds.forEach((id,i)=>{const value=document.getElementById(id);value?.previousElementSibling&&(value.previousElementSibling.textContent=headerLabels[i]);});}
  function headerState(text){headerIds.forEach(id=>{const value=document.getElementById(id);if(value)value.textContent=text;});}
  function renderHeader(data){
    if(!header)return;
    const stats=data.statistics;
    if(!stats||!['total','legacy','corpus'].every(group=>stats[group]&&['documents','indexed_documents','chunks'].every(k=>Number.isSafeInteger(stats[group][k])&&stats[group][k]>=0)))throw new Error('知识统计接口未返回完整计数');
    ['documents','indexed_documents','chunks'].forEach((key,i)=>document.getElementById(headerIds[i]).textContent=numbers.format(stats.total[key]));
    summaryNote.textContent='原文献库 '+numbers.format(stats.legacy.documents)+' 条 + 文献总库 '+numbers.format(stats.corpus.documents)+' 篇 · 可检索数量按实际索引状态统计 · 每 15 秒自动更新 · '+new Date().toLocaleTimeString('zh-CN')+' 更新';
  }
  function scheduleSummary(){clearTimeout(timer);if(workspaceVisible())timer=setTimeout(async()=>{if(!workspaceVisible())return;if(!document.hidden){await summary();if(!panel.hidden&&detail.hidden&&list.getAttribute('aria-busy')!=='true')refresh();}scheduleSummary();},15000);}
  const labels={pending:'等待索引',running:'索引中',ready:'可检索',failed:'索引失败',blocked:'正文待复核'};
  const button=(text,fn)=>{const b=el('button',text,'k-button');b.type='button';b.onclick=fn;return b;};
  async function api(path){const r=await fetch(path,{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error(r.status===401?'请先登录':'读取失败（'+r.status+'）');return r.json();}
  const intro=el('div',undefined,'kc-intro');intro.append(el('p','EARTH LITERATURES','kc-eyebrow'),el('h2','地学文献总库'),el('p','保留原始学科分类、正文和来源记录。正文入库与检索索引分别统计。','kc-note'));
  const metrics=el('div',undefined,'kc-metrics');metrics.setAttribute('aria-live','polite');
  const controls=el('form',undefined,'kc-controls');
  const query=el('input');query.type='search';query.placeholder='搜索文献标题';query.setAttribute('aria-label','搜索文献标题');
  const category=el('select');category.setAttribute('aria-label','学科分类');category.append(new Option('全部学科',''));
  const state=el('select');state.setAttribute('aria-label','索引状态');state.append(new Option('全部状态',''));Object.entries(labels).forEach(([k,v])=>state.append(new Option(v,k)));
  const search=button('搜索',()=>refresh(true));const reset=button('清除筛选',()=>{query.value='';category.value='';state.value='';refresh(true);});
  controls.append(query,category,state,search,reset);controls.onsubmit=e=>{e.preventDefault();refresh(true);};category.onchange=state.onchange=()=>refresh(true);
  const status=el('p','', 'kc-note');status.setAttribute('role','status');
  const list=el('div',undefined,'kc-list');
  const pager=el('div',undefined,'kc-pager');
  const prev=button('上一页',()=>{if(history.length>1){history.pop();refresh();}});
  const page=el('span','第 1 页');const more=button('下一页',()=>{if(next){history.push(next);refresh();}});
  pager.append(prev,page,more,button('刷新统计',()=>{summary();refresh();}));
  const detail=el('section',undefined,'kc-detail');detail.hidden=true;
  const catalog=el('section');catalog.append(controls,status,list,pager);
  panel.append(intro,metrics,catalog,detail);
  async function summary(){if(summaryPending||!workspaceVisible())return;const ticket=sessionEpoch,request=++summaryGeneration;summaryPending=true;try{
    const data=await api('/api/knowledge-corpus');if(!workspaceVisible()||ticket!==sessionEpoch||request!==summaryGeneration)return;
    renderHeader(data);
    const total=data.collections.reduce((n,c)=>n+c.imported_documents,0), expected=data.collections.reduce((n,c)=>n+c.expected_documents,0);
    metrics.replaceChildren();[['文献总库',total],['已可检索',data.states.ready||0],['索引中／等待', (data.states.pending||0)+(data.states.running||0)],['待处理',(data.states.failed||0)+(data.states.blocked||0)],['账号容量',data.account_capacity]].forEach(([label,value])=>{const box=el('div');box.append(el('strong',numbers.format(value)),el('span',label));metrics.append(box);});
    intro.lastChild.textContent='正文入库 '+numbers.format(total)+' / '+numbers.format(expected)+' 篇；另保留原文献库 '+numbers.format(data.legacy_documents)+' 篇。原数据包不含 PDF 文件，来源 JSONL 可下载。';
    const selected=category.value;category.replaceChildren(new Option('全部学科',''));
    const categories=new Map();data.collections.forEach(c=>Object.entries(c.metadata.categories||{}).forEach(([id,value])=>categories.set(id,value)));
    [...categories].sort().forEach(([id,value])=>category.append(new Option((value.label||id)+' · '+numbers.format(value.deduplicated),id)));
    category.value=selected;
  }catch(e){if(ticket===sessionEpoch&&request===summaryGeneration&&workspaceVisible()){status.textContent=e.message;headerState('未读取');summaryNote.textContent='全知识库统计暂未读取，将自动重试；'+e.message;}}finally{if(request===summaryGeneration)summaryPending=false;}}
  async function refresh(resetPage=false){
    if(resetPage)history=[''];const ticket=++generation;status.textContent='正在读取文献…';list.setAttribute('aria-busy','true');prev.disabled=more.disabled=true;
    const params=new URLSearchParams({q:query.value.trim(),category:category.value,state:state.value,after:history[history.length-1],limit:'50'});
    try{const data=await api('/api/knowledge-corpus/papers?'+params);if(ticket!==generation||panel.hidden)return;
      list.replaceChildren();data.documents.forEach(doc=>{const card=el('article',undefined,'kc-paper');
        const title=button(doc.title||'未提供标题',()=>open(doc.id));title.classList.add('kc-title');
        const meta=el('p',[doc.year||'年份未记录',...doc.l1_labels,...doc.l2_labels].join(' · '),'kc-note');
        const stateTag=el('span',labels[doc.index_state]||doc.index_state,'kc-state '+(doc.index_state==='ready'?'is-ready':''));
        card.append(title,meta,stateTag);list.append(card);
      });next=data.next_cursor;page.textContent='第 '+history.length+' 页';prev.disabled=history.length===1;more.disabled=!next;
      status.textContent=data.documents.length?'本页 '+data.documents.length+' 篇 · 按稳定编号分页':'没有符合条件的文献';
    }catch(e){if(ticket===generation)status.textContent=e.message;}finally{if(ticket===generation)list.setAttribute('aria-busy','false');}
  }
  async function open(id){
    const ticket=++generation;catalog.hidden=true;detail.hidden=false;detail.replaceChildren(el('p','读取原文…'));
    try{const doc=await api('/api/knowledge-corpus/papers/'+id);if(ticket!==generation||panel.hidden)return;
      const back=button('← 返回文献列表',()=>{generation++;detail.hidden=true;catalog.hidden=false;});
      const title=el('h2',doc.title);const note=el('p','原始解析文本 · '+numbers.format(doc.total_characters)+' 字符 · '+(labels[doc.index_state]||doc.index_state),'kc-note');
      const provenance=el('p','分类来自原资料包；来源一致性检查不代表科学结论已审核。数据包没有原 PDF 或附图二进制文件。','kc-note');
      const download=el('a','下载原始 JSONL');download.href='/api/knowledge-corpus/papers/'+id+'/source';download.className='k-button';
      const text=el('pre',doc.body,'kc-body');const load=button('继续阅读',async()=>{load.disabled=true;try{const d=await api('/api/knowledge-corpus/papers/'+id+'?start='+load.dataset.start);if(ticket!==generation)return;text.append(document.createTextNode(d.body));load.dataset.start=d.next_start;load.hidden=d.next_start===null;}catch(e){note.textContent=e.message;}finally{load.disabled=false;}});
      load.dataset.start=doc.next_start;load.hidden=doc.next_start===null;
      detail.replaceChildren(back,title,note,provenance,download,text,load);
    }catch(e){detail.replaceChildren(button('返回列表',()=>{detail.hidden=true;catalog.hidden=false;}),el('p',e.message));}
  }
  new MutationObserver(()=>{if(panel.hidden){generation++;if(!workspace)clearTimeout(timer);return;}loaded=true;summary();refresh();scheduleSummary();}).observe(panel,{attributes:true,attributeFilter:['hidden']});
  if(workspace)new MutationObserver(()=>{if(workspace.hidden){clearTimeout(timer);summaryGeneration++;summaryPending=false;return;}summary();scheduleSummary();}).observe(workspace,{attributes:true,attributeFilter:['hidden']});
  document.addEventListener('geoagent:knowledge-catalog-updated',()=>summary());
  document.getElementById('knowledge-refresh')?.addEventListener('click',()=>{summary();if(!panel.hidden&&detail.hidden)refresh();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&workspaceVisible()){summary();scheduleSummary();}});
  function clearSession(){generation++;sessionEpoch++;summaryGeneration++;summaryPending=false;clearTimeout(timer);loaded=false;history=[''];next=null;list.replaceChildren();detail.replaceChildren();metrics.replaceChildren();query.value='';catalog.hidden=false;detail.hidden=true;headerState('—');summaryNote.textContent='';}
  document.addEventListener('geoagent:session-reset',clearSession);
  document.getElementById('logout')?.addEventListener('click',clearSession,{capture:true});
  if(workspaceVisible()){summary();scheduleSummary();}
})();

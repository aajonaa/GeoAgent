'use strict';
(() => {
  const $ = id => document.getElementById(id), dialog = () => $('admin-usage-dialog');
  let hooks, me, epoch = 0, uid = null, runPage = 1, logRun = null, logOffset = null, logSource = '';
  let logEpoch = 0, overview = null, detail = null, tab = 'runs', search = '', sort = 'tokens';
  const node = (tag, value, cls) => { const n = document.createElement(tag); if (value !== undefined) n.textContent = value; if (cls) n.className = cls; return n; };
  const fmt = n => n == null ? '未知' : Number(n).toLocaleString('zh-CN', {maximumFractionDigits: 2});
  const short = n => n == null ? '未知' : new Intl.NumberFormat('zh-CN', {notation: 'compact', maximumFractionDigits: 2}).format(n);
  const date = t => t ? new Date(t * 1000).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) : '未知';
  const sum = (items, key) => items.reduce((n, item) => n + (Number(item[key]) || 0), 0);
  const statuses = {completed:'已完成',failed:'失败',running:'进行中',stopping:'停止中',cancelled:'已取消',stopped:'已停止',budget_exhausted:'预算已用尽',needs_input:'等待补充信息',interrupted:'已中断',incomplete:'未完成',waiting:'等待中',matched:'已命中'};
  function action(label, fn, cls = 'usage-button') { const b = node('button', label, cls); b.type = 'button'; b.onclick = fn; return b; }
  const badge = (label, kind = '') => node('span', label, 'usage-badge ' + kind);
  function table(headers, rows, empty = '所选期间暂无记录') {
    const wrap = node('div', undefined, 'usage-table-wrap'), t = node('table'), head = node('tr');
    wrap.tabIndex = 0; wrap.setAttribute('aria-label', headers.join('、') + '，可横向滚动');
    for (const h of headers) { const th = node('th', h); th.scope = 'col'; head.append(th); }
    const thead = node('thead'); thead.append(head); t.append(thead); const body = node('tbody');
    for (const row of rows) { const tr = node('tr'); for (const value of row) { const td = node('td'); if (value instanceof Node) td.append(value); else td.textContent = value ?? '未知'; tr.append(td); } body.append(tr); }
    if (!rows.length) { const tr = node('tr'), td = node('td', empty, 'usage-empty'); td.colSpan = headers.length; tr.append(td); body.append(tr); }
    t.append(body); wrap.append(t); return wrap;
  }
  function heading(title, note, right) { const h = node('div', undefined, 'usage-section-heading'), left = node('div'); left.append(node('h3', title)); if (note) left.append(node('p', note)); h.append(left); if (right) h.append(right); return h; }
  function metric(label, value, note, accent = false) { const n = node('article', undefined, 'usage-metric' + (accent ? ' is-primary' : '')); n.append(node('span', label, 'usage-metric-label'), node('strong', short(value)), node('span', note, 'usage-metric-note')); n.title = label + '：' + fmt(value); return n; }
  function metrics(s, all = false) { const grid = node('div', undefined, 'usage-metrics'); grid.append(metric('期间已记录 Token', s.period_tokens, '全部历史 ' + short(s.total_tokens) + ' Token', true), metric('模型请求', s.model_calls, '期间用量缺失 ' + fmt(s.missing_usage_calls) + ' 次'), metric('工具调用', s.tool_calls, '按实际工具请求计数'), all ? metric('有模型请求的账号', s.active, '共 ' + fmt(s.accounts) + ' 个账号') : metric('日均已记录 Token', s.daily_average_tokens, '包含期间未使用的自然日')); return grid; }
  function dates() { return new URLSearchParams({start: $('usage-start').value, end: $('usage-end').value}); }
  function clearLogs() { logEpoch++; logRun = null; logOffset = null; logSource = ''; $('usage-logs').replaceChildren(); }
  function clear() { epoch++; me = null; uid = null; overview = detail = null; clearLogs(); dialog().close(); $('admin-usage-open').hidden = true; $('usage-content').replaceChildren(); $('usage-message').textContent = ''; }
  function resetView() { uid = null; runPage = 1; tab = 'runs'; clearLogs(); dialog().querySelector('.usage-workspace').scrollTop = 0; }
  async function refresh() {
    const ticket = ++epoch; clearLogs(); $('usage-refresh').disabled = true; $('usage-content').setAttribute('aria-busy', 'true');
    $('usage-message').className = 'usage-message'; $('usage-message').textContent = '正在汇总使用记录…';
    $('usage-content').replaceChildren(node('div', '正在读取统计数据…', 'usage-loading'));
    try {
      const current = await hooks.api('/api/me'); if (ticket !== epoch || !dialog().open) return;
      if (current.id !== me?.id || current.role !== 'admin') { clear(); return; }
      const params = dates(); if (uid) params.set('page', String(runPage));
      const data = await hooks.api(uid ? '/api/admin/usage/users/' + encodeURIComponent(uid) + '?' + params : '/api/admin/usage?' + params);
      if (ticket !== epoch || !dialog().open) return;
      $('usage-message').textContent = `${data.period.start} — ${data.period.end} · 上海时区 · ${data.period.days} 个自然日`;
      $('usage-period-note').textContent = `${data.period.days} 天统计窗口`;
      if (!uid) { overview = data; renderOverview(); } else { detail = data; renderDetail(); }
    } catch (e) { if (ticket !== epoch) return; $('usage-message').className = 'usage-message is-error'; $('usage-message').textContent = '读取失败：' + e.message; const empty = node('div', undefined, 'usage-empty'); empty.append(node('p', '暂时无法读取统计数据'), action('重新加载', refresh)); $('usage-content').replaceChildren(empty); }
    finally { if (ticket === epoch) { $('usage-refresh').disabled = false; $('usage-content').setAttribute('aria-busy', 'false'); } }
  }
  function openUser(id) { uid = id; runPage = 1; tab = 'runs'; dialog().querySelector('.usage-workspace').scrollTop = 0; refresh(); }
  function renderOverview() {
    const data = overview, items = data.items, content = $('usage-content'); content.replaceChildren();
    $('usage-view-label').textContent = '研究组概览'; $('usage-subtitle').textContent = '从模型用量到任务执行，查看真实记录的研究活动。';
    const total = Object.fromEntries(['total_tokens','period_tokens','model_calls','tool_calls','missing_usage_calls'].map(k => [k, sum(items, k)]));
    content.append(metrics({...total, active: items.filter(u => u.model_calls > 0).length, accounts: items.length}, true));
    const insights = node('div', undefined, 'usage-insights'), models = node('section', undefined, 'usage-panel'), activity = node('section', undefined, 'usage-panel');
    models.append(heading('模型请求分布', '按所选期间的请求次数统计', badge('请求次数')));
    const counts = {}; for (const u of items) for (const [name, count] of Object.entries(u.models || {})) counts[name] = (counts[name] || 0) + count;
    const rows = Object.entries(counts).sort((a,b) => b[1]-a[1]), max = Math.max(1, ...rows.map(r => r[1])), chart = node('div', undefined, 'usage-model-chart');
    for (const [name,count] of rows.slice(0,4)) { const row = node('div', undefined, 'usage-model-row'), label = node('div', undefined, 'usage-model-label'), track = node('meter'); label.append(node('span',name),node('strong',fmt(count)+' 次')); track.min=0; track.max=max; track.value=count; track.setAttribute('aria-label', `${name}，${fmt(count)} 次请求`); row.append(label,track); chart.append(row); }
    if (!rows.length) chart.append(node('p','所选期间暂无模型请求','usage-empty'));
    if (rows.length>4) chart.append(node('p',`另有 ${rows.length-4} 种模型，可在用户详情中查看。`,'usage-caption'));
    models.append(chart); activity.append(heading('研究活动','实际执行记录'));
    for (const [label,key] of [['工具调用','tool_calls'],['Skill 实际加载','skill_loads'],['知识检索','retrieval_calls']]) { const line=node('div',undefined,'usage-activity-row'); line.append(node('span',label),node('strong',fmt(sum(items,key))+' 次')); activity.append(line); }
    insights.append(models,activity); content.append(insights);
    const members=node('section',undefined,'usage-panel'); members.append(heading('用户使用明细','选择用户，查看模型、工具与脱敏任务日志。',badge(items.length+' 个账号')));
    const tools=node('div',undefined,'usage-user-tools'), input=node('input'), select=node('select'), target=node('div'); input.type='search'; input.placeholder='搜索用户名'; input.value=search; input.setAttribute('aria-label','搜索使用统计用户');
    for (const [value,label] of [['tokens','按期间 Token 排序'],['calls','按模型请求排序'],['name','按用户名排序']]) { const o=node('option',label); o.value=value; select.append(o); } select.value=sort; select.setAttribute('aria-label','用户排序方式');
    input.oninput=()=>{search=input.value;renderUsers(target);}; select.onchange=()=>{sort=select.value;renderUsers(target);}; tools.append(input,select); members.append(tools,target); content.append(members); renderUsers(target);
    if (data.accounting_errors) content.append(node('p',`统计写入失败 ${fmt(data.accounting_errors)} 次，当前记录可能不完整。`,'usage-alert'));
    content.append(coverage());
  }
  function renderUsers(target) {
    const items=overview.items.filter(u=>u.username.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
    items.sort((a,b)=>sort==='name'?a.username.localeCompare(b.username,'zh-CN'):(sort==='calls'?b.model_calls-a.model_calls:b.period_tokens-a.period_tokens)||a.username.localeCompare(b.username));
    const rows=items.map(u=>{
      const identity=node('div',undefined,'usage-identity'), name=node('div'); name.append(node('strong',u.username),node('small',(u.role==='admin'?'管理员':'成员')+(u.disabled?' · 已停用':''))); identity.append(node('span',u.username.slice(0,1).toUpperCase(),'usage-avatar'),name);
      const tokens=node('div',undefined,'usage-token-cell'); tokens.append(node('strong',fmt(u.period_tokens)),node('small','历史 '+fmt(u.total_tokens)));
      const coverageCell=node('div',undefined,'usage-coverage-cell'); coverageCell.append(badge(!u.model_calls?'暂无模型请求':u.missing_usage_calls?`${fmt(u.missing_usage_calls)} 次用量缺失`:'期间用量无缺失',!u.model_calls?'':u.missing_usage_calls?'is-warning':'is-good')); if(u.missing_traces)coverageCell.append(node('small',`历史 ${fmt(u.missing_traces)} 份任务日志缺失`));
      return [identity,tokens,fmt(u.daily_average_tokens),fmt(u.model_calls),fmt(u.tool_calls),coverageCell,action('查看详情 ↗',()=>openUser(u.id),'usage-link')];
    }); target.replaceChildren(table(['用户','期间 Token / 历史','日均 Token','模型请求','工具调用','记录覆盖','操作'],rows,search?'没有匹配的用户，请尝试其他用户名':'暂无用户记录'));
  }
  function coverage() { const box=node('details',undefined,'usage-coverage'); box.id='usage-coverage'; box.append(node('summary','关于统计口径与记录覆盖'),node('p','总 Token 为全部历史已记录值，其余指标按所选期间统计；日均 = 期间已记录 Token ÷ 自然日天数，包含未使用日。供应商未返回用量时标为未知，不按零消耗处理。'),node('p','工具、Skill、检索只统计已记录事件。历史未记录的辅助请求无法补回；任务日志缺失不代表任务没有执行。这里展示应用调用与任务记录，页面点击、停留时长等行为不在本统计范围内。')); return box; }
  function renderDetail() {
    const data=detail,s=data.summary,content=$('usage-content'); content.replaceChildren();clearLogs();
    $('usage-view-label').textContent='用户详情'; $('usage-subtitle').textContent=s.username+' · '+(s.role==='admin'?'管理员':'成员')+(s.disabled?' · 账号已停用':'');
    const nav=node('div',undefined,'usage-detail-heading'); nav.append(action('← 所有用户',()=>{resetView();refresh();},'usage-link'),node('span',s.username,'usage-detail-name'),badge(s.role==='admin'?'管理员':'成员'));content.append(nav,metrics(s));
    const alerts=[];if(s.missing_usage_calls)alerts.push(`期间 ${fmt(s.missing_usage_calls)} 次用量未知`);if(s.all_time_missing_usage_calls)alerts.push(`历史 ${fmt(s.all_time_missing_usage_calls)} 次用量未知`);if(s.missing_traces)alerts.push(`历史 ${fmt(s.missing_traces)} 份任务日志缺失`);if(alerts.length)content.append(node('p',alerts.join(' · '),'usage-alert'));
    const tabs=node('div',undefined,'usage-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','用户使用详情分类');
    const panels=[['runs','任务与日志',data.total_runs],['conversations','对话轨迹',null],['models','模型调用',s.model_calls],['tools','工具',s.tool_calls],['skills','Skill',s.skill_loads],['retrievals','知识检索',s.retrieval_calls]],body=node('section',undefined,'usage-panel usage-tab-panel');body.id='usage-tab-panel';body.setAttribute('role','tabpanel');
    for(const [key,label,count]of panels){const b=action(count == null ? label : label+' '+fmt(count),()=>{tab=key;renderDetail();$('usage-tab-'+key).focus();});b.id='usage-tab-'+key;b.setAttribute('role','tab');b.setAttribute('aria-selected',String(tab===key));b.setAttribute('aria-controls',body.id);b.tabIndex=tab===key?0:-1;b.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const at=panels.findIndex(p=>p[0]===tab),next=e.key==='Home'?0:e.key==='End'?panels.length-1:(at+(e.key==='ArrowRight'?1:-1)+panels.length)%panels.length;tab=panels[next][0];renderDetail();$('usage-tab-'+tab).focus();};tabs.append(b);}
    body.setAttribute('aria-labelledby','usage-tab-'+tab);content.append(tabs,body);
    if(tab==='runs'){
      body.append(heading('任务与日志','任务时间按上海时区展示；日志由服务端脱敏。',badge(fmt(data.total_runs)+' 个任务')),table(['开始时间','任务状态','请求模型','任务 ID','日志'],data.runs.map(r=>{const id=node('code',r.id.slice(0,12)+'…','usage-run-id');id.title=r.id;return[date(r.created),badge(statuses[r.status]||r.status,r.status==='completed'?'is-good':['failed','budget_exhausted'].includes(r.status)?'is-warning':''),r.model,id,action('打开日志 →',()=>{logRun=r.id;logOffset=0;loadLogs(false);},'usage-link')];})));
      const pager=node('div',undefined,'usage-pager'),pages=Math.max(1,Math.ceil(data.total_runs/50)),prev=action('← 上一页',()=>{runPage--;refresh();}),next=action('下一页 →',()=>{runPage++;refresh();});prev.disabled=runPage<=1;next.disabled=runPage>=pages;pager.append(node('span',`第 ${runPage} / ${pages} 页 · 每页最多 50 条`),prev,next);body.append(pager);
    }else if(tab==='conversations'){
      showConversationIndex(body, uid);
    }else if(tab==='models'){
      body.append(heading('基座模型','请求模型与供应商报告模型分别展示。'),table(['请求模型','请求次数','已记录 Token','用量缺失','供应商报告模型'],data.models.map(m=>[m.model,fmt(m.calls),fmt(m.tokens),fmt(m.missing_usage),m.reported_models.join('\n')||'未报告'])),heading('模型调用明细','最近 50 条记录'),table(['时间','用途','模型','输入 Token','输出 Token','总 Token','错误'],data.model_details.map(c=>[date(c.time),c.category||'task',c.model,fmt(c.usage?.input_tokens),fmt(c.usage?.output_tokens),fmt(c.usage?.total_tokens),c.error_type||'—'])));
    }else if(tab==='tools'){
      body.append(heading('工具调用','失败、缓存命中与结果未知分别计数。'),table(['工具','调用次数','失败','缓存命中','结果未知'],data.tools.map(t=>[t.name,fmt(t.calls),fmt(t.failed),fmt(t.cached),fmt(t.unknown)])));
    }else if(tab==='skills'){
      body.append(heading('Skill 实际加载','实际加载与任务最初选择的 Skill 分别记录。'),table(['Skill','加载次数'],Object.entries(data.skills).map(([name,n])=>[name,fmt(n)])),heading('加载明细','最近 50 条记录'),table(['时间','Skill','来源','开放的工具','任务'],data.skill_details.map(s=>[date(s.time),s.skill,s.source,(s.exposed_tools||[]).join(', '),s.rid])));
    }else{
      body.append(heading('知识检索','最近 50 条记录；展开来源可查看引用片段。'),table(['时间','查询','来源 / 状态','耗时 ms','候选数','返回来源与片段'],data.retrievals.map(r=>{const refs=node('details',undefined,'usage-references');refs.append(node('summary',(r.references||[]).length+' 个引用片段'));for(const x of r.references||[]){const item=node('article');item.append(node('strong',x.title||x.document_id),node('small',`${x.citation_id||''} · score=${x.rerank_score??'未知'}`),node('p',x.text||'未记录片段正文'));refs.append(item);}return[date(r.time),r.query,r.source+' / '+(statuses[r.status]||r.status||'未知'),fmt(r.duration_ms),fmt(r.candidates),refs];})));
    }content.append(coverage());
  }
  function auditListing(body, {title, note, back, endpoint, cursor, next, headers, row, empty}) {
    body.replaceChildren(heading(title, note, back));
    const results = node('div'), message = node('p', undefined, 'usage-caption');
    message.setAttribute('role', 'status');
    const more = action('继续读取', load);
    let position = 0;
    const rows = [], ticket = epoch;
    const current = () => ticket === epoch && dialog().open && body.isConnected && body.contains(results);
    body.append(results, message, more);

    async function load() {
      more.disabled = true;
      message.textContent = '正在读取…';
      try {
        const data = await hooks.api(endpoint + '?' + new URLSearchParams({[cursor]: String(position)}));
        if (!current()) return;
        rows.push(...data.items);
        results.replaceChildren(table(headers, rows.map(row), empty));
        position = data[next];
        more.hidden = position == null;
        message.textContent = '';
      } catch (error) {
        if (current()) {
          message.textContent = '读取失败：' + error.message;
          more.textContent = '重试';
        }
      } finally { if (current()) more.disabled = false; }
    }

    load();
  }

  function showConversationIndex(body, ownerId) {
    clearLogs();
    auditListing(body, {
      title:'对话轨迹',
      note:'按对话查看已留存的提问、运行事件和答复。此处包含该账号的全部历史。',
      endpoint:'/api/admin/usage/users/' + encodeURIComponent(ownerId) + '/conversations',
      cursor:'offset', next:'next_offset', headers:['对话','任务数','最近更新','操作'],
      row: item => [item.title, fmt(item.run_count), date(item.updated),
        action('查看对话 →', () => showConversationRuns(body, ownerId, item), 'usage-link')],
      empty:'该账号暂无对话',
    });
  }

  function showConversationRuns(body, ownerId, conversation) {
    clearLogs();
    auditListing(body, {
      title:conversation.title,
      note:'按提交顺序显示这段对话中的任务。',
      back:action('← 所有对话', () => showConversationIndex(body, ownerId)),
      endpoint:'/api/admin/usage/conversations/' + encodeURIComponent(conversation.id),
      cursor:'after', next:'next_after', headers:['提交时间','状态','模式','模型','模型轮次','操作'],
      row: run => [date(run.created), badge(statuses[run.status] || run.status),
        run.mode === 'ask' ? '询问' : run.mode === 'agent' ? '执行' : '未记录',
        run.model || '未记录', fmt(run.turns), action('打开轨迹 →', () => {
          logRun = run.id;
          logOffset = 0;
          loadLogs(false);
        }, 'usage-link')],
      empty:'这段对话暂无任务',
    });
  }

  function renderRunTranscript(target, run, source) {
    const section = node('section', undefined, 'usage-run-transcript');
    const status = statuses[run.status] || run.status;
    section.append(heading('任务摘要', '提交于 ' + date(run.created), badge(status)));
    for (const [key, label, empty] of [
      ['prompt_text','用户提问','未记录提问'],
      ['reply_text','最终答复','未保存最终答复'],
      ['reason','结束原因',''],
    ]) {
      if (!run[key] && !empty) continue;
      const block = node('details', undefined, 'usage-event');
      block.append(node('summary', label + (run.truncated?.includes(key) ? '（预览已截断）' : '')),
                   node('pre', run[key] || empty));
      section.append(block);
    }
    if (source === 'task_events')
      section.append(node('p', '这次任务没有独立轨迹文件，以下显示已保存的应用事件。', 'usage-caption'));
    target.append(section);
  }

  async function loadLogs(append){
    const ticket=++logEpoch,view=epoch,rid=logRun,target=$('usage-logs');
    if(!append){logSource = ''; target.replaceChildren(heading('任务轨迹','显示已保存的脱敏记录，时间为上海时区。',action('收起日志',clearLogs)),node('code',rid,'usage-log-run'));}
    const loading=node('p','正在读取日志…','usage-caption');target.append(loading);const more=target.querySelector('.usage-load-more');if(more)more.disabled=true;
    try{const data=await hooks.api(`/api/admin/usage/runs/${encodeURIComponent(rid)}/logs?offset=${logOffset}&limit=50&source=${encodeURIComponent(logSource)}`);if(ticket!==logEpoch||view!==epoch||rid!==logRun||!dialog().open)return;more?.remove();target.querySelector('.usage-log-error')?.remove();
      if (data.run) renderRunTranscript(target, data.run, data.source);
      for(const row of data.items){const event=node('details',undefined,'usage-event'),title=node('summary');title.append(node('span',undefined,'usage-event-dot'),node('strong',row.event||row.kind||'任务事件'),node('time',typeof row.time==='number'?date(row.time):row.time?new Date(row.time).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'时间未记录'));event.append(title,node('pre',JSON.stringify(row,null,2)));target.append(event);}
      logSource = data.source;
      logOffset=data.next_offset;if(logOffset!=null)target.append(action('继续读取 50 条',()=>loadLogs(true),'usage-button usage-load-more'));else target.append(node('p',data.items.length||append?'已读取到日志末尾':'该任务暂无可显示的日志','usage-log-end'));if(!append)target.scrollIntoView({block:'start',behavior:'smooth'});
    }catch(e){if(ticket===logEpoch&&view===epoch){target.append(node('p','日志读取失败：'+e.message,'usage-log-error'));if(more)more.disabled=false;else target.append(action('重新读取日志',()=>loadLogs(append),'usage-button usage-load-more'));}}finally{loading.remove();}
  }
  function open(){if(me?.role!=='admin')return;resetView();if(!dialog().open)dialog().showModal();refresh();}
  function session(user){clear();me=user;$('admin-usage-open').hidden=user.role!=='admin';if(location.pathname==='/admin/usage'&&user.role==='admin')open();}
  function day(t){const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(t).map(p=>[p.type,p.value]));return `${p.year}-${p.month}-${p.day}`;}
  function setDays(days){const end=new Date();$('usage-start').value=day(new Date(end.getTime()-(days-1)*86400000));$('usage-end').value=day(end);runPage=1;refresh();}
  function mount(h){hooks=h;const today=day(new Date());$('usage-start').max=$('usage-end').max=today;$('usage-start').value=day(new Date(Date.now()-29*86400000));$('usage-end').value=today;$('admin-usage-open').onclick=open;$('usage-close').onclick=()=>dialog().close();$('usage-overview').onclick=()=>{resetView();refresh();};$('usage-range-7').onclick=()=>setDays(7);$('usage-range-30').onclick=()=>setDays(30);$('usage-definition').onclick=()=>{const box=$('usage-coverage');if(box){box.open=true;box.scrollIntoView({block:'start',behavior:'smooth'});}};$('usage-filter').onsubmit=e=>{e.preventDefault();if($('usage-start').value>$('usage-end').value){$('usage-message').textContent='开始日期不能晚于结束日期。';$('usage-message').className='usage-message is-error';return;}runPage=1;refresh();};dialog().addEventListener('close',()=>{epoch++;clearLogs();overview=detail=null;$('usage-content').replaceChildren();$('usage-refresh').disabled=false;});document.addEventListener('visibilitychange',()=>{if(dialog().open){epoch++;clearLogs();overview=detail=null;$('usage-content').replaceChildren();if(!document.hidden)refresh();}});}
  window.OreSageAdminUsage={mount,session,clear};
})();

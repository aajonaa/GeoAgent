'use strict';
// Native event presentation only. This module never invokes models or tools.
(() => {
  const el = (tag, text, cls) => element(tag, text, cls);
  const str = value => typeof value === 'string' ? value : '';
  const secret = /^(?:api[_-]?key|api[_-]?token|access[_-]?token|authorization|password|secret|credential|signature)$/i;
  const clean = value => JSON.parse(JSON.stringify(value ?? null, (key, item) => secret.test(key) ? '[凭证已遮蔽]' : item));
  function safeURL(value) {
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password
          || [...url.searchParams.keys()].some(key => /token|key|secret|password|signature|authorization/i.test(key))) return null;
      return url;
    } catch { return null; }
  }
  const paths = {
    search:'M21 21l-5-5 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
    process:'M8 3h8l4 5v12H4V3h4 M8 12h8 M8 16h5 M15 3v5h5',
    tool:'M4 5h16v14H4z M4 10h16 M9 10v9',
    check:'M5 12l4 4L19 6',
    source:'M3 5c4-1 7 0 9 2 2-2 5-3 9-2v14c-4-1-7 0-9 2-2-2-5-3-9-2V5z M12 7v14'
  };
  function icon(kind) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [key,value] of Object.entries({viewBox:'0 0 24 24',width:'17',height:'17',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'})) svg.setAttribute(key,value);
    const path = document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d', paths[kind] || paths.tool); svg.append(path); return svg;
  }
  function entry(title, kind, status) {
    const details = el('details', undefined, 'timeline-entry timeline-' + kind);
    const summary = el('summary'), label = el('span',title,'timeline-label');
    const badge = el('span',status,'timeline-state'), arrow = el('span','','timeline-chevron'); arrow.setAttribute('aria-hidden','true');
    summary.append(icon(kind), label, badge, arrow);
    const body = el('div',undefined,'timeline-body'); details.append(summary,body);
    return {details,summary,label,status:badge,body};
  }
  function disclosure(label, text) {
    const details=el('details',undefined,'timeline-raw'); details.append(el('summary',label),el('pre',text)); return details;
  }
  function attach(rid,ui) {
    if (ui.timeline) return ui.timeline;
    ui.activity.classList.add('activity-timeline'); ui.list.classList.add('timeline-list');
    ui.summary.textContent='执行过程'; ui.activity.open=!ui.finished;
    const view={rid,rows:new Map(),stages:new Map(),streams:new Map(),lastStage:null,sequence:-1,userToggled:false}; ui.timeline=view;
    // Programmatic open/close must not be mistaken for a user's preference.
    ui.summary.addEventListener('click',()=>{view.userToggled=true;});
    ui.summary.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key))view.userToggled=true;});
    return view;
  }
  function closeStage(view, failed=false) {
    if (view.lastStage && view.lastStage.status.textContent==='进行中') {
      view.lastStage.status.textContent=failed?'需重新检查':'已结束';
      view.lastStage.details.dataset.state=failed?'attention':'done';
    }
  }
  function issueSpec(category) {
    return ({review_evidence:['补齐审核证据','缺少对应原文引用；只修正审核记录，不重跑成功工具。'],
      review_format:['修正审核记录格式','审核结构未通过校验，不等同于服务连接故障。'],
      model_service:['处理模型服务故障','服务连接或供应商响应异常；原始记录保留。'],
      model_protocol:['修正原生调用格式','无效响应不会作为工具调用执行。'],
      answer_validation:['修正答复内容','答复尚未满足需求或来源支持要求。'],
      verification_error:['处理验证异常','验证过程异常，未据此放行答复。']})[category] || ['处理运行问题','完整原始记录保留。'];
  }
  function phase(data,view) {
    if(data.message==='Checking the result')return ['核对结果','核对需求、已有工具记录与答复；此阶段开始不代表检查已通过。','check'];
    if(data.message==='Preparing answer')return ['整理答复','根据已有执行结果组织说明与成果链接。','process'];
    if(data.message==='Compacting context')return ['整理上下文','压缩工作上下文，原始执行记录与工具证据仍保留。','process'];
    if(data.message==='Correcting the result')return ['处理检查问题','上一轮答复未通过检查，进入纠正流程。','check'];
    if(data.message==='Correcting a model response'||data.message==='Retrying the completion check')return view.issue ? [...issueSpec(view.issue.category),'check'] : ['重新检查审核','正在恢复检查；历史记录未提供更细的故障类别。','check'];
    if(data.message==='Model is working'||data.message==='GeoGPT is working')return [data.phase==='intent'?'理解任务':'分析下一步','这是运行时记录的模型阶段。若接口返回可展示的过程文本，将在这里显示；不推测隐藏思考。','process'];
    return null;
  }
  function stage(ui,data,view) {
    const spec=phase(data,view); if(!spec)return;
    closeStage(view,/Correcting|Retrying/.test(data.message));
    const row=entry(spec[0],spec[2],ui.finished?'已结束':'进行中');
    row.details.dataset.state=ui.finished?'done':'running';
    row.body.append(el('p',spec[1],'timeline-note'));
    if(Number.isSafeInteger(data.turn))row.body.append(el('small','执行轮次 '+data.turn,'timeline-provenance'));
    ui.list.append(row.details); view.lastStage=row;
    const phaseName=data.phase || 'execution';
    if(spec[2]==='process')view.stages.set(phaseName+':'+data.turn,row);
  }
  function processText(ui,data,view) {
    if(data.source!=='provider_reasoning_content'||data.verified!==false||!str(data.text).trim())return;
    const key=(data.phase||'execution')+':'+data.turn;
    let row=view.stages.get(key);
    if(!row){row=entry('模型过程','process','未核验');ui.list.append(row.details);view.stages.set(key,row);}
    row.label.textContent='模型过程'; row.status.textContent='未核验';
    if(!row.process){
      row.body.replaceChildren(el('p','由所选模型接口返回，未经结果审核，不代表工具已经执行，也不作为科学结论。','timeline-note'));
      row.process=el('div',undefined,'timeline-process-text'); row.process.tabIndex=0;
      row.process.setAttribute('aria-label','模型返回的过程文本'); row.body.append(row.process);
    }
    row.process.textContent=data.text;
  }
  function sourceCard(row) {
    const item=el('div',undefined,'timeline-source'); const url=safeURL(row.url);
    const title=str(row.title)||url?.hostname||'来源记录';
    const name=el(url?'a':'strong',title,'timeline-source-title');
    if(url){name.href=url.href;name.target='_blank';name.rel='noopener noreferrer';}
    const copy=el('div'); copy.append(name);
    const meta=[url?.hostname,str(row.published_date),str(row.citation_id)].filter(Boolean).join(' · ');
    if(meta)copy.append(el('small',meta,'timeline-source-meta'));
    const snippet=str(row.snippet)||str(row.text);
    if(snippet)copy.append(disclosure('查看摘录',snippet));
    if(!url && row.url)copy.append(el('small','该链接不能安全打开；完整返回值保留。','timeline-source-meta'));
    item.append(icon('source'),copy); return item;
  }
  function displayArguments(value) {
    // Decode only for presentation. The event and stored execution evidence stay untouched.
    try {
      const parsed = typeof value === 'string' ? JSON.parse(value) : value;
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? clean(parsed) : null;
    } catch { return null; }
  }
  function params(args) {
    if (!args || typeof args !== 'object' || Array.isArray(args)) {
      return el('p', '参数无法结构化显示；请查看保存的执行记录。未据此执行或推断工具调用。', 'timeline-note');
    }
    const box=el('dl',undefined,'timeline-parameters');
    for(const [key,value] of Object.entries(args||{})) {
      if(secret.test(key)||value===null||typeof value==='object'||key==='code')continue;
      const cell=el('div'); cell.append(el('dt',key),el('dd',String(value))); box.append(cell);
    }
    return box;
  }
  function tool(ui,data,view) {
    closeStage(view);
    const id=data.id || data.result?.call_id; if(typeof id!=='string')return;
    let row=view.rows.get(id); const name=data.name || data.result?.name || row?.name || '工具';
    if(!row) {
      row=entry(name,name==='web_search'||name==='web_fetch'?'search':'tool','执行中');
      row.details.classList.add('tool-card'); row.name=name; row.id=id;
      row.input=el('pre'); row.output=el('pre'); row.arguments={};
      row.description=el('p','','timeline-object'); row.content=el('div',undefined,'timeline-tool-content');
      row.raw=el('details',undefined,'timeline-raw'); row.raw.addEventListener('toggle',()=>{if(row.raw.open&&row.result)row.output.textContent=JSON.stringify(row.result,null,2);}); row.raw.append(el('summary','调用参数与完整返回值（凭证已遮蔽）'),row.input,row.output);
      row.body.append(row.description,row.content,row.raw);
      view.rows.set(id,row);ui.tools.set(id,row);ui.list.append(row.details);
    }
    if(data.kind==='tool_start') {
      row.arguments=displayArguments(data.arguments);
      const args=row.arguments||{}, description=window.GeoAgentExperience?.describeTool(name,args);
      row.label.textContent=name==='web_search'?'搜索资料'+(str(args.query)?' · '+str(args.query):''):name==='web_fetch'?'读取网页 · '+(safeURL(args.url)?.hostname||'来源网页'):(description?.title||name).replace(/^正在/,'');
      row.description.textContent=name==='web_search'?str(args.query):description?.detail||name;
      row.input.textContent=JSON.stringify({tool:name,arguments:row.arguments??'[参数无法安全结构化显示；原始记录已保留]',...(typeof data.arguments==='string'&&row.arguments?{display_note:'JSON 字符串参数已展开显示，原始执行记录未修改。'}:{})},null,2);
      if(!row.result)row.content.replaceChildren(params(row.arguments),el('p','等待工具返回。','timeline-note'));
      return;
    }
    const receipt=clean(data.result||{}); row.result=receipt;
    const success=receipt.status==='ok', output=receipt.data && typeof receipt.data==='object'?receipt.data:{};
    row.status.textContent=success?(receipt.cached||output.cache_hit?'已复用':'已完成'):'未完成';
    row.details.dataset.state=success?'done':'error'; if(row.raw.open)row.output.textContent=JSON.stringify(receipt,null,2);
    if(typeof data.duration_seconds==='number')row.status.textContent+=' · '+duration(data.duration_seconds);
    row.content.replaceChildren();
    if(!success)row.content.append(el('p',str(receipt.error?.message)||'工具没有返回成功结果。','timeline-error'));
    else if(name==='web_search'&&Array.isArray(output.results)) {
      row.status.textContent=output.results.length+' 条来源'+(output.cache_hit?' · 已复用':'');
      const sources=el('div',undefined,'timeline-sources');
      for(const source of output.results)if(source&&typeof source==='object')sources.append(sourceCard(source));
      row.content.append(sources,el('p',output.results.length?'以下是工具实际返回的来源，不代表内容已经核实。':'本次没有检索到来源。','timeline-note'));
    } else if(name==='web_fetch') {
      row.content.append(sourceCard({url:output.url,title:safeURL(output.url)?.hostname||'网页摘录',snippet:output.content}));
      if(output.truncated)row.content.append(el('p','本次返回的是分页摘录；全文未在此响应中返回。','timeline-note'));
    } else {
      row.content.append(params(row.arguments));
      const metrics=el('dl',undefined,'timeline-metrics');
      const values=Object.entries(output).filter(([key,value])=>!secret.test(key)&&value!==null&&['number','boolean','string'].includes(typeof value)&&String(value).length<180);
      for(const [key,value] of values.slice(0,8)){const cell=el('div');cell.append(el('dt',key),el('dd',String(value)));metrics.append(cell);}
      if(values.length)row.content.append(metrics);
      if(values.length>8)row.content.append(el('p','其余字段见完整返回值。','timeline-note'));
      const artifacts=Array.isArray(receipt.artifacts)?receipt.artifacts:[];
      for(const file of artifacts)if(str(file?.path))row.content.append(el('p',file.path,'timeline-file'));
      row.content.append(el('p','以上来自工具返回；单位沿用字段，不由界面推断。图像与文件可在本轮成果中查看。','timeline-note'));
    }
    const download=el('a','下载执行记录','timeline-receipt');
    download.href='/api/runs/'+encodeURIComponent(view.rid)+'/receipts/'+encodeURIComponent(id);download.download='tool-result.json';row.content.append(download);
  }
  function duration(seconds) {
    seconds=Math.max(0,Number(seconds)||0);
    return seconds<60?seconds.toFixed(1)+'s':Math.floor(seconds/60)+'m '+Math.floor(seconds%60)+'s';
  }
  const timingGroups=[
    ['排队',['queue']],['模型等待',['model_wait']],['接收输出',['model_stream']],
    ['专业与通用工具',['tools']],['审核',['review_wait','review_stream']],
    ['知识检索',['retrieval']],['准备与调度',['runtime']],['保存成果',['publishing']]
  ];
  function timing(ui,data) {
    if(!ui.timing) {
      const root=el('details',undefined,'timeline-timing'), summary=el('summary','阶段耗时');
      const grid=el('dl',undefined,'timeline-timing-grid');
      root.append(summary,grid,el('p','各阶段按实际运行计时，互不重叠；工具内的模型调用计入模型耗时。历史未记录的时间不补造。','timeline-note'));
      ui.overview?.box?.append(root);
      ui.timing={root,summary,grid};
    }
    ui.timing.snapshot=data;ui.timing.anchor=performance.now();tick(ui);
  }
  function tick(ui) {
    if(!ui.timing?.snapshot)return;
    const view=ui.timing, data=view.snapshot, totals={...data.totals_seconds};
    if(data.active&&!ui.finished)totals[data.active]=(totals[data.active]||0)+(data.active_seconds||0)+Math.max(0,performance.now()-view.anchor)/1000;
    const entries=timingGroups.map(([label,keys])=>[label,keys.reduce((sum,key)=>sum+(totals[key]||0),0)]);
    view.summary.textContent='阶段耗时 · '+entries.filter(([,value])=>value>=.1).map(([label,value])=>label+' '+duration(value)).join(' · ');
    view.grid.replaceChildren();
    for(const [label,value] of entries){const cell=el('div');cell.append(el('dt',label),el('dd',duration(value)));view.grid.append(cell);}
  }
  function streamEvent(ui,data,view) {
    if(!str(data.request_id))return;
    let row=view.streams.get(data.request_id);
    if(!row) {
      row=view.stages.get((data.phase||'execution')+':'+data.turn);
      if(!row||row.requestId) {
        const label=data.phase==='review'?'审核结果':data.phase==='final_answer'?'整理答复':data.phase==='context_compaction'?'整理上下文':'模型响应';
        row=entry(label,data.phase==='review'?'check':'process','等待模型');
        row.body.append(el('p','来自真实模型请求；片段不作为工具执行或最终答复证据。','timeline-note'));ui.list.append(row.details);
      }
      row.requestId=data.request_id;row.channels={};view.streams.set(data.request_id,row);
      row.transport=el('p','','timeline-provenance');row.body.append(row.transport);
      row.details.open=!ui.finished&&['execution','intent','final_answer'].includes(data.phase);
    }
    if(data.kind==='stream_open'){
      row.status.textContent=ui.finished?'已结束':'等待模型';
      row.transport.textContent=(data.transport==='native_stream'?'原生流式接收':'完整响应模式（不模拟逐字输出）')+' · 排队 '+duration(data.queue_seconds);
    }
    if(data.kind==='stream_delta'&&data.verified===false&&['text','reasoning'].includes(data.channel)&&typeof data.text==='string'){
      let channel=row.channels[data.channel];
      if(!channel){
        const box=el('details',undefined,'timeline-stream-content');
        const title=data.channel==='reasoning'?'模型返回的过程文本（未核实）':'生成中的草稿（未审核，不是最终答复）';
        const content=el('div','','timeline-process-text'); content.setAttribute('aria-live','off');
        box.append(el('summary',title),content);box.open=data.channel==='text'&&!ui.finished;row.body.append(box);
        channel=row.channels[data.channel]={content,length:0};
      }
      if(data.offset!==channel.length)return;
      // Offsets are Unicode code points (Python len), not UTF-16 code units.
      channel.content.textContent+=data.text;channel.length+=Array.from(data.text).length;
      row.status.textContent=ui.finished?'已结束':'正在接收';
    }
    if(data.kind==='stream_end'){
      row.status.textContent=(data.complete?'响应已接收':'响应中断')+' · '+duration(data.duration_seconds);
      row.details.dataset.state=data.complete?'done':'error';
      row.transport.textContent+=(data.first_text_seconds===null||data.first_text_seconds===undefined?' · 无文本片段':' · 首段文本 '+duration(data.first_text_seconds));
      if(!data.complete)row.body.append(el('p','响应不完整；没有因此执行部分工具调用。','timeline-error'));
    }
  }
  function event(rid,data,eventId) {
    const ui=state.runs.get(rid); if(!ui)return; const view=attach(rid,ui);
    const sequence=typeof eventId==='string'&&/^\d+$/.test(eventId)?Number(eventId):null;
    if(Number.isSafeInteger(sequence)){if(sequence<=view.sequence)return;view.sequence=sequence;}
    if(data.kind==='stage_timing')timing(ui,data);
    if(data.kind==='diagnostic') {
      closeStage(view);
      const spec=issueSpec(data.category), row=entry(spec[0],'check',data.blocking?'等待恢复':'待纠正');
      row.details.dataset.state='attention';row.body.append(el('p',spec[1],'timeline-note'));
      ui.list.append(row.details);view.issue={...data,row};
    }
    if(data.kind==='review_result'&&data.passed===true&&view.issue) {
      view.issue.row.status.textContent='已纠正';view.issue.row.details.dataset.state='done';view.issue=null;
    }
    if(['stream_open','stream_delta','stream_end'].includes(data.kind))streamEvent(ui,data,view);
    if(data.kind==='status')stage(ui,data,view);
    if(data.kind==='model_process')processText(ui,data,view);
    if(data.kind==='tool_start'||data.kind==='tool_result')tool(ui,data,view);
    if(data.kind==='knowledge_sources'&&Array.isArray(data.references)) {
      closeStage(view); const row=entry('检索知识资料','search',data.references.length+' 个片段');
      const sources=el('div',undefined,'timeline-sources');for(const ref of data.references)sources.append(sourceCard({...ref,url:ref.source}));
      row.body.append(sources,el('p','知识库召回的原文片段，相关性不等于事实正确性。','timeline-note'));ui.list.append(row.details);
    }
    if(data.kind==='context_compacted') {
      const row=entry('上下文已整理','process','已结束');
      row.body.append(el('p','字符量 '+data.before_chars+' → '+data.after_chars+'；原始记录和执行证据保留。','timeline-note'));ui.list.append(row.details);
    }
    if(data.kind==='finished') {
      if(data.status==='completed'&&view.issue){view.issue.row.status.textContent='已纠正';view.issue.row.details.dataset.state='done';view.issue=null;}
      closeStage(view);if(!view.userToggled&&data.status==='completed')ui.activity.open=false;
      if(ui.timing?.snapshot){ui.timing.snapshot.active=null;tick(ui);}
      for(const row of view.rows.values())if(!row.result){row.status.textContent='未记录结果';row.details.dataset.state='unknown';}
    }
    ui.summary.textContent='执行过程'+(view.rows.size?' · '+view.rows.size+' 次工具调用':'');
  }
  window.GeoAgentTimeline={attach,event,tick};
})();

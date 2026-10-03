'use strict';
(() => {
  const el = (tag, text, className) => element(tag, text, className);
  const view = $('library-view'), main = view.closest('.main'), drawer = $('library-detail');
  const labels = {registered:'已接入', partial:'部分受阻', blocked:'未接入'};
  const categories = {Runtime:'运行时基础工具', GeoscienceTools:'地学通用', 'deep-earth':'深部地球',
    earthquake:'地震', 'remote-sensing':'遥感', geodesy:'大地测量', mining:'矿产',
    'deep-time':'深时地学', ccs:'碳捕集与封存', Other:'其他'};
  let data = null, kind = 'skills', epoch = 0, detailEpoch = 0, current = null, trail = [];
  const categoryName = value => categories[value] || value;
  const badge = status => el('span', labels[status] || '状态未知', 'library-status is-' + status);
  const listNode = values => {
    const list = el('ul');
    for (const value of values || []) list.append(el('li', String(value)));
    if (!list.children.length) list.append(el('li', '尚未声明，请查看完整说明。'));
    return list;
  };
  function closeDetail() { detailEpoch++; current = null; trail = []; if (drawer.open) drawer.close(); }
  function close({focus = true} = {}) {
    closeDetail(); view.hidden = true; main.classList.remove('library-open');
    $('library-open').setAttribute('aria-pressed', 'false');
    if (focus) {
      const menu = $('menu-button');
      (menu.getClientRects().length ? menu : $('library-open')).focus();
    }
  }
  function reset() {
    epoch++; data = null; kind = 'skills'; close({focus:false});
    $('library-search').value = ''; $('library-category').value = ''; $('library-status').value = '';
    $('library-results').replaceChildren(); selectKind('skills');
  }
  function empty(title, message, retry = false) {
    const panel = el('div', undefined, 'library-empty');
    panel.append(el('span', retry ? '!' : '/', 'library-empty-mark'), el('h2', title), el('p', message));
    const button = el('button', retry ? '重新加载' : '清除筛选', 'outline');
    button.type = 'button'; button.addEventListener('click', retry ? load : resetFilters);
    panel.append(button); $('library-results').replaceChildren(panel);
  }
  async function load() {
    const requestEpoch = ++epoch; $('library-results').setAttribute('aria-busy', 'true');
    $('library-results').replaceChildren(el('p', '正在读取运行时注册表…', 'library-loading'));
    try {
      const result = await api('/api/library');
      if (epoch !== requestEpoch || !state.me) return;
      data = result;
      $('library-stats').replaceChildren();
      for (const [number, title, subtitle] of [
        [data.counts.skills, 'Skills', '可浏览的方法'],
        [data.counts.professional_tools, '专业工具', '包含尚未接入条目'],
        [data.counts.registered_tools, '已接入工具', '含运行时基础工具'],
      ]) {
        const stat = el('div', undefined, 'library-stat');
        stat.append(el('strong', String(number)), el('span', title), el('small', subtitle));
        $('library-stats').append(stat);
      }
      $('library-skills-count').textContent = data.counts.skills;
      $('library-tools-count').textContent = data.counts.tools;
      $('library-disclaimer').textContent = data.notice;
      $('library-revision').textContent = '注册表 ' + data.revision + ' · ' + data.release;
      populateCategories(); render();
    } catch (error) {
      if (epoch === requestEpoch && state.me) empty('暂时无法读取目录', error.message, true);
    } finally { if (epoch === requestEpoch) $('library-results').setAttribute('aria-busy','false'); }
  }
  async function open() {
    if (!state.me) return;
    view.hidden = false; main.classList.add('library-open');
    $('files-panel').hidden = true; $('sidebar').classList.remove('open');
    $('library-open').setAttribute('aria-pressed','true');
    if (!data) await load(); else render();
    if (!view.hidden) $('library-search').focus();
  }
  function populateCategories() {
    const selected = $('library-category').value;
    $('library-category').replaceChildren(new Option('全部分类',''));
    for (const category of [...new Set(data[kind].map(row => row.category))].sort())
      $('library-category').append(new Option(categoryName(category),category));
    $('library-category').value = [...$('library-category').options].some(option=>option.value===selected) ? selected : '';
  }
  function selectKind(next) {
    kind = next;
    for (const button of document.querySelectorAll('[data-library-kind]')) {
      const selected = button.dataset.libraryKind === kind;
      button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
    }
    $('library-results').setAttribute('aria-labelledby','library-' + kind + '-tab');
    if (data) { populateCategories(); render(); }
  }
  function resetFilters() {
    $('library-search').value = ''; $('library-category').value = ''; $('library-status').value = '';
    render(); $('library-search').focus();
  }
  function render() {
    if (!data) return;
    const words = $('library-search').value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
    const category = $('library-category').value, status = $('library-status').value;
    const rows = data[kind].filter(row => {
      const haystack = [row.id, row.name, row.description, row.category, categoryName(row.category),
                       ...(row.tags || []), ...(row.tool_preview || [])].join(' ').toLocaleLowerCase();
      return (!category || row.category === category) && (!status || row.status === status)
        && words.every(word => haystack.includes(word));
    }).sort((a,b) => ({registered:0,partial:1,blocked:2}[a.status] - {registered:0,partial:1,blocked:2}[b.status])
      || a.name.localeCompare(b.name));
    $('library-match-count').textContent = rows.length + ' / ' + data[kind].length + ' 个条目';
    const target = $('library-results'); target.className = 'library-results ' + (kind === 'skills' ? 'library-grid' : 'library-tool-list');
    target.replaceChildren();
    if (!rows.length) { empty('没有找到匹配条目', '试试其他关键词，或切换分类与接入状态。'); return; }
    for (const row of rows) {
      const button = el('button', undefined, kind === 'skills' ? 'library-card' : 'library-tool-row');
      button.type = 'button';
      if (kind === 'skills') {
        const head = el('span', undefined, 'library-card-top');
        head.append(el('span', 'S', 'library-asset-icon'), badge(row.status));
        button.append(head, el('strong', row.name, 'library-card-title'), el('span', row.description, 'library-description'));
        const meta = el('span', undefined, 'library-card-meta');
        meta.append(el('span', categoryName(row.category)), el('span', row.available_tool_count + '/' + row.tool_count + ' 关联工具已接入'));
        button.append(meta);
        const preview = el('span', undefined, 'library-tool-preview');
        for (const tool of row.tool_preview || []) preview.append(el('code', tool));
        button.append(preview);
        const foot = el('span', undefined, 'library-card-foot');
        foot.append(el('span', '查看方法与关联工具'), el('span', '↗'));
        button.append(foot);
      } else {
        const title = el('span', undefined, 'library-tool-main');
        title.append(el('strong', row.name), el('span', row.description, 'library-description'));
        button.append(el('span', row.scope === 'runtime' ? 'R' : 'T', 'library-asset-icon'),
          title, el('span', categoryName(row.category), 'library-tool-category'), badge(row.status), el('span','›','library-chevron'));
      }
      button.addEventListener('click',()=>showDetail(row.kind,row.id)); target.append(button);
    }
  }
  function section(title, content) {
    const block = el('section', undefined, 'library-detail-section');
    block.append(el('h3',title),content); return block;
  }
  function rawDetails(title, value) {
    const details = el('details',undefined,'library-raw'), pre = el('pre');
    pre.textContent = typeof value === 'string' ? value : JSON.stringify(value,null,2);
    details.append(el('summary',title),pre); return details;
  }
  function typeName(schema) {
    if (schema.type) return Array.isArray(schema.type) ? schema.type.join(' | ') : schema.type + (schema.type === 'array' && schema.items ? '<' + typeName(schema.items) + '>' : '');
    if (schema.anyOf || schema.oneOf) return (schema.anyOf || schema.oneOf).map(typeName).join(' | ');
    return schema.$ref || '未声明';
  }
  function parameters(schema) {
    const container = el('div',undefined,'library-parameters'), required = new Set(schema.required || []);
    const properties = schema.properties || {};
    if (!Object.keys(properties).length) {
      container.append(el('p', '结构类型：' + typeName(schema) + '。完整约束见下方 Schema。', 'muted'));
    }
    for (const [name, value] of Object.entries(properties)) {
      const row = el('div',undefined,'library-parameter');
      const head = el('div',undefined,'library-parameter-heading');
      head.append(el('code',name),el('span',typeName(value),'library-type'),
        el('span',required.has(name)?'必填':'可选','library-required'));
      row.append(head,el('p',value.description || '未提供字段说明。'));
      const constraints = [];
      for (const key of ['minimum','maximum','exclusiveMinimum','exclusiveMaximum','minItems','maxItems','minLength','maxLength','multipleOf','pattern','default','const','enum','format','unit','units'])
        if (Object.prototype.hasOwnProperty.call(value,key)) constraints.push(key + ': ' + JSON.stringify(value[key]));
      if (constraints.length) row.append(el('small',constraints.join(' · ')));
      if (value.properties || value.items?.properties || value.allOf || value.oneOf || value.anyOf || value.$ref)
        row.append(rawDetails('嵌套结构与字段约束',value));
      container.append(row);
    }
    if (schema.additionalProperties === false) container.append(el('p','不允许传入未声明的字段。','library-schema-note'));
    container.append(rawDetails('查看完整 JSON Schema',schema));
    return container;
  }
  function links(rows, targetKind) {
    const list = el('div',undefined,'library-related');
    if (!rows.length) list.append(el('p','暂无关联条目。','muted'));
    for (const row of rows) {
      const button = el('button',undefined,'library-related-item'); button.type='button';
      const text = el('span'); text.append(el('strong',row.name || row.id));
      if (row.reason) text.append(el('small',row.reason));
      button.append(text,badge(row.status)); button.addEventListener('click',()=>showDetail(targetKind,row.id,true)); list.append(button);
    }
    return list;
  }
  function useNote() {
    if (!current) return;
    const blocked = Boolean(state.busy || window.GeoToolHITL?.blocksComposer());
    $('library-use').disabled = blocked || !current.example_prompt;
    $('library-use-note').textContent = blocked ? '当前任务仍在运行或等待回复。请先处理当前任务，或新建对话。'
      : current.example_prompt ? '只填入草稿，不会自动发送、加载技能或执行工具。请先核对参数和材料。'
      : current.status === 'blocked' ? '此条目尚未接入。可以查看说明，但不能发起示例调用。' : '暂无通过 Schema 检查的输入示例。';
  }
  async function showDetail(nextKind, id, push = false) {
    if (push === true && current) trail.push({kind:current.kind,id:current.id});
    else if (push === false) trail=[];
    const requestEpoch = ++detailEpoch; current=null;
    $('library-detail-back').hidden = !trail.length;
    $('library-detail-body').replaceChildren(el('h2','正在读取条目…'));
    $('library-detail-body').firstChild.id='library-detail-title';
    $('library-use').disabled=true; $('library-use-note').textContent='';
    if (!drawer.open) drawer.showModal();
    try {
      const row = await api('/api/library/' + nextKind + '/' + encodeURIComponent(id));
      if (requestEpoch !== detailEpoch || !drawer.open || !state.me) return;
      current=row;
      const body=$('library-detail-body'); body.replaceChildren();
      const meta=el('div',undefined,'library-detail-meta');
      meta.append(el('span',row.kind==='skills'?'SKILL':'TOOL','eyebrow'),badge(row.status),el('span',categoryName(row.category)));
      const title=el('h2',row.name); title.id='library-detail-title';
      body.append(meta,title,el('code',row.id,'library-id'),el('p',row.description,'library-detail-description'));
      if (row.reason) body.append(el('p',row.reason,'library-blocker'));
      if (row.when_to_use) body.append(section('何时使用',el('p',row.when_to_use)));
      if (row.kind==='skills') {
        body.append(section('所需输入',listNode(row.required_inputs)),section('预期结果',listNode(row.expected_outputs)),
          section('关联工具 · ' + row.available_tool_count + '/' + row.tool_count + ' 已接入',links(row.tools,'tools')));
        if (row.constraints.length) body.append(section('适用边界',listNode(row.constraints)));
        const document=el('div',undefined,'answer library-skill-document'); markdown(document,row.instructions || '尚未提供 Skill 文档。');
        body.append(section(row.document_kind,document));
      } else {
        body.append(section('输入参数',parameters(row.input_schema)),section('输出结构',parameters(row.output_schema)));
        if (row.example_arguments) body.append(section('参数示例',rawDetails('展开示例 JSON',row.example_arguments)));
        if (row.path_fields.length) body.append(section('所需文件',el('p','路径字段：' + row.path_fields.join('、') + '。请先将实际文件加入对话，使用任务内相对路径。')));
        if (row.limitations.length) body.append(section('方法与限制',listNode(row.limitations)));
        body.append(section('关联 Skills',links(row.skills,'skills')));
        const note=el('p','版本：' + row.version + ' · 源头验收标记：' + row.validation,'library-schema-note'); body.append(note);
      }
      if (row.example_prompt) body.append(section('任务示例',el('pre',row.example_prompt,'library-prompt-example')));
      useNote(); body.scrollTop=0;
    } catch(error) {
      if(requestEpoch!==detailEpoch || !drawer.open)return;
      const title=el('h2','无法读取条目');title.id='library-detail-title';
      $('library-detail-body').replaceChildren(title,el('p',error.message,'error'));
    }
  }
  $('library-open').addEventListener('click',open);
  $('library-back').addEventListener('click',()=>close());
  $('library-detail-close').addEventListener('click',closeDetail);
  drawer.addEventListener('close',()=>{detailEpoch++;current=null;trail=[];});
  $('library-detail-back').addEventListener('click',()=>{
    const previous=trail.pop(); if(previous)showDetail(previous.kind,previous.id,'back');
  });
  for(const button of document.querySelectorAll('[data-library-kind]')) {
    button.addEventListener('click',()=>selectKind(button.dataset.libraryKind));
    button.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault(); const next=event.key==='Home'?'skills':event.key==='End'?'tools':kind==='skills'?'tools':'skills';
      selectKind(next);$('library-'+next+'-tab').focus();
    });
  }
  for(const id of ['library-search','library-category','library-status'])$(id).addEventListener(id==='library-search'?'input':'change',render);
  $('library-reset').addEventListener('click',resetFilters);
  $('library-use').addEventListener('click',()=>{
    if(!current?.example_prompt || state.busy || window.GeoToolHITL?.blocksComposer()) {useNote();return;}
    const prompt=$('prompt'),example=current.example_prompt,draft=prompt.value.trim();
    if(draft!==example)prompt.value=draft?draft+'\n\n'+example:example;
    close({focus:false});prompt.focus();
    notice(draft&&draft!==example?'示例已追加到现有草稿，请核对后再发送。':'示例已填入草稿，请核对输入后再发送。');
  });
  window.GeoToolLibrary={close,reset};
})();

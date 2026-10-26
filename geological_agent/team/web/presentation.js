'use strict';
// Presentation is derived from native receipts. Nothing here dispatches tools,
// parses model HTML or evaluates model-written JavaScript.
(() => {
  const preference = 'geoagent:result-view:v1';
  let enabled = true, sequence = 0;
  try { enabled = localStorage.getItem(preference) !== 'text'; } catch { /* Optional preference only. */ }
  const registry = new Map();
  const make = (tag, text, cls) => element(tag, text, cls);
  const button = (text, action, cls = 'outline') => {
    const node = make('button', text, cls); node.type = 'button';
    node.addEventListener('click', action); return node;
  };
  const note = text => make('p', text, 'rich-note');
  function link(text, href, download) {
    const a = make('a', text, 'rich-link'); a.href = href;
    if (download) a.download = download;
    return a;
  }
  function assetURL(ctx, name, kind = 'download') {
    return '/api/conversations/' + encodeURIComponent(ctx.conversation_id) + '/' + kind
      + '?name=' + encodeURIComponent(name) + '&generation=' + encodeURIComponent(ctx.generation);
  }
  const receiptURL = (ctx, call) => '/api/runs/' + encodeURIComponent(ctx.run_id) + '/receipts/' + encodeURIComponent(call);
  function frame(title, kind) {
    const node = make('section', undefined, 'rich-card rich-' + kind);
    const header = make('header', undefined, 'rich-card-heading');
    header.append(make('span', kind.toUpperCase(), 'rich-eyebrow'), make('h3', title));
    node.append(header); return node;
  }
  function details(label, text) {
    const node = make('details', undefined, 'rich-details');
    node.append(make('summary', label), make('pre', text)); return node;
  }
  function select(label, entries, value, onChange) {
    const wrap = make('label', label, 'rich-select');
    const input = make('select'); input.id = 'rich-select-' + (++sequence); wrap.htmlFor = input.id;
    input.setAttribute('aria-label', label);
    for (const [key, text] of entries) { const option = make('option', text); option.value = key; input.append(option); }
    input.value = String(value); input.addEventListener('change', () => onChange(input.value));
    wrap.append(input); return {wrap, input};
  }
  function safeURL(value) {
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
    catch { return null; }
  }
  function modal(title, body) {
    const dialog = make('dialog', undefined, 'rich-modal'), head = make('header', undefined, 'rich-modal-heading');
    const h = make('h2', title); h.id = 'rich-dialog-' + (++sequence); dialog.setAttribute('aria-labelledby', h.id);
    head.append(h, button('关闭', () => dialog.close(), 'quiet'));
    dialog.append(head, body); dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog); dialog.showModal(); return dialog;
  }

  registry.set('metrics', (block, ctx) => {
    const p = block.props;
    if (!Array.isArray(p.items) || p.items.some(item => typeof item.label !== 'string' || typeof item.value !== 'string')) throw new Error('Invalid metric fields');
    const card = frame(block.title, 'metrics'), grid = make('div', undefined, 'rich-metric-grid');
    const more = make('details', undefined, 'rich-details'); more.append(make('summary', '展开其余 ' + Math.max(0, p.items.length - 6) + ' 个字段'));
    const extra = make('div', undefined, 'rich-metric-grid'); more.append(extra);
    p.items.forEach((item, index) => {
      const cell = make('div', undefined, 'rich-metric');
      cell.append(make('span', item.label, 'rich-metric-label'), make('strong', item.value, 'rich-metric-value'));
      (index < 6 ? grid : extra).append(cell);
    });
    card.append(grid); if (p.items.length > 6) card.append(more);
    card.append(note((p.cached ? '复用的工具返回值' : '实际工具返回值') + ' · 字段名保留单位信息，不推断单位；这不代表独立科学认证。'));
    card.append(link('下载原始工具结果', receiptURL(ctx, p.call_id), 'tool-result.json'));
    return card;
  });

  function numeric(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value !== 'string' || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null;
    const text = value.trim(), number = Number(text);
    if (!Number.isFinite(number) || (/^[+-]?\d+$/.test(text) && !Number.isSafeInteger(number))) return null;
    return number;
  }
  function svgElement(tag, attributes = {}, text) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function chart(rows, columns, offset = 0) {
    const box = make('section', undefined, 'rich-chart');
    const numericColumns = columns.map((_, i) => i).filter(i => rows.length && rows.every(row => numeric(row[i]) !== null));
    if (!numericColumns.length) { box.append(note('当前页没有完整的数值列，不生成推测图表。空值、非数值和不安全的大整数不会被偷偷转成 0。')); return box; }
    let x = -1, y = numericColumns[0], mode = 'scatter';
    const controls = make('div', undefined, 'rich-chart-controls'), canvas = make('div', undefined, 'rich-chart-canvas');
    const cursor = make('p', '悬停或用 Tab 选择数据点，查看原始单元格值。', 'rich-chart-cursor');
    cursor.setAttribute('role', 'status'); cursor.setAttribute('aria-live', 'polite');
    controls.append(select('横轴', [[-1, '当前行序号'], ...numericColumns.map(i => [i, columns[i]])], x, value => { x = Number(value); draw(); }).wrap,
      select('纵轴', numericColumns.map(i => [i, columns[i]]), y, value => { y = Number(value); draw(); }).wrap,
      select('图形', [['scatter', '散点'], ['line', '折线'], ['bar', '柱形']], mode, value => { mode = value; draw(); }).wrap);
    box.append(controls, canvas, cursor, note('仅绘制当前表格页，共 ' + rows.length + ' 行；未补值、未平滑。轴标签沿用列名，具体单位以原始资料为准。'));
    function draw() {
      canvas.replaceChildren();
      const xs = rows.map((row, i) => x < 0 ? offset + i + 1 : numeric(row[x]));
      const ys = rows.map(row => numeric(row[y]));
      let minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      if (mode === 'bar') { minY = Math.min(minY, 0); maxY = Math.max(maxY, 0); }
      if (minX === maxX) { const delta = Math.max(Math.abs(minX) * .05, 1); minX -= delta; maxX += delta; }
      if (minY === maxY) { const delta = Math.max(Math.abs(minY) * .05, 1); minY -= delta; maxY += delta; }
      // Extreme finite values can overflow the subtraction; keep the raw table.
      if (!Number.isFinite(maxX - minX) || !Number.isFinite(maxY - minY)) { canvas.append(note('数值跨度超过浏览器图表范围，请使用原始表格。')); return; }
      const sx = value => 92 + (value - minX) / (maxX - minX) * 586;
      const sy = value => 254 - (value - minY) / (maxY - minY) * 208;
      const svg = svgElement('svg', {viewBox:'0 0 720 318', role:'img', 'aria-label':columns[y] + '，当前页数据图'});
      svg.append(svgElement('title', {}, columns[y] + ' / ' + (x < 0 ? '行序号' : columns[x])));
      const tickText = value => Math.abs(value) >= 1e6 || (value !== 0 && Math.abs(value) < .001) ? value.toExponential(2) : Number(value.toPrecision(5)).toString();
      for (let i = 0; i <= 4; i++) {
        const yy = minY + (maxY - minY) * i / 4, xx = minX + (maxX - minX) * i / 4;
        svg.append(svgElement('line', {x1:92, y1:sy(yy), x2:678, y2:sy(yy), class:'rich-grid-line'}));
        svg.append(svgElement('text', {x:83, y:sy(yy)+4, 'text-anchor':'end', class:'rich-axis-text'}, tickText(yy)));
        svg.append(svgElement('text', {x:sx(xx), y:275, 'text-anchor':'middle', class:'rich-axis-text'}, tickText(xx)));
      }
      svg.append(svgElement('text', {x:92, y:22, class:'rich-axis-label'}, columns[y]));
      svg.append(svgElement('text', {x:386, y:304, 'text-anchor':'middle', class:'rich-axis-label'}, x < 0 ? '行序号' : columns[x]));
      if (mode === 'line') svg.append(svgElement('polyline', {points:xs.map((value, i) => sx(value)+','+sy(ys[i])).join(' '), class:'rich-plot-line', fill:'none'}));
      rows.forEach((row, i) => {
        const point = mode === 'bar'
          ? svgElement('rect', {x:sx(xs[i])-Math.min(18, 260/rows.length), y:Math.min(sy(ys[i]), sy(0)), width:Math.min(36, 520/rows.length), height:Math.max(1, Math.abs(sy(ys[i])-sy(0))), class:'rich-plot-bar', tabindex:0})
          : svgElement('circle', {cx:sx(xs[i]), cy:sy(ys[i]), r:4, class:'rich-plot-point', tabindex:0});
        const text = (x < 0 ? '行 ' + (offset+i+1) : columns[x] + ': ' + String(row[x])) + ' · ' + columns[y] + ': ' + String(row[y]);
        point.append(svgElement('title', {}, text)); point.setAttribute('aria-label', text);
        point.addEventListener('pointerenter', () => { cursor.textContent = text; });
        point.addEventListener('focus', () => { cursor.textContent = text; }); svg.append(point);
      });
      canvas.append(svg);
    }
    draw(); return box;
  }

  registry.set('table', (block, ctx) => {
    const p = block.props, file = p.file;
    if (!file && (!Array.isArray(p.columns) || !Array.isArray(p.rows))) throw new Error('Invalid table');
    const card = frame(block.title, 'table'), header = make('div', undefined, 'rich-card-actions');
    const download = file ? assetURL(ctx, file.name) : receiptURL(ctx, p.call_id);
    header.append(link(file ? '下载原文件' : '下载完整工具结果', download, file ? file.name.split('/').pop() : 'tool-result.json'));
    card.append(header);
    if (file) card.append(note('任务文件快照 · SHA-256 ' + file.sha256));
    const body = make('div'), status = note(''), content = make('div'), pager = make('div', undefined, 'rich-pager');
    body.append(status, content, pager); card.append(body);
    let offset = 0, sort = -1, descending = false, tableMode = 'table';
    const requests = window.GeoPresentationState.latestRequest();
    let data = null;
    const tabs = make('div', undefined, 'rich-segments'); tabs.setAttribute('aria-label', '数据展示方式');
    const tabTable = button('数据表', () => { tableMode = 'table'; paint(); }, 'quiet');
    const tabChart = button('图表', () => { tableMode = 'chart'; paint(); }, 'quiet'); tabs.append(tabTable, tabChart);
    card.insertBefore(tabs, body);
    async function load() {
      const token = requests.begin(); body.setAttribute('aria-busy', 'true'); status.textContent = '正在读取该次任务的数据…';
      try {
        const incoming = file ? await api('/api/runs/' + encodeURIComponent(ctx.run_id) + '/table?name=' + encodeURIComponent(file.name)
          + '&offset=' + offset + '&limit=50&sort=' + sort + '&descending=' + descending)
          : {...p, rows:p.rows.map(row => [...row]), offset:0};
        if (!requests.current(token)) return;
        data = incoming;
        if (file && data.sha256 !== file.sha256) throw new Error('文件快照哈希不匹配，未展示数据。');
        if (!file && sort >= 0) data.rows.sort((a,b) => {
          const aa = numeric(a[sort]), bb = numeric(b[sort]);
          const order = aa !== null && bb !== null ? aa - bb : String(a[sort] ?? '').localeCompare(String(b[sort] ?? ''));
          return descending ? -order : order;
        });
        paint();
      } catch (error) {
        if (!requests.current(token)) return;
        status.textContent = '预览不可用：' + error.message + ' 原始文件和任务结果不受影响。';
        content.replaceChildren(button('重试预览', load)); pager.replaceChildren();
      } finally { if (requests.current(token)) body.removeAttribute('aria-busy'); }
    }
    function paint() {
      if (!data) return;
      if (!Array.isArray(data.rows) || data.rows.some(row => !Array.isArray(row) || row.length !== data.columns.length)) {
        status.textContent = '表格列数不一致，未删除或补造数据；请下载原始结果。'; return;
      }
      content.replaceChildren(); pager.replaceChildren();
      tabTable.setAttribute('aria-pressed', String(tableMode === 'table')); tabChart.setAttribute('aria-pressed', String(tableMode === 'chart'));
      const start = data.rows.length ? (data.offset || 0)+1 : 0, end = (data.offset || 0)+data.rows.length;
      status.textContent = '显示 ' + start + '–' + end + ' / ' + data.total + ' 行'
        + (file ? ' · 排序针对完整文件' : ' · 排序与绘图仅针对当前预览；完整数据请下载');
      if (tableMode === 'chart') content.append(chart(data.rows, data.columns, data.offset || 0));
      else {
        const scroll = make('div', undefined, 'rich-table-scroll'), table = make('table'), head = make('thead'), hr = make('tr');
        table.append(make('caption', block.title));
        data.columns.forEach((name, index) => {
          const th = make('th'); th.scope = 'col'; th.setAttribute('aria-sort', sort === index ? descending ? 'descending' : 'ascending' : 'none');
          th.append(button(String(name) + (sort === index ? descending ? ' ↓' : ' ↑' : ''), () => {
            descending = sort === index ? !descending : false; sort = index; offset = 0; load();
          }, 'rich-sort')); hr.append(th);
        }); head.append(hr); table.append(head);
        const tb = make('tbody');
        for (const row of data.rows) {
          const tr = make('tr'); for (const value of row) { const td = make('td', value === null ? 'null' : String(value)); if (value === null) td.className = 'rich-null'; tr.append(td); } tb.append(tr);
        }
        table.append(tb); scroll.append(table); content.append(scroll);
      }
      if (file && data.total > 50) {
        const previous = button('上一页', () => { offset = Math.max(0, offset-50); load(); }); previous.disabled = offset === 0;
        const next = button('下一页', () => { offset += 50; load(); }); next.disabled = offset + data.rows.length >= data.total;
        pager.append(previous, note('每页 50 行'), next);
      }
    }
    if (file) {
      status.textContent = '按需读取，不将整份文件塞进模型上下文。';
      content.append(button('查看数据与图表', load));
    } else load();
    return card;
  });

  registry.set('images', (block, ctx) => {
    const files = block.props.files;
    if (!Array.isArray(files) || !files.length || files.some(file => typeof file.name !== 'string' || typeof file.sha256 !== 'string')) throw new Error('Invalid image references');
    if (window.GeoAgentExperience) {
      const card = frame('图片与处理结果', 'image');
      card.append(note(files.length + ' 个图像文件，按需预览；下载保留原始科学数值与坐标。'),
        button('查看这些图像', () => window.GeoAgentExperience.files(ctx, files[0].name)));
      return card;
    }
    const card = frame('图片与处理结果', 'image'), grid = make('div', undefined, 'rich-image-pair');
    const knownPair = (block.props.pairs || [])[0];
    const names = [knownPair?.before || files[0].name, knownPair?.after || files[Math.min(1,files.length-1)].name];
    [0,1].forEach(index => {
      const panel = make('section'), view = make('div', undefined, 'rich-image-viewport'), foot = make('div');
      const picker = select(index ? '对比图 B' : '参考图 A', files.map(file => [file.name,file.name]), names[index], value => { names[index] = value; paint(); });
      panel.append(picker.wrap, view, foot); grid.append(panel);
      function paint() {
        view.replaceChildren(); foot.replaceChildren();
        const file = files.find(item => item.name === names[index]); if (!file) return;
        const src = assetURL(ctx, file.name, 'image'), img = make('img'); img.src = src; img.alt = file.name; img.loading = 'lazy';
        img.addEventListener('error', () => { view.replaceChildren(note('该图暂不能预览，请下载原文件。')); });
        view.append(img);
        foot.append(button('放大查看', () => {
          const large = make('img'); large.src = src; large.alt = file.name; large.className = 'rich-image-large'; modal(file.name, large);
        }, 'quiet'), link('下载原文件', assetURL(ctx, file.name), file.name.split('/').pop()), details('文件指纹', file.sha256));
      }
      paint();
    });
    card.append(grid, note(knownPair ? '默认配对来自工具记录，文件名与 SHA-256 均匹配。你可以切换到同一任务快照中的其他图片。' : '手动图片对比，不代表两幅图已经配准，也不推断处理前后关系。'),
      note('各图独立缩放显示。GeoTIFF 预览可能包含波段拉伸；原始数值、坐标和 NoData 信息以下载文件为准。'));
    return card;
  });

  registry.set('sources', block => {
    if (!Array.isArray(block.props.items)) throw new Error('Invalid sources');
    const card = make('details', undefined, 'rich-card citation-retrieval');
    card.append(make('summary', '检索记录 · ' + block.props.items.length + ' 个片段'));
    card.append(note('正文使用的文献列在“参考资料”中。这里保留本轮检索记录，包括未被引用的资料。'));
    for (const source of block.props.items) {
      const item = make('article', undefined, 'rich-source');
      item.append(make('h4', String(source.title || '未命名资料')));
      const url = typeof source.source === 'string' ? safeURL(source.source) : null;
      if (url) { const a = link('打开资料来源',url); a.target = '_blank'; a.rel = 'noopener noreferrer'; item.append(a); }
      else item.append(details('来源记录', String(source.source || '来源说明未记录')));
      item.append(details('查看检索时的原文片段', String(source.text || '原文片段未记录')));
      item.append(details('技术详情', JSON.stringify({citation_id:source.citation_id, sha256:source.sha256}, null, 2)));
      if (typeof source.document_id === 'string' && source.document_id) item.append(button('查看知识库原文', async () => {
        const owner = state.me?.id, body = make('pre', '正在读取…', 'rich-source-document');
        const dialog = modal(String(source.title || '知识资料'), body);
        try {
          const result = await api('/api/knowledge/' + encodeURIComponent(source.document_id));
          if (!state.me || state.me.id !== owner) { dialog.close(); return; }
          body.textContent = typeof result.body === 'string' ? result.body : typeof result.text === 'string' ? result.text : '当前资料未提供正文。请查看保留的检索片段。';
        } catch (error) { body.textContent = '当前原文不可用：' + error.message + '。检索时的片段仍保留在卡片中。'; }
      }, 'quiet'));
      card.append(item);
    }
    return card;
  });

  function applyPreference() {
    for (const ui of state.runs.values()) {
      if (!ui.rich) continue;
      ui.rich.panel.hidden = !enabled;
      if (ui.rich.compact) ui.rich.compact.hidden = !enabled;
      ui.rich.visual.setAttribute('aria-pressed', String(enabled));
      ui.rich.plain.setAttribute('aria-pressed', String(!enabled));
    }
  }
  function choose(value) {
    enabled = value; try { localStorage.setItem(preference, enabled ? 'visual' : 'text'); } catch { /* Nonessential. */ }
    applyPreference();
  }
  function attach(rid, ui) {
    if (ui.rich) return;
    const root = make('section', undefined, 'rich-results'); root.setAttribute('aria-label', '任务结果展示');
    const toolbar = make('div', undefined, 'rich-toolbar'), label = make('span', 'RESULTS / EVIDENCE', 'rich-eyebrow');
    const modes = make('div', undefined, 'rich-segments'), visual = button('成果面板', () => { choose(true); window.GeoAgentExperience?.open(rid, ui); }, 'quiet'), plain = button('纯文本', () => choose(false), 'quiet');
    modes.append(visual, plain); toolbar.append(label, modes);
    const panel = make('div', undefined, 'rich-result-view'), status = note(''), blocks = make('div', undefined, 'rich-blocks');
    panel.append(status, blocks); root.append(toolbar, panel); ui.answer.after(root);
    ui.rich = {root, panel, status, blocks, visual, plain, version:0, timer:null};
    applyPreference(); refresh(rid, ui);
  }
  async function refresh(rid, ui) {
    const rich = ui.rich, view = state.view, cid = state.cid, version = ++rich.version;
    const current = () => state.view === view && state.cid === cid && state.runs.get(rid) === ui && rich.version === version;
    try {
      const result = await api('/api/runs/' + encodeURIComponent(rid) + '/presentation');
      if (!current()) return;
      if (result.version !== 1 || result.run_id !== rid || result.conversation_id !== cid || !Array.isArray(result.blocks)) throw new Error('不支持的展示数据版本');
      ui.artifactContext = result;
      if (typeof markdown === 'function' && typeof ui.answerText === 'string') markdown(ui.answer, ui.answerText, result);
      // A literature answer needs citations, not an empty scientific dashboard.
      rich.root.hidden = !result.blocks.some(block => block.component !== 'sources');
      rich.status.textContent = result.blocks.length
        ? '来自实际工具回执与该次任务的文件快照。回答审核与科学正确性不是一回事。'
        : ['running','stopping'].includes(result.status) ? '执行结果返回后将在这里显示。' : '本轮没有可展示的结构化结果。文字答复和执行记录保留在上方。';
      const existing = new Map([...rich.blocks.children].map(node => [node.dataset.block,node]));
      const order = [], seen = new Set();
      for (const block of result.blocks) {
        if (typeof block.id !== 'string' || seen.has(block.id)) throw new Error('展示块标识不完整或重复');
        seen.add(block.id);
        const signature = JSON.stringify([block,result.generation]);
        let node = existing.get(block.id);
        if (node?.dataset.signature === signature) { order.push(node); continue; }
        try {
          if (block.version !== 1 || !block.props || typeof block.props !== 'object' || !registry.has(block.component)) throw new Error('未知组件或版本');
          node = registry.get(block.component)(block,result);
        } catch (error) {
          node = frame('结果预览暂不可用', 'fallback');
          node.append(note(error.message + '；未执行任何额外操作。原始工具记录仍在上方。'), details('查看展示数据', JSON.stringify(block,null,2)));
        }
        node.dataset.block = block.id; node.dataset.signature = signature; order.push(node);
      }
      rich.blocks.replaceChildren(...order);
      window.GeoScientificViewer?.attach(rid, ui, result);
      window.GeoAgentExperience?.results(rid, ui, result);
    } catch (error) {
      if (!current()) return;
      rich.status.replaceChildren(document.createTextNode('结果视图加载失败：' + error.message + '。文字和文件仍可使用。 '), button('重试', () => refresh(rid,ui), 'quiet'));
    }
  }
  function onEvent(rid, data) {
    const ui = state.runs.get(rid); if (!ui) return;
    attach(rid, ui);
    if (['tool_result','knowledge_sources','finished'].includes(data.kind)) {
      clearTimeout(ui.rich.timer);
      ui.rich.timer = setTimeout(() => {
        if (state.runs.get(rid) === ui) refresh(rid,ui);
      }, data.kind === 'finished' ? 0 : 200);
    }
  }
  window.GeoAgentPresentation = {attach, event:onEvent};
  for (const [rid,ui] of state.runs) attach(rid,ui);
})();

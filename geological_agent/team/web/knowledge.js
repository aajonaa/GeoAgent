'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const view = $('knowledge-view'), main = $('messages').closest('.main');
  const importer = $('knowledge-import');
  main.append(view);
  const tabs = ['library', 'detail', 'search'];
  const numbers = new Intl.NumberFormat('zh-CN');
  let epoch = 0, catalogEpoch = 0, detailEpoch = 0, searchEpoch = 0, fileEpoch = 0;
  let catalog = null, catalogError = '', currentDoc = null, lastSearch = null;
  let detailOrigin = 'library', importing = false, reading = false, searching = false, deleting = false;

  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  }
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', name === 'arrow' ? 'm9 5 7 7-7 7' : 'M7 3h7l5 5v13H5V3h2m7 0v6h5M8 13h8M8 17h5');
    svg.append(path); return svg;
  }
  function button(text, action, cls = '') {
    const node = el('button', text, 'k-button ' + cls); node.type = 'button';
    node.addEventListener('click', action); return node;
  }
  function message(id, text, error = false) {
    $(id).textContent = text; $(id).classList.toggle('is-error', error);
  }
  function numeric(value) { return typeof value === 'number' && Number.isFinite(value); }
  function count(value) { return numeric(value) ? numbers.format(value) : '未提供'; }
  function score(value, precision = 3) { return numeric(value) ? value.toFixed(precision) : '未提供'; }
  function date(value) {
    const d = new Date(value);
    return value && !Number.isNaN(d.getTime()) ? d.toLocaleDateString('zh-CN') : '未提供';
  }
  function tag(text, good = false) { return el('span', text, 'k-tag' + (good ? ' is-indexed' : '')); }
  function docState(doc) { return numeric(doc.chunks) ? (doc.chunks > 0 ? '有索引' : '无索引') : '状态未提供'; }
  function modelName(value) { return typeof value === 'string' && value ? value : '接口未提供'; }
  function empty(target, title, note, action) {
    const box = el('div', undefined, 'k-empty');
    box.append(el('span', '01', 'k-empty-number'), el('h2', title), el('p', note));
    if (action) box.append(action); target.replaceChildren(box);
  }

  function selectTab(name, focus = false) {
    for (const tab of tabs) {
      const selected = tab === name, control = $('knowledge-tab-' + tab);
      control.setAttribute('aria-selected', String(selected)); control.tabIndex = selected ? 0 : -1;
      $('knowledge-panel-' + tab).hidden = !selected;
    }
    if (focus) $('knowledge-tab-' + name).focus();
  }
  function close(focus = true) {
    if (view.hidden) return;
    epoch++; catalogEpoch++; detailEpoch++; searchEpoch++; pdfTicket++;
    clearTimeout(pdfTimer);
    if (searching) message('knowledge-search-status', '已离开此工作区，未继续展示本次请求。后端请求不一定取消，可以重新测试。');
    searching = false; $('knowledge-search').disabled = false;
    $('knowledge-results').setAttribute('aria-busy', 'false');
    view.hidden = true; main.classList.remove('knowledge-open');
    $('knowledge-open').setAttribute('aria-pressed', 'false');
    if (focus) $('knowledge-open').focus();
  }
  function open() {
    if (main.classList.contains('library-open')) $('library-back').click();
    if (view.hidden) epoch++;
    view.hidden = false; main.classList.add('knowledge-open');
    $('knowledge-open').setAttribute('aria-pressed', 'true');
    $('files-panel').hidden = true; $('sidebar').classList.remove('open');
    selectTab('library');
    $('knowledge-heading').focus({preventScroll: true});
    refresh(); refreshPdfJobs();
  }
  async function refresh() {
    const turn = epoch, ticket = ++catalogEpoch;
    $('knowledge-documents').setAttribute('aria-busy', 'true');
    $('knowledge-refresh').disabled = true;
    message('knowledge-status', '正在读取当前账号的知识资料…');
    try {
      const data = await api('/api/knowledge');
      if (turn !== epoch || ticket !== catalogEpoch || view.hidden) return;
      if (!Array.isArray(data.documents)) throw new Error('知识接口未返回有效的文献清单。');
      catalog = data; catalogError = '';
      $('knowledge-file').accept = data.pdf_service?.enabled ? '.pdf,.txt,.md,.markdown' : '.txt,.md,.markdown';
      $('knowledge-count').textContent = count(data.documents.length);
      $('knowledge-indexed-count').textContent = data.documents.every(d => numeric(d.chunks))
        ? count(data.documents.filter(d => d.chunks > 0).length) : '未提供';
      $('knowledge-chunk-count').textContent = data.documents.every(d => numeric(d.chunks))
        ? count(data.documents.reduce((sum, d) => sum + d.chunks, 0)) : '未提供';
      renderCatalog();
      message('knowledge-status', '已同步资料与索引数量。检索使用当前后端配置，不自动切换模型。');
    } catch (error) {
      if (turn !== epoch || ticket !== catalogEpoch || view.hidden) return;
      catalog = null; catalogError = error.message;
      for (const id of ['knowledge-count', 'knowledge-indexed-count', 'knowledge-chunk-count']) $(id).textContent = '未读取';
      renderCatalog(); message('knowledge-status', error.message, true);
    } finally {
      if (ticket === catalogEpoch) {
        $('knowledge-documents').setAttribute('aria-busy', 'false');
        $('knowledge-refresh').disabled = false;
      }
    }
  }
  function renderCatalog() {
    const target = $('knowledge-documents');
    if (!catalog) {
      $('knowledge-match-count').textContent = '';
      empty(target, '暂时无法读取文献库', catalogError || '请重新连接知识服务。', button('重试', refresh)); return;
    }
    const query = $('knowledge-filter').value.toLocaleLowerCase().trim(), filter = $('knowledge-filter-state').value;
    const rows = catalog.documents.filter(doc =>
      (!query || (String(doc.title || '') + ' ' + String(doc.source || '')).toLocaleLowerCase().includes(query)) &&
      (filter === 'all' || (filter === 'indexed' ? numeric(doc.chunks) && doc.chunks > 0 : doc.chunks === 0)));
    target.replaceChildren();
    $('knowledge-match-count').textContent = count(rows.length) + ' / ' + count(catalog.documents.length) + ' 份资料';
    if (!rows.length) {
      empty(target, catalog.documents.length ? '没有匹配的资料' : '从第一份可信资料开始',
        catalog.documents.length ? '试试其他标题、来源或索引状态。' : '原文会保留在文献库中。建立索引后，可以去检索试验检查召回。',
        catalog.documents.length ? button('清除筛选', () => {
          $('knowledge-filter').value = ''; $('knowledge-filter-state').value = 'all'; renderCatalog();
        }) : button('添加文献', openImport, 'k-primary'));
      return;
    }
    for (const doc of rows) {
      const row = el('button', undefined, 'k-document-row'); row.type = 'button';
      const head = el('span', undefined, 'k-document-main'), file = el('span', undefined, 'k-document-icon');
      file.append(icon('document'));
      const title = el('span', undefined, 'k-document-title');
      title.append(el('strong', doc.title || '未命名资料'), el('small', doc.source || '未提供来源'));
      head.append(file, title); row.title = (doc.title || '') + '\n' + (doc.source || '');
      const arrow = el('span', undefined, 'k-document-arrow'); arrow.append(icon('arrow'));
      row.append(head, tag(docState(doc), doc.chunks > 0), el('span', count(doc.chunks), 'k-number'),
        el('span', date(doc.created_at), 'k-number k-date'), arrow);
      row.addEventListener('click', () => openDocument(doc.id)); target.append(row);
    }
  }

  function sourceNode(source) {
    try {
      const url = new URL(source);
      if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) {
        const link = el('a', source); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
      }
    } catch (_) { /* Plain source descriptions remain text, never HTML. */ }
    return el('span', source || '未提供来源');
  }
  async function openDocument(id, hit = null, origin = 'library') {
    if (!id) return;
    const turn = epoch, ticket = ++detailEpoch; detailOrigin = origin;
    selectTab('detail'); $('knowledge-detail').setAttribute('aria-busy', 'true');
    empty($('knowledge-detail'), '正在读取原文', '只读取当前账号可以访问的资料。');
    try {
      const data = await api('/api/knowledge/' + encodeURIComponent(id));
      if (turn !== epoch || ticket !== detailEpoch || view.hidden) return;
      currentDoc = {...(catalog?.documents.find(d => d.id === id) || {}), ...data};
      if (typeof currentDoc.body !== 'string') throw new Error('接口没有返回原始正文。');
      renderDocument(hit);
    } catch (error) {
      if (turn !== epoch || ticket !== detailEpoch || view.hidden) return;
      currentDoc = null; empty($('knowledge-detail'), '无法读取这份资料', error.message,
        button('返回文献库', () => selectTab('library', true)));
    } finally { if (ticket === detailEpoch) $('knowledge-detail').setAttribute('aria-busy', 'false'); }
  }
  function renderDocument(hit = null) {
    const doc = currentDoc; if (!doc) return;
    const target = $('knowledge-detail'); target.replaceChildren();
    const heading = el('header', undefined, 'k-detail-heading'), title = el('div');
    title.append(el('p', 'SOURCE / ORIGINAL', 'k-eyebrow'), el('h2', doc.title || '资料原文'));
    const source = el('p'); source.append(sourceNode(doc.source)); title.append(source);
    heading.append(title, button(detailOrigin === 'search' ? '返回检索结果' : '返回文献库', () => selectTab(detailOrigin, true)));
    const stats = el('div', undefined, 'k-detail-stats');
    stats.append(tag(docState(doc), doc.chunks > 0), tag(count(doc.chunks) + ' 个索引片段'),
      tag(count(Array.from(doc.body).length) + ' 字符'));
    const layout = el('div', undefined, 'k-detail-layout'), reader = el('section', undefined, 'k-reader');
    const readerHead = el('div', undefined, 'k-pane-heading'); readerHead.append(el('strong', '原始正文'), el('span', '只读 · 保留原始表述'));
    const pre = el('pre', undefined, 'k-original'); let mark = null, locationNote = '';
    if (hit) {
      const characters = Array.from(doc.body), start = hit.start_char, end = hit.end_char;
      if ((!hit.sha256 || hit.sha256 === doc.sha256) && Number.isInteger(start) && Number.isInteger(end) &&
          start >= 0 && end > start && end <= characters.length && characters.slice(start, end).join('') === hit.text) {
        mark = el('mark', hit.text); mark.tabIndex = -1;
        pre.append(document.createTextNode(characters.slice(0, start).join('')), mark,
          document.createTextNode(characters.slice(end).join('')));
        locationNote = '已核对片段与当前原文一致，并高亮字符 ' + count(start) + '–' + count(end) + '。';
      } else {
        pre.textContent = doc.body;
        locationNote = '此片段与当前原文或位置不一致，未高亮。请重新检索，不将旧位置当作有效引用。';
      }
    } else pre.textContent = doc.body;
    reader.append(readerHead, pre);
    const evidence = el('section', undefined, 'k-evidence-panel'), evidenceHead = el('div', undefined, 'k-pane-heading');
    evidenceHead.append(el('strong', '检索片段'), el('span', '最近一次检索'));
    const body = el('div', undefined, 'k-evidence-body');
    if (locationNote) body.append(el('p', locationNote, 'k-caption'));
    const pieces = searchCandidates().filter(item => item.document_id === doc.id);
    body.append(el('p', pieces.length ? '下面是这份资料在最近一次检索中的候选，不是全文分块清单。'
      : '这里展示真实召回片段。先到检索试验输入问题，再回来对照原文。', 'k-caption'));
    for (const [i, piece] of pieces.entries()) body.append(hitCard(piece, i + 1, false, () => renderDocument(piece)));
    body.append(button('去检索试验', () => { selectTab('search'); $('knowledge-query').focus(); }));
    body.append(el('p', '当前接口提供正文与字符位置；PDF 页码、版面坐标、Token 数和全文分块详情尚未开放。', 'k-caption'));
    evidence.append(evidenceHead, body); layout.append(reader, evidence);
    const record = el('details', undefined, 'k-model-record'); record.append(el('summary', '来源与索引记录'));
    const metadata = el('dl');
    for (const [key, value] of [['文档 ID', doc.id], ['原文 SHA256', doc.sha256], ['索引模型标识', doc.embedding_key], ['添加时间', doc.created_at]]) {
      metadata.append(el('dt', key), el('dd', modelName(value)));
    }
    record.append(metadata);
    const actions = el('div', undefined, 'k-detail-actions');
    actions.append(el('span', '只删除当前账号的这份资料。', 'k-caption'), button('删除资料', () => removeDocument(doc.id), 'k-danger'));
    target.append(heading, stats, layout, record, actions);
    if (mark) requestAnimationFrame(() => { if (mark.isConnected) mark.scrollIntoView({block: 'center'}); });
  }
  async function removeDocument(id) {
    if (deleting || !window.confirm('删除这份知识资料及其索引？已完成对话的引用快照会保留；PDF 导入任务中的原文件和解析结果也会保留。')) return;
    deleting = true; const turn = epoch;
    try {
      await api('/api/knowledge/' + encodeURIComponent(id), {method: 'DELETE'});
      if (turn !== epoch || view.hidden) return;
      if (currentDoc?.id === id) currentDoc = null;
      lastSearch = null; $('knowledge-results').replaceChildren(el('p', '资料已变更，请重新测试召回。', 'k-caption'));
      empty($('knowledge-detail'), '这份资料已删除', '可以返回文献库继续查看其他资料。');
      selectTab('library'); await refresh();
    } catch (error) { if (turn === epoch && !view.hidden) message('knowledge-status', error.message, true); }
    finally { deleting = false; }
  }

  function searchCandidates() { return Array.isArray(lastSearch?.candidates) ? lastSearch.candidates : (lastSearch?.references || []); }
  function hitCard(hit, position, before, action = null) {
    const card = el('details', undefined, 'k-hit'), summary = el('summary');
    const title = el('span', undefined, 'k-hit-title');
    title.append(el('strong', hit.title || '未命名资料'), el('small', before
      ? 'RRF ' + score(hit.rrf_score, 5) : '重排分数 ' + score(hit.rerank_score)));
    summary.append(el('span', String(position).padStart(2, '0'), 'k-hit-rank'), title);
    const content = el('div', undefined, 'k-hit-content'); content.append(el('p', hit.text || '未返回片段正文'));
    const metadata = el('div', undefined, 'k-evidence-meta');
    if (numeric(hit.ranks?.dense)) metadata.append(tag('语义 #' + hit.ranks.dense));
    if (numeric(hit.ranks?.lexical)) metadata.append(tag('关键词 #' + hit.ranks.lexical));
    if ((lastSearch?.references || []).some(item => item.citation_id === hit.citation_id)) metadata.append(tag('通过筛选', true));
    if (Number.isInteger(hit.start_char) && Number.isInteger(hit.end_char)) metadata.append(el('span', '字符 ' + count(hit.start_char) + '–' + count(hit.end_char)));
    if (hit.citation_id) metadata.append(el('code', hit.citation_id));
    content.append(metadata);
    const openSource = button(action ? '在原文中定位' : '查看原文位置', action || (() => openDocument(hit.document_id, hit, 'search')));
    openSource.disabled = !hit.document_id; content.append(openSource); card.append(summary, content); return card;
  }
  function renderSearch() {
    const target = $('knowledge-results'); target.replaceChildren();
    if (!lastSearch) return;
    const candidates = searchCandidates(), references = lastSearch.references || [];
    const summary = el('div', undefined, 'k-result-summary');
    summary.append(el('strong', count(candidates.length) + ' 个返回候选'), el('span', '/'),
      el('span', count(references.length) + ' 个通过筛选'), el('span', '/'),
      el('span', numeric(lastSearch.duration_ms) ? count(lastSearch.duration_ms) + ' ms' : '耗时未提供'));
    target.append(summary);
    if (!candidates.length) {
      empty(target, '暂时没有找到相关片段', lastSearch.status === 'empty'
        ? '先添加资料并建立索引，再来测试。' : '检查资料是否有索引，或换一种问法。没有命中，不代表资料中一定没有答案。'); return;
    }
    if (!references.length) target.append(el('p', '候选没有通过当前后端的筛选策略。下面仍可查看候选，但不将其标记为可用证据。', 'k-caption'));
    const grid = el('div', undefined, 'k-comparison');
    const haveFusionScores = candidates.every(item => numeric(item.rrf_score));
    const fused = haveFusionScores ? [...candidates].sort((a, b) => b.rrf_score - a.rrf_score || String(a.citation_id).localeCompare(String(b.citation_id))) : [];
    for (const [title, description, rows, before] of [['融合召回', '语义 + 关键词 / RRF', fused, true], ['重排结果', '后端返回顺序', candidates, false]]) {
      const column = el('section'), heading = el('header', undefined, 'k-comparison-heading');
      heading.append(el('h3', title), el('span', description)); column.append(heading);
      if (!rows.length) column.append(el('p', '接口未返回融合分数，无法还原重排前顺序。', 'k-caption'));
      rows.forEach((hit, i) => column.append(hitCard(hit, i + 1, before))); grid.append(column);
    }
    target.append(grid, el('p', '两列比较的是本次接口返回的同一组候选，不代表召回全集。相关性分数不是事实正确率，不同模型的分数不能直接比较。', 'k-caption'));
    const details = el('details', undefined, 'k-model-record'); details.append(el('summary', '本次检索的模型与策略'));
    const fields = el('dl');
    for (const [name, value] of [['Embedding', modelName(lastSearch.embedding_key)], ['Reranker', modelName(lastSearch.reranker)], ['筛选阈值', score(lastSearch.threshold)], ['查询 Token', numeric(lastSearch.rerank_query_tokens_used) ? count(lastSearch.rerank_query_tokens_used) + ' / ' + count(lastSearch.rerank_query_tokens_total) : '接口未提供']]) fields.append(el('dt', name), el('dd', value));
    details.append(fields); target.append(details);
  }
  $('knowledge-search-form').addEventListener('submit', async event => {
    event.preventDefault(); const query = $('knowledge-query').value.trim();
    if (!query || searching) return;
    searching = true; const ticket = ++searchEpoch, turn = epoch;
    $('knowledge-search').disabled = true; $('knowledge-results').setAttribute('aria-busy', 'true');
    lastSearch = null; $('knowledge-results').replaceChildren();
    message('knowledge-search-status', '正在检索并重排，等待后端返回真实候选…');
    try {
      const result = await api('/api/knowledge/search', {method: 'POST', body: {query}});
      if (ticket !== searchEpoch || turn !== epoch || view.hidden) return;
      if (!Array.isArray(result.references)) throw new Error('检索接口没有返回有效的证据列表。');
      lastSearch = result; renderSearch();
      message('knowledge-search-status', '检索完成。展开候选可查看完整片段；点击原文位置可核对出处。');
    } catch (error) {
      if (ticket !== searchEpoch || turn !== epoch || view.hidden) return;
      message('knowledge-search-status', error.message, true);
    } finally {
      if (ticket === searchEpoch) {
        searching = false; $('knowledge-search').disabled = false;
        $('knowledge-results').setAttribute('aria-busy', 'false');
      }
    }
  });


  const pdfLabels = {awaiting_upload:'等待上传',receiving:'正在上传',submitting:'提交解析',
    queued:'等待 GPU',parsing:'GPU 解析中',fetching:'获取解析结果',parsed:'待预览确认',
    indexing:'正在建立索引',indexed:'已入库',failed:'处理失败',submission_unknown:'提交状态待确认'};
  const pdfActive = new Set(['receiving','submitting','queued','parsing','fetching','indexing']);
  let pdfFile = null, pdfUploadJob = null, pdfJobs = [], pdfTimer = null, pdfTicket = 0;

  function resetPdfSelection() {
    pdfFile = null; pdfUploadJob = null;
    $('knowledge-text').disabled = false; $('knowledge-text').required = true;
    $('knowledge-pdf-selection').hidden = true;
    $('knowledge-save').textContent = '保存并建立索引';
  }
  function artifactLink(job, kind, label) {
    const link = el('a', label, 'k-button');
    link.href = '/api/knowledge/pdf/jobs/' + encodeURIComponent(job.id) + '/artifacts/' + kind;
    link.setAttribute('download', ''); return link;
  }
  function renderPdfJobs() {
    const target = $('knowledge-pdf-jobs');
    target.replaceChildren();
    $('knowledge-pdf-count').textContent = pdfJobs.length ? count(pdfJobs.length) + ' 项' : '还没有导入任务';
    for (const job of pdfJobs) {
      const row = el('article', undefined, 'k-pdf-job');
      const title = el('div', undefined, 'k-pdf-job-title');
      title.append(el('strong', job.title), el('span', job.filename + ' · ' + count(Math.ceil(job.bytes / 1024)) + ' KB', 'k-caption'));
      const status = el('div', undefined, 'k-pdf-job-status');
      status.append(tag(pdfLabels[job.state] || job.state, job.state === 'indexed'));
      if (job.pages !== null && job.pages !== undefined) status.append(el('span', count(job.pages) + ' 页', 'k-caption'));
      const actions = el('div', undefined, 'k-pdf-job-actions');
      if ((job.artifacts || []).includes('markdown')) actions.append(button('预览解析结果', () => openPdfPreview(job.id)));
      if (job.state === 'indexed' && job.index?.id) actions.append(button('打开入库资料', () => openDocument(job.index.id), 'k-primary'));
      if ((job.artifacts || []).includes('original')) actions.append(artifactLink(job, 'original', '原 PDF'));
      row.append(title, status, actions);
      if (job.error) row.append(el('p', job.error, 'k-pdf-job-error'));
      target.append(row);
    }
    if (!pdfJobs.length) target.append(el('p', '上传 PDF 后，任务会保留在这里。解析在独立 GPU 服务上运行，离开页面不停止已提交的任务。', 'k-caption'));
  }
  async function refreshPdfJobs() {
    if (view.hidden) return;
    clearTimeout(pdfTimer);
    const turn = epoch, ticket = ++pdfTicket;
    try {
      const result = await api('/api/knowledge/pdf/jobs');
      if (turn !== epoch || ticket !== pdfTicket || view.hidden) return;
      if (!Array.isArray(result.jobs)) throw new Error('无法读取 PDF 导入任务。');
      const rows = result.jobs;
      for (const job of rows.filter(item => ['queued','parsing','fetching'].includes(item.state)).slice(0,5)) {
        const updated = await api('/api/knowledge/pdf/jobs/' + encodeURIComponent(job.id));
        Object.assign(job, updated);
        if (turn !== epoch || ticket !== pdfTicket || view.hidden) return;
      }
      pdfJobs = rows; renderPdfJobs();
      $('knowledge-parser-state').textContent = result.service?.enabled
        ? 'PDF · 5060 Ti 私有解析 / 原文与结果分别保留'
        : 'PDF 私有连接尚未配置；文本与 Markdown 入口仍可用';
      if (pdfJobs.some(job => pdfActive.has(job.state))) pdfTimer = setTimeout(refreshPdfJobs, 4000);
    } catch (error) {
      if (turn === epoch && ticket === pdfTicket && !view.hidden) $('knowledge-parser-state').textContent = '无法同步解析任务：' + error.message;
    }
  }
  async function openPdfPreview(id) {
    const turn = epoch, ticket = ++detailEpoch;
    selectTab('detail');
    empty($('knowledge-detail'), '正在读取解析结果', '保留原 PDF；解析文本尚不等于已通过人工核对。');
    try {
      const result = await api('/api/knowledge/pdf/jobs/' + encodeURIComponent(id) + '/preview');
      if (turn !== epoch || ticket !== detailEpoch || view.hidden) return;
      const job = result.job, target = $('knowledge-detail');
      target.replaceChildren();
      const heading = el('header', undefined, 'k-detail-heading'), name = el('div');
      name.append(el('p', 'PDF / PARSED SOURCE', 'k-eyebrow'), el('h2', job.title), el('p', job.filename, 'k-caption'));
      heading.append(name, button('返回文献库', () => selectTab('library', true)));
      const path = el('ol', undefined, 'k-pdf-path');
      for (const label of ['上传原文','GPU 解析','预览确认','分块与索引']) path.append(el('li', label));
      const facts = el('div', undefined, 'k-detail-stats');
      facts.append(tag(pdfLabels[job.state] || job.state), tag(count(job.pages) + ' 页'), tag(count(result.total_characters) + ' 字符'));
      const downloads = el('div', undefined, 'k-pdf-downloads');
      for (const [kind,label] of [['original','原 PDF'],['markdown','完整 Markdown'],['middle_json','版面 JSON'],['structured_content','结构化 JSON'],['zip','解析文件包']])
        if ((job.artifacts || []).includes(kind)) downloads.append(artifactLink(job,kind,label));
      const note = el('p', result.preview_truncated
        ? '当前仅预览前 120,000 字符，完整解析文本已保留在下载文件中。超出当前入库限制，不会截断后入库。'
        : '请核对多栏阅读顺序、公式、表格和图注。这里显示解析器的 Markdown 原文，不将其改写成摘要。', 'k-caption');
      const reader = el('section',undefined,'k-reader');
      reader.append(el('div','解析 Markdown · 只读','k-pane-heading'),el('pre',result.text,'k-original'));
      const record = el('details',undefined,'k-model-record');
      record.append(el('summary','解析与来源记录'));
      const fields = el('dl');
      for (const [key,value] of [['原 PDF SHA256',job.sha256],['解析正文 SHA256',job.text_sha256],
        ['解析模型',job.parser?.model_used],['解析版本',job.parser?.parser_version],['来源',job.source]])
        fields.append(el('dt',key),el('dd',modelName(value)));
      record.append(fields);
      const status = el('p',job.error || job.index_note || '', 'k-caption'); status.setAttribute('role','status');
      const actions = el('div',undefined,'k-pdf-confirm');
      actions.append(el('p','确认后使用当前知识后端分块、Embedding 入库。Rerank 发生在查询阶段，不在上传时运行；不会自动切换到另一套模型。','k-caption'));
      if (job.state === 'indexed' && job.index?.id) {
        actions.append(button('查看已入库资料',()=>openDocument(job.index.id),'k-primary'));
      } else {
        const confirm = button('已核对，确认入库', async () => {
          confirm.disabled = true; status.textContent = '正在分块并建立索引，原始解析结果会保留…';
          try {
            const saved = await api('/api/knowledge/pdf/jobs/' + encodeURIComponent(id) + '/ingest', {method:'POST',body:{confirmed:true}});
            if (turn !== epoch || ticket !== detailEpoch || view.hidden) return;
            status.textContent = saved.state === 'indexed' ? '已建立 ' + count(saved.index.chunks) + ' 个索引片段。请到检索试验验证。' : (saved.error || '尚未完成入库。');
            await refresh(); await refreshPdfJobs();
            if (saved.state === 'indexed') await openPdfPreview(id);
          } catch (error) {
            if (turn === epoch && ticket === detailEpoch && !view.hidden) status.textContent = error.message + ' 请先刷新导入任务，确认状态再重试。';
          } finally { if (confirm.isConnected) confirm.disabled = false; }
        },'k-primary');
        confirm.disabled = !job.can_index || job.state !== 'parsed';
        actions.append(confirm);
      }
      target.append(heading,path,facts,downloads,note,reader,record,status,actions);
    } catch (error) {
      if (turn === epoch && ticket === detailEpoch && !view.hidden) empty($('knowledge-detail'),'无法读取解析结果',error.message);
    }
  }
  async function submitPdf(title, source) {
    const turn = epoch;
    importing = true; importLock(true);
    message('knowledge-import-status','正在保存 PDF 原文件。请等待提交完成，之后可以关闭页面。');
    try {
      let job = pdfUploadJob;
      if (job) {
        const recorded = await api('/api/knowledge/pdf/jobs/' + encodeURIComponent(job.id));
        if (recorded.state !== 'awaiting_upload') {
          message('knowledge-import-status','已有导入记录：' + (pdfLabels[recorded.state] || recorded.state) + '。请在导入任务中查看，不会重复提交。');
          await refreshPdfJobs(); return;
        }
      } else {
        job = await api('/api/knowledge/pdf/jobs',{method:'POST',body:{filename:pdfFile.name,bytes:pdfFile.size,title,source}});
        pdfUploadJob = job;
      }
      const response = await fetch('/api/knowledge/pdf/jobs/' + encodeURIComponent(job.id) + '/file',{
        method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/pdf','X-PDF-Upload-Token':job.upload_token},body:pdfFile});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'PDF 上传未完成');
      if (turn !== epoch || view.hidden) return;
      resetPdfSelection(); $('knowledge-form').reset(); textCount();
      $('knowledge-file-label').textContent = 'PDF · 最多 50 MiB / UTF-8 文本与 Markdown · 最多 240 KB';
      importer.close(); selectTab('library');
      message('knowledge-status',result.state === 'submission_unknown' ? result.error : 'PDF 已提交，真实处理状态见导入任务。解析完成后请预览并确认入库。',result.state === 'submission_unknown');
      await refreshPdfJobs();
      $('knowledge-pdf-queue').open = true;
    } catch (error) {
      message('knowledge-import-status',error.message + ' 若网络中断，请先查看导入任务；不要重复上传。',true);
      await refreshPdfJobs();
    } finally { importing = false; importLock(false); $('knowledge-text').disabled = Boolean(pdfFile); }
  }

  function openImport() { importer.showModal(); message('knowledge-import-status', ''); }
  function closeImport() { if (!importing && !reading) importer.close(); }
  function textCount() { $('knowledge-text-count').textContent = count(Array.from($('knowledge-text').value).length) + ' / 120,000 字符'; }
  function importLock(locked) {
    for (const id of ['knowledge-save', 'knowledge-file', 'knowledge-title', 'knowledge-source', 'knowledge-text', 'knowledge-drop', 'knowledge-import-close', 'knowledge-import-cancel']) $(id).disabled = locked;
  }
  async function readFile(file) {
    if (!file || importing || reading) return;
    if (/\.pdf$/i.test(file.name)) {
      if (!catalog?.pdf_service?.enabled) { message('knowledge-import-status','PDF 私有连接尚未配置，暂时不能提交解析。',true); return; }
      if (!file.size || file.size > (catalog.pdf_service.max_bytes || 52428800)) { message('knowledge-import-status','PDF 必须大于 0 字节且不超过 50 MiB。',true); return; }
      pdfFile = file; pdfUploadJob = null;
      $('knowledge-title').value = file.name.slice(0,160);
      $('knowledge-file-label').textContent = file.name + ' · ' + count(Math.ceil(file.size / 1024)) + ' KB';
      $('knowledge-text').value = ''; $('knowledge-text').disabled = true; $('knowledge-text').required = false;
      $('knowledge-pdf-selection').hidden = false; $('knowledge-save').textContent = '上传并解析 PDF';
      $('knowledge-file').value = ''; textCount();
      message('knowledge-import-status','已选择 PDF，尚未上传。提交后先解析和预览，不会自动入库。'); return;
    }
    resetPdfSelection();
    if (!/\.(txt|md|markdown)$/i.test(file.name)) { message('knowledge-import-status', '请选择 PDF、UTF-8 文本或 Markdown 文件。', true); return; }
    if (file.size > 240000) { message('knowledge-import-status', '文本文件超过当前入口的 240 KB 限制。', true); return; }
    reading = true; const ticket = ++fileEpoch; importLock(true);
    try {
      const text = new TextDecoder('utf-8', {fatal: true}).decode(await file.arrayBuffer());
      if (ticket !== fileEpoch) return;
      if (text.includes('\x00') || Array.from(text).length > 120000) throw new Error('正文包含无效字符，或超过 120,000 字符。');
      $('knowledge-title').value = file.name.slice(0, 160); $('knowledge-text').value = text;
      $('knowledge-file-label').textContent = file.name + ' · ' + count(file.size) + ' bytes';
      textCount(); message('knowledge-import-status', '文件已读入，确认来源和正文后再保存。尚未上传或建立索引。');
    } catch (error) { message('knowledge-import-status', error instanceof TypeError ? '无法按 UTF-8 读取文件，请检查文件编码。' : error.message, true); }
    finally { reading = false; importLock(false); $('knowledge-file').value = ''; }
  }
  $('knowledge-form').addEventListener('submit', async event => {
    event.preventDefault(); if (importing || reading) return;
    const title = $('knowledge-title').value.trim(), text = $('knowledge-text').value;
    if (pdfFile) {
      if (!title) { message('knowledge-import-status','请填写资料标题。',true); return; }
      await submitPdf(title, $('knowledge-source').value.trim()); return;
    }
    if (!title || !text.trim()) { message('knowledge-import-status', '请填写标题和非空正文。', true); return; }
    if (text.includes('\x00') || Array.from(text).length > 120000) { message('knowledge-import-status', '正文包含无效字符，或超过 120,000 字符。', true); return; }
    importing = true; importLock(true);
    message('knowledge-import-status', '已提交给当前知识后端，等待分块和索引结果。后端未提供分阶段进度，不显示模拟百分比。');
    try {
      const result = await api('/api/knowledge', {method: 'POST', body: {title, text, source: $('knowledge-source').value.trim() || '用户上传资料'}});
      await refresh();
      if (result.reused && result.chunks === 0) {
        message('knowledge-import-status', '已存在同样的原文，但当前没有索引片段。后端未提供重建接口，本次不标记为索引完成。', true); return;
      }
      $('knowledge-form').reset(); $('knowledge-file-label').textContent = 'PDF · 最多 50 MiB / UTF-8 文本与 Markdown · 最多 240 KB'; textCount();
      importer.close(); selectTab('library');
      message('knowledge-status', result.reused ? '后端已复用同标题、同内容的资料。请检查索引数量，并到检索试验验证。' : '后端已返回保存结果。请检查索引数量，并到检索试验验证。');
    } catch (error) { message('knowledge-import-status', error.message + ' 若请求中断，请先刷新文献库，确认是否已入库再重试。', true); }
    finally { importing = false; importLock(false); }
  });

  $('knowledge-open').setAttribute('aria-pressed', 'false');
  $('knowledge-open').addEventListener('click', open);
  $('knowledge-close').addEventListener('click', () => close());
  $('knowledge-menu').addEventListener('click', () => $('menu-button').click());
  for (const id of ['library-open', 'new-chat', 'conversation-list', 'logout']) $(id).addEventListener('click', () => close(false), {capture: true});
  $('knowledge-refresh').addEventListener('click', () => { refresh(); refreshPdfJobs(); });
  $('knowledge-add').addEventListener('click', openImport);
  $('knowledge-browse').addEventListener('click', () => selectTab('library', true));
  $('knowledge-filter').addEventListener('input', renderCatalog);
  $('knowledge-filter-state').addEventListener('change', renderCatalog);
  for (const [i, name] of tabs.entries()) {
    const tab = $('knowledge-tab-' + name);
    tab.addEventListener('click', () => selectTab(name));
    tab.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (i + 1) % tabs.length : event.key === 'ArrowLeft' ? (i + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next !== null) { event.preventDefault(); selectTab(tabs[next], true); }
    });
  }
  for (const id of ['knowledge-import-close', 'knowledge-import-cancel']) $(id).addEventListener('click', closeImport);
  importer.addEventListener('cancel', event => { if (importing || reading) event.preventDefault(); });
  importer.addEventListener('close', () => { fileEpoch++; $('knowledge-add').focus(); });
  $('knowledge-drop').addEventListener('click', () => $('knowledge-file').click());
  $('knowledge-file').addEventListener('change', event => readFile(event.target.files[0]));
  $('knowledge-text').addEventListener('input', textCount);
  for (const name of ['dragenter', 'dragover']) $('knowledge-drop').addEventListener(name, event => {
    event.preventDefault(); if (!importing && !reading) $('knowledge-drop').classList.add('is-dragging');
  });
  $('knowledge-drop').addEventListener('dragleave', () => $('knowledge-drop').classList.remove('is-dragging'));
  $('knowledge-drop').addEventListener('drop', event => {
    event.preventDefault(); $('knowledge-drop').classList.remove('is-dragging');
    if (event.dataTransfer.files.length !== 1) { message('knowledge-import-status', '当前入口每次接收一份资料，请逐份添加。', true); return; }
    readFile(event.dataTransfer.files[0]);
  });
})();

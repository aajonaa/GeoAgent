'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const view = $('knowledge-view'), main = $('messages').closest('.main');
  const importer = $('knowledge-import');
  main.append(view);
  const tabs = ['library', 'corpus', 'graph', 'detail', 'search'];
  const numbers = new Intl.NumberFormat('zh-CN');
  let epoch = 0, catalogEpoch = 0, detailEpoch = 0, searchEpoch = 0, fileEpoch = 0;
  let catalog = null, catalogError = '', currentDoc = null, lastSearch = null;
  let detailOrigin = 'library', importing = false, reading = false, searching = false, deleting = false;
  let organizationTimer = null;


  let readerGeneration = 0, disposeReader = null, disposeContent = null;
  function stopPdfReader() {
    readerGeneration++;
    if (disposeReader) disposeReader();
    if (disposeContent) disposeContent();
    disposeReader = null; disposeContent = null;
  }

  function richPdfContent(source, text, textSha) {
    const panel = el('section', undefined, 'k-rich-document');
    panel.append(el('p', '正在读取图文…', 'k-caption'));
    const ticket = readerGeneration;
    import('/api/knowledge/pdf/reader-assets/content.mjs').then(module => {
      if (ticket !== readerGeneration || !panel.isConnected || view.hidden) return;
      disposeContent = module.mountContent(panel, source, {text, textSha,
        onPage: page => disposeReader?.goToPage?.(page)});
    }).catch(() => { if (panel.isConnected) panel.replaceChildren(el('p', '排版阅读未能载入，整理后 Markdown 和原文件仍可查看。', 'k-caption')); });
    return panel;
  }

  function pdfComparison(source, sections, options = {}) {
    const layout = el('div', undefined, 'k-pdf-comparison');
    const host = el('section', undefined, 'k-pdf-reader');
    host.append(el('p', '正在准备 PDF 原文阅读器…', 'k-caption'));
    const aside = el('div', undefined, 'k-pdf-comparison-text');
    const controls = el('div', undefined, 'k-reader-switch');
    const panels = [];
    sections.forEach(([label, content], index) => {
      const panel = el('div', undefined, 'k-reader-tab-content'); panel.hidden = index !== 0; panel.append(content);
      const tab = button(label, () => {
        panels.forEach((entry, i) => { entry.panel.hidden = i !== index; entry.tab.setAttribute('aria-pressed', String(i === index)); });
      });
      tab.setAttribute('aria-pressed', String(index === 0)); panels.push({panel, tab}); controls.append(tab);
    });
    if (sections.length > 1) aside.append(controls);
    panels.forEach(entry => aside.append(entry.panel)); layout.append(host, aside);
    const ticket = readerGeneration;
    import('/api/knowledge/pdf/reader-assets/reader.mjs').then(module => {
      if (ticket !== readerGeneration || !host.isConnected || view.hidden) return;
      disposeReader = module.mountReader(host, source, options);
    }).catch(() => {
      if (ticket !== readerGeneration || !host.isConnected) return;
      host.replaceChildren(el('p', 'PDF 阅读器未能载入，原文件仍可下载。', 'k-caption'), artifactLink(source, 'original', '下载原 PDF'));
    });
    return layout;
  }

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
  /* page-coverage:start */
  function sourceCoverage(value) {
    const coverage = value?.coverage || value?.index?.coverage || value?.metadata?.source_coverage ||
      value?.chunks_detail?.find(piece => piece.metadata?.source_coverage)?.metadata.source_coverage;
    return coverage?.status === 'partial' ? coverage : null;
  }
  function coverageSummary(coverage) {
    return '部分入库 ' + count(coverage.included_section_pages.length) + ' / ' + count(coverage.source_pages) +
      ' 页；原 PDF 第 ' + coverage.excluded_original_pdf_pages.join('、') + ' 页待复核，文字未进入检索。';
  }
  /* page-coverage:end */
  function coverageNotice(coverage) {
    const note = el('section', undefined, 'k-evidence-panel'); note.setAttribute('role', 'status');
    const body = el('div', undefined, 'k-evidence-body');
    body.append(el('strong', '部分入库 · 原文完整保留'), el('p', coverageSummary(coverage), 'k-caption'),
      el('p', '成功页沿用原有正文、表格和来源检查；问题页仅保留原图，不代表整段已解析或审核完成。', 'k-caption'));
    if (/^[a-f0-9]{32}$/.test(coverage.job_id || '')) body.append(button('查看原 PDF 与待复核页', () => openPdfPreview(coverage.job_id)));
    note.append(body); return note;
  }
  function docState(doc) { return sourceCoverage(doc) ? '部分入库' : numeric(doc.chunks) ? (doc.chunks > 0 ? '有索引' : '无索引') : '状态未提供'; }
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
    stopPdfReader(); currentDoc = null;
    clearTimeout(organizationTimer);
    empty($('knowledge-detail'), '请选择资料', '从文献库打开资料，查看原文与索引。');
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
      for (const doc of data.documents) {
        const coverage = data.organization?.documents?.[doc.id]?.coverage;
        if (coverage) doc.coverage = coverage;
      }
      $('knowledge-file').accept = data.pdf_service?.enabled ? '.pdf,.txt,.md,.markdown' : '.txt,.md,.markdown';
      if ($('knowledge-panel-corpus')) {
        document.dispatchEvent(new CustomEvent('geoagent:knowledge-catalog-updated'));
      } else {
        $('knowledge-count').textContent = count(data.documents.length);
        $('knowledge-indexed-count').textContent = data.documents.every(d => numeric(d.chunks))
          ? count(data.documents.filter(d => d.chunks > 0).length) : '未提供';
        $('knowledge-chunk-count').textContent = data.documents.every(d => numeric(d.chunks))
          ? count(data.documents.reduce((sum, d) => sum + d.chunks, 0)) : '未提供';
      }
      renderCatalog();
      clearTimeout(organizationTimer);
      if (data.organization?.batches?.some(batch => batch.state === 'processing')) {
        organizationTimer = setTimeout(() => { if (!view.hidden) refresh(); }, 15000);
      }
      message('knowledge-status', data.retrieval_profile
        ? '已配置 Qwen3-Embedding-0.6B · ' + count(data.retrieval_profile.dimensions) + ' 维 / Qwen3-Reranker-0.6B。旧资料未自动重建索引。'
        : '已同步资料与索引数量，模型配置未由接口提供。');
    } catch (error) {
      if (turn !== epoch || ticket !== catalogEpoch || view.hidden) return;
      catalog = null; catalogError = error.message;
      if (!$('knowledge-panel-corpus')) for (const id of ['knowledge-count', 'knowledge-indexed-count', 'knowledge-chunk-count']) $(id).textContent = '未读取';
      renderCatalog(); message('knowledge-status', error.message, true);
    } finally {
      if (ticket === catalogEpoch) {
        $('knowledge-documents').setAttribute('aria-busy', 'false');
        $('knowledge-refresh').disabled = false;
      }
    }
  }
  function resetOrganizationFilters() {
    for (const key of ['groups','deposits','topics']) $('knowledge-facet-' + key).value = '';
  }
  function matchesOrganization(metadata, filters) {
    return ['groups', 'deposits', 'topics'].every(key => {
      const selected = filters[key] || '', values = metadata?.[key] || [];
      return !selected || (selected === '__unclassified__' ? values.length === 0 : values.includes(selected));
    });
  }
  function organizationControls() {
    let root = $('knowledge-organization');
    if (!root) {
      root = el('section', undefined, 'k-organization'); root.id = 'knowledge-organization';
      const summary = el('div'); summary.id = 'knowledge-batch-progress'; summary.setAttribute('aria-live', 'polite');
      const controls = el('div', undefined, 'k-facet-controls');
      for (const [key, label] of [['groups','原始分组'], ['deposits','矿床／矿区'], ['topics','研究主题']]) {
        const wrap = el('label', undefined, 'k-facet'); wrap.append(el('span', label));
        const select = el('select'); select.id = 'knowledge-facet-' + key;
        select.setAttribute('aria-label', label); select.addEventListener('change', renderCatalog);
        wrap.append(select); controls.append(wrap);
      }
      const clear = button('重置分类', () => {
        resetOrganizationFilters();
        renderCatalog();
      }); controls.append(clear); root.append(summary, controls,
        el('p', '保留原始相关性分组；矿床和主题依据解析正文自动整理，不代表地质结论已被核实。', 'k-caption'));
      $('knowledge-panel-library').querySelector('.k-list-head').before(root);
    }
    const organization = catalog?.organization || {}, progress = $('knowledge-batch-progress');
    progress.replaceChildren();
    for (const batch of organization.batches || []) {
      const card = el('div', undefined, 'k-batch-card');
      card.append(el('strong', batch.label || '文献导入'),
        el('p', batch.original_volumes ? count(batch.original_volumes) + ' 本原书 · ' + count(batch.original_pdf_pages) + ' 页 · ' + count(batch.total) + ' 个页段' : count(batch.original_files) + ' 个 PDF · 去重后 ' + count(batch.total) + ' 篇 · ' + count(batch.duplicate_copies) + ' 个重复副本'));
      const meter = el('progress'); meter.max = batch.total || 1; meter.value = batch.indexed || 0;
      meter.setAttribute('aria-label', batch.original_volumes ? '完整入库的页段，不包含部分入库页段' : '已完成索引的独立文献'); card.append(meter,
        el('p', '完整解析 ' + count(batch.parsed) + ' · 完整入库 ' + count(batch.indexed) + ' · 部分入库 ' + count(batch.partially_indexed || 0) + ' · 待处理／复核 ' + count((batch.failed || 0) + (batch.blocked || 0)) + (batch.pending_pages ? ' · 待复核页 ' + count(batch.pending_pages) : '')));
      if (batch.queue_note) card.append(el('small', batch.queue_note, 'k-caption'));
      if (batch.incomplete_files) card.append(el('small', count(batch.incomplete_files) + ' 个未完成下载文件保留在待补清单'));
      progress.append(card);
    }
    const filters = {};
    for (const key of ['groups','deposits','topics']) {
      const select = $('knowledge-facet-' + key), previous = select.value;
      select.replaceChildren();
      for (const value of ['', ...(organization.facets?.[key] || []), '__unclassified__']) {
        const option = el('option', value === '' ? '全部' : value === '__unclassified__' ? '未分类' : value);
        option.value = value; select.append(option);
      }
      select.value = [...select.options].some(option => option.value === previous) ? previous : '';
      filters[key] = select.value;
    }
    return filters;
  }
  function renderCatalog() {
    const target = $('knowledge-documents');
    const facets = organizationControls();
    if (!catalog) {
      $('knowledge-match-count').textContent = '';
      empty(target, '暂时无法读取文献库', catalogError || '请重新连接知识服务。', button('重试', refresh)); return;
    }
    const query = $('knowledge-filter').value.toLocaleLowerCase().trim(), filter = $('knowledge-filter-state').value;
    const rows = catalog.documents.filter(doc =>
      (!query || (String(doc.title || '') + ' ' + String(doc.source || '')).toLocaleLowerCase().includes(query)) &&
      (filter === 'all' || (filter === 'indexed' ? numeric(doc.chunks) && doc.chunks > 0 : doc.chunks === 0)) &&
      matchesOrganization(catalog.organization?.documents?.[doc.id], facets));
    target.replaceChildren();
    $('knowledge-match-count').textContent = count(rows.length) + ' / ' + count(catalog.documents.length) + ' 份资料';
    if (!rows.length) {
      empty(target, catalog.documents.length ? '没有匹配的资料' : '从第一份可信资料开始',
        catalog.documents.length ? '试试其他标题、来源或索引状态。' : '原文会保留在文献库中。建立索引后，可以去检索试验检查召回。',
        catalog.documents.length ? button('清除筛选', () => {
          $('knowledge-filter').value = ''; $('knowledge-filter-state').value = 'all'; resetOrganizationFilters(); renderCatalog();
        }) : button('添加文献', openImport, 'k-primary'));
      return;
    }
    for (const doc of rows) {
      const row = el('button', undefined, 'k-document-row'); row.type = 'button';
      const head = el('span', undefined, 'k-document-main'), file = el('span', undefined, 'k-document-icon');
      file.append(icon('document'));
      const title = el('span', undefined, 'k-document-title');
      title.append(el('strong', doc.title || '未命名资料'), el('small', doc.source || '未提供来源'));
      const metadata = catalog.organization?.documents?.[doc.id];
      if (metadata) {
        const labels = el('span', undefined, 'k-document-labels');
        for (const value of [...(metadata.groups || []), ...(metadata.deposits || []), ...(metadata.topics || [])]) labels.append(tag(value));
        if (metadata.aliases?.length > 1) labels.append(tag(metadata.aliases.length + ' 个同源文件'));
        title.append(labels);
      }
      head.append(file, title); row.title = (doc.title || '') + '\n' + (doc.source || '');
      const arrow = el('span', undefined, 'k-document-arrow'); arrow.append(icon('arrow'));
      row.append(head, tag(docState(doc), doc.chunks > 0 && !sourceCoverage(doc)), el('span', count(doc.chunks), 'k-number'),
        el('span', date(doc.created_at), 'k-number k-date'), arrow);
      row.addEventListener('click', () => openDocument(doc.id)); target.append(row);
    }
  }

  function literaturePanel(job) {
    const panel = el('section', undefined, 'k-evidence-panel');
    const heading = el('div', undefined, 'k-pane-heading');
    heading.append(el('strong', '结构化文献'), el('span', '原文 / 内容块 / 向量化输入'));
    const content = el('div', undefined, 'k-evidence-body');
    content.append(el('p', '正在读取结构和真实分块，不调用模型…', 'k-caption'));
    panel.append(heading, content);
    const turn = epoch, ticket = detailEpoch;
    api('/api/knowledge/pdf/jobs/' + encodeURIComponent(job.id) + '/literature').then(data => {
      if (turn !== epoch || ticket !== detailEpoch || view.hidden) return;
      content.replaceChildren();
      if (data.coverage) content.append(coverageNotice(data.coverage));
      const doc = data.document, stats = el('div', undefined, 'k-detail-stats');
      stats.append(tag(count(doc.blocks.length) + ' 个内容块'), tag(count(data.chunks.length) + ' 个候选分块'),
        tag(data.can_index ? '待人工核对' : '质量检查受阻', false));
      content.append(stats, el('p', '按解析器提供的阅读顺序组织；没有把自动解析当作已核实原文。图示转写、页眉页脚和参考文献保留，但不进入本版正文索引。', 'k-caption'));
      const issues = el('details', undefined, 'k-model-record');
      issues.append(el('summary', '质量检查与排除规则 (' + count(doc.issues.length) + ')'));
      const labels = {human_reading_order_and_numeric_review_required:'请核对多栏顺序、数字、单位与公式',
        merged_table_cells:'已按真实合并关系展开检索行，请核对原表',ambiguous_formula:'公式存在不明确的数字间距或括号，保留原样，需人工核对',ambiguous_caption_reference:'图表编号重复，未自动指定归属',table_header_unidentified:'表头未被可靠识别，首行仅作为上下文保留',
        unsupported_block_type:'存在尚未支持的内容块',empty_page:'页面未提取到内容',chunk_contract:'分块无法满足保真和长度要求'};
      for (const issue of doc.issues) issues.append(el('p', (issue.block_id ? issue.block_id + ' · ' : '') + (issue.message || labels[issue.code] || issue.code), 'k-caption'));
      content.append(issues);
      const controls = el('div', undefined, 'k-reader-switch');
      const blocks = el('div'), pieces = el('div'); pieces.hidden = true;
      const show = (isChunks) => { blocks.hidden = isChunks; pieces.hidden = !isChunks;
        b1.setAttribute('aria-pressed', String(!isChunks)); b2.setAttribute('aria-pressed', String(isChunks)); };
      const b1 = button('内容结构', () => show(false)); b1.setAttribute('aria-pressed','true');
      const b2 = button('分块与 Embedding 输入', () => show(true)); b2.setAttribute('aria-pressed','false');
      controls.append(b1,b2); content.append(controls);
      const names = {text:'正文',paragraph:'段落',paragraph_title:'章节标题',doc_title:'文献标题',table:'表格',image:'图片',figure:'图片',chart:'图表',
        header:'页眉',footer:'页脚',ref_text:'参考文献',page_number:'页码',page_footnote:'脚注',equation:'公式',list:'列表'};
      for (const block of doc.blocks) {
        const item = el('details',undefined,'k-hit'), summary = el('summary');
        summary.append(el('span', 'P' + block.source.page, 'k-hit-rank'), el('strong', names[block.kind] || block.kind),
          el('span', !block.indexable ? '保留但不索引' : !data.can_index ? '索引受阻' : ['image','figure','chart'].includes(block.kind) ? '仅图注／注释可索引' : '可用于正文索引','k-caption'));
        const detail = el('div',undefined,'k-hit-content');
        detail.append(el('p', '物理位置：' + block.section_path.join(' / '),'k-caption'),el('pre',block.text || '没有提取文本；请查看原 PDF。','k-original'));
        if (block.references_from?.length) {
          const refs = el('div',undefined,'k-model-record'); refs.append(el('strong','正文引用位置（不改写章节归属）'));
          for (const ref of block.references_from) {
            refs.append(el('p', ref.section_path.join(' / ') + ' · P' + ref.source.page + ' · ' + ref.context,'k-caption'),
              button('查看引用页 ' + ref.source.page,()=>disposeReader?.goToPage?.(ref.source.page)));
          }
          detail.append(refs);
        }
        if (block.retrieval_transformations?.length) {
          const derived = el('details',undefined,'k-model-record');
          derived.append(el('summary','检索规范化视图（原文不变）'), el('pre',block.retrieval_text,'k-original'));
          for (const edit of block.retrieval_transformations) {
            derived.append(el('p',edit.rule === 'explicit_table_spans' ? '依据原表 rowspan / colspan 展开，空白单元格不猜填。' : '仅规范公式中的明确空白，不推断数字。','k-caption'),
              el('pre',edit.raw + '\n→\n' + edit.text,'k-original'));
          }
          detail.append(derived);
        }
        if (block.source.bbox) detail.append(el('p','解析器坐标：' + block.source.bbox.join(', ') + ' · ' + block.source.coordinate_space,'k-caption'));
        if (block.derived_description) {
          const derived = el('details'); derived.append(el('summary',block.kind === 'chart' ? '图表自动转写（非原文，不入正文索引）' : '解析器生成的描述（非原文，不入正文索引）'),el('pre',block.derived_description,'k-original')); detail.append(derived);
        }
        detail.append(button('查看 PDF 第 ' + block.source.page + ' 页',()=>disposeReader?.goToPage?.(block.source.page)));
        item.append(summary,detail); blocks.append(item);
      }
      data.chunks.forEach((piece,i)=>pieces.append(hitCard(piece,i+1,null,()=>disposeReader?.goToPage?.(piece.metadata?.sources?.[0]?.page || 1))));
      content.append(blocks,pieces);
      const confirmRow = el('div',undefined,'k-pdf-confirm');
      const label = el('label'), check = el('input'); check.type='checkbox';
      label.append(check, document.createTextNode(data.coverage ? ' 仅发布已通过的页面；待复核页文字保持隔离，不标记整段完成。' : ' 我已核对阅读顺序、图表、数字与单位，确认建立结构化索引。'));
      const status=el('p','原文和已有索引不会被删除。','k-caption'); status.setAttribute('role','status');
      const submit=button('确认并建立结构化索引',async()=>{
        submit.disabled=true; check.disabled=true; status.textContent='正在使用本地 Qwen 分块向量化，等待真实入库结果…';
        try {
          const saved=await api('/api/knowledge/pdf/jobs/'+encodeURIComponent(job.id)+'/literature/ingest',
            {method:'POST',body:{confirmed:true,basis:data.basis}});
          if (turn !== epoch || ticket !== detailEpoch || view.hidden) return;
          status.textContent=saved.state === 'partially_indexed' ? coverageSummary(saved.index.coverage) : '已建立 '+count(saved.index.chunks)+' 个结构化片段。';
          await refresh(); await refreshPdfJobs();
          confirmRow.append(button('打开资料与索引',()=>openDocument(saved.index.id),'k-primary'));
        } catch(error) { if (turn===epoch && ticket===detailEpoch && !view.hidden) status.textContent=error.message; }
        finally { if(submit.isConnected) {check.disabled=false;submit.disabled=!check.checked || !data.can_index;} }
      },'k-primary');
      submit.disabled=true; check.disabled=!data.can_index;
      check.addEventListener('change',()=>{submit.disabled=!check.checked || !data.can_index;});
      confirmRow.append(label,submit,status);content.append(confirmRow);
    }).catch(error=>{if(turn===epoch && ticket===detailEpoch && !view.hidden) content.replaceChildren(el('p',error.message,'k-caption'));});
    return panel;
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
  document.addEventListener('geoagent:graph-source', event => {
    const source = event.detail;
    if (!view.hidden && source?.document_id) openDocument(source.document_id, source.hit || null, 'graph');
  });
  async function openDocument(id, hit = null, origin = 'library') {
    if (!id) return;
    stopPdfReader();
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
    stopPdfReader();
    const target = $('knowledge-detail'); target.replaceChildren();
    const heading = el('header', undefined, 'k-detail-heading'), title = el('div');
    title.append(el('p', 'SOURCE / ORIGINAL', 'k-eyebrow'), el('h2', doc.title || '资料原文'));
    const source = el('p'); source.append(sourceNode(doc.source)); title.append(source);
    heading.append(title, button(detailOrigin === 'graph' ? '返回知识图谱' : detailOrigin === 'search' ? '返回检索结果' : '返回文献库', () => selectTab(detailOrigin, true)));
    const stats = el('div', undefined, 'k-detail-stats');
    stats.append(tag(docState(doc), doc.chunks > 0 && !sourceCoverage(doc)), tag(count(doc.chunks) + ' 个索引片段'),
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
    evidenceHead.append(el('strong', '索引分块'), el('span', '原文可定位'));
    const body = el('div', undefined, 'k-evidence-body');
    if (locationNote) body.append(el('p', locationNote, 'k-caption'));
    const retrieved = searchCandidates().filter(item => item.document_id === doc.id);
    const pieces = Array.isArray(doc.chunks_detail) ? doc.chunks_detail.map(piece => ({
      ...piece, title: doc.title, sha256: doc.sha256, document_id: doc.id,
      ...retrieved.find(item => item.citation_id === piece.citation_id)
    })) : retrieved;
    body.append(el('p', Array.isArray(doc.chunks_detail)
      ? '下面是当前 Qwen 索引的完整分块。展开可查看原文、Token 数和标题路径；点击定位可核对原文。'
      : '下面是最近一次检索的候选，不是全文分块清单。', 'k-caption'));
    for (const [i, piece] of pieces.entries()) body.append(hitCard(piece, i + 1, null, () => renderDocument(piece)));
    body.append(button('去检索试验', () => { selectTab('search'); $('knowledge-query').focus(); }));
    body.append(el('p', '按标题、段落和表格优先分块，最多 512 Tokens；过长块保留约 64 Tokens 重叠。正文与字符位置可回溯，PDF 页码来自逐字匹配段落或已核验的结构化来源块，未定位部分请手动核对；不推断版面坐标。', 'k-caption'));
    evidence.append(evidenceHead, body); layout.append(reader, evidence);
    const record = el('details', undefined, 'k-model-record'); record.append(el('summary', '来源与索引记录'));
    const metadata = el('dl');
    for (const [key, value] of [['文档 ID', doc.id], ['原文 SHA256', doc.sha256], ['索引模型标识', doc.embedding_key], ['添加时间', doc.created_at]]) {
      metadata.append(el('dt', key), el('dd', modelName(value)));
    }
    record.append(metadata);
    const actions = el('div', undefined, 'k-detail-actions');
    actions.append(el('span', '只删除当前账号的这份资料。', 'k-caption'), button('删除资料', () => removeDocument(doc.id), 'k-danger'));
    const rich = doc.pdf_source ? richPdfContent(doc.pdf_source, doc.body, doc.sha256) : null;
    const sections = hit ? [['原文定位', reader], ['排版阅读', rich], ['索引分块', evidence]]
      : [['排版阅读', rich], ['整理后 Markdown', reader], ['索引分块', evidence]];
    const display = doc.pdf_source ? pdfComparison(doc.pdf_source, sections,
      {text: doc.body, textSha: doc.sha256, hit}) : layout;
    target.append(heading, stats);
    if (sourceCoverage(doc)) target.append(coverageNotice(sourceCoverage(doc)));
    target.append(display, record, actions);
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
    title.append(el('strong', before === null ? '片段 ' + count(hit.ordinal || position) : hit.title || '未命名资料'), el('small', before === null
      ? count(hit.metadata?.token_count) + ' Tokens' : before ? 'RRF ' + score(hit.rrf_score, 5) : '重排分数 ' + score(hit.rerank_score)));
    summary.append(el('span', String(position).padStart(2, '0'), 'k-hit-rank'), title);
    const content = el('div', undefined, 'k-hit-content'); content.append(el('p', hit.text || '未返回片段正文'));
    const metadata = el('div', undefined, 'k-evidence-meta');
    if (sourceCoverage(hit)) content.append(el('p', coverageSummary(sourceCoverage(hit)), 'k-caption'));
    if (numeric(hit.ranks?.dense)) metadata.append(tag('语义 #' + hit.ranks.dense));
    if (numeric(hit.ranks?.lexical)) metadata.append(tag('关键词 #' + hit.ranks.lexical));
    if ((lastSearch?.references || []).some(item => item.citation_id === hit.citation_id)) metadata.append(tag('通过筛选', true));
    if (Number.isInteger(hit.start_char) && Number.isInteger(hit.end_char)) metadata.append(el('span', '字符 ' + count(hit.start_char) + '–' + count(hit.end_char)));
    if (numeric(hit.metadata?.token_count)) metadata.append(tag(count(hit.metadata.token_count) + ' Tokens'));
    if (hit.metadata?.section_path?.length) metadata.append(el('span', hit.metadata.section_path.join(' / ')));
    if (hit.metadata?.continued) metadata.append(tag('长块续段'));
    if (hit.metadata?.sources?.length) metadata.append(tag('PDF ' + [...new Set(hit.metadata.sources.map(s => s.page))].join(', ') + ' 页'));
    if (hit.metadata?.table_header_repeated) metadata.append(tag('保留表头与单位'));
    if (hit.metadata?.related_sections?.length) metadata.append(el('span', '正文引用：' + hit.metadata.related_sections.map(p=>p.join(' / ')).join('; ')));
    if (hit.metadata?.retrieval_transformations?.length) {
      const mapped = el('details',undefined,'k-model-record');
      mapped.append(el('summary','检索规范化与来源映射（非逐字原文）'),el('pre',hit.metadata.retrieval_text,'k-original'));
      for (const edit of hit.metadata.retrieval_transformations) mapped.append(el('p', edit.block_id + ' · 原文字符 ' + edit.start + '–' + edit.end,'k-caption'),el('pre',edit.raw + '\n→\n' + edit.text,'k-original'));
      content.append(mapped);
    }
    if (hit.metadata?.embedding_text) {
      const input = el('details', undefined, 'k-model-record');
      input.append(el('summary','实际 Embedding 输入 (' + count(hit.metadata.token_count) + ' Tokens)'),
        el('pre',hit.metadata.embedding_text,'k-original'),el('code',hit.metadata.embedding_input_sha256 || ''));
      content.append(input);
    }
    if (typeof hit.rerank_input === 'string') {
      const input = el('details', undefined, 'k-model-record');
      input.append(el('summary', '实际 Rerank 输入'), el('pre', hit.rerank_input, 'k-original'));
      content.append(input);
    }
    const reasonLabels = {
      requested_metadata_missing: '片段未包含本次所问的书目字段',
      bibliographic_not_requested: '书目信息：本次未询问，不作为正文证据',
      below_threshold: '相关性未达阈值',
      outside_result_limit: '达到结果数量上限',
    };
    if (reasonLabels[hit.selection_reason]) metadata.append(tag(reasonLabels[hit.selection_reason]));
    if (hit.evidence_order_reason === 'numeric_source_before_caption') metadata.append(tag('近分同文献：含所问量纲数值的正文优先'));
    if (hit.evidence_order_reason === 'supporting_caption') metadata.append(tag('补充图注：不含所问量纲的数值'));
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
    const scope = lastSearch.document_scope;
    if (scope && scope.mode !== 'all') {
      const note = scope.mode === 'scoped'
        ? '检索范围：' + (scope.documents || []).map(doc => doc.title).join('；')
        : scope.mode === 'ambiguous'
          ? '找到多份同名文献，请补充完整标题或 DOI。本次未扩大检索范围。'
          : '指定文献尚无可用索引，请核对作者、年份、标题或 DOI。本次未检索其他文献。';
      target.append(el('p', note, 'k-caption k-document-scope'));
    } else if (scope?.reason === 'explicit_cross_document_request') {
      target.append(el('p', '检索范围：按你的要求跨文献检索。', 'k-caption k-document-scope'));
    }
    const coverage = lastSearch.document_coverage;
    if (coverage?.status === 'partial') {
      const missing = (scope?.documents || []).filter(doc => (coverage.missing_document_ids || []).includes(doc.id));
      target.append(el('p', '以下指定文献尚未返回通过筛选的证据：' + missing.map(doc => doc.title).join('；') + '。不会用其他文献代替。', 'k-caption k-document-coverage'));
    }
    if (!candidates.length) {
      const placeholder = el('div');
      empty(placeholder, '暂时没有找到相关片段', lastSearch.status === 'empty'
        ? '先添加资料并建立索引，再来测试。' : '检查资料是否有索引，或换一种问法。没有命中，不代表资料中一定没有答案。');
      target.append(placeholder); return;
    }
    if (!references.length) target.append(el('p', '候选没有通过当前后端的筛选策略。下面仍可查看候选，但不将其标记为可用证据。', 'k-caption'));
    const grid = el('div', undefined, 'k-comparison');
    const haveFusionScores = candidates.every(item => numeric(item.rrf_score));
    const fused = haveFusionScores ? [...candidates].sort((a, b) => b.rrf_score - a.rrf_score || String(a.citation_id).localeCompare(String(b.citation_id))) : [];
    for (const [title, description, rows, before] of [['融合召回', (lastSearch.recall_channels?.includes('catalog') ? '语义 + 关键词 + 书目字段 / RRF' : '语义 + 关键词 / RRF'), fused, true], ['重排结果', '相关性分数 + 证据排序', candidates, false]]) {
      const column = el('section'), heading = el('header', undefined, 'k-comparison-heading');
      heading.append(el('h3', title), el('span', description)); column.append(heading);
      if (!rows.length) column.append(el('p', '接口未返回融合分数，无法还原重排前顺序。', 'k-caption'));
      rows.forEach((hit, i) => column.append(hitCard(hit, i + 1, before))); grid.append(column);
    }
    target.append(grid, el('p', '两列比较的是本次接口返回的同一组候选，不代表召回全集。相关性分数不是事实正确率，不同模型的分数不能直接比较。', 'k-caption'));
    const details = el('details', undefined, 'k-model-record'); details.append(el('summary', '本次检索的模型与策略'));
    const fields = el('dl');
    for (const [name, value] of [['Embedding', modelName(lastSearch.retrieval_profile?.embedding_model || lastSearch.embedding_key)], ['Reranker', modelName(lastSearch.reranker)], ['筛选阈值', score(lastSearch.threshold)], ['查询 Token', numeric(lastSearch.rerank_query_tokens_used) ? count(lastSearch.rerank_query_tokens_used) + ' / ' + count(lastSearch.rerank_query_tokens_total) : '接口未提供']]) fields.append(el('dt', name), el('dd', value));
    const actualStrategies = Array.isArray(lastSearch.retrieval_profile?.active_chunkers)
      ? lastSearch.retrieval_profile.active_chunkers : [];
    const strategyText = actualStrategies.length
      ? actualStrategies.map(item => modelName(item.id) + ' (' + count(item.chunks) + ' chunks)').join(' / ')
      : '接口未提供候选的实际策略';
    fields.append(el('dt', '本次候选分块策略'), el('dd', strategyText),
      el('dt', '筛选说明'), el('dd', lastSearch.rerank_policy?.calibrated === false
        ? '当前阈值 ' + score(lastSearch.threshold) + '，尚未经过真实文献集校准；不代表事实可信度。'
        : modelName(lastSearch.rerank_policy?.method)));
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
    indexing:'正在建立索引',indexed:'已入库',partially_indexed:'部分入库 · 有页面待复核',failed:'处理失败',submission_unknown:'提交状态待确认'};
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
      if (sourceCoverage(job)) status.append(el('span', coverageSummary(sourceCoverage(job)), 'k-caption'));
      if (job.pages !== null && job.pages !== undefined) status.append(el('span', count(job.pages) + ' 页', 'k-caption'));
      const actions = el('div', undefined, 'k-pdf-job-actions');
      if ((job.artifacts || []).includes('markdown')) actions.append(button('预览解析结果', () => openPdfPreview(job.id)));
      if (['indexed','partially_indexed'].includes(job.state) && job.index?.id) actions.append(button('打开入库资料', () => openDocument(job.index.id), 'k-primary'));
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
    stopPdfReader(); currentDoc = null;
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
      for (const [kind,label] of [['original','原 PDF'],['markdown','原始解析 Markdown'],['middle_json','版面 JSON'],['structured_content','结构化 JSON'],['zip','解析文件包']])
        if ((job.artifacts || []).includes(kind)) downloads.append(artifactLink(job,kind,label));
      const preparedLink = el('a', '整理后 Markdown', 'k-button');
      preparedLink.href = '/api/knowledge/pdf/jobs/' + encodeURIComponent(id) + '/content/markdown';
      preparedLink.download = 'content.md'; downloads.append(preparedLink);
      facts.append(tag(count(result.images || 0) + ' 张图片'));
      const note = el('p', result.preview_truncated
        ? '当前仅预览前 120,000 字符，完整解析文本已保留在下载文件中。超出当前入库限制，不会截断后入库。'
        : '图片已独立保存，不把图片编码送入向量索引。请核对多栏顺序、表格、公式和图注；解析器生成的图示转写单独标注，不作为原文入库。', 'k-caption');
      const reader = el('section',undefined,'k-reader');
      reader.append(el('div','整理后 Markdown · 只读','k-pane-heading'),el('pre',result.text,'k-original'));
      const record = el('details',undefined,'k-model-record');
      record.append(el('summary','解析与来源记录'));
      const fields = el('dl');
      for (const [key,value] of [['原 PDF SHA256',job.sha256],['原始解析 SHA256',job.text_sha256],['整理后正文 SHA256',result.text_sha256],
        ['解析模型',job.parser?.model_used],['解析版本',job.parser?.parser_version],['来源',job.source]])
        fields.append(el('dt',key),el('dd',modelName(value)));
      record.append(fields);
      const status = el('p',job.error || job.index_note || '', 'k-caption'); status.setAttribute('role','status');
      const actions = el('div',undefined,'k-pdf-confirm');
      actions.append(el('p','确认后按结构切块，并使用 Qwen3-Embedding-0.6B 建立 1,024 维索引。查询时再使用 Qwen3-Reranker-0.6B 重排；原 PDF 和解析原文保留。','k-caption'));
      if (['indexed','partially_indexed'].includes(job.state) && job.index?.id) {
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
      const pdfSource = {...job, text_sha256: result.text_sha256};
      const rich = richPdfContent(pdfSource, result.text, result.text_sha256);
      const comparison = pdfComparison(pdfSource, [['排版阅读', rich], ['结构化内容', literaturePanel(job)], ['整理后 Markdown', reader]],
        {text: result.text, textSha: result.text_sha256});
      target.append(heading,path,facts,downloads);
      if (sourceCoverage(job)) target.append(coverageNotice(sourceCoverage(job)));
      target.append(note,comparison,record,status,actions);
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


/* Original source folders remain user-authored classifications. */
(() => {
  'use strict';
  /* original-groups-summary:start */
  function originalGroupSummary(documents, jobs) {
    const labels = ['高相关', '中相关', '低相关'];
    const indexed = new Map();
    for (const [id, doc] of Object.entries(documents || {})) {
      if (!doc || !Array.isArray(doc.groups)) continue;
      indexed.set(doc.sha256 || id, doc);
    }
    const papers = new Map();
    for (const job of jobs || []) {
      const source = String(job.source || '');
      const match = source.match(/原分组[：:]([^；;]+)/);
      if (!match) continue;
      const groups = labels.filter(label => match[1].includes(label));
      if (!groups.length) continue;
      const key = job.sha256 || job.id;
      papers.set(key, {job, groups, indexed: indexed.has(key)});
    }
    const groups = labels.map(label => {
      const members = [...papers.values()].filter(p => p.groups.includes(label));
      const indexedCount = [...indexed.values()].filter(d => d.groups.includes(label)).length;
      return {label, total: Math.max(members.length, indexedCount), indexed: indexedCount,
        pending: members.filter(p => !p.indexed).map(p => p.job)};
    });
    return {groups, total: Math.max(papers.size, indexed.size), indexed: indexed.size,
      pending: [...papers.values()].filter(p => !p.indexed).map(p => p.job)};
  }
  /* original-groups-summary:end */
  const byId = id => document.getElementById(id);
  const make = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  let summary = null, bar = null, pendingPanel = null, loading = false, initialized = false;
  const buttons = new Map();
  /* original-groups-reset:start */
  function resetOriginalGroupFilter(field) {
    if (field.tagName === 'SELECT') field.selectedIndex = 0;
    else field.value = '';
    field.dispatchEvent(new Event(field.tagName === 'SELECT' ? 'change' : 'input', {bubbles:true}));
  }
  /* original-groups-reset:end */
  function choose(label) {
    const select = byId('knowledge-facet-groups');
    if (!select) return;
    for (const id of ['knowledge-facet-deposits', 'knowledge-facet-topics', 'knowledge-filter-state', 'knowledge-filter']) {
      const field = byId(id);
      if (field) resetOriginalGroupFilter(field);
    }
    select.value = label;
    select.dispatchEvent(new Event('change', {bubbles:true}));
    sync();
  }
  function showJob(job) {
    const queue = byId('knowledge-pdf-queue');
    if (!queue) return;
    queue.open = true;
    const link = [...queue.querySelectorAll('a')].find(a => a.getAttribute('href') === '/api/knowledge/pdf/jobs/' + job.id + '/artifacts/original');
    const row = link && link.closest('.k-pdf-job');
    if (row) {
      row.scrollIntoView({block:'center', behavior:'smooth'});
      const preview = [...row.querySelectorAll('button')].find(b => /预览解析结果/.test(b.textContent));
      if (preview) preview.click();
    } else queue.scrollIntoView({block:'start', behavior:'smooth'});
  }
  function sync() {
    if (!bar || !summary) return;
    const selected = byId('knowledge-facet-groups')?.value || '';
    buttons.forEach((button, label) => button.setAttribute('aria-pressed', String(label === selected)));
    pendingPanel.replaceChildren();
    const group = summary.groups.find(g => g.label === selected);
    const pending = group ? group.pending : summary.pending;
    if (!pending.length) {pendingPanel.hidden = true; return;}
    pendingPanel.hidden = false;
    const title = make('summary', 'kg-pending-title', '尚未入库 · ' + pending.length + ' 篇');
    pendingPanel.append(title, make('p', 'kg-note', '原 PDF 和已有解析结果均保留。下列论文尚不能作为检索证据，不会被计作入库成功。'));
    const list = make('div', 'kg-pending-list');
    const states = {failed:'解析失败', parsed:'待复核', submission_unknown:'提交状态待核对', parsing:'解析中', queued:'排队中', receiving:'上传中', indexed:'索引记录待核对', partially_indexed:'部分入库，问题页待复核'};
    pending.forEach(job => {
      const row = make('article', 'kg-pending-row');
      const text = make('div', 'kg-pending-copy');
      text.append(make('strong', '', job.title || job.filename || '未命名论文'), make('span', 'kg-note', states[job.state] || '尚未入库'));
      row.append(text);
      if ((job.artifacts || []).includes('original')) {
        const link = make('a', 'k-button', '原 PDF');
        link.href = '/api/knowledge/pdf/jobs/' + encodeURIComponent(job.id) + '/artifacts/original';
        link.download = '';
        row.append(link);
      }
      const action = make('button', 'k-button', '查看任务');
      action.type = 'button'; action.addEventListener('click', () => showJob(job)); row.append(action);
      list.append(row);
    });
    pendingPanel.append(list);
  }
  function mount() {
    const select = byId('knowledge-facet-groups'), panel = byId('knowledge-panel-library');
    if (!select || !panel || !summary) return;
    if (!bar) {
      bar = make('section', 'kg-folders'); bar.id = 'knowledge-original-groups';
      bar.setAttribute('aria-label', '原始文件夹分类');
      const head = make('div', 'kg-heading');
      const copy = make('div'); copy.append(make('p', 'kg-eyebrow', 'ORIGINAL COLLECTIONS'), make('h2', '', '按原来的分类，找到论文。'));
      const all = make('button', 'kg-all', '全部论文'); all.type = 'button';
      all.addEventListener('click', () => choose('')); buttons.set('', all); head.append(copy, all);
      const cards = make('div', 'kg-cards'); cards.setAttribute('role', 'group'); cards.setAttribute('aria-label', '论文相关性分类');
      summary.groups.forEach((group, n) => {
        const button = make('button', 'kg-card'); button.type = 'button'; button.dataset.group = group.label;
        const cap = make('span', 'kg-card-top'); cap.append(make('span', 'kg-number', '0' + (n + 1)), make('span', 'kg-folder-mark', ''));
        const count = make('span', 'kg-count'); count.append(make('strong', '', String(group.total)), make('span', '', '篇'));
        button.append(cap, make('strong', 'kg-label', group.label), count, make('span', 'kg-indexed', group.indexed + ' 篇可检索'));
        button.addEventListener('click', () => choose(group.label)); buttons.set(group.label, button); cards.append(button);
      });
      bar.append(head, cards, make('p', 'kg-note', '沿用原始文件夹分组，不重新评级。同一篇论文若原本位于多个分类，会保留多个归属。'));
      pendingPanel = make('details', 'kg-pending'); pendingPanel.id = 'knowledge-group-pending';
      bar.append(pendingPanel);
      panel.insertBefore(bar, byId('knowledge-pdf-queue') || panel.firstChild);
      const queue = byId('knowledge-pdf-queue');
      if (queue) queue.open = false;
      select.parentElement.classList.add('kg-native-group');
      select.addEventListener('change', sync);
    }
    if (!initialized) {initialized = true; choose(select.value || '高相关');} else sync();
  }
  async function load() {
    const view = byId('knowledge-view');
    if (loading || !view || view.hidden) return;
    loading = true;
    try {
      const catalogResponse = await fetch('/api/knowledge/catalog', {credentials:'same-origin',cache:'no-store'});
      const jobResponse = await fetch('/api/knowledge/pdf/jobs', {credentials:'same-origin',cache:'no-store'});
      if (!catalogResponse.ok || !jobResponse.ok) return;
      const catalog = await catalogResponse.json(), payload = await jobResponse.json();
      const jobs = Array.isArray(payload) ? payload : payload.jobs || [];
      summary = originalGroupSummary(catalog.documents || {}, jobs);
      if (!summary.total) return;
      mount();
    } catch (error) {
      console.warn('Original folder categories unavailable; existing library controls remain available.');
    } finally {loading = false;}
  }
  function start() {
    const view = byId('knowledge-view');
    if (!view) return;
    new MutationObserver(() => {if (!view.hidden) load();}).observe(view, {attributes:true,attributeFilter:['hidden']});
    const rows = byId('knowledge-documents');
    if (rows) new MutationObserver(() => {if (summary) mount(); else load();}).observe(rows, {childList:true});
    byId('knowledge-refresh')?.addEventListener('click', load);
    if (!view.hidden) load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true}); else start();
})();

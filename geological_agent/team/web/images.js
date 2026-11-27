'use strict';
// Answer links resolve only against the authenticated, immutable run manifest.
// No model-written HTML, filesystem URL, or remote image is executed or loaded.
(() => {
  function localName(value) {
    let name;
    try { name = decodeURIComponent(value); } catch { return null; }
    name = name.replace(/^(?:sandbox:)?\/mnt\/data\//, '').replace(/^\.\//, '');
    if (!name || /[\x00-\x1f\x7f\\:?#]/.test(name) || name.startsWith('/') || name.split('/').some(part => !part || part === '.' || part === '..')) return null;
    return name;
  }
  function fileURL(context, name, kind) {
    return '/api/conversations/' + encodeURIComponent(context.conversation_id) + '/' + kind
      + '?name=' + encodeURIComponent(name) + '&generation=' + encodeURIComponent(context.generation);
  }
  const imagePattern = /\.(png|jpe?g|webp|tiff?|svg)$/i;
  const textPattern = /\.(md|markdown|txt|log|json|geojson|jsonl|ya?ml|xml|html|css|js|py|r|sql|tex|bib)$/i;
  const readerAssets = '/api/knowledge/pdf/reader-assets/pdfjs/';
  const panel = $('artifact-preview'), title = $('artifact-preview-title');
  const body = $('artifact-preview-body'), picker = $('artifact-preview-files');
  const close = $('artifact-preview-close'), evidence = $('artifact-preview-evidence');
  const download = $('artifact-preview-download');
  let selection = null, origin = null, fromFiles = false;

  function stopPreview() {
    const previous = selection;
    selection = null;
    if (!previous) return;
    previous.controller.abort();
    previous.render?.cancel();
    previous.pdf?.destroy().catch(() => {});
  }
  function closePreview(restore = false) {
    stopPreview();
    panel.hidden = true;
    body.replaceChildren();
    picker.replaceChildren(); picker.onchange = null;
    evidence.onclick = null;
    download.removeAttribute('href');
    if (restore && fromFiles) $('files-panel').hidden = false;
    if (restore && origin?.isConnected) origin.focus();
    origin = null;
    fromFiles = false;
  }
  close.addEventListener('click', () => closePreview(true));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || panel.hidden || document.querySelector('dialog[open]')) return;
    event.preventDefault();
    closePreview(true);
  });

  const current = view => selection === view;
  const status = text => element('p', text, 'artifact-preview-status');
  async function get(url, view) {
    const response = await fetch(url, {signal:view.controller.signal, cache:'no-store'});
    if (!response.ok) throw new Error('Artifact preview unavailable');
    return response;
  }
  function pageControls(previous, next) {
    const controls = element('div', undefined, 'artifact-preview-pages');
    const back = element('button', '上一页', 'quiet'), forward = element('button', '下一页', 'quiet');
    const count = element('span');
    back.type = forward.type = 'button';
    back.addEventListener('click', previous);
    forward.addEventListener('click', next);
    controls.append(back, count, forward);
    return {controls, back, count, forward};
  }
  async function showPDF(view) {
    const bytes = await (await get(view.href, view)).arrayBuffer();
    const lib = await import(readerAssets + 'build/pdf.mjs');
    if (!current(view)) return;
    lib.GlobalWorkerOptions.workerSrc = readerAssets + 'build/pdf.worker.mjs';
    view.pdf = lib.getDocument({data:new Uint8Array(bytes), isEvalSupported:false, enableXfa:false,
      useWasm:false, disableFontFace:true, isOffscreenCanvasSupported:false,
      cMapUrl:readerAssets + 'cmaps/', cMapPacked:true, standardFontDataUrl:readerAssets + 'standard_fonts/'});
    const documentPdf = await view.pdf.promise;
    if (!current(view)) return;
    let pageNumber = 1;
    const pages = pageControls(() => paint(pageNumber - 1), () => paint(pageNumber + 1));
    const canvas = element('canvas', undefined, 'artifact-pdf-page');
    canvas.setAttribute('role', 'img');
    body.replaceChildren(pages.controls, canvas);
    async function paint(number) {
      pages.back.disabled = pages.forward.disabled = true;
      pages.count.textContent = number + ' / ' + documentPdf.numPages;
      canvas.setAttribute('aria-label', 'PDF 第 ' + number + ' 页');
      try {
        const page = await documentPdf.getPage(number);
        if (!current(view)) return;
        const natural = page.getViewport({scale:1});
        const scale = Math.min(2, 1600 / Math.max(natural.width, natural.height));
        const viewport = page.getViewport({scale});
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        view.render = page.render({canvasContext:canvas.getContext('2d'), viewport});
        await view.render.promise;
        if (!current(view)) return;
        view.render = null;
        pageNumber = number;
        pages.back.disabled = number <= 1;
        pages.forward.disabled = number >= documentPdf.numPages;
      } catch {
        if (current(view)) body.replaceChildren(status('PDF 页面加载失败，可以下载原文件。'));
      }
    }
    await paint(1);
  }
  async function showTable(view) {
    const limit = 30;
    let offset = 0;
    const pages = pageControls(() => paint(offset - limit), () => paint(offset + limit));
    const scroller = element('div', undefined, 'artifact-table-scroll');
    body.replaceChildren(pages.controls, scroller);
    async function paint(start) {
      pages.back.disabled = pages.forward.disabled = true;
      try {
        const response = await get(view.table + '&offset=' + start + '&limit=' + limit, view);
        const {columns, rows, total} = await response.json();
        if (!current(view)) return;
        const table = element('table'), head = element('thead'), header = element('tr'), contents = element('tbody');
        for (const value of columns) {
          const cell = element('th', value); cell.scope = 'col'; header.append(cell);
        }
        head.append(header);
        for (const row of rows) {
          const record = element('tr');
          for (const value of row) record.append(element('td', value));
          contents.append(record);
        }
        table.append(head, contents); scroller.replaceChildren(table);
        offset = start;
        pages.count.textContent = (total ? (start + 1) + '–' + (start + rows.length) : '0') + ' / ' + total + ' 行';
        pages.back.disabled = !start;
        pages.forward.disabled = start + rows.length >= total;
      } catch {
        if (current(view)) body.replaceChildren(status('表格预览不可用，可以下载原文件。'));
      }
    }
    await paint(0);
  }
  function showImage(context, file, view) {
    const name = file.name, url = fileURL(context, name, 'image');
    let attempt = 0;
    function load() {
      if (!current(view)) return;
      const image = element('img', undefined, 'artifact-preview-image');
      image.alt = name;
      image.addEventListener('load', () => {
        if (!current(view)) return;
        body.replaceChildren(image);
        if (/\.tiff?$/i.test(name)) body.append(status('GeoTIFF 预览展示第 1 波段及显示拉伸效果。原文件包含数值与坐标。'));
      }, {once:true});
      image.addEventListener('error', () => {
        if (!current(view)) return;
        if (!attempt) {
          attempt++;
          load();
          return;
        }
        const retry = element('button', '重试预览', 'outline');
        retry.type = 'button';
        retry.addEventListener('click', () => {
          attempt++;
          body.replaceChildren(status('正在重新加载预览…'));
          load();
        });
        body.replaceChildren(status('暂时无法显示图片，原文件仍可下载。'), retry);
      }, {once:true});
      image.src = url + (attempt ? '&retry=' + Date.now() + '-' + attempt : '');
    }
    load();
  }
  async function paintFile(context, file) {
    stopPreview();
    const name = file.name, href = fileURL(context, name, 'download');
    const view = {href, controller:new AbortController(), table:fileURL(context, name, 'table-preview')};
    selection = view;
    picker.value = name;
    title.textContent = name;
    $('artifact-preview-meta').textContent = context.run_id ? '本轮成果' : '对话文件';
    download.href = href;
    download.download = name.split('/').pop();
    body.scrollTop = 0;
    body.replaceChildren(status('正在加载预览…'));
    try {
      if (imagePattern.test(name)) {
        showImage(context, file, view);
      } else if (/\.pdf$/i.test(name)) {
        await showPDF(view);
      } else if (/\.(csv|tsv)$/i.test(name)) {
        await showTable(view);
      } else if (textPattern.test(name) && file.bytes <= 512 * 1024) {
        const text = await (await get(href, view)).text();
        if (!current(view)) return;
        if (/\.(md|markdown)$/i.test(name)) {
          const article = element('article', undefined, 'artifact-preview-markdown');
          markdown(article, text, context);
          body.replaceChildren(article);
        } else {
          body.replaceChildren(element('pre', text, 'artifact-preview-text'));
        }
      } else {
        body.replaceChildren(status(textPattern.test(name)
          ? '文件较大，可以下载查看完整内容。' : '此格式暂未提供网页预览，可以下载原文件。'));
      }
    } catch {
      if (current(view)) body.replaceChildren(status('预览加载失败，可以下载原文件。'));
    }
  }
  function openFile(context, name, trigger, openEvidence) {
    if (!state.me || !state.cid || context?.conversation_id !== state.cid || !context.generation || !Array.isArray(context.files)) return;
    const files = context.files;
    const file = name ? files.find(item => item.name === name)
      : files.find(item => imagePattern.test(item.name)) || files[0];
    if (!file) return;
    const source = trigger || document.activeElement;
    if (!panel.contains(source)) {
      origin = source;
      fromFiles = $('files-panel').contains(source);
    }
    $('files-panel').hidden = true;
    panel.hidden = false;
    picker.replaceChildren(...files.map(item => {
      const option = element('option', item.name); option.value = item.name; return option;
    }));
    picker.hidden = files.length < 2;
    picker.onchange = () => {
      const next = files.find(item => item.name === picker.value);
      if (next) paintFile(context, next);
    };
    evidence.hidden = !openEvidence;
    evidence.onclick = openEvidence || null;
    paintFile(context, file);
    if (!panel.contains(document.activeElement)) close.focus();
  }

  function renderLink(token, context) {
    const parsed = /^(!?)\[([^\]\n]*)\]\(([\s\S]*)\)$/.exec(token);
    if (!parsed) return document.createTextNode(token);
    const label = parsed[2] || '查看图片';
    let destination = parsed[3].trim();
    const titled = /^(?:<([^>]+)>|(.+?))(?:\s+["'][^"']*["'])$/.exec(destination);
    if (titled) destination = titled[1] || titled[2];
    else if (destination.startsWith('<') && destination.endsWith('>')) destination = destination.slice(1, -1);
    const name = localName(destination);
    const file = context?.generation && context.conversation_id && Array.isArray(context.files)
      ? context.files.find(item => item.name === name) : null;
    if (file) {
      const href = fileURL(context, name, 'download'), link = element('button', label, 'quiet answer-file-link');
      link.type = 'button';
      link.addEventListener('click', () => openFile(context, name, link));
      if (!imagePattern.test(name)) return link;
      const wrap = element('span', undefined, 'answer-image'), show = element('button', undefined, 'answer-image-open'), img = element('img');
      const src = fileURL(context, name, 'image');
      show.type = 'button'; show.setAttribute('aria-label', '预览图片：' + label);
      img.src = src; img.alt = label; img.loading = 'lazy'; img.decoding = 'async'; show.append(img);
      const open = event => openFile(context, name, event.currentTarget); show.addEventListener('click', open);
      const actions = element('span', undefined, 'answer-image-actions'), zoom = element('button', '侧栏预览', 'quiet'), download = element('a', '下载原图');
      zoom.type = 'button'; zoom.setAttribute('aria-label', '侧栏预览：' + label); zoom.addEventListener('click', open);
      download.href = href; download.download = name.split('/').pop(); actions.append(zoom, download);
      img.addEventListener('error', () => { show.replaceChildren(element('span', '暂不能预览，请下载原图', 'image-failed')); show.disabled = true; zoom.disabled = true; });
      wrap.append(link, show, actions); return wrap;
    }
    // External references may be links, but never automatically fetched pixels.
    if (/^https?:\/\//i.test(destination)) {
      try {
        const url = new URL(destination);
        if (!url.username && !url.password && ['http:', 'https:'].includes(url.protocol)) {
          const link = element('a', label); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
        }
      } catch { /* Keep unsafe or malformed destinations inert. */ }
    }
    const unresolved = element('span', label, 'answer-file-unavailable');
    if (name && context?.generation) { unresolved.append(document.createTextNode('（本轮未保存此文件）')); unresolved.title = name; }
    return unresolved;
  }
  window.GeoAgentArtifacts = {renderLink, openFile, closePreview, fileURL};
})();
(() => {
  let files = [], cid = null, generation = '';
  const dialog = document.createElement('dialog'); dialog.id = 'image-dialog';
  dialog.setAttribute('aria-labelledby', 'image-dialog-title');
  const header = element('header', undefined, 'image-dialog-header');
  const heading = element('h2', '图片对比'); heading.id = 'image-dialog-title';
  const close = element('button', '关闭', 'quiet'); close.type = 'button'; close.addEventListener('click', () => dialog.close());
  header.append(heading, close); dialog.append(header);
  const compare = element('div', undefined, 'image-compare'); dialog.append(compare);
  const note = element('p', 'SVG 矢量图可无损放大，预览仅展示经检查的静态内容；原文件完整保留。预览保留透明区域。GeoTIFF 默认展示第 1 波段，按采样有效值做显示拉伸；下载原始文件保留科学数值与坐标。视觉模型会收到图片像素，请仅提交可发送给所选模型的材料。', 'image-dialog-note');
  dialog.append(note); document.body.append(dialog);
  const panels = ['原图 / 参考', '处理结果'].map((title, index) => {
    const panel = element('section'), label = element('label', title), select = element('select');
    select.id = 'image-select-' + index; label.htmlFor = select.id; label.append(select);
    const viewport = element('div', undefined, 'image-viewport');
    const image = element('img'); viewport.append(image);
    const actions = element('div', undefined, 'image-actions'), zoom = element('button', '放大查看', 'outline'), download = element('a', '下载原文件');
    zoom.type = 'button'; zoom.addEventListener('click', () => { const expanded = viewport.classList.toggle('is-zoomed'); zoom.textContent = expanded ? '适应窗口' : '放大查看'; zoom.setAttribute('aria-pressed', String(expanded)); });
    actions.append(zoom, download); panel.append(label, viewport, actions); compare.append(panel);
    select.addEventListener('change', () => paint(index));
    image.addEventListener('error', () => { image.hidden = true; viewport.setAttribute('aria-label', '图片预览失败，请下载原文件检查'); });
    return {select, viewport, image, download, zoom};
  });
  function url(name, kind = 'image') { return '/api/conversations/' + encodeURIComponent(cid) + '/' + kind + '?name=' + encodeURIComponent(name) + '&generation=' + encodeURIComponent(generation); }
  function paint(index) {
    const panel = panels[index], name = panel.select.value;
    panel.viewport.classList.toggle('is-svg', /\.svg$/i.test(name));
    panel.image.hidden = false; panel.image.alt = name; panel.image.src = url(name);
    panel.viewport.classList.remove('is-zoomed'); panel.zoom.textContent = '放大查看'; panel.zoom.setAttribute('aria-pressed', 'false');
    panel.download.href = url(name, 'download'); panel.download.download = name.split('/').pop();
  }
  function open(name) {
    if (!files.length) return;
    panels.forEach((panel, index) => {
      panel.select.replaceChildren();
      for (const file of files) { const option = element('option', file.name); option.value = file.name; panel.select.append(option); }
      panel.select.value = index === 0 ? files[0].name : (name || files[files.length - 1].name);
      paint(index);
    });
    dialog.showModal();
  }
  function clear() { window.GeoAgentExperience?.clear(); files = []; cid = null; generation = ''; if (dialog.open) dialog.close(); window.GeoAgentArtifacts.closePreview(); document.getElementById('image-gallery')?.remove(); for (const p of panels) { p.image.removeAttribute('src'); p.select.replaceChildren(); p.download.removeAttribute('href'); } }
  function render(result, conversation) {
    if (state.cid !== conversation) return;
    cid = conversation; generation = result.generation;
    files = result.files.filter(file => /\.(png|jpe?g|webp|tiff?|svg)$/i.test(file.name));
    document.getElementById('image-gallery')?.remove();
    if (!files.length) return;
    const gallery = element('section', undefined, 'image-gallery'); gallery.id = 'image-gallery'; gallery.setAttribute('aria-label', '对话图片');
    const head = element('div', undefined, 'image-gallery-head'), text = element('div');
    text.append(element('h3', '图片与处理结果'), element('p', files.length + ' 个图像文件 · 原件保留，可对比和下载'));
    const button = element('button', '对比图片', 'outline'); button.type = 'button'; button.addEventListener('click', () => open());
    head.append(text, button); gallery.append(head);
    const browse = element('button', '查看对话图像与文件', 'quiet'); browse.type = 'button';
    browse.addEventListener('click', () => window.GeoAgentExperience?.files({...result, conversation_id:conversation}));
    gallery.append(browse); $('messages').append(gallery);
  }
  window.GeoAgentImages = {render, clear};
})();


// Compact research experience: presentation only, never tool execution.
(() => {
  const el = (tag, text, cls) => element(tag, text, cls);
  const btn = (text, click, cls = 'outline') => {
    const node = el('button', text, cls); node.type = 'button'; node.addEventListener('click', click); return node;
  };
  const number = value => Number.isSafeInteger(value) && value > 0 ? value.toLocaleString('en-US') : '未记录';
  const imageFile = file => /\.(png|jpe?g|webp|tiff?|svg)$/i.test(file.name);
  const safeName = name => typeof name === 'string' && name.length > 0 && !/[\x00-\x1f\x7f\\:?#]/.test(name)
    && !name.startsWith('/') && !name.split('/').some(part => !part || part === '.' || part === '..');
  const manifest = context => Array.isArray(context?.files) ? context.files.filter(file =>
    safeName(file.name) && typeof file.sha256 === 'string' && file.sha256.length > 0) : [];
  const valid = context => typeof state !== 'undefined' && Boolean(state.me && state.cid
    && context?.conversation_id === state.cid && typeof context.generation === 'string' && context.generation);
  const url = (ctx, file, kind = 'download') => '/api/conversations/' + encodeURIComponent(ctx.conversation_id)
    + '/' + kind + '?name=' + encodeURIComponent(file.name) + '&generation=' + encodeURIComponent(ctx.generation);
  const terminal = status => ({completed:'已完成',needs_input:'等待补充信息',stopped:'已停止',cancelled:'已停止',failed:'执行失败',paused:'已暂停',stopping:'正在停止',budget_exhausted:'运行预算已耗尽',incomplete:'尚未完成',interrupted:'执行中断'})[status] || '状态待确认';
  function classifyIssue(reason) {
    if (typeof reason !== 'string') return null;
    if (reason.startsWith('Invalid source review blocks: ')) {
      try {
        const errors = JSON.parse(reason.slice('Invalid source review blocks: '.length));
        const values = errors && typeof errors === 'object' && !Array.isArray(errors) ? Object.values(errors) : [];
        if (values.length && values.every(value => typeof value === 'string' && /^(Compared term needs its exact quoted source evidence|Quoted text is absent from the exact source field|Supported block needs exact evidence|Cross-language source claim omitted)/.test(value))) return 'review_evidence';
      } catch { /* Old malformed records remain classified as review format errors. */ }
      return 'review_format';
    }
    if (/^(Model provider error:|HTTPStatusError:|ReadTimeout:|ConnectError:)/.test(reason)) return 'model_service';
    if (/^(Semantic review requires|Invalid semantic review JSON|Semantic review needs)/.test(reason)) return 'review_format';
    if (/^(The model service did not honor native|Model stream ended without)/.test(reason)) return 'model_protocol';
    return null;
  }
  function issueAction(category) {
    return ({
      review_evidence:{title:'正在补齐审核证据',detail:'修正审核引用，不重新执行已成功的工具'},
      review_format:{title:'正在修正审核记录格式',detail:'审核记录尚未通过校验，不代表模型服务断开'},
      model_service:{title:'模型服务调用异常',detail:'正在处理服务连接或供应商响应问题'},
      model_protocol:{title:'正在修正原生调用格式',detail:'无效响应不会被当成工具调用执行'},
      answer_validation:{title:'正在修正答复内容',detail:'答复尚未通过需求或来源校验'},
      verification_error:{title:'验证过程出现异常',detail:'保留已有结果，等待恢复验证'}
    })[category] || {title:'正在处理检查问题',detail:'原始记录保留'};
  }
  function terminalAction(status, reason, outcome) {
    if (reason === '任务已达到执行时限。完整调研报告未完成。' ||
        reason === 'TimeoutError: Managed task execution deadline exceeded') {
      return {title:'任务已超时', detail:'可查看本轮已保存的检索和执行记录'};
    }
    if (status !== 'needs_input') return {title:terminal(status),detail:''};
    const category = outcome?.failure_category || classifyIssue(reason);
    if (outcome?.recovery_required || category) {
      const review = outcome?.business_state === 'review_blocked' || ['review_evidence','review_format','answer_validation','verification_error'].includes(category);
      return {title:review?'审核受阻，等待恢复':'模型调用受阻，等待恢复',
        detail:category === 'review_evidence'?'审核证据尚未补齐；可重试审核，不需要补充研究资料':'可在下方重试或调整模型；已有文件与执行记录保留'};
    }
    return {title:'等待补充信息',detail:'回复下方问题后继续；已有执行记录保留'};
  }
  let active = null;
  function clear() {
    if (active) active.dialog.close();
    document.getElementById('effective-model-summary')?.remove();
  }
  function metadata(profile, provenance) {
    const box = el('div', undefined, 'effective-model-card');
    box.append(el('strong', profile?.model || '模型未记录'), el('span', provenance, 'experience-muted'));
    const grid = el('dl', undefined, 'effective-model-grid');
    for (const [label, value] of [['上下文窗口', number(profile?.context_window_tokens)],
      ['最大输出', number(profile?.max_output_tokens)]]) {
      const item = el('div'); item.append(el('dt', label), el('dd', value + (value === '未记录' ? '' : ' Tokens'))); grid.append(item);
    }
    box.append(grid);
    return box;
  }
  function recordedProfile(data) {
    const profile = {...data.profile}, budget = data.context_budget;
    // Legacy events recorded these values in the same event's budget.
    // Never consult today's model settings or infer unrecorded parameters.
    if (typeof budget?.tokenizer_model === 'string' && budget.tokenizer_model === profile.model) {
      profile.context_window_tokens ??= budget.context_window_tokens;
      profile.max_output_tokens ??= budget.output_reserve_tokens;
    }
    return profile;
  }
  function model(profile) {
    const anchor = document.querySelector('.model-profile-picker');
    if (!anchor || !profile || !state.me) return;
    let section = document.getElementById('effective-model-summary');
    if (!section) { section = el('section'); section.id = 'effective-model-summary'; anchor.after(section); }
    section.replaceChildren(metadata(profile, profile.source === 'builtin' ? '新任务使用 · 内置服务配置'
      : profile.storage === 'account_encrypted' ? '新任务使用 · 已保存的连接配置' : '新任务使用 · 当前连接配置'),
      el('p', '账号默认值只初始化新连接；历史任务以各轮执行记录为准。这里是运行时配置，不是供应商容量认证。', 'experience-muted'));
  }
  function attach(rid, ui) {
    if (ui.overview) return;
    const box = el('section', undefined, 'run-overview'); box.setAttribute('aria-label', '任务执行概况');
    const heading = el('strong', ui.finished ? terminal(ui.status) : '任务已接收', 'run-action-title');
    const target = el('span', '', 'run-action-target'); target.hidden = true;
    const copy = el('div', undefined, 'run-action-copy');
    copy.setAttribute('role', 'status'); copy.setAttribute('aria-live', 'polite'); copy.setAttribute('aria-atomic', 'true');
    copy.append(heading, target);
    const indicator = el('span', '', 'run-action-indicator'); indicator.setAttribute('aria-hidden', 'true');
    const line = el('div', undefined, 'run-overview-line'); line.append(indicator, copy);
    if (ui.elapsed) line.append(ui.elapsed);
    const summaryMeta = el('div', undefined, 'run-summary-meta');
    const currentStage = el('span', '当前阶段 · 等待执行记录', 'run-current-stage');
    const milestoneCount = el('span', '关键里程碑 · 0', 'run-milestone-count');
    summaryMeta.append(currentStage, milestoneCount);
    const openItems = el('details', undefined, 'run-open-items'); openItems.hidden = true; openItems.open = false;
    const openSummary = el('summary', '未完成事项 · 0'), openList = el('ul');
    openSummary.setAttribute('aria-label', '本轮未完成事项'); openItems.append(openSummary, openList);
    const counts = el('span', '等待执行记录', 'experience-muted');
    const technical = el('div', undefined, 'run-technical-details'); technical.append(counts);
    const details = el('details', undefined, 'run-model-details'); details.append(el('summary', '本轮模型参数'));
    const body = el('div'); body.append(el('p', '执行事件尚未提供模型参数，不使用当前连接的值替代。', 'experience-muted'));
    details.append(body); technical.append(details); ui.activity.append(technical);
    const milestones = el('ul', undefined, 'run-milestones');
    milestones.hidden = true;
    milestones.setAttribute('aria-label', '阶段成果');
    const preview = el('section', undefined, 'run-draft-preview');
    preview.hidden = true;
    preview.setAttribute('aria-label', '答复草稿');
    const draftLabel = el('p', '草稿 · 正在生成', 'run-draft-label');
    const draftText = el('div', '', 'run-draft-text');
    draftText.setAttribute('aria-live', 'off');
    const draftBody = document.createTextNode('');
    draftText.append(draftBody);
    preview.append(draftLabel, draftText);
    const researchNote = el('p', '', 'run-research-note');
    researchNote.hidden = true;
    box.append(line, summaryMeta, openItems, milestones, researchNote);
    ui.activity.before(box);
    const findings = el('section', undefined, 'run-findings');
    findings.hidden = true;
    findings.setAttribute('aria-label', '已确认的阶段发现');
    findings.setAttribute('aria-live', 'polite');
    ui.answer.before(findings, preview);
    ui.overview = {box, heading, target, counts, body, calls:new Map(), turn:0,
      milestones, milestoneCount, currentStage, openItems, openSummary, openList, interrupted:new Map(), knowledgeIssue:false, timing:null, phase:'',
      findings, findingsByKey:new Map(), shownPages:0, findingFiles:new Map(),
      researchNote, preview, draftLabel, draftBody, pendingDraft:null, visibleDraft:null, sourceUrls:new Set(),
      facts:{knowledgeCount:null, pagesRead:0, reviewed:false},
      action:{title:'任务已接收', detail:'正在准备执行'}, sequence:-1, connection:''};
    box.dataset.state = ui.finished ? ui.status : 'working';
    if (ui.summary) ui.summary.textContent = '查看执行详情';
    ui.overview.reason = ui.reason?.textContent || '';
    paintActivity(ui);
  }
  // Labels describe observed operations, never model thoughts or guessed plans.
  const operations = {
    skill_find:'正在查找适用的分析方法', skill_load:'正在读取技能说明',
    read_file:'正在读取文件', write_file:'正在保存文件', execute_python:'正在运行计算程序',
    web_search:'正在搜索公开资料', web_fetch:'正在读取网页资料',
    context_search:'正在检索历史上下文', context_read:'正在读取历史上下文',
    request_user_input:'正在准备需要你确认的问题',
    GeoIllustration:'正在绘制图件', GeoImageInspect:'正在检查影像尺寸、波段和坐标信息',
    GeoImageTransform:'正在处理图片', GeoRasterPreview:'正在生成栅格预览',
    GeoImageAnalyze:'正在解读影像内容', GeoRasterChangeAnalysis:'正在分析两期影像变化',
    GeoMapColorExtract:'正在提取图例颜色对应的候选区域', GeoPlotDigitize:'正在提取并标定图中曲线',
    GeoOrdinaryKrigingGrid:'正在进行克里金插值', GeoExactZonalStatistics:'正在计算区域统计',
    GeoMagnitudeToEnergy:'正在估算地震释放能量', GeoHaversineDistance:'正在计算地理距离',
    GeoBearing:'正在计算初始方位角',
    MineralResourcesSearchDeposits:'正在检索矿床记录', MineralResourcesGetDeposit:'正在读取矿床详情',
    MineralResourcesCountrySummary:'正在汇总矿产记录', MineralResourcesRankCommodityCountries:'正在比较各国矿产记录',
    DeepEarthQueryLITHO1:'正在查询地球结构模型节点', DeepEarthQuerySEMUCB:'正在查询地震波速度样本'
  };
  const indices = {NDVI:'NDVI 植被指数', NDWI:'NDWI 水体指数', NBR:'NBR 归一化燃烧比', NDTI:'NDTI 归一化差异浊度指数'};
  const text = value => typeof value === 'string' ? value.replace(/[\x00-\x1f\x7f]/g, ' ').trim().slice(0, 180) : '';
  function toolAction(name, args = {}) {
    if (typeof args === 'string') {
      try { args = JSON.parse(args); } catch { args = {}; }
    }
    name = text(name); args = args && typeof args === 'object' && !Array.isArray(args) ? args : {};
    let title = operations[name];
    if (name === 'GeoRasterIndexAnalysis') title = indices[args.index] ? '正在计算 ' + indices[args.index] : '正在计算遥感指数';
    if (name.startsWith('RemoteSensing') && indices[name.slice(13)]) title = '正在计算 ' + indices[name.slice(13)];
    if (!title) {
      const suffixes = {InterpolateIDW:'正在进行反距离加权插值', RasterAlgebra:'正在计算栅格代数',
        ZonalStatistics:'正在计算分区统计', RenderMap:'正在绘制地图', CloudMask:'正在应用影像质量掩膜',
        LinearTrend:'正在计算线性趋势', SensSlope:'正在估计稳健趋势斜率', MannKendallTest:'正在检验趋势显著性'};
      title = Object.entries(suffixes).find(([suffix]) => name.endsWith(suffix))?.[1];
    }
    const paths = [...new Set(['path','source','dataset_path','input_path','raster_path','before_path','after_path']
      .map(key => args[key]).filter(value => safeName(value)).map(text))];
    let detail = paths.slice(0, 2).join(' · ');
    if (name === 'web_search') detail = text(args.query);
    if (name === 'web_fetch') {
      try {
        const url = new URL(args.url);
        if (['http:', 'https:'].includes(url.protocol)) detail = url.hostname;
      } catch { /* An incomplete tool argument has no destination to show. */ }
    }
    if (name === 'skill_load') detail = text(args.skill_id);
    if (name === 'skill_find') detail = '正在匹配已登记的技能与工具';
    if (name === 'context_search') detail = text(args.query);
    if (name === 'context_read') detail = text(args.name || args.path);
    if (name === 'execute_python') detail = 'Python · 以实际运行结果为准';
    return {title:title || '正在执行工具', detail:detail || name};
  }
  function stageAction(data, view) {
    if (['Correcting a model response','Retrying the completion check'].includes(data.message) && view.issue) return issueAction(view.issue.category);
    if (data.message === 'Stopping the task; keeping the last committed files') {
      return {title:'正在停止任务', detail:'已保存的文件会保留'};
    }
    if (data.message === 'Compacting context') return {title:'正在整理历史上下文', detail:'保留原始执行记录和工具证据'};
    if (data.message === 'Preparing answer') return {title:'正在整理答复', detail:'根据已有执行结果组织说明与成果链接'};
    if (data.message === 'Checking the result') {
      const title = ({
        human_input:'正在判断是否需要补充信息',
        knowledge_semantics:'正在核对结论与文献是否一致',
        answer:'正在核对答复和引用',
        final_answer:'正在核对答复与原始证据',
      })[data.phase] || '正在检查执行结果';
      return {title, detail:''};
    }
    if (data.message === 'Correcting the result') return {title:'正在处理结果检查发现的问题', detail:'不会将未通过检查的内容当作最终结果'};
    if (data.message === 'Correcting a model response') return {title:'正在修正模型响应格式', detail:'不执行格式无效的工具调用'};
    if (data.message === 'Retrying the completion check') return {title:'正在重新检查完成情况', detail:''};
    if (['Starting an isolated task environment', 'Running in the service account environment (OS isolation disabled)'].includes(data.message)) {
      return {title:'正在准备执行', detail:''};
    }
    if (data.message === 'Model is working' || data.message === 'GeoGPT is working') {
      const title = ({
        intent:'正在理解任务要求',
        source_selection:'正在选择资料来源',
        source_relevance:'正在筛选相关资料',
        vision:'正在解读影像内容',
      })[data.phase] || (view.calls.size ? '正在综合已有结果' : '正在规划分析步骤');
      return {title, detail:''};
    }
    return {title:'正在处理任务', detail:''};
  }
  function setProgressLayout(ui, compact) {
    const box = ui.overview.box, layout = compact ? 'compact' : 'detailed';
    if (box.dataset.layout === layout) return;
    box.dataset.layout = layout;
    if (compact) box.append(ui.activity);
    else box.after(ui.activity);
    if (ui.timing) (compact ? ui.activity : box).append(ui.timing.root);
  }
  function paintActivity(ui) {
    const view = ui.overview, running = [...view.calls.values()].filter(call => call.status === 'running');
    let action = view.action, status = 'working';
    if (ui.finished || !['running', 'stopping'].includes(ui.status)) {
      status = ui.status;
      action = terminalAction(ui.status, view.reason, view.outcome);
    } else if (ui.status === 'stopping') {
      status = 'stopping'; action = {title:'正在停止任务', detail:'等待当前操作安全结束'};
    } else if (view.connection) {
      status = 'reconnecting'; action = {title:view.connection === 'failed' ? '执行状态连接中断' : '连接中断，正在重连',
        detail:'暂时无法确认最新进度；已有记录保留'};
    } else if (running.length) {
      action = running[running.length - 1].action;
      if (running.length > 1) action = {...action, detail:action.detail + ' · 另有 ' + (running.length - 1) + ' 项操作尚未返回'};
    }
    const compact = ui.mode === 'ask' && !ui.hasExtendedProgress;
    setProgressLayout(ui, compact);
    if (compact && status === 'working' && !view.issue) {
      const checking = /^正在(?:检查|核对|处理.*问题|重新检查)/.test(action.title);
      if (action.title !== '任务已接收' && action.title !== '正在停止任务') {
        action = {title:checking ? '正在核对' : '正在生成答复', detail:''};
      }
    }
    if (view.heading.textContent !== action.title) view.heading.textContent = action.title;
    if (view.target.textContent !== action.detail) view.target.textContent = action.detail;
    view.target.hidden = !action.detail; view.box.dataset.state = status;
    paintSummary(view, ui);
  }
  const stageLabels = {
    runtime:'准备与调度', queue:'排队等待', model_wait:'等待模型响应', model_stream:'接收模型输出',
    tools:'执行工具', retrieval:'检索资料', review_wait:'等待结果审核', review_stream:'接收审核输出',
    publishing:'保存成果', context_compaction:'整理上下文'
  };
  const phaseLabels = {intent:'理解任务要求', source_selection:'选择资料来源', source_relevance:'筛选相关资料', vision:'解读影像内容',
    execution:'执行分析', review:'核对结果', final_answer:'整理答复', human_input:'确认补充信息', knowledge_semantics:'核对文献与结论'};
  function paintSummary(view, ui) {
    const stage = view.timing?.active || view.phase;
    const stageText = view.timing?.active ? stageLabels[stage] : phaseLabels[stage];
    view.currentStage.textContent = '当前阶段 · ' + (ui.finished ? '本轮已结束' : stageText || '等待执行记录');
    const milestoneCount = Number(view.facts.knowledgeCount > 0) + Number(view.sourceUrls.size > 0)
      + Number(view.facts.pagesRead > 0) + Number(view.facts.reviewed);
    view.milestoneCount.textContent = '关键里程碑 · ' + milestoneCount;
    const items = [];
    if (ui.status !== 'completed') {
      if (view.issue) items.push({key:'issue', label:'运行检查仍需处理：' + issueAction(view.issue.category).title});
      if (view.knowledgeIssue) items.push({key:'knowledge', label:'知识库检索未成功，可重试或改用其他来源'});
      const calls = new Map();
      for (const call of view.calls.values()) {
        if (call.status === 'ok') continue;
        const name = call.name || '工具';
        const group = calls.get(name) || {failed:0, running:0, unknown:0, retryable:false};
        if (call.status === 'running') group.running++;
        else if (call.status === 'unknown') group.unknown++;
        else { group.failed++; group.retryable ||= call.retryable === true; }
        calls.set(name, group);
      }
      for (const [name, group] of calls) {
        const state = [group.failed ? group.failed + ' 次未完成' : '', group.running ? group.running + ' 次执行中' : '', group.unknown ? group.unknown + ' 次结果未记录' : ''].filter(Boolean).join(' · ');
        items.push({key:'tool:' + name, label:name + ' · ' + state + (group.retryable ? ' · 可重试' : '')});
      }
      for (const [id, phase] of view.interrupted) items.push({key:'stream:' + id, label:'模型响应中断 · ' + (phaseLabels[phase] || phase || '执行阶段')});
      if (ui.finished && ui.status !== 'completed') items.push({key:'terminal', label:'本轮尚未交付完整结果，可在执行记录中查看中断位置和下一步操作'});
    }
    const signature = JSON.stringify(items);
    if (view.openItems.dataset.signature === signature) return;
    view.openItems.dataset.signature = signature;
    view.openSummary.textContent = '未完成事项 · ' + items.length;
    view.openList.replaceChildren(...items.map(item => el('li', item.label)));
    view.openItems.hidden = !items.length;
  }
  function paintMilestones(view, ui) {
    const facts = view.facts;
    const labels = [];
    if (facts.knowledgeCount > 0) labels.push('找到 ' + facts.knowledgeCount + ' 个知识库片段');
    if (view.sourceUrls.size) labels.push('找到 ' + view.sourceUrls.size + ' 条候选网页');
    if (facts.pagesRead) labels.push('完成 ' + facts.pagesRead + ' 次网页读取');
    if (facts.reviewed && view.box.dataset.layout !== 'compact') labels.push('本轮审核已通过');
    const current = [...view.milestones.children].map(node => node.textContent);
    if (current.length !== labels.length || labels.some((label, index) => label !== current[index])) {
      view.milestones.replaceChildren(...labels.map(label => el('li', label)));
      view.milestones.hidden = !labels.length;
    }
    paintSummary(view, ui);
  }
  function recordPublicSources(view, results) {
    for (const result of results) {
      try {
        const url = new URL(result?.url);
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) continue;
        url.hash = '';
        view.sourceUrls.add(url.href);
      } catch { /* A search result without a valid URL is not counted as a webpage. */ }
    }
  }
  function finding(view, key, label, content) {
    if (view.findingsByKey.has(key)) return;
    const entry = el('article', undefined, 'run-finding');
    const heading = el('p', label, 'run-finding-label');
    entry.append(heading, content);
    view.findingsByKey.set(key, heading);
    view.findings.append(entry);
    view.findings.hidden = false;
    return heading;
  }
  function pageFinding(view, output) {
    const content = typeof output.content === 'string' ? output.content.trim() : '';
    if (!content || view.shownPages >= 3 || output.offset > 0) return;
    const url = window.GeoAgentTimeline?.sourceURL(output.url);
    if (!url) return;
    url.hash = '';
    const key = 'page:' + url.href;
    if (view.findingsByKey.has(key)) return;
    const titleLine = content.split(/\r?\n/, 1)[0].replace(/^#{1,6}\s+/, '');
    const link = el('a', text(titleLine) || url.hostname);
    link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    const body = el('div'); body.append(link);
    const abstract = /(?:^|\n)\s*(?:#{1,6}\s*)?Abstract\s*[:\n]\s*(\S[^\n]+)/i.exec(content)?.[1];
    if (abstract) {
      const excerpt = text(abstract);
      body.append(el('blockquote', excerpt + (abstract.length > excerpt.length ? '…' : '')));
    }
    finding(view, key, abstract ? '已读取来源 · 摘要摘录' : '已读取来源', body);
    view.shownPages++;
  }
  function toolFinding(ui, receipt) {
    if (ui.mode !== 'agent' || receipt?.status !== 'ok') return;
    const view = ui.overview, output = receipt.data;
    if (receipt.name === 'web_fetch' && output) pageFinding(view, output);
    const artifacts = Array.isArray(receipt.artifacts) ? receipt.artifacts : [];
    const paths = artifacts.map(item => item?.path).filter(path => safeName(path) && !path.startsWith('.'));
    const fresh = [...new Set(paths)].filter(path => !view.findingFiles.has(path));
    if (!fresh.length) return;
    const images = fresh.every(path => /\.(?:png|jpe?g|svg|webp|tiff?)$/i.test(path));
    const label = finding(view, 'files:' + fresh.join('\n'), images ? '已生成图件' : '已生成文件', el('p', fresh.join(' · ')));
    for (const name of fresh) view.findingFiles.set(name, {label, paths:fresh, images});
    markSavedFindings(ui, ui.resultContext);
  }
  function markSavedFindings(ui, context) {
    if (!context?.generation || !ui.overview) return;
    const saved = new Set(manifest(context).map(file => file.name));
    for (const {label, paths, images} of new Set(ui.overview.findingFiles.values())) {
      if (paths.every(name => saved.has(name))) label.textContent = images ? '图件已保存' : '文件已保存';
    }
  }
  function showDraft(view, draft, label) {
    view.visibleDraft = draft;
    view.draftBody.data = draft.text;
    view.draftLabel.textContent = label;
    view.preview.hidden = false;
  }
  function updateDraft(ui, data) {
    if (!['execution','final_answer'].includes(data.phase) || data.channel !== 'text' ||
        data.verified !== false || !data.request_id || typeof data.text !== 'string') return;
    const view = ui.overview;
    let draft = view.pendingDraft;
    if (draft?.id !== data.request_id) {
      if (data.offset !== 0) return;
      draft = view.pendingDraft = {id:data.request_id, chars:0, text:''};
    }
    if (draft.chars !== data.offset) return;
    draft.chars += Array.from(data.text).length;
    draft.text += data.text;
    if (view.visibleDraft === draft) {
      view.draftBody.appendData(data.text);
      return;
    }
    if (view.visibleDraft || !draft.text.trim()) return;

    // Research turns can narrate a tool call before they begin drafting.
    // A leading heading with body text can be shown as a provisional draft.
    const shortAnswer = ui.mode === 'ask' && !ui.hasExtendedProgress;
    const startsReport = /^\s*#{1,3}[ \t]+\S[^\n]*\n\s*\S/.test(draft.text);
    if (shortAnswer || startsReport || data.phase === 'final_answer') {
      showDraft(view, draft, '草稿 · 正在生成');
    }
  }
  function finishDraft(view, data) {
    const draft = view.pendingDraft;
    if (!draft || draft.id !== data.request_id) return;
    view.pendingDraft = null;
    const callsTools = data.native_tool_calls > 0 || data.finish_reason === 'tool_calls';
    if (callsTools || data.complete === false) {
      if (view.visibleDraft === draft) {
        view.visibleDraft = null;
        view.preview.hidden = true;
        view.draftBody.data = '';
      }
      if (callsTools && draft.text.trim()) {
        const chars = Array.from(draft.text.trim());
        view.researchNote.textContent = '调研进展 · ' + chars.slice(0, 320).join('') + (chars.length > 320 ? '…' : '');
        view.researchNote.hidden = false;
      }
      return;
    }
    if (view.visibleDraft === draft) {
      view.draftLabel.textContent = '草稿 · 待核对';
    } else if (!view.visibleDraft && data.complete === true && draft.text.trim()) {
      showDraft(view, draft, '草稿 · 待核对');
    }
  }
  function event(rid, data, eventId) {
    const ui = state.runs.get(rid); if (!ui) return;
    attach(rid, ui); const view = ui.overview;
    const sequence = typeof eventId === 'string' && /^\d+$/.test(eventId) ? Number(eventId) : null;
    if (Number.isSafeInteger(sequence)) {
      if (sequence <= view.sequence) return;
      view.sequence = sequence;
    }
    if (data.kind === 'connection_lost' || data.kind === 'connection_failed') view.connection = data.kind === 'connection_failed' ? 'failed' : 'reconnecting';
    else view.connection = '';
    if (data.kind === 'diagnostic') { view.issue = data; if (!ui.finished) view.action = issueAction(data.category); }
    if (data.kind === 'stage_timing') {
      view.timing = data;
      if (!data.active) view.phase = '';
    }
    if (data.kind === 'review_result') {
      view.facts.reviewed = data.passed === true;
      if (data.passed === true) {
        view.issue = null;
        if (!ui.finished) view.action = {title:'本轮审核已通过', detail:'正在准备交付'};
      }
    }
    if (data.kind === 'knowledge_start' && !ui.finished) {
      view.action = {title:'正在查找知识库资料', detail:''};
    }
    if (data.kind === 'knowledge_sources' && Array.isArray(data.references)) {
      view.knowledgeIssue = data.status === 'unavailable';
      if (data.status !== 'unavailable') view.facts.knowledgeCount = data.references.length;
      if (ui.mode === 'agent' && data.status !== 'unavailable' && data.references.length) {
        const titles = [...new Set(data.references.map(ref => text(ref?.title)).filter(Boolean))];
        const message = '检索返回 ' + data.references.length + ' 个片段' + (titles.length ? '，包括《' + titles[0] + '》。' : '。');
        finding(view, 'knowledge', '知识库检索', el('p', message));
      }
      if (!ui.finished) view.action = data.status === 'unavailable'
        ? {title:'知识库暂不可用，正在继续任务', detail:''}
        : {title:'知识库检索已返回', detail:data.references.length ? '' : '本次未返回相关片段'};
    }
    if (['knowledge_start','knowledge_sources','tool_start','tool_result','skill_selected'].includes(data.kind)
        || (data.kind === 'stage_timing' && (data.active === 'retrieval' || data.totals_seconds?.retrieval))) {
      ui.hasExtendedProgress = true;
    }
    if (data.kind === 'stream_delta' && !ui.finished) {
      updateDraft(ui, data);
      return;
    }
    if (data.kind === 'stream_end' && !ui.finished) {
      if (data.request_id && data.complete === false) view.interrupted.set(data.request_id, data.phase || 'execution');
      else if (data.request_id) view.interrupted.delete(data.request_id);
      if (data.native_tool_calls > 0 || data.finish_reason === 'tool_calls') ui.hasExtendedProgress = true;
      finishDraft(view, data);
    }
    if (data.kind === 'status' && /Checking the result|Correcting the result|Retrying the completion check/.test(data.message)) {
      view.draftLabel.textContent = '草稿 · 正在核对';
    }
    if (data.kind === 'run_outcome') view.outcome = data;
    if (data.kind === 'model_config') view.body.replaceChildren(metadata(recordedProfile(data), '本轮实际使用 · 执行事件快照'));
    if (data.kind === 'status') {
      if (!ui.finished && data.phase) view.phase = data.phase;
      if (!ui.finished) view.action = stageAction(data, view);
      if (Number.isSafeInteger(data.turn)) view.turn = Math.max(view.turn, data.turn);
    }
    if (data.kind === 'context_compacted' && !ui.finished) view.action = {title:'上下文已整理，准备继续任务', detail:'原始记录和工具证据保留'};
    if ((data.kind === 'tool_start' || data.kind === 'tool_result') && typeof data.id === 'string') {
      const previous = view.calls.get(data.id) || {};
      if (data.kind === 'tool_start') view.calls.set(data.id, {...previous, name:data.name,
        action:previous.action || toolAction(data.name, data.arguments), status:previous.status || 'running'});
      else {
        const ok = data.result?.status === 'ok', cached = data.cached === true || data.result?.cached === true;
        toolFinding(ui, data.result);
        view.calls.set(data.id, {...previous, name:previous.name || data.name || data.result?.name,
          status:ok ? 'ok' : 'error', cached, retryable:data.result?.error?.retryable === true});
        const name = previous.name || data.name || data.result?.name;
        if (ok && name === 'web_search' && Array.isArray(data.result?.data?.results)) {
          recordPublicSources(view, data.result.data.results);
        }
        if (ok && name === 'web_fetch' && previous.status !== 'ok') view.facts.pagesRead++;
        view.action = ok && name === 'web_search'
          ? {title:'网页检索已返回', detail:''}
          : ok && name === 'web_fetch'
            ? {title:'网页内容已返回', detail:''}
            : {title:ok ? cached ? '已复用工具结果，准备下一步' : '工具处理完成，准备下一步'
              : '这一步未完成，正在判断下一步', detail:previous.action?.detail || text(name)};
      }
    }
    if (data.kind === 'finished') {
      for (const [id, call] of view.calls) {
        if (call.status === 'running') view.calls.set(id, {...call, status:'unknown'});
      }
    }
    const calls = [...view.calls.values()];
    const count = status => calls.filter(call => call.status === status).length;
    view.counts.textContent = calls.length
      ? calls.length + ' 次工具调用 · ' + count('ok') + ' 成功'
        + (count('error') ? ' · ' + count('error') + ' 失败' : '')
        + (count('running') ? ' · ' + count('running') + ' 执行中' : '')
        + (count('unknown') ? ' · ' + count('unknown') + ' 结果未记录' : '')
        + (calls.some(call => call.cached) ? ' · ' + calls.filter(call => call.cached).length + ' 复用' : '')
      : '尚无工具执行记录';
    if (view.turn) view.counts.textContent += ' · 执行轮次 ' + view.turn;
    if (data.kind === 'finished') {
      ui.status = data.status || ui.status; ui.finished = true;
      view.reason = data.reason || ui.reason?.textContent || view.reason || '';
      if (Number.isSafeInteger(data.turns)) view.turn = Math.max(view.turn, data.turns);
      view.preview.hidden = true;
      view.draftBody.data = '';
      view.pendingDraft = view.visibleDraft = null;
      view.researchNote.hidden = true;
    }
    paintActivity(ui);
    if (['knowledge_sources','tool_result','review_result','finished'].includes(data.kind)) paintMilestones(view, ui);
  }
  function openEvidence(ui) {
    const panel = ui?.rich?.panel;
    if (!panel || active) return;
    const dialog = el('dialog', undefined, 'results-drawer'), head = el('header', undefined, 'results-drawer-head');
    const title = el('h2', '工具证据'); title.id = 'results-evidence-title';
    dialog.setAttribute('aria-labelledby', title.id);
    head.append(title, btn('关闭工具证据', () => dialog.close(), 'quiet'));
    const body = el('div', undefined, 'results-drawer-body'), originalHidden = panel.hidden;
    panel.hidden = false; body.append(panel); dialog.append(head, body);
    const record = {dialog};
    dialog.addEventListener('close', () => {
      ui.rich.root.append(panel); panel.hidden = originalHidden;
      dialog.remove(); if (active === record) active = null;
    });
    active = record; document.body.append(dialog); dialog.showModal();
  }
  function openFiles(context, selected, ui) {
    if (!valid(context)) return;
    const files = manifest(context);
    const evidence = context.blocks?.some(block => block.component !== 'sources') && ui?.rich
      ? () => openEvidence(ui) : null;
    if (files.length) window.GeoAgentArtifacts.openFile({...context, files}, selected, undefined, evidence);
    else if (evidence) evidence();
  }
  function results(rid, ui, context) {
    if (!valid(context) || state.runs.get(rid) !== ui) return;
    ui.resultContext = context; ui.rich.root.classList.add('has-results-panel');
    markSavedFindings(ui, context);
    const images = [...ui.answer.querySelectorAll('.answer-image')];
    images.forEach((node, index) => node.classList.toggle('is-secondary', index > 0));
    if (!ui.rich.compact) {
      ui.rich.compact = el('section', undefined, 'results-compact');
      ui.rich.toolbarPlaceholder = ui.rich.root.querySelector('.rich-toolbar');
      ui.rich.toolbarPlaceholder.after(ui.rich.compact);
    }
    const signature = JSON.stringify([context.generation, context.files, context.blocks.map(block => block.id), images.length]);
    if (ui.rich.compact.dataset.signature === signature) return;
    ui.rich.compact.dataset.signature = signature; ui.rich.compact.replaceChildren();
    const files = manifest(context), imageFiles = files.filter(imageFile);
    const info = el('div', undefined, 'results-compact-info');
    info.append(el('span', '已保存的成果', 'experience-eyebrow'),
      el('strong', files.length + ' 个文件 · ' + imageFiles.length + ' 幅图像'),
      el('p', '预览、下载和原始工具证据集中查看。', 'experience-muted'),
      btn('查看全部成果', () => open(rid, ui)));
    ui.rich.compact.append(info);
    if (!images.length && imageFiles.length) {
      const file = imageFiles.find(item => /\.(png|jpe?g|webp|svg)$/i.test(item.name)) || imageFiles[0];
      const show = btn('', () => openFiles(context, file.name, ui), 'results-cover');
      show.setAttribute('aria-label', '预览成果：' + file.name);
      const image = el('img'); image.src = url(context, file, 'image'); image.alt = file.name; image.loading = 'lazy';
      image.addEventListener('error', () => show.replaceChildren(el('span', '预览不可用，点击查看下载。')));
      show.append(image); ui.rich.compact.append(show);
    }
    ui.rich.compact.hidden = !files.length;
  }
  function open(rid, ui) {
    if (state.runs.get(rid) !== ui || !ui.resultContext) return;
    openFiles(ui.resultContext, undefined, ui);
  }
  window.GeoAgentExperience = {attach, event, model, results, open, files:openFiles, clear, describeTool:toolAction, classifyIssue};
  if (typeof state !== 'undefined' && state.me) {
    for (const [rid, ui] of state.runs) attach(rid, ui);
    if (typeof modelSettings !== 'undefined' && modelSettings) model(modelSettings);
  }
})();

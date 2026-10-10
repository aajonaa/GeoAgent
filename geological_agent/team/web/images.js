'use strict';
// Answer links resolve only against the authenticated, immutable run manifest.
// No model-written HTML, filesystem URL, or remote image is executed or loaded.
(() => {
  let sequence = 0;
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
  function preview(label, src, downloadURL, name) {
    const dialog = element('dialog', undefined, 'answer-image-dialog');
    const title = element('h2', label), head = element('header', undefined, 'image-dialog-header');
    title.id = 'answer-image-title-' + (++sequence); dialog.setAttribute('aria-labelledby', title.id);
    const close = element('button', '关闭', 'quiet'); close.type = 'button'; close.addEventListener('click', () => dialog.close());
    head.append(title, close);
    const viewport = element('div', undefined, 'image-viewport'), image = element('img');
    viewport.classList.toggle('is-svg', /\.svg$/i.test(name));
    image.src = src; image.alt = label; viewport.append(image);
    image.addEventListener('error', () => viewport.replaceChildren(element('p', '预览不可用，请下载原图。', 'image-failed')));
    const actions = element('div', undefined, 'image-actions'), zoom = element('button', '原尺寸查看', 'outline'), download = element('a', '下载原图');
    zoom.type = 'button'; zoom.addEventListener('click', () => {
      const expanded = viewport.classList.toggle('is-zoomed'); zoom.textContent = expanded ? '适应窗口' : '原尺寸查看'; zoom.setAttribute('aria-pressed', String(expanded));
    });
    download.href = downloadURL; download.download = name.split('/').pop(); actions.append(zoom, download);
    dialog.append(head, viewport, actions); dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog); dialog.showModal();
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
      const href = fileURL(context, name, 'download'), link = element('a', label, 'answer-file-link');
      link.href = href; link.download = name.split('/').pop();
      if (!/\.(png|jpe?g|webp|tiff?|svg)$/i.test(name)) return link;
      const wrap = element('span', undefined, 'answer-image'), show = element('button', undefined, 'answer-image-open'), img = element('img');
      const src = fileURL(context, name, 'image');
      show.type = 'button'; show.setAttribute('aria-label', '放大图片：' + label);
      img.src = src; img.alt = label; img.loading = 'lazy'; img.decoding = 'async'; show.append(img);
      const open = () => preview(label, src, href, name); show.addEventListener('click', open);
      const actions = element('span', undefined, 'answer-image-actions'), zoom = element('button', '放大查看', 'quiet'), download = element('a', '下载原图');
      zoom.type = 'button'; zoom.setAttribute('aria-label', '放大查看：' + label); zoom.addEventListener('click', open);
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
  window.GeoAgentArtifacts = {renderLink, preview};
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
  function clear() { window.GeoAgentExperience?.clear(); files = []; cid = null; generation = ''; if (dialog.open) dialog.close(); for (const preview of document.querySelectorAll('.answer-image-dialog')) preview.close(); document.getElementById('image-gallery')?.remove(); for (const p of panels) { p.image.removeAttribute('src'); p.select.replaceChildren(); p.download.removeAttribute('href'); } }
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
  const format = name => name.split('.').pop().toUpperCase();
  const size = bytes => Number.isFinite(bytes) && bytes >= 0
    ? (bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MiB' : (bytes / 1024).toFixed(1) + ' KiB') : '大小未记录';
  const terminal = status => ({completed:'已完成',needs_input:'等待补充信息',stopped:'已停止',failed:'执行失败',paused:'已暂停',stopping:'正在停止',budget_exhausted:'运行预算已耗尽',incomplete:'尚未完成'})[status] || '状态待确认';
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
    if (status !== 'needs_input') return {title:terminal(status),detail:''};
    const category = outcome?.failure_category || classifyIssue(reason);
    if (outcome?.recovery_required || category) {
      const review = outcome?.business_state === 'review_blocked' || ['review_evidence','review_format','answer_validation','verification_error'].includes(category);
      return {title:review?'审核受阻，等待恢复':'模型调用受阻，等待恢复',
        detail:category === 'review_evidence'?'审核证据尚未补齐；可重试审核，不需要补充研究资料':'可在下方重试或调整模型；已有文件与执行记录保留'};
    }
    return {title:'等待补充信息',detail:'回复下方问题后继续；已有执行记录保留'};
  }
  let active = null, serial = 0;
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
    const heading = el('strong', ui.finished ? terminal(ui.status) : '正在准备任务', 'run-action-title');
    const target = el('span', '', 'run-action-target'); target.hidden = true;
    const copy = el('div', undefined, 'run-action-copy');
    copy.setAttribute('role', 'status'); copy.setAttribute('aria-live', 'polite'); copy.setAttribute('aria-atomic', 'true');
    copy.append(heading, target);
    const indicator = el('span', '', 'run-action-indicator'); indicator.setAttribute('aria-hidden', 'true');
    const line = el('div', undefined, 'run-overview-line'); line.append(indicator, copy);
    if (ui.elapsed) line.append(ui.elapsed);
    const counts = el('span', '等待执行记录', 'experience-muted');
    const technical = el('div', undefined, 'run-technical-details'); technical.append(counts);
    const details = el('details', undefined, 'run-model-details'); details.append(el('summary', '本轮模型参数'));
    const body = el('div'); body.append(el('p', '执行事件尚未提供模型参数，不使用当前连接的值替代。', 'experience-muted'));
    details.append(body); technical.append(details); ui.activity.append(technical);
    box.append(line); ui.activity.before(box);
    ui.overview = {box, heading, target, counts, body, calls:new Map(), turn:0,
      action:{title:'正在准备任务', detail:''}, sequence:-1, connection:''};
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
    request_user_input:'正在准备需要你确认的问题',
    GeoImageInspect:'正在检查影像尺寸、波段和坐标信息',
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
    if (name === 'skill_load') detail = text(args.skill_id);
    if (name === 'skill_find') detail = '正在匹配已登记的技能与工具';
    if (name === 'execute_python') detail = 'Python · 以实际运行结果为准';
    return {title:title || '正在执行工具', detail:detail || name};
  }
  function stageAction(data, view) {
    if (['Correcting a model response','Retrying the completion check'].includes(data.message) && view.issue) return issueAction(view.issue.category);
    if (data.message === 'Compacting context') return {title:'正在整理历史上下文', detail:'保留原始执行记录和工具证据'};
    if (data.message === 'Preparing answer') return {title:'正在整理答复', detail:'根据已有执行结果组织说明与成果链接'};
    if (data.message === 'Checking the result') return {title:data.phase === 'human_input'
      ? '正在检查是否需要你补充信息' : data.phase === 'final_answer' ? '正在核对答复与原始证据' : '正在检查结果', detail:''};
    if (data.message === 'Correcting the result') return {title:'正在处理结果检查发现的问题', detail:'不会将未通过检查的内容当作最终结果'};
    if (data.message === 'Correcting a model response') return {title:'正在修正模型响应格式', detail:'不执行格式无效的工具调用'};
    if (data.message === 'Retrying the completion check') return {title:'正在重新检查完成情况', detail:''};
    if (data.message === 'Starting an isolated task environment') return {title:'正在准备任务执行环境', detail:''};
    if (data.message === 'Running in the service account environment (OS isolation disabled)')
      return {title:'正在准备任务执行环境', detail:'使用服务账号环境，未启用系统沙箱'};
    if (data.message === 'Model is working' || data.message === 'GeoGPT is working') {
      const title = data.phase === 'intent' ? '正在理解任务要求' : data.phase === 'vision' ? '正在解读影像内容'
        : view.calls.size ? '正在根据执行结果规划下一步' : '正在规划分析步骤';
      return {title, detail:'等待模型响应'};
    }
    return {title:'正在处理任务', detail:''};
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
    if (view.heading.textContent !== action.title) view.heading.textContent = action.title;
    if (view.target.textContent !== action.detail) view.target.textContent = action.detail;
    view.target.hidden = !action.detail; view.box.dataset.state = status;
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
    if (data.kind === 'review_result' && data.passed === true) { view.issue = null; if (!ui.finished) view.action = {title:'来源审核已通过',detail:'准备交付已核对的答复'}; }
    if (data.kind === 'run_outcome') view.outcome = data;
    if (data.kind === 'model_config') view.body.replaceChildren(metadata(data.profile, '本轮实际使用 · 执行事件快照'));
    if (data.kind === 'status') {
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
        view.calls.set(data.id, {...previous, name:previous.name || data.name || data.result?.name,
          status:ok ? 'ok' : 'error', cached});
        view.action = {title:ok ? cached ? '已复用工具结果，准备下一步' : '工具处理完成，准备下一步'
          : '工具未完成，等待下一步处理', detail:previous.action?.detail || text(data.name || data.result?.name)};
      }
    }
    const calls = [...view.calls.values()];
    const count = status => calls.filter(call => call.status === status).length;
    view.counts.textContent = calls.length
      ? calls.length + ' 次工具调用 · ' + count('ok') + ' 成功'
        + (count('error') ? ' · ' + count('error') + ' 失败' : '')
        + (count('running') ? ' · ' + count('running') + ' 执行中' : '')
        + (calls.some(call => call.cached) ? ' · ' + calls.filter(call => call.cached).length + ' 复用' : '')
      : '尚无工具执行记录';
    if (view.turn) view.counts.textContent += ' · 执行轮次 ' + view.turn;
    if (data.kind === 'finished') {
      ui.status = data.status || ui.status; ui.finished = true;
      view.reason = data.reason || ui.reason?.textContent || view.reason || '';
      if (Number.isSafeInteger(data.turns)) view.turn = Math.max(view.turn, data.turns);
    }
    paintActivity(ui);
  }
  function download(ctx, file, label = '下载原文件') {
    const node = el('a', label); node.href = url(ctx, file); node.download = file.name.split('/').pop(); return node;
  }
  function openFiles(context, selected, ui) {
    if (!valid(context)) return;
    const files = manifest(context), key = [context.conversation_id, context.run_id || '', context.generation].join(':');
    if (!files.length && !ui?.rich) return;
    if (active?.key === key) { if (selected) active.select(selected); return; }
    if (active) active.dialog.close();
    const dialog = el('dialog', undefined, 'results-drawer'), head = el('header', undefined, 'results-drawer-head');
    const id = 'results-title-' + (++serial), title = el('h2', '研究成果'); title.id = id; dialog.setAttribute('aria-labelledby', id);
    const intro = el('div'); intro.append(el('span', 'RESULTS / FILES / EVIDENCE', 'experience-eyebrow'), title);
    head.append(intro, btn('关闭成果面板', () => dialog.close(), 'quiet'));
    const body = el('div', undefined, 'results-drawer-body');
    body.append(el('p', context.run_id ? '本轮任务快照 · ' + files.length + ' 个文件' : '当前对话文件快照 · ' + files.length + ' 个文件', 'experience-muted'));
    const images = files.filter(imageFile);
    let selectImage = () => {};
    if (images.length) {
      const label = el('label', '选择图像', 'results-image-label'), select = el('select');
      select.id = 'results-image-' + serial; label.htmlFor = select.id;
      for (const file of images) { const option = el('option', file.name); option.value = file.name; select.append(option); }
      label.append(select);
      const viewport = el('div', undefined, 'results-preview'), meta = el('div', undefined, 'results-image-meta');
      const actions = el('div', undefined, 'results-actions'), note = el('p', undefined, 'results-science-note');
      function paint() {
        const file = images.find(item => item.name === select.value); if (!file) return;
        viewport.replaceChildren(); actions.replaceChildren(); meta.replaceChildren();
        const image = el('img'); image.alt = file.name; image.decoding = 'async'; image.src = url(context, file, 'image');
        image.addEventListener('error', () => {
          if (select.value === file.name) viewport.replaceChildren(el('p', '预览不可用，原始文件仍可下载。', 'image-failed'));
        }); viewport.append(image);
        const fingerprint = el('details'); fingerprint.append(el('summary', '文件指纹'), el('code', file.sha256));
        meta.append(el('strong', file.name), el('span', format(file.name) + ' · ' + size(file.bytes)), fingerprint);
        note.textContent = /\.tiff?$/i.test(file.name)
          ? 'GeoTIFF 快速预览：默认第 1 波段，按有效采样值做显示拉伸。预览颜色不能直接代表指数值；数值、坐标与 NoData 以原文件和工具证据为准。'
          : '这是保存的图像产物，不从颜色推断科学数值。日期、波段、色标与质量掩膜以图内标注、来源文件和工具记录为准；缺失的信息不自动补造。';
        actions.append(btn('放大查看', () => window.GeoAgentArtifacts.preview(file.name, url(context, file, 'image'), url(context, file), file.name)), download(context, file));
      }
      selectImage = name => { if (images.some(file => file.name === name)) { select.value = name; paint(); } };
      select.value = images.some(file => file.name === selected) ? selected : images[0].name;
      select.addEventListener('change', paint); paint();
      body.append(label, viewport, meta, actions, note);
    }
    const downloads = el('details', undefined, 'results-downloads'); downloads.open = images.length === 0;
    downloads.append(el('summary', '全部文件与下载 · ' + files.length));
    for (const file of files) {
      const row = el('div', undefined, 'results-file-row'), name = el('div');
      name.append(el('strong', file.name), el('small', format(file.name) + ' · ' + size(file.bytes)));
      row.append(name);
      if (imageFile(file)) row.append(btn('预览', () => selectImage(file.name), 'quiet'));
      row.append(download(context, file, '下载')); downloads.append(row);
    }
    body.append(downloads);
    const panel = ui?.rich?.panel, oldHidden = panel?.hidden;
    if (panel) {
      const evidence = el('details', undefined, 'results-evidence');
      evidence.append(el('summary', '工具证据与交互分析')); panel.hidden = false; evidence.append(panel); body.append(evidence);
    }
    body.append(el('p', '文件指纹用于追溯内容一致性，不代表科学结论已获独立验证。原始文件和执行记录不会被此视图修改。', 'experience-muted'));
    dialog.append(head, body);
    const record = {key, dialog, select:selectImage};
    dialog.addEventListener('close', () => {
      if (panel && ui.rich.root.isConnected) { ui.rich.root.append(panel); panel.hidden = oldHidden; }
      dialog.remove(); if (active === record) active = null;
    });
    active = record; document.body.append(dialog); dialog.showModal();
  }
  function results(rid, ui, context) {
    if (!valid(context) || state.runs.get(rid) !== ui) return;
    ui.resultContext = context; ui.rich.root.classList.add('has-results-panel');
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
    ui.rich.compact.hidden = ui.rich.panel.hidden;
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

/* Private, canvas-only PDF reader. No document scripts, remote viewers, or HTML. */
const ROOT = '/api/knowledge/pdf/reader-assets/';
let pdfLibrary;
function library() {
  if (!pdfLibrary) pdfLibrary = import(ROOT + 'pdfjs/build/pdf.mjs').then(mod => {
    mod.GlobalWorkerOptions.workerSrc = ROOT + 'pdfjs/build/pdf.worker.mjs';
    return mod;
  }).catch(error => { pdfLibrary = null; throw error; });
  return pdfLibrary;
}
function node(tag, text, cls) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (cls) item.className = cls;
  return item;
}
function control(text, label, action) {
  const item = node('button', text, 'k-button');
  item.type = 'button'; item.setAttribute('aria-label', label);
  item.addEventListener('click', action); return item;
}
export function validatedReaderAnchors(metadata, source, textSha) {
  if (!source?.text_sha256 || source.text_sha256 !== textSha ||
      metadata?.source?.sha256 !== source.sha256 ||
      metadata?.source?.text_sha256 !== textSha) return [];
  return (Array.isArray(metadata.anchors) ? metadata.anchors : []).filter(anchor =>
    anchor.mapping !== 'verified_structured_block' ||
    (metadata.location_status === 'structured_blocks' &&
      /^[a-f0-9]{64}$/.test(metadata.structure_sha256 || '') &&
      anchor.basis_sha256 === textSha && typeof anchor.block_id === 'string' && anchor.block_id.length > 0));
}
export function pagesForRange(anchors, text, expectedHash, actualHash, hit) {
  if (!hit || expectedHash !== actualHash || (hit.sha256 && hit.sha256 !== actualHash)) return [];
  const chars = Array.from(text || '');
  const {start_char: start, end_char: end} = hit;
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start ||
      end > chars.length || chars.slice(start, end).join('') !== hit.text) return [];
  return [...new Set(anchors.filter(a => {
    if (!Number.isInteger(a.start_char) || !Number.isInteger(a.end_char) ||
        a.start_char < 0 || a.end_char <= a.start_char || a.end_char > chars.length ||
        !Number.isInteger(a.page) || a.page <= 0) return false;
    const contained = a.start_char >= start && a.end_char <= end;
    const boundBlock = a.mapping === 'verified_structured_block' && a.basis_sha256 === actualHash &&
      Array.isArray(hit.metadata?.block_ids) && hit.metadata.block_ids.includes(a.block_id);
    return contained || (boundBlock && a.start_char < end && a.end_char > start);
  }).map(a => a.page))].sort((a, b) => a - b);
}
export function mountReader(host, source, options = {}) {
  let stopped = false, documentPdf = null, loading = null, renderTask = null;
  let requestedPage = 1, zoom = 'fit', revision = 0, paintChain = Promise.resolve(), resizeTimer;
  let anchors = [], metadata = null;
  const abort = new AbortController();
  host.className = 'k-pdf-reader';
  const heading = node('div', undefined, 'k-pane-heading');
  heading.append(node('strong', 'PDF 原文'), node('span', '原始版式 · 本地渲染'));
  const toolbar = node('div', undefined, 'k-pdf-toolbar');
  const previous = control('上一页', 'PDF 上一页', () => go(requestedPage - 1));
  const next = control('下一页', 'PDF 下一页', () => go(requestedPage + 1));
  const pageInput = node('input'); pageInput.type = 'number'; pageInput.min = '1'; pageInput.value = '1';
  pageInput.setAttribute('aria-label', 'PDF 页码');
  const pageTotal = node('span', '/ —', 'k-pdf-page-total');
  const select = node('select'); select.setAttribute('aria-label', 'PDF 缩放');
  for (const [value, label] of [['fit','适合宽度'],['0.75','75%'],['1','100%'],['1.25','125%'],['1.5','150%'],['2','200%']]) {
    const option = node('option', label); option.value = value; select.append(option);
  }
  const download = node('a', '下载原 PDF', 'k-button');
  const base = '/api/knowledge/pdf/jobs/' + encodeURIComponent(source.id);
  download.href = base + '/artifacts/original'; download.download = source.filename || 'source.pdf';
  toolbar.append(previous, pageInput, pageTotal, next, select, download);
  const status = node('p', '正在读取原 PDF…', 'k-pdf-reader-status');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const stage = node('div', undefined, 'k-pdf-stage');
  stage.tabIndex = 0; stage.setAttribute('aria-label', 'PDF 页面，可滚动查看');
  const canvas = node('canvas'); canvas.hidden = true; canvas.setAttribute('role', 'img');
  stage.append(canvas);
  const locations = node('div', undefined, 'k-pdf-locations');
  host.replaceChildren(heading, toolbar, status, stage, locations);
  const controls = [previous, next, pageInput, select];
  controls.forEach(item => { item.disabled = true; });
  function message(text, error = false) {
    if (stopped) return;
    status.textContent = text; status.classList.toggle('is-error', error);
  }
  function updateControls() {
    if (!documentPdf || stopped) return;
    previous.disabled = requestedPage <= 1; next.disabled = requestedPage >= documentPdf.numPages;
    pageInput.disabled = select.disabled = false;
    pageInput.value = String(requestedPage); pageInput.max = String(documentPdf.numPages);
    pageTotal.textContent = '/ ' + documentPdf.numPages;
  }
  function go(page) {
    if (!documentPdf || !Number.isInteger(page) || page < 1 || page > documentPdf.numPages || stopped) {
      pageInput.value = String(requestedPage); return;
    }
    requestedPage = page; updateControls(); queuePaint();
  }
  function queuePaint() {
    const ticket = ++revision;
    if (renderTask) renderTask.cancel();
    paintChain = paintChain.catch(() => {}).then(async () => {
      if (stopped || ticket !== revision || !documentPdf) return;
      const pageNumber = requestedPage;
      const page = await documentPdf.getPage(pageNumber);
      if (stopped || ticket !== revision) return;
      const available = stage.clientWidth - 32;
      if (available <= 0) return;
      const natural = page.getViewport({scale: 1});
      const scale = zoom === 'fit' ? Math.min(3, available / natural.width) : Number(zoom);
      const viewport = page.getViewport({scale});
      const pixels = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(8000000 / (viewport.width * viewport.height)));
      canvas.width = Math.max(1, Math.floor(viewport.width * pixels));
      canvas.height = Math.max(1, Math.floor(viewport.height * pixels));
      canvas.style.width = Math.round(viewport.width) + 'px'; canvas.style.height = Math.round(viewport.height) + 'px';
      canvas.hidden = false; canvas.setAttribute('aria-label', 'PDF 原文第 ' + pageNumber + ' 页');
      stage.setAttribute('aria-busy', 'true'); message('正在显示第 ' + pageNumber + ' 页…');
      renderTask = page.render({canvasContext: canvas.getContext('2d'),
        transform: pixels !== 1 ? [pixels, 0, 0, pixels, 0, 0] : null, viewport});
      try { await renderTask.promise; }
      catch (error) { if (error.name !== 'RenderingCancelledException') throw error; else return; }
      finally { renderTask = null; }
      if (stopped || ticket !== revision) return;
      stage.setAttribute('aria-busy', 'false'); stage.scrollTop = 0;
      host.dataset.renderedPage = String(pageNumber);
      message('第 ' + pageNumber + ' / ' + documentPdf.numPages + ' 页 · 原文件 SHA256 已核对');
    }).catch(error => {
      if (stopped) return;
      stage.setAttribute('aria-busy', 'false');
      message('本页渲染未完成，可切换页码重试或下载原 PDF。', true);
    });
  }
  pageInput.addEventListener('change', () => go(Number(pageInput.value)));
  pageInput.addEventListener('keydown', event => { if (event.key === 'Enter') go(Number(pageInput.value)); });
  select.addEventListener('change', () => { zoom = select.value; queuePaint(); });
  let width = 0;
  const observer = new ResizeObserver(entries => {
    const current = entries[0]?.contentRect.width || 0;
    if (current <= 0 || Math.abs(current - width) < 2) return;
    width = current; clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (zoom === 'fit') queuePaint(); }, 120);
  });
  observer.observe(stage);
  function pageLinks() {
    if (stopped || !documentPdf || !metadata) return;
    locations.replaceChildren();
    const matchedAnchors = validatedReaderAnchors(metadata, source, options.textSha)
      .filter(a => a.page <= documentPdf.numPages);
    const structured = metadata.location_status === "structured_blocks";
    const matched = pagesForRange(matchedAnchors, options.text, source.text_sha256, options.textSha, options.hit)
      .filter(page => page <= documentPdf.numPages);
    if (options.hit) {
      locations.append(node('p', matched.length
        ? (structured ? '片段所属解析块位于（已核验结构化来源）：' : '片段中已有逐字匹配的段落位于：') : '此片段暂无可确认的 PDF 页码，请手动对照原文。', 'k-caption'));
      for (const page of matched) locations.append(control('第 ' + page + ' 页', '定位 PDF 第 ' + page + ' 页', () => go(page)));
      if (matched.length) go(matched[0]);
    }
    const record = node('details', undefined, 'k-pdf-page-links');
    record.append(node('summary', (structured ? '已核验解析块的页码定位' : '解析段落的页码定位') + (matchedAnchors.length ? ' · ' + matchedAnchors.length + ' 处' : '')));
    record.append(node('p', (structured ? '按已核验的原文件、结构化来源和正文版本关联页码；重构表格按所属来源块定位，不推断坐标。' : '仅列出解析器提供页码且正文中唯一、逐字匹配的段落。不代表所有内容都已定位；不推断坐标或阅读顺序。'), 'k-caption'));
    if (!matchedAnchors.length) record.append(node('p', '当前没有通过校验的页码定位，原 PDF 仍可正常翻阅。', 'k-caption'));
    if (metadata.anchors_limited) record.append(node('p', '页码目录仅展示前 2,000 处，其余原始版面信息保留在结构化 JSON 中。', 'k-caption'));
    const list = node('div', undefined, 'k-pdf-anchor-list');
    const chars = Array.from(options.text || '');
    for (const anchor of matchedAnchors) {
      const text = chars.slice(anchor.start_char, anchor.end_char).join('');
      const item = control('第 ' + anchor.page + ' 页 · ' + text.slice(0, 85), '查看第 ' + anchor.page + ' 页：' + text.slice(0, 85), () => go(anchor.page));
      list.append(item);
    }
    record.append(list); locations.append(record);
  }
  async function start() {
    try {
      if (!/^[a-f0-9]{64}$/.test(source.sha256 || '')) throw new Error('missing_hash');
      const response = await fetch(base + '/artifacts/original', {credentials: 'same-origin', signal: abort.signal});
      if (!response.ok) throw new Error('download_failed');
      if (Number(response.headers.get('Content-Length')) > 52428800) throw new Error('oversized');
      const buffer = await response.arrayBuffer();
      if (stopped) return;
      if (!buffer.byteLength || buffer.byteLength > 52428800) throw new Error('oversized');
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(n => n.toString(16).padStart(2, '0')).join('');
      if (stopped) return;
      if (hash !== source.sha256) throw new Error('hash_mismatch');
      const pdf = await library(); if (stopped) return;
      loading = pdf.getDocument({data: new Uint8Array(buffer), isEvalSupported: false, enableXfa: false,
        useWasm: false, disableFontFace: true, isOffscreenCanvasSupported: false,
        cMapUrl: ROOT + 'pdfjs/cmaps/', cMapPacked: true,
        standardFontDataUrl: ROOT + 'pdfjs/standard_fonts/'});
      documentPdf = await loading.promise;
      if (stopped) { await documentPdf.destroy(); return; }
      host.dataset.pdfPages = String(documentPdf.numPages); updateControls(); queuePaint();
      try {
        const response = await fetch(base + '/reader?text_sha256=' + encodeURIComponent(source.text_sha256 || ''), {credentials: 'same-origin', signal: abort.signal});
        if (!response.ok) throw new Error('metadata_failed');
        metadata = await response.json();
        if (stopped) return;
        anchors = Array.isArray(metadata.anchors) ? metadata.anchors : [];
        pageLinks();
      } catch (error) {
        if (!stopped) locations.append(node('p', '页码关联暂不可用，不影响阅读原 PDF。', 'k-caption'));
      }
    } catch (error) {
      if (stopped) return;
      const text = error.message === 'hash_mismatch'
        ? '原 PDF 与来源哈希不一致，已停止展示，请检查原文件。'
        : error.name === 'PasswordException' ? '此 PDF 已加密，请下载后使用密码打开。'
        : '原 PDF 未能载入，请重新打开资料或下载原文件。';
      message(text, true); controls.forEach(item => { item.disabled = true; });
    }
  }
  start();
  const dispose = () => {
    if (stopped) return;
    stopped = true; revision++; abort.abort(); observer.disconnect(); clearTimeout(resizeTimer);
    if (renderTask) renderTask.cancel();
    if (loading) loading.destroy().catch(() => {});
    controls.forEach(item => { item.disabled = true; });
    canvas.width = canvas.height = 0;
  };
  dispose.goToPage = go;
  return dispose;
}

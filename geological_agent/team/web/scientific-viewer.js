'use strict';
// Render only authenticated, receipt-bound analysis documents. Never execute
// uploaded HTML or model-authored renderer tags.
(() => {
  let nextId = 0;
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  };
  const button = (label, handler) => {
    const n = el('button', label, 'quiet'); n.type = 'button'; n.addEventListener('click', handler); return n;
  };
  function selector(label, options, handler) {
    const wrap = el('label', label, 'science-field'), input = el('select');
    input.id = 'science-select-' + (++nextId); wrap.htmlFor = input.id; input.setAttribute('aria-label', label);
    for (const [value, title] of options) {const option = el('option', title); option.value = value; input.append(option);}
    input.addEventListener('change', () => handler(input.value)); wrap.append(input); return {wrap, input};
  }
  function slider(label, value, handler) {
    const wrap = el('label', label, 'science-field'), input = el('input');
    input.type = 'range'; input.min = '0'; input.max = '100'; input.value = String(value);
    input.setAttribute('aria-label', label); input.addEventListener('input', () => handler(Number(input.value)));
    wrap.append(input); return {wrap, input};
  }
  const short = value => typeof value === 'number' ? Number(value.toPrecision(7)).toLocaleString('en-US') : value === null ? '未提供' : String(value);
  const rgb = color => Array.isArray(color) && color.length === 3 && color.every(v => Number.isInteger(v) && v >= 0 && v <= 255) ? 'rgb(' + color.join(',') + ')' : '#78847c';
  function viewer(record, bundle) {
    const doc = record.document, layers = doc.layers;
    const url = (name, kind = 'image') => '/api/conversations/' + encodeURIComponent(bundle.conversation_id) + '/' + kind
      + '?name=' + encodeURIComponent(name) + '&generation=' + encodeURIComponent(bundle.generation);
    const card = el('section', undefined, 'science-card'); card.setAttribute('aria-label', '科学图像分析');
    const heading = el('header', undefined, 'science-heading');
    const title = el('div'); title.append(el('p', 'IMAGE LAB / SCIENTIFIC OUTPUT', 'science-eyebrow'), el('h3', doc.title));
    heading.append(title, el('span', doc.analysis_type.replaceAll('_', ' '), 'science-badge')); card.append(heading);
    if (!Array.isArray(layers) || layers.length < 2) { card.append(el('p', '图层不完整，保留原始文件下载。')); return card; }
    const layout = el('div', undefined, 'science-layout'), main = el('div', undefined, 'science-main');
    const controls = el('aside', undefined, 'science-controls'), toolbar = el('div', undefined, 'science-toolbar');
    const viewport = el('div', undefined, 'science-viewport'); viewport.tabIndex = 0; viewport.setAttribute('aria-label', '图像画布，可放大、拖动或滚动');
    const canvas = el('div', undefined, 'science-canvas');
    const base = el('img', undefined, 'science-base'), overlay = el('img', undefined, 'science-overlay'), divider = el('div', undefined, 'science-divider');
    base.draggable = overlay.draggable = false;
    let primary = layers[0], secondary = layers.find(l => l.role === 'analysis_preview') || layers[1];
    let mode = 'overlay', opacity = 70, split = 50, zoom = 1, pixelSequence = 0;
    base.addEventListener('error', () => { status.textContent = '参考图加载失败，原始结果仍可下载。'; });
    overlay.addEventListener('error', () => { status.textContent = '结果图加载失败，原始结果仍可下载。'; });
    canvas.append(base, overlay, divider); viewport.append(canvas);
    const status = el('p', '点击图像查看该像素的原始计算值；数值不从预览颜色反推。', 'science-status'); status.setAttribute('role', 'status');
    if (!doc.pixel_file) status.textContent = '像素坐标叠加；候选提取需人工检查，不代表已确认的地学结论。';
    const legend = el('div', undefined, 'science-legend');
    function paint() {
      base.src = url(primary.path); base.alt = primary.label;
      overlay.src = url(secondary.path); overlay.alt = secondary.label;
      overlay.style.opacity = mode === 'swipe' ? '1' : String(opacity / 100);
      overlay.style.clipPath = mode === 'swipe' ? 'inset(0 ' + (100 - split) + '% 0 0)' : 'none';
      divider.hidden = mode !== 'swipe'; divider.style.left = split + '%';
      canvas.style.width = zoom * 100 + '%';
      alpha.wrap.hidden = mode === 'swipe'; swipe.wrap.hidden = mode !== 'swipe';
      legend.replaceChildren(el('strong', secondary.label));
      if (secondary.role === 'analysis_preview' || secondary.role === 'candidate_overlay') {
        for (const item of doc.legend || []) {
          const line = el('span', undefined, 'science-legend-item'), swatch = el('i');
          swatch.style.background = rgb(item.color);
          line.append(swatch, el('span', item.label ?? short(item.value))); legend.append(line);
        }
      } else if (secondary.role === 'class_preview') {
        legend.append(el('small', '区间边界：' + (doc.parameters.breaks || (doc.analysis_type === 'raster_change' ? [-doc.parameters.threshold, doc.parameters.threshold] : [0, .2, .5])).join(' / ') + '。各类计数见 statistics.csv；颜色不代表地物语义。'));
      }
    }
    const a = selector('参考图层', layers.map(l => [l.id, l.label]), value => { primary = layers.find(l => l.id === value); paint(); });
    const b = selector('结果图层', layers.map(l => [l.id, l.label]), value => { secondary = layers.find(l => l.id === value); paint(); });
    a.input.value = primary.id; b.input.value = secondary.id;
    const viewMode = selector('对照方式', [['overlay', '透明叠加'], ['swipe', '滑动对照']], value => {mode = value; paint();});
    const alpha = slider('结果图层透明度', opacity, value => {opacity = value; paint();});
    const swipe = slider('对照分隔位置', split, value => {split = value; paint();});
    const size = el('span', '100%');
    const scale = delta => {zoom = Math.max(1, Math.min(4, zoom + delta)); size.textContent = Math.round(zoom * 100) + '%'; paint();};
    toolbar.append(button('缩小', () => scale(-.5)), size, button('放大', () => scale(.5)),
      button('适应画布', () => {zoom = 1; size.textContent = '100%'; paint();}),
      button('全屏', async () => {try { if (document.fullscreenElement) await document.exitFullscreen(); else await card.requestFullscreen(); } catch { status.textContent = '当前浏览器不支持全屏，请使用放大。'; }}));
    let drag = null, moved = false;
    viewport.addEventListener('pointerdown', e => {if (e.button !== 0) return; moved = false; drag = {x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop}; viewport.setPointerCapture(e.pointerId);});
    viewport.addEventListener('pointermove', e => {if (!drag) return; if (Math.abs(e.clientX-drag.x)+Math.abs(e.clientY-drag.y)>5) moved=true; viewport.scrollLeft=drag.left-e.clientX+drag.x; viewport.scrollTop=drag.top-e.clientY+drag.y;});
    viewport.addEventListener('pointerup', () => {drag=null;}); viewport.addEventListener('pointercancel', () => {drag=null;});
    viewport.addEventListener('click', async e => {
      if (moved || !doc.pixel_file || !doc.grid) return;
      const rect = base.getBoundingClientRect();
      if (!rect.width || !rect.height || e.clientX < rect.left || e.clientX >= rect.right || e.clientY < rect.top || e.clientY >= rect.bottom) return;
      const column = Math.floor((e.clientX-rect.left)/rect.width*doc.grid.width), row = Math.floor((e.clientY-rect.top)/rect.height*doc.grid.height), token = ++pixelSequence;
      status.textContent = '读取原始计算像素…';
      try {
        const value = await api('/api/runs/' + encodeURIComponent(bundle.run_id) + '/scientific-pixel?manifest=' + encodeURIComponent(record.manifest_path) + '&column=' + column + '&row=' + row);
        if (token !== pixelSequence || !card.isConnected) return;
        status.textContent = '列 ' + value.column + ' · 行 ' + value.row + ' · ' + (value.valid ? short(value.value) + ' ' + value.unit : 'NoData')
          + ' · ' + value.crs + ' (' + short(value.x) + ', ' + short(value.y) + ')';
      } catch(error) {if (token === pixelSequence && card.isConnected) status.textContent = '像素读取失败：' + error.message;}
    });
    controls.append(a.wrap, b.wrap, viewMode.wrap, alpha.wrap, swipe.wrap, legend);
    if (doc.grid) controls.append(el('p', doc.grid.crs + ' · ' + doc.grid.width + ' × ' + doc.grid.height + '\n' + doc.grid.area_method, 'science-note'));
    const metrics = el('div', undefined, 'science-statistics');
    for (const [name, value] of Object.entries(doc.statistics || {})) {const row = el('div'); row.append(el('span', name.replaceAll('_',' ')),el('strong',short(value))); metrics.append(row);}
    const more = el('details', undefined, 'science-details'); more.append(el('summary', '统计与处理说明'), metrics);
    for (const warning of doc.warnings || []) more.append(el('p', warning, 'science-note'));
    const downloads = el('div', undefined, 'science-downloads');
    const outputs = [...doc.outputs, {path:record.manifest_path, role:'完整分析清单'}];
    for (const file of outputs) {const link = el('a', file.path.split('/').pop()); link.href = url(file.path, 'download'); link.download = file.path.split('/').pop(); downloads.append(link);}
    const provenance = el('details', undefined, 'science-details'); provenance.append(el('summary', '来源与参数'), el('pre', JSON.stringify({inputs:doc.inputs,parameters:doc.parameters,manifest_sha256:record.manifest_sha256},null,2)));
    main.append(toolbar,viewport,status); layout.append(main,controls); card.append(layout,more,downloads,provenance); paint();
    return card;
  }
  async function attach(rid, ui, presentation) {
    if (!ui.rich || !presentation.generation) return;
    if (!ui.science) {
      const root = el('div', undefined, 'science-results'); ui.rich.panel.prepend(root);
      ui.science = {root, version:0, signature:null};
    }
    const science=ui.science, signature=presentation.generation;
    if (science.signature===signature) return;
    const version=++science.version;
    try {
      const bundle=await api('/api/runs/'+encodeURIComponent(rid)+'/scientific-images');
      if (science.version!==version || !science.root.isConnected || state.runs.get(rid)!==ui || state.cid!==bundle.conversation_id) return;
      if (bundle.generation!==signature) return;
      science.root.replaceChildren(...bundle.analyses.map(item=>viewer(item,bundle)));
      for (const error of bundle.errors) science.root.append(el('p', '分析图层不可用：'+error.error, 'science-error'));
      science.signature=signature;
    } catch(error) {
      if (science.version===version && science.root.isConnected) science.root.replaceChildren(el('p','科学图像加载失败：'+error.message,'science-error'),button('重试',()=>attach(rid,ui,presentation)));
    }
  }
  window.GeoScientificViewer={attach};
  // Existing page history may have loaded before this deferred module.
  for (const [rid,ui] of state.runs) if (ui.rich) api('/api/runs/'+encodeURIComponent(rid)+'/presentation').then(p=>attach(rid,ui,p)).catch(()=>{});
})();

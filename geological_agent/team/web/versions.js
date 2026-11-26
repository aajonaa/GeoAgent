'use strict';
(() => {
  let sequence = 0;
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  };
  const button = (label, cls = 'quiet') => {
    const node = el('button', label, cls); node.type = 'button'; return node;
  };
  const select = (label, options) => {
    const wrap = el('label', label, 'version-field'), input = el('select');
    input.setAttribute('aria-label', label);
    for (const [value, text] of options) {
      const option = el('option', text); option.value = value; input.append(option);
    }
    wrap.append(input); return {wrap, input};
  };
  const date = value => value ? new Date(value * 1000).toLocaleString('zh-CN', {hour12:false}) : '时间未记录';
  const short = value => typeof value === 'string' && value ? value.slice(0, 12) : '—';
  const url = (cid, name, generation, kind = 'download') => `/api/conversations/${encodeURIComponent(cid)}/${kind}?name=${encodeURIComponent(name)}&generation=${encodeURIComponent(generation)}`;
  function figure(card, item, cid, generation) {
    const box = el('details', undefined, 'version-figure');
    box.append(el('summary', item.name));
    const preview = el('img'); preview.src = url(cid, item.name, generation, 'image'); preview.alt = item.name;
    preview.addEventListener('error', () => { preview.hidden = true; });
    const dl = el('a', '下载原图'); dl.href = url(cid, item.name, generation); dl.download = item.name.split('/').pop();
    const rows = el('dl', undefined, 'version-metadata');
    const values = [
      ['来源', item.source || '未记录'], ['坐标参考', item.coordinate_reference || '未记录'],
      ['源数据坐标参考', item.source_coordinate_reference || '未记录'],
      ['仿射变换', Array.isArray(item.transform) ? item.transform.join(', ') : '未记录'],
      ['单位', item.units || '未记录'],
      ...(Array.isArray(item.band_units) ? [['波段单位', item.band_units.map((unit, index) => `${index + 1}: ${unit || '未记录'}`).join('；')]] : []),
      ['比例尺', item.cartographic_scale || '未记录'],
      ['像素尺寸', item.width && item.height ? `${item.width} × ${item.height}` : '未记录'],
      ['元数据清单', item.manifest || '未记录'],
    ];
    for (const [name, value] of values) rows.append(el('dt', name), el('dd', value));
    box.append(preview, dl, rows, el('p', '仅显示保存的元数据；缺失字段不推断。', 'version-note'));
    card.append(box);
  }
  function evidence(root, bundle, cid, generation) {
    const section = el('section', undefined, 'version-evidence');
    section.append(el('h4', '结论与证据定位'), el('p', bundle.note, 'version-note'));
    if (!bundle.items.length) { section.append(el('p', '此版本没有可定位的已保存引用。', 'muted')); root.append(section); return; }
    for (const item of bundle.items) {
      const card = el('details', undefined, 'version-evidence-card');
      card.append(el('summary', `运行 ${item.run_id.slice(0,8)} · ${item.items.length} 个来源`));
      const answer = el('blockquote', item.answer, 'version-answer'); card.append(answer);
      for (const ref of item.items) {
        const source = el('article', undefined, 'version-source');
        source.append(el('strong', ref.title || ref.source || '未命名来源'),
          el('p', `${ref.pages?.length ? 'PDF 第 ' + ref.pages.join('、') + ' 页' : '页码未记录'} · SHA-256 ${short(ref.sha256)}`, 'version-note'),
          el('blockquote', ref.text));
        source.append(el('p', '关系：仅保存原文引用；支持或反驳需人工判断。', 'version-note'));
        if (ref.document_id) {
          const link = el('button', '查看资料全文');
          link.addEventListener('click', () => window.GeoAgentCitations?.openDocument?.(ref));
          source.append(link);
        }
        card.append(source);
      }
      if (item.unavailable_ids.length) card.append(el('p', `${item.unavailable_ids.length} 处引用未绑定到唯一来源。`, 'version-warning'));
      section.append(card);
    }
    root.append(section);
  }
  async function render(result, cid) {
    const host = document.getElementById('versions-panel');
    if (!host) return;
    const token = ++sequence, owner = state.me?.id;
    host.replaceChildren();
    if (!cid) return;
    const status = el('p', '正在读取成果版本…', 'version-status'); status.setAttribute('role', 'status');
    const section = el('section', undefined, 'versions-section');
    section.append(el('h3', '成果版本'), el('p', '历史版本只读；恢复会创建新版本，不改写原快照。', 'version-note'), status);
    host.append(section);
    try {
      const bundle = await api(`/api/conversations/${encodeURIComponent(cid)}/generations`);
      if (token !== sequence || state.cid !== cid || state.me?.id !== owner || !host.isConnected) return;
      const items = bundle.items || [];
      if (!items.length) { status.textContent = '尚无成果版本。'; return; }
      const label = item => `${item.current ? '当前 · ' : ''}${date(item.created)} · ${item.file_count} 个文件`;
      const choices = items.map(item => [item.generation, label(item)]);
      const current = select('查看版本', choices), left = select('基准版本', choices), right = select('对比版本', choices);
      current.input.value = bundle.items.find(item => item.current)?.generation || items[0].generation;
      left.input.value = items[Math.min(1, items.length - 1)].generation;
      right.input.value = items[0].generation;
      const detail = el('div', undefined, 'version-detail'), compare = el('div', undefined, 'version-compare');
      let detailSequence = 0, compareSequence = 0;
      const actions = el('div', undefined, 'version-actions');
      const compareButton = button('比较版本');
      const restore = button('恢复此版本为新版本', 'outline');
      actions.append(compareButton, restore);
      const controls = el('div', undefined, 'version-controls'); controls.append(current.wrap, actions); section.append(controls);
      section.append(left.wrap, right.wrap, detail, compare);
      const load = async generation => {
        const request = ++detailSequence;
        try {
          status.textContent = '正在读取版本详情…'; detail.replaceChildren(); compare.replaceChildren();
          const [version, sources] = await Promise.all([
            api(`/api/conversations/${encodeURIComponent(cid)}/generation?id=${encodeURIComponent(generation)}`),
            api(`/api/conversations/${encodeURIComponent(cid)}/generation-evidence?generation=${encodeURIComponent(generation)}`)]);
          if (request !== detailSequence || token !== sequence || state.cid !== cid || state.me?.id !== owner) return;
          status.textContent = `${version.file_count} 个文件 · ${(version.bytes/1024).toFixed(1)} KiB`;
          const list = el('div', undefined, 'version-files');
          for (const file of version.files) {
            const row = el('div', undefined, 'version-file');
            const link = el('a', file.name); link.href = url(cid, file.name, generation); link.download = file.name.split('/').pop();
            row.append(link, el('small', `${(file.bytes/1024).toFixed(1)} KiB · SHA-256 ${short(file.sha256)}`)); list.append(row);
          }
          detail.append(list);
          if (version.figures.length) {
            detail.append(el('h4', '图件与已记录元数据'));
            for (const item of version.figures) figure(detail, item, cid, generation);
          }
          evidence(detail, sources, cid, generation);
        } catch (error) {
          if (request === detailSequence && token === sequence && state.cid === cid && state.me?.id === owner) status.textContent = '版本读取失败：' + error.message;
        }
      };
      current.input.addEventListener('change', () => load(current.input.value));
      compareButton.addEventListener('click', async () => {
        const request = ++compareSequence;
        try {
          const value = await api(`/api/conversations/${encodeURIComponent(cid)}/generation-compare?left=${encodeURIComponent(left.input.value)}&right=${encodeURIComponent(right.input.value)}`);
          if (request !== compareSequence || token !== sequence || state.cid !== cid || state.me?.id !== owner) return;
          compare.replaceChildren(el('h4', '版本差异'));
          for (const item of value.changes) {
            const row = el('div', `version-change ${item.status}`);
            row.append(el('strong', item.name), el('span', item.status), el('small', `${short(item.left_sha256)} → ${short(item.right_sha256)}`));
            compare.append(row);
          }
          compare.append(el('p', `新增 ${value.counts.added} · 删除 ${value.counts.removed} · 修改 ${value.counts.modified} · 未变 ${value.counts.unchanged}`, 'version-note'));
        } catch (error) { if (request === compareSequence && token === sequence && state.cid === cid && state.me?.id === owner) status.textContent = '比较失败：' + error.message; }
      });
      restore.addEventListener('click', async () => {
        const generation = current.input.value;
        if (!window.confirm('将此版本恢复为当前成果？系统会创建新版本，历史版本保持不变。')) return;
        restore.disabled = true; status.textContent = '正在创建新版本…';
        try {
          await api(`/api/conversations/${encodeURIComponent(cid)}/generation-restore?generation=${encodeURIComponent(generation)}`, {method:'POST'});
          if (token !== sequence || state.cid !== cid || state.me?.id !== owner) return;
          status.textContent = '已恢复为新版本。'; await window.loadFiles();
        } catch (error) { if (token === sequence && state.cid === cid && state.me?.id === owner) status.textContent = '恢复失败：' + error.message; }
        finally { restore.disabled = false; }
      });
      await load(current.input.value);
    } catch (error) {
      if (token === sequence && state.cid === cid && state.me?.id === owner && host.isConnected) status.textContent = '成果版本加载失败：' + error.message;
    }
  }
  window.GeoAgentVersions = {render};
})();

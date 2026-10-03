'use strict';
(() => {
  const dialog = document.getElementById('knowledge-dialog');
  let generation = 0;
  const out = document.getElementById('knowledge-results');
  const status = document.getElementById('knowledge-status');
  const el = (tag, text, cls) => { const node = document.createElement(tag); node.textContent = text; if (cls) node.className = cls; return node; };
  async function refresh() {
    const current = ++generation;
    status.textContent = '正在加载你的知识库…';
    try {
      const data = await api('/api/knowledge');
      if (current !== generation || !dialog.open) return;
      const list = document.getElementById('knowledge-documents'); list.replaceChildren();
      document.getElementById('knowledge-count').textContent = data.documents.length + ' 份资料';
      for (const doc of data.documents) {
        const card = el('article', '', 'knowledge-document');
        card.append(el('strong', doc.title), el('p', doc.chunks + ' 个片段 · SHA256 ' + doc.sha256.slice(0, 12), 'muted'));
        const source = el('p', doc.source, 'knowledge-source'); card.append(source);
        const read = el('button', '查看原文', 'quiet'); read.type = 'button';
        read.onclick = async () => {
          try {
            const raw = await api('/api/knowledge/' + encodeURIComponent(doc.id));
            if (current !== generation || !dialog.open) return;
            out.replaceChildren(el('h3', raw.title), el('pre', raw.body, 'knowledge-text'));
          } catch (error) { status.textContent = error.message; }
        };
        const remove = el('button', '删除', 'quiet'); remove.type = 'button';
        remove.onclick = async () => {
          if (!window.confirm('删除这份知识资料？已完成对话的引用快照会保留。')) return;
          remove.disabled = true;
          try { await api('/api/knowledge/' + encodeURIComponent(doc.id), {method:'DELETE'}); await refresh(); }
          catch (error) { status.textContent = error.message; remove.disabled = false; }
        };
        card.append(read, remove); list.append(card);
      }
      if (!data.documents.length) list.append(el('p', '还没有资料。添加一份文本后，新问题会自动检索，无需额外指令。', 'muted'));
      status.textContent = '每次提问自动检索；仅使用相关片段，并保留来源。';
    } catch (error) { if (current === generation) status.textContent = error.message; }
  }
  document.getElementById('knowledge-open').onclick = () => { dialog.showModal(); refresh(); };
  document.getElementById('knowledge-close').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { generation++; out.replaceChildren(); status.textContent = ''; document.getElementById('knowledge-documents').replaceChildren(); });
  document.getElementById('knowledge-file').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    if (!/\.(txt|md|markdown)$/i.test(file.name) || file.size > 240000) { status.textContent = '首版支持 UTF-8 文本或 Markdown，文件不超过 240 KB。'; return; }
    document.getElementById('knowledge-title').value = file.name;
    document.getElementById('knowledge-text').value = await file.text();
  };
  document.getElementById('knowledge-form').onsubmit = async event => {
    event.preventDefault();
    const button = document.getElementById('knowledge-save'); button.disabled = true;
    status.textContent = '正在分块与建立索引，请稍候…';
    try {
      const result = await api('/api/knowledge', {method:'POST', body:{
        title:document.getElementById('knowledge-title').value,
        source:document.getElementById('knowledge-source').value || '用户上传资料',
        text:document.getElementById('knowledge-text').value
      }});
      document.getElementById('knowledge-form').reset(); await refresh();
      status.textContent = (result.reused ? '资料已经存在，已复用索引。' : '已保存并建立索引。') + ' 后续问题将自动检索。';
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  };
  document.getElementById('knowledge-search-form').onsubmit = async event => {
    event.preventDefault();
    const button = document.getElementById('knowledge-search'); button.disabled = true; out.replaceChildren();
    status.textContent = '向量与关键词召回后，正在进行 cross-encoder 重排…';
    try {
      const result = await api('/api/knowledge/search', {method:'POST', body:{query:document.getElementById('knowledge-query').value}});
      status.textContent = result.status === 'matched' ? '命中 ' + result.references.length + ' 个片段 · ' + result.duration_ms + ' ms' : '没有足够相关的知识片段，不会把无关内容当成答案。';
      for (const ref of result.references) {
        const card = el('article', '', 'knowledge-hit');
        card.append(el('h3', ref.title), el('p', '[' + ref.citation_id + ']', 'knowledge-citation'),
          el('p', ref.text, 'knowledge-excerpt'),
          el('small', '字符 ' + ref.start_char + '–' + ref.end_char + ' · 重排 ' + ref.rerank_score.toFixed(3) + ' · ' + ref.source));
        out.append(card);
      }
      out.append(el('p', '重排分数表示相对相关性，不代表事实正确率。', 'muted'));
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  };
})();

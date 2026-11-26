'use strict';
// A reading layer over saved references. No HTML from models, new retrieval,
// altered answers, inferred authors/pages, or claims of scientific approval.
(() => {
  let sequence = 0;
  const dialogs = new Set();
  const make = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  function disclosure(label, text, cls = 'citation-technical') {
    const box = make('details', undefined, cls);
    box.append(make('summary', label), make('pre', text)); return box;
  }
  function pages(ref) {
    const values = Array.isArray(ref.pages) ? ref.pages : [];
    const valid = [...new Set(values.filter(n => Number.isSafeInteger(n) && n > 0))].sort((a,b) => a-b);
    return valid.length ? 'PDF 第 ' + valid.join('、') + ' 页' : '页码未记录';
  }
  function title(ref) {
    const recorded = Array.isArray(ref.section_path) ? ref.section_path[0] : null;
    return typeof recorded === 'string' && recorded.trim() ? recorded : String(ref.title || '未命名资料');
  }
  function modal(titleText, content, {panel = false, trigger = document.activeElement} = {}) {
    const dialog = make('dialog', undefined, 'citation-dialog');
    dialog.classList.toggle('citation-panel', panel);
    const head = make('header'), heading = make('h2', titleText);
    heading.id = 'citation-dialog-' + (++sequence);
    dialog.setAttribute('aria-labelledby', heading.id);
    const close = make('button', '关闭', 'quiet'); close.type = 'button';
    close.autofocus = true;
    close.addEventListener('click', () => dialog.close());
    head.append(heading, close); dialog.append(head, content);
    dialog.addEventListener('close', () => {
      dialogs.delete(dialog); dialog.remove();
      if (trigger?.isConnected) trigger.focus({preventScroll:true});
    });
    document.body.append(dialog); dialogs.add(dialog); dialog.showModal();
    return dialog;
  }
  function context(assets) {
    const byId = new Map();
    const items = assets?.citations?.items || [];
    for (const ref of items) {
      if (ref && typeof ref.citation_id === 'string' && typeof ref.text === 'string') byId.set(ref.citation_id, ref);
    }
    return {byId, groups:new Map(), unknown:new Set(), original:'',
      pending:!assets, conflicts:new Set(assets?.citations?.conflicting_ids || [])};
  }
  function mark(id, ctx) {
    const ref = ctx.byId.get(id), wrap = make('sup', undefined, 'citation-marker');
    const button = make('button'); button.type = 'button'; wrap.append(button);
    button.setAttribute('aria-haspopup', 'dialog');
    if (!ref) {
      ctx.unknown.add(id); button.textContent = '?'; button.className = 'citation-unavailable';
      const reason = ctx.pending ? '引用来源正在读取' : ctx.conflicts.has(id) ? '来源快照存在冲突，未绑定' : '引用记录不可用';
      button.setAttribute('aria-label', reason); button.title = reason;
      button.addEventListener('click', () => {
        const body = make('div'); body.append(make('p', reason + '。原始答复未改动，不将此引用显示为已核实来源。'));
        body.append(disclosure('查看原始引用标记', '[' + id + ']'));
        modal('引用详情', body, {panel:true, trigger:button});
      });
      return wrap;
    }
    // Same document AND version share a number; each occurrence keeps its own excerpt.
    const key = ref.document_id ? JSON.stringify([ref.document_id, ref.sha256]) : id;
    let group = ctx.groups.get(key);
    if (!group) {
      group = {number:ctx.groups.size+1, ref, refs:new Map()};
      ctx.groups.set(key, group);
    }
    group.refs.set(id, ref);
    button.textContent = String(group.number);
    button.title = title(ref) + ' · ' + pages(ref);
    button.setAttribute('aria-label', '引用 ' + group.number + '：' + button.title);
    button.addEventListener('click', () => openReferences(ctx, button, group, id));
    return wrap;
  }
  async function openDocument(ref) {
    const owner = state.me?.id, view = state.view;
    const body = make('div', undefined, 'citation-document-body');
    body.append(make('p', '正在读取原文…', 'citation-meta'));
    const dialog = modal(title(ref), body);
    try {
      const result = await api('/api/knowledge/' + encodeURIComponent(ref.document_id));
      if (!dialog.open || state.me?.id !== owner || state.view !== view) { if (dialog.open) dialog.close(); return; }
      body.replaceChildren();
      if (ref.sha256 && result.sha256 !== ref.sha256) {
        body.append(make('p', '知识库资料版本已变化。当前引用仍绑定检索时的原文片段，未用新版本替换。', 'citation-warning'));
        body.append(make('blockquote', ref.text, 'citation-quote')); return;
      }
      const text = typeof result.body === 'string' ? result.body : result.text;
      body.append(make('p', pages(ref) + ' · 以下为保存的资料正文，不是重新生成的摘要。', 'citation-meta'));
      body.append(make('pre', typeof text === 'string' ? text : '当前资料未提供正文；引用卡片中的原文片段仍保留。', 'citation-document'));
    } catch (error) {
      if (!dialog.open || state.me?.id !== owner || state.view !== view) { if (dialog.open) dialog.close(); return; }
      body.replaceChildren(make('p', '原文暂不可用：' + error.message + '。检索时的片段仍保留在引用卡片中。', 'citation-warning'));
    }
  }
  function sourceCard(group, selectedId) {
    const card = make('details', undefined, 'citation-card');
    card.open = Boolean(selectedId);
    const summary = make('summary'), info = make('span', undefined, 'citation-card-heading');
    info.append(make('span', title(group.ref), 'citation-title'));
    const pageSet = [...new Set([...group.refs.values()].map(pages))];
    info.append(make('span', pageSet.join(' · ') + ' · ' + group.refs.size + ' 个引用片段', 'citation-meta'));
    summary.append(make('span', String(group.number), 'citation-number'), info, make('span', undefined, 'citation-chevron'));
    summary.lastChild.setAttribute('aria-hidden', 'true'); card.append(summary);
    const body = make('div', undefined, 'citation-card-body');
    for (const [id, ref] of group.refs) {
      const excerpt = make('details', undefined, 'citation-excerpt');
      excerpt.open = id === selectedId;
      excerpt.append(make('summary', pages(ref) + ' · 原文片段'), make('blockquote', ref.text, 'citation-quote'));
      excerpt.append(make('p', '关系：仅保存原文引用；支持或反驳需人工判断。', 'citation-meta'));
      if (ref.quality_status === 'manual_review_required') excerpt.append(make('p', '解析质量标记：待人工复核', 'citation-meta'));
      if (ref.reused) excerpt.append(make('p', '沿用此对话先前保存的检索片段', 'citation-meta'));
      excerpt.append(disclosure('技术详情', JSON.stringify({citation_id:id, document_id:ref.document_id,
        source:ref.source, sha256:ref.sha256, original_sha256:ref.original_sha256,
        origin_run_id:ref.origin_run_id, anchors:ref.anchors, quality_status:ref.quality_status}, null, 2)));
      body.append(excerpt);
    }
    if (typeof group.ref.document_id === 'string' && group.ref.document_id) {
      const open = make('button', '查看资料全文', 'citation-document-link'); open.type = 'button';
      open.addEventListener('click', () => openDocument(group.ref)); body.append(open);
    }
    card.append(body);
    return card;
  }
  function openReferences(ctx, trigger, selectedGroup = ctx.groups.values().next().value, selectedId = selectedGroup?.refs.keys().next().value) {
    const content = make('div', undefined, 'citation-panel-content');
    const list = make('div', undefined, 'citation-list');
    let selectedCard;
    for (const group of ctx.groups.values()) {
      const card = sourceCard(group, group === selectedGroup ? selectedId : null);
      list.append(card);
      if (group === selectedGroup) selectedCard = card;
    }
    content.append(list);
    if (ctx.unknown.size) {
      content.append(make('p', ctx.pending ? '正在读取已保存的引用记录…' : '部分引用无法关联到唯一的来源记录。', 'citation-warning'));
    }
    content.append(disclosure('结论上下文 · 原始答复', ctx.original, 'citation-original'));
    modal('参考资料', content, {panel:true, trigger});
    selectedCard?.querySelector('.citation-excerpt[open]')?.scrollIntoView({block:'nearest'});
  }
  function finish(target, ctx, original) {
    if (!ctx.groups.size && !ctx.unknown.size) return;
    ctx.original = original;
    const root = make('div', undefined, 'answer-references');
    const button = make('button', undefined, 'citation-sources-button');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'dialog');
    const count = ctx.groups.size + ' 篇' + (ctx.unknown.size ? ' · ' + ctx.unknown.size + (ctx.pending ? ' 处待加载' : ' 处未绑定') : '');
    button.append(make('span', '参考资料'), make('span', count, 'citation-meta'));
    button.addEventListener('click', () => openReferences(ctx, button));
    root.append(button);
    target.append(root);
  }
  function clear() { for (const dialog of [...dialogs]) dialog.close(); }
  window.GeoAgentCitations = {context, mark, finish, clear, openDocument};
  // The auth screen is the existing logout/expiry boundary. No account state is cached.
  document.addEventListener('DOMContentLoaded', () => {
    const auth = document.getElementById('auth-screen');
    if (auth) new MutationObserver(() => { if (!auth.hidden) clear(); }).observe(auth, {attributes:true, attributeFilter:['hidden']});
  });
})();

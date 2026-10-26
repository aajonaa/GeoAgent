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
  function modal(titleText, content) {
    const dialog = make('dialog', undefined, 'citation-dialog');
    const head = make('header'), heading = make('h2', titleText);
    heading.id = 'citation-dialog-' + (++sequence);
    dialog.setAttribute('aria-labelledby', heading.id);
    const close = make('button', '关闭', 'quiet'); close.type = 'button';
    close.addEventListener('click', () => dialog.close());
    head.append(heading, close); dialog.append(head, content);
    const previous = document.activeElement;
    dialog.addEventListener('close', () => {
      dialogs.delete(dialog); dialog.remove();
      if (previous?.isConnected) previous.focus();
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
    return {byId, groups:new Map(), unknown:new Set(), root:null,
      pending:!assets, conflicts:new Set(assets?.citations?.conflicting_ids || [])};
  }
  function mark(id, ctx) {
    const ref = ctx.byId.get(id), wrap = make('sup', undefined, 'citation-marker');
    const button = make('button'); button.type = 'button'; wrap.append(button);
    if (!ref) {
      ctx.unknown.add(id); button.textContent = '?'; button.className = 'citation-unavailable';
      const reason = ctx.pending ? '引用来源正在读取' : ctx.conflicts.has(id) ? '来源快照存在冲突，未绑定' : '引用记录不可用';
      button.setAttribute('aria-label', reason); button.title = reason;
      button.addEventListener('click', () => {
        const body = make('div'); body.append(make('p', reason + '。原始答复未改动，不将此引用显示为已核实来源。'));
        body.append(disclosure('查看原始引用标记', '[' + id + ']')); modal('引用详情', body);
      });
      return wrap;
    }
    // Same document AND version share a number; each occurrence keeps its own excerpt.
    const key = ref.document_id ? JSON.stringify([ref.document_id, ref.sha256]) : id;
    let group = ctx.groups.get(key);
    if (!group) {
      group = {number:ctx.groups.size+1, ref, refs:new Map(), buttons:[], node:null,
        id:'citation-source-' + (++sequence), excerpts:new Map()};
      ctx.groups.set(key, group);
    }
    group.refs.set(id, ref); group.buttons.push(button);
    button.textContent = String(group.number);
    button.title = title(ref) + ' · ' + pages(ref);
    button.setAttribute('aria-label', '引用 ' + group.number + '：' + button.title);
    button.setAttribute('aria-controls', group.id); button.setAttribute('aria-expanded', 'false');
    button.addEventListener('click', () => {
      if (!ctx.root || !group.node) return;
      ctx.root.open = true; group.node.open = true;
      const excerpt = group.excerpts.get(id); if (excerpt) excerpt.open = true;
      const destination = excerpt || group.node;
      destination.scrollIntoView({block:'nearest', behavior:'auto'});
      destination.querySelector('summary').focus({preventScroll:true});
    });
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
  function sourceCard(group) {
    const card = make('details', undefined, 'citation-card'); card.id = group.id; group.node = card;
    const summary = make('summary'), info = make('span', undefined, 'citation-card-heading');
    info.append(make('span', title(group.ref), 'citation-title'));
    const pageSet = [...new Set([...group.refs.values()].map(pages))];
    info.append(make('span', pageSet.join(' · ') + ' · ' + group.refs.size + ' 个引用片段', 'citation-meta'));
    summary.append(make('span', String(group.number), 'citation-number'), info, make('span', undefined, 'citation-chevron'));
    summary.lastChild.setAttribute('aria-hidden', 'true'); card.append(summary);
    const body = make('div', undefined, 'citation-card-body');
    for (const [id, ref] of group.refs) {
      const excerpt = make('details', undefined, 'citation-excerpt');
      excerpt.append(make('summary', pages(ref) + ' · 原文片段'), make('blockquote', ref.text, 'citation-quote'));
      if (ref.quality_status === 'manual_review_required') excerpt.append(make('p', '解析质量标记：待人工复核', 'citation-meta'));
      if (ref.reused) excerpt.append(make('p', '沿用此对话先前保存的检索片段', 'citation-meta'));
      excerpt.append(disclosure('技术详情', JSON.stringify({citation_id:id, document_id:ref.document_id,
        source:ref.source, sha256:ref.sha256, original_sha256:ref.original_sha256,
        origin_run_id:ref.origin_run_id, anchors:ref.anchors, quality_status:ref.quality_status}, null, 2)));
      group.excerpts.set(id, excerpt); body.append(excerpt);
    }
    if (typeof group.ref.document_id === 'string' && group.ref.document_id) {
      const open = make('button', '查看资料全文', 'citation-document-link'); open.type = 'button';
      open.addEventListener('click', () => openDocument(group.ref)); body.append(open);
    }
    card.append(body);
    card.addEventListener('toggle', () => { for (const button of group.buttons) button.setAttribute('aria-expanded', String(card.open && ctxRootOpen(card))); });
    return card;
  }
  function ctxRootOpen(card) { return Boolean(card.closest('.answer-references')?.open); }
  function finish(target, ctx, original) {
    if (!ctx.groups.size && !ctx.unknown.size) return;
    const root = make('details', undefined, 'answer-references'); ctx.root = root;
    const summary = make('summary'), label = make('span', '参考资料', 'citation-section-label');
    const count = ctx.groups.size + ' 篇' + (ctx.unknown.size ? ' · ' + ctx.unknown.size + (ctx.pending ? ' 处待加载' : ' 处未绑定') : '');
    summary.append(label, make('span', count, 'citation-meta'), make('span', undefined, 'citation-chevron'));
    summary.lastChild.setAttribute('aria-hidden', 'true'); root.append(summary);
    const list = make('div', undefined, 'citation-list');
    for (const group of ctx.groups.values()) list.append(sourceCard(group));
    root.append(list);
    if (ctx.unknown.size) root.append(make('p', ctx.pending ? '正在读取已保存的引用记录…' : '部分引用未能绑定唯一的来源记录，未补造文献或页码。', 'citation-warning'));
    root.append(disclosure('查看原始答复', original, 'citation-original'));
    root.addEventListener('toggle', () => {
      for (const group of ctx.groups.values()) for (const button of group.buttons) button.setAttribute('aria-expanded', String(root.open && group.node.open));
    });
    target.append(root);
  }
  function clear() { for (const dialog of [...dialogs]) dialog.close(); }
  window.GeoAgentCitations = {context, mark, finish, clear};
  // The auth screen is the existing logout/expiry boundary. No account state is cached.
  document.addEventListener('DOMContentLoaded', () => {
    const auth = document.getElementById('auth-screen');
    if (auth) new MutationObserver(() => { if (!auth.hidden) clear(); }).observe(auth, {attributes:true, attributeFilter:['hidden']});
  });
})();

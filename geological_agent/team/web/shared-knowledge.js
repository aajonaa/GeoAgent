'use strict';
(() => {
  const $=id=>document.getElementById(id),dialog=()=>$('shared-dialog');let hooks,me,epoch=0,offset=0,next=null,previewDoc=null,start=0,chunks=0;
  const n=(tag,value,cls)=>{const x=document.createElement(tag);if(value!==undefined)x.textContent=value;if(cls)x.className=cls;return x;};
  function button(label,fn){const b=n('button',label,'quiet');b.type='button';b.onclick=fn;return b;}
  function clear(){epoch++;me=null;dialog().close();$('shared-content').replaceChildren();$('shared-open').hidden=true;$('shared-open').setAttribute('aria-expanded','false');$('shared-query').value='';$('shared-message').textContent='';}
  function params(){return new URLSearchParams({kind:$('shared-kind').value,q:$('shared-query').value.trim(),offset:String(offset),limit:'50'});}
  async function listing(){const ticket=++epoch;previewDoc=null;$('shared-content').replaceChildren();$('shared-message').textContent='正在读取研究组公共资料…';try{const data=await hooks.api('/api/shared-knowledge?'+params());if(ticket!==epoch||!dialog().open)return;next=data.next_offset;const source=data.sources[0];$('shared-message').textContent=`公共知识文档 ${source?.published_documents.toLocaleString()||0} 份，文献合集 ${source?.published_collections||0} 个。当前显示第 ${offset+1}–${offset+data.documents.length} 条。个人上传请使用“个人资料库”。公共知识文档建议使用明确关键词；文献合集支持语义检索。`;
    const list=n('div',undefined,'shared-list');for(const doc of data.documents){const row=n('article');row.append(n('strong',doc.title),n('p',`${doc.chunks??0} 个片段 · ${doc.index_state||'知识文档'}${doc.year?' · '+doc.year:''}`),button('预览原文 / 切片',()=>{previewDoc=doc.id;start=0;chunks=0;preview();}));list.append(row);}if(!data.documents.length)list.append(n('p','没有匹配的公共资料。'));$('shared-content').append(list);const pager=n('div',undefined,'admin-users-footer');if(offset)pager.append(button('上一页',()=>{offset=Math.max(0,offset-50);listing();}));if(next!=null)pager.append(button('下一页',()=>{offset=next;listing();}));$('shared-content').append(pager);
  }catch(e){if(ticket===epoch)$('shared-message').textContent='读取失败：'+e.message;}}
  async function preview(){const ticket=++epoch;$('shared-content').replaceChildren();$('shared-message').textContent='正在读取已发布的原文与切片…';try{const data=await hooks.api(`/api/shared-knowledge/${encodeURIComponent(previewDoc)}?kind=${$('shared-kind').value}&start=${start}&chunk_offset=${chunks}`);if(ticket!==epoch||!dialog().open)return;$('shared-message').textContent='研究组共享资料 · 只读。个人上传默认仅本人可见。';const c=$('shared-content');c.append(button('← 返回公共资料列表',listing),n('h3',data.title),n('small',`文档 ${data.id} · SHA256 ${data.sha256||'未提供'}`),n('h4','原文预览'),n('pre',data.body||'这条记录当前没有可预览的正文；目录记录与全文索引状态分别展示。','shared-text'));if(data.next_start!=null)c.append(button('下一段原文',()=>{start=data.next_start;preview();}));c.append(n('h4','索引切片'));if(data.chunks_detail){for(const part of data.chunks_detail){const d=n('details'),head=n('summary',`${part.citation_id} · 字符 ${part.start_char}–${part.end_char}`);d.append(head,n('pre',part.text,'shared-text'));c.append(d);}if(data.next_chunk_offset!=null)c.append(button('下一页切片',()=>{chunks=data.next_chunk_offset;preview();}));}else c.append(n('p',`该文献记录有 ${data.chunks||0} 个索引片段；可通过检索查看命中的原文片段。`));}catch(e){if(ticket===epoch)$('shared-message').textContent=e.message;}}
  async function search(){const query=$('shared-query').value.trim();if(!query){$('shared-message').textContent='请先填写检索问题。';return;}const ticket=++epoch;$('shared-content').replaceChildren();$('shared-message').textContent='正在执行公共资料混合检索与重排…';try{const data=await hooks.api('/api/shared-knowledge/search',{method:'POST',body:{query}});if(ticket!==epoch||!dialog().open)return;$('shared-message').textContent=`检索状态 ${data.status}；返回 ${(data.references||[]).length} 个片段。公共知识文档建议使用明确关键词；文献合集支持语义检索。`;$('shared-content').append(button('返回资料列表',listing));for(const hit of data.references||[]){const row=n('article',undefined,'shared-hit');row.append(n('h3',hit.title),n('small',`${hit.citation_id} · 重排分数 ${hit.rerank_score??'未提供'}`),n('pre',hit.text,'shared-text'));if(hit.document_id&&Number.isInteger(hit.shared_source_index))row.append(button('在原文中定位',()=>openReference(hit)));$('shared-content').append(row);}}catch(e){if(ticket===epoch)$('shared-message').textContent=e.message;}}
  async function openReference(hit) {
    const ticket = ++epoch;
    const content = $('shared-content');
    content.replaceChildren();
    $('shared-message').textContent = '正在定位原文…';
    const citedStart = Math.max(0, Number(hit.start_char) || 0);
    const from = hit.shared_source_kind === 'corpus' ? Math.max(0, citedStart - 400) : citedStart;
    const query = new URLSearchParams({source: hit.shared_source_index, kind: hit.shared_source_kind, start: from});
    try {
      const data = await hooks.api('/api/shared-knowledge/' + encodeURIComponent(hit.document_id) + '?' + query);
      if (ticket !== epoch || !dialog().open) return;
      const offset = citedStart - data.start_char;
      const length = hit.end_char - citedStart;
      if (data.sha256 !== hit.sha256 || offset < 0 || length < 1
          || Array.from(data.body).slice(offset, offset + length).join('') !== hit.text) {
        throw new Error('当前原文与引用片段不一致，请重新检索。');
      }
      $('shared-message').textContent = '已定位引用原文';
      const chars = Array.from(data.body), body = n('pre', undefined, 'shared-text');
      body.append(chars.slice(0, offset).join(''), n('mark', hit.text), chars.slice(offset + length).join(''));
      content.append(button('返回检索结果', search), n('h3', data.title),
        n('small', `${hit.citation_id} · 字符 ${citedStart}–${hit.end_char}`), body);
    } catch (error) {
      if (ticket !== epoch || !dialog().open) return;
      content.append(button('返回检索结果', search));
      $('shared-message').textContent = error.message;
    }
  }
  function mount(h){hooks=h;const titleFilter=$('shared-filter-title');$('shared-open').onclick=()=>{if(!me)return;offset=0;$('sidebar').classList.remove('open');dialog().showModal();$('shared-open').setAttribute('aria-expanded','true');listing();};$('shared-close').onclick=()=>dialog().close();$('shared-filter').onsubmit=e=>{e.preventDefault();if(titleFilter)search();else{offset=0;listing();}};if(titleFilter)titleFilter.onclick=()=>{offset=0;listing();};else $('shared-search').onclick=search;$('shared-kind').onchange=()=>{offset=0;listing();};dialog().addEventListener('close',()=>{epoch++;$('shared-open').setAttribute('aria-expanded','false');$('shared-content').replaceChildren();});}
  function session(user){clear();me=user;$('shared-open').hidden=!user;}
  window.OreSageSharedKnowledge={mount,session,clear};
})();

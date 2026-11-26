/* Build a read-only view from typed tokens. Never inject document HTML. */
function el(tag,text,cls) {
  const node=document.createElement(tag);
  if (text !== undefined) node.textContent=String(text);
  if (cls) node.className=cls;
  return node;
}
function action(text,fn) {
  const button=el('button',text,'k-button');button.type='button';
  button.addEventListener('click',fn);return button;
}
export function safeLink(value) {
  try {
    const url=new URL(value);
    return ['http:','https:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
export function assetName(value) {
  return typeof value==='string' && /^pdf-asset:[a-f0-9]{64}\.(png|jpg|webp|gif)$/.test(value)
    ? value.slice(10) : null;
}
function mathText(parent,text) {
  const pattern=/\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$(?!\d)|\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]/g;
  let start=0;
  for (const match of text.matchAll(pattern)) {
    parent.append(document.createTextNode(text.slice(start,match.index)));
    const span=el('span',undefined,'k-document-math');
    const formula=match[1]||match[2]||match[3]||match[4];
    try {
      if (!window.katex) throw new Error('Math renderer unavailable');
      window.katex.render(formula,span,{displayMode:Boolean(match[1]||match[4]),
        throwOnError:true,trust:false,strict:'ignore',maxExpand:500,maxSize:20});
    } catch {
      span.textContent=match[0];span.title='公式未能排版，保留解析器原始表达式';
    }
    parent.append(span);start=match.index+match[0].length;
  }
  parent.append(document.createTextNode(text.slice(start)));
}
export function mountContent(host,source,options) {
  const abort=new AbortController();let stopped=false;
  const base='/api/knowledge/pdf/jobs/'+encodeURIComponent(source.id);
  host.className='k-rich-document';
  host.append(el('p','正在整理可读的图文视图…','k-caption'));
  async function start() {
    try {
      const response=await fetch(base+'/content?text_sha256='+encodeURIComponent(options.textSha),
        {credentials:'same-origin',signal:abort.signal});
      if (!response.ok) throw new Error('Content unavailable');
      const data=await response.json();
      if (stopped) return;
      const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',
        new TextEncoder().encode(options.text)))].map(value=>value.toString(16).padStart(2,'0')).join('');
      if (stopped) return;
      if (data.sha256!==options.textSha || digest!==data.sha256) throw new Error('Content hash mismatch');
      const assets=new Map(data.assets.map(asset=>[asset.name,asset]));
      const rendered=new Set();
      const article=el('article',undefined,'k-document-body');
      const heading=el('div',undefined,'k-pane-heading');
      heading.append(el('strong','图文阅读'),el('span','原图保留 · 待人工核对'));
      const figures=el('details',undefined,'k-document-figures');
      figures.append(el('summary','图片目录 · '+data.assets.length+' 张'));
      const figureLinks=el('div',undefined,'k-document-figure-links');
      const figureMap=new Map();
      function figure(name,alt) {
        const asset=assets.get(name);
        if (!asset) return el('span','[图片关联未通过校验]');
        rendered.add(name);
        const box=el('figure',undefined,'k-document-figure');
        box.dataset.asset=name;
        const image=el('img');image.src=base+'/content/assets/'+encodeURIComponent(name);
        image.alt=alt || asset.captions.join(' ') || '论文图片';image.loading='lazy';image.decoding='async';
        image.addEventListener('error',()=>box.append(el('p','图片暂不可用，请对照左侧原 PDF。','k-caption')),{once:true});
        const caption=el('figcaption');
        if (asset.captions.length) mathText(caption,asset.captions.join('\n'));
        else caption.textContent=alt || '解析器保留的原图';
        const commands=el('div',undefined,'k-document-figure-actions');
        for (const page of asset.pages) commands.append(action('查看原 PDF 第 '+page+' 页',()=>options.onPage(page)));
        const download=el('a','打开图片','k-button');download.href=image.src;download.target='_blank';
        download.rel='noopener noreferrer';commands.append(download);
        box.append(image,caption,commands);
        for (const item of data.derived.filter(item=>item.asset===name)) {
          const details=el('details',undefined,'k-derived-content');
          details.append(el('summary','解析器图示转写 · 非论文原文 · 未入索引'),
            el('pre',item.text));
          box.append(details);
        }
        figureMap.set(name,box);
        return box;
      }
      function htmlTable(token) {
        const wrap=el('div',undefined,'k-document-table-wrap');
        const table=el('table');
        const body=el('tbody');
        token.rows.forEach((row,index)=>{
          const tr=el('tr');
          row.forEach(cell=>{
            const td=el(cell.header || index===0 ? 'th':'td');
            td.rowSpan=cell.rowspan;td.colSpan=cell.colspan;
            mathText(td,cell.text);tr.append(td);
          });
          body.append(tr);
        });
        table.append(body);wrap.append(table);return wrap;
      }
      const allowed=new Set(['p','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote',
        'em','strong','s','table','thead','tbody','tr','th','td','a']);
      function tokens(items,parent) {
        const stack=[parent], opened=[];
        for (const token of items) {
          const here=()=>stack[stack.length-1];
          if (token.type==='inline') {tokens(token.children||[],here());continue;}
          if (token.type==='safe_table') {here().append(htmlTable(token));continue;}
          if (token.type==='image') {
            const name=assetName(token.attrs?.src);
            here().append(name ? figure(name,token.content) : el('span','[未加载外部或未关联的图片]'));
            continue;
          }
          if (token.type==='text') {mathText(here(),token.content);continue;}
          if (['fence','code_block','code_inline'].includes(token.type)) {
            const code=el('code',token.content);
            if (token.type==='code_inline') here().append(code);
            else {const pre=el('pre');pre.append(code);here().append(pre);}
            continue;
          }
          if (token.type==='softbreak') {here().append(document.createTextNode('\n'));continue;}
          if (token.type==='hardbreak') {here().append(el('br'));continue;}
          if (token.type==='hr') {here().append(el('hr'));continue;}
          if (token.type==='html_inline') {
            if (/^<br\s*\/?>$/i.test(token.content)) here().append(el('br'));
            else here().append(document.createTextNode(token.content));
            continue;
          }
          if (token.nesting===1) {
            const tag=allowed.has(token.tag)?token.tag:'span';
            const node=el(tag);
            if (tag==='a') {
              const href=safeLink(token.attrs?.href);
              if (href) {node.href=href;node.target='_blank';node.rel='noopener noreferrer';}
            }
            if (tag==='ol' && /^\d+$/.test(String(token.attrs?.start||''))) node.start=Number(token.attrs.start);
            if (tag==='table') {const wrap=el('div',undefined,'k-document-table-wrap');here().append(wrap);wrap.append(node);}
            else here().append(node);
            opened.push(tag);stack.push(node);
          } else if (token.nesting===-1 && opened.length) {opened.pop();stack.pop();}
          else if (token.content) here().append(document.createTextNode(token.content));
        }
      }
      tokens(data.tokens,article);
      for (const asset of data.assets) {
        if (!rendered.has(asset.name)) article.append(figure(asset.name,'解析器保留的图片'));
        const box=figureMap.get(asset.name);
        figureLinks.append(action((asset.pages.length?'第 '+asset.pages.join('、')+' 页 · ':'')+
          (asset.captions.join(' ').slice(0,64)||'图片'),()=>{
            box?.scrollIntoView({block:'start',behavior:'auto'});
          }));
      }
      figures.append(figureLinks);
      const note=el('p','图片编码不参与分块；原始 Markdown 可下载。排版完成不代表 OCR、表格数值或多栏顺序已经核实。','k-content-note');
      host.replaceChildren(heading,note,figures,article);
      host.dataset.ready='true';
    } catch(error) {
      if (!stopped) host.replaceChildren(el('p','图文视图暂不可用，请查看整理后 Markdown 或下载原始文件。','k-caption'));
    }
  }
  start();
  return ()=>{stopped=true;abort.abort();};
}

'use strict';
(() => {
  let files = [], cid = null, generation = '';
  const dialog = document.createElement('dialog'); dialog.id = 'image-dialog';
  dialog.setAttribute('aria-labelledby', 'image-dialog-title');
  const header = element('header', undefined, 'image-dialog-header');
  const heading = element('h2', '图片对比'); heading.id = 'image-dialog-title';
  const close = element('button', '关闭', 'quiet'); close.type = 'button'; close.addEventListener('click', () => dialog.close());
  header.append(heading, close); dialog.append(header);
  const compare = element('div', undefined, 'image-compare'); dialog.append(compare);
  const note = element('p', '预览保留透明区域。GeoTIFF 默认展示第 1 波段，按采样有效值做显示拉伸；下载原始文件保留科学数值与坐标。视觉模型会收到图片像素，请仅提交可发送给所选模型的材料。', 'image-dialog-note');
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
  function clear() { files = []; cid = null; generation = ''; if (dialog.open) dialog.close(); document.getElementById('image-gallery')?.remove(); for (const p of panels) { p.image.removeAttribute('src'); p.select.replaceChildren(); p.download.removeAttribute('href'); } }
  function render(result, conversation) {
    if (state.cid !== conversation) return;
    cid = conversation; generation = result.generation;
    files = result.files.filter(file => /\.(png|jpe?g|webp|tiff?)$/i.test(file.name));
    document.getElementById('image-gallery')?.remove();
    if (!files.length) return;
    const gallery = element('section', undefined, 'image-gallery'); gallery.id = 'image-gallery'; gallery.setAttribute('aria-label', '对话图片');
    const head = element('div', undefined, 'image-gallery-head'), text = element('div');
    text.append(element('h3', '图片与处理结果'), element('p', files.length + ' 个图像文件 · 原件保留，可对比和下载'));
    const button = element('button', '对比图片', 'outline'); button.type = 'button'; button.addEventListener('click', () => open());
    head.append(text, button); gallery.append(head);
    const grid = element('div', undefined, 'image-grid');
    for (const file of files) {
      const card = element('article', undefined, 'image-card'), show = element('button'), img = element('img');
      show.type = 'button'; show.setAttribute('aria-label', '查看图片 ' + file.name); show.addEventListener('click', () => open(file.name));
      img.alt = file.name; img.loading = 'lazy'; img.src = url(file.name);
      img.addEventListener('error', () => { show.replaceChildren(element('span', '暂不能预览，可下载原文件', 'image-failed')); });
      show.append(img); const foot = element('footer'), link = element('a', '下载');
      link.href = url(file.name, 'download'); link.download = file.name.split('/').pop();
      foot.append(element('strong', file.name), link, element('small', (file.bytes / 1024).toFixed(1) + ' KiB · SHA-256 ' + file.sha256.slice(0, 12)));
      card.append(show, foot); grid.append(card);
    }
    gallery.append(grid); $('messages').append(gallery);
  }
  window.GeoAgentImages = {render, clear};
})();

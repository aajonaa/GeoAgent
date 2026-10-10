'use strict';
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
class Node {
  constructor(tag, text = '') { this.tag = tag; this.children = []; this._text = text; this.attributes = {}; this.events = {}; this.classes = new Set(); this.classList = {toggle:(key, force) => {const value = force === undefined ? !this.classes.has(key) : force; if (value) this.classes.add(key); else this.classes.delete(key); return value;}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(key, fn) { this.events[key] = fn; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  remove() { this.removed = true; }
}
const all = node => [node, ...node.children.flatMap(all)];
const root = path.join(__dirname, '../geological_agent/team/web');
const sandbox = {URL, window:{}, document:{createElement:tag => new Node(tag), createTextNode:text => new Node('#text', text), body:new Node('body')}};
const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
vm.createContext(sandbox);
vm.runInContext(app.slice(app.indexOf('function element('), app.indexOf('async function api(')) + app.slice(app.indexOf('function inline('), app.indexOf('async function initialize(')), sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'images.js'), 'utf8'), sandbox);
const files = ['jilin-results/triptych-2021-09-02.png', 'jilin-ndvi/values.tif', 'jilin-results/statistics.csv', 'diagram.svg', 'folder/map (final).png', 'folder/中文 图.png'];
const context = {run_id:'run-one', conversation_id:'owner-conversation', generation:'immutable-generation', files:files.map(name => ({name, sha256:'original-hash'}))};
const render = (text, ctx = context) => {const node = new Node('div'); sandbox.markdown(node, text, ctx); return node;};
const token = '[三联图 PNG](jilin-results/triptych-2021-09-02.png)';
const answer = render('### 查看与下载\n- ' + token + '\n- [CSV](jilin-results/statistics.csv)');
const image = all(answer).find(n => n.tag === 'img');
assert(image, 'A normal PNG link must display an image, without requiring ! syntax');
assert.equal(image.alt, '三联图 PNG');
assert.equal(image.src, '/api/conversations/owner-conversation/image?name=jilin-results%2Ftriptych-2021-09-02.png&generation=immutable-generation');
const csv = all(answer).find(n => n.tag === 'a' && n.textContent === 'CSV');
assert.equal(csv.download, 'statistics.csv'); assert(csv.href.includes('&generation=immutable-generation'));
assert(!answer.textContent.includes('](jilin-'));
for (const [name, href] of [['NDVI','jilin-ndvi/values.tif'],['SVG','diagram.svg'],['Parentheses','folder/map (final).png'],['Unicode','folder/%E4%B8%AD%E6%96%87%20%E5%9B%BE.png'],['Sandbox','sandbox:/mnt/data/diagram.svg']]) {
  assert(all(render('![' + name + '](' + href + ')')).some(n => n.tag === 'img'), name);
}
for (const target of ['javascript:alert(1)', 'data:image/svg+xml,evil', '//evil.example/x.png', '../diagram.svg', '%2e%2e/diagram.svg', '/api/conversations/other/image?name=diagram.svg', 'missing.png']) {
  const nodes = all(render('[Unsafe](' + target + ')'));
  assert(!nodes.some(n => n.tag === 'img' || n.tag === 'a'), target);
}
assert(!all(render(token, null)).some(n => n.tag === 'img'));
assert(!all(render(token, {...context, generation:''})).some(n => n.tag === 'img'));
assert(!all(render(token, {...context, files:[]})).some(n => n.tag === 'img'));
const second = all(render(token, {...context, conversation_id:'second', generation:'old-two'})).find(n => n.tag === 'img');
assert(second.src.includes('/second/image?') && second.src.endsWith('generation=old-two'));
const external = all(render('![External](https://example.org/image.png)'));
assert(!external.some(n => n.tag === 'img')); assert(external.some(n => n.tag === 'a' && n.rel === 'noopener noreferrer'));
const ticks = String.fromCharCode(96);
assert(!all(render(ticks + token + ticks)).some(n => n.tag === 'img'));
assert(!all(render(ticks.repeat(3) + '\n' + token + '\n' + ticks.repeat(3))).some(n => n.tag === 'img'));
assert(!all(render('<img src=x onerror=alert(1)>')).some(n => n.tag === 'img'));
all(answer).find(n => n.tag === 'button' && n.attributes['aria-label'] === '放大图片：三联图 PNG').events.click();
const modal = sandbox.document.body.children.find(n => n.className === 'answer-image-dialog');
assert(modal?.open); assert(all(modal).some(n => n.tag === 'img' && n.src === image.src));
const zoom = all(modal).find(n => n.tag === 'button' && n.textContent === '原尺寸查看'); zoom.events.click();
assert.equal(zoom.textContent, '适应窗口');
all(modal).find(n => n.tag === 'button' && n.textContent === '关闭').events.click(); assert(modal.removed);
image.events.error(); assert(answer.textContent.includes('暂不能预览')); assert(all(answer).some(n => n.tag === 'a' && n.download.endsWith('.png')));
console.log('Answer image/link rendering, immutable snapshots, zoom/download and unsafe-link cases passed');

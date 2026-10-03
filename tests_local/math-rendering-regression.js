const fs=require('fs'), vm=require('vm'), assert=require('assert');
class Node {
  constructor(tag,text=''){this.tag=tag;this.children=[];this._text=text;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;this._text='';}
  set textContent(text){this._text=String(text);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>typeof x==='string'?x:x.textContent).join('');}
}
const calls=[];
const sandbox={document:{createElement:tag=>new Node(tag),createTextNode:text=>new Node('#text',text)},
 window:{katex:{render:(text,node,options)=>{calls.push({text,options});node.textContent=text;}}}};
const source=fs.readFileSync(process.argv[2],'utf8');
vm.createContext(sandbox);
const element=source.slice(source.indexOf('function element('),source.indexOf('async function api('));
const renderer=source.slice(source.indexOf('function inline('),source.indexOf('async function initialize('));
vm.runInContext(element+renderer,sandbox);
function test(text,expected){calls.length=0;const target=new Node('div');sandbox.markdown(target,text);assert.deepStrictEqual(calls.map(x=>x.text),expected);for(const c of calls){assert.strictEqual(c.options.trust,false);assert.strictEqual(c.options.throwOnError,false);}return target;}
test('\\[ E=10^{13.8} \\]',['E=10^{13.8}']);
test('- Formula: \\[ E=10^{13.8} \\]',[' E=10^{13.8} ']);
test('$$E=10^{13.8}$$',['E=10^{13.8}']);
test('\\[\nE=10^{13.8}\n\\]',['E=10^{13.8}']);
test('$$\nE=10^{13.8}\n$$',['E=10^{13.8}']);
test('Energy \\(6.31\\times10^{13}\\) J',['6.31\\times10^{13}']);
const ticks=String.fromCharCode(96).repeat(3);
test(ticks+'\n\\[ not math \\]\n'+ticks,[]);
const unclosed=test('\\[\nnot closed\nnext paragraph',[]);assert(unclosed.textContent.includes('next paragraph'));
const unsafe=test('<img src=x onerror=alert(1)>',[]);assert(unsafe.textContent.includes('<img'));
sandbox.window.katex=null;
const fallback=test('\\[ E=1 \\]',[]);assert(fallback.textContent.includes('\\['));
console.log('10 math rendering/security cases passed');

'use strict';
// Isolated, explicitly synthetic UI-event playback. Never calls a model or the live application API.
const http = require('node:http'), fs = require('node:fs'), path = require('node:path');
const web = path.resolve(__dirname, '../geological_agent/team/web');
const experienceSource = fs.readFileSync(path.join(web, 'images.js'), 'utf8');
const marker = experienceSource.indexOf('// Compact research experience:');
if (marker < 0) throw new Error('Experience module not found');
const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GeoAgent activity playback acceptance</title><link rel="stylesheet" href="/assets/style.css"><link rel="stylesheet" href="/assets/images.css">
<style>body{display:block;overflow:auto;padding:clamp(16px,4vw,48px)}main{max-width:900px;margin:auto}.fixture-controls{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}.fixture-controls button{padding:9px 14px}article{padding:24px;border:1px solid #d7e0d1;border-radius:20px;background:#fffef9}.fixture-note{color:#66776c;font-size:13px}.run-elapsed{white-space:nowrap}</style>
<main><h1>GeoAgent</h1><p class="fixture-note">UI 事件回放验收 · 合成事件，非真实任务 · 不调用模型，不访问已有文件</p>
<div class="fixture-controls"><button id="inspect">影像检查</button><button id="ndvi">计算 NDVI</button><button id="review">结果审核</button><button id="lost">连接中断</button><button id="hitl">等待用户</button><button id="complete">完成</button></div>
<article><h2>夹皮沟 Sentinel-2 影像分析</h2><p id="elapsed" class="run-elapsed">Working for 0m 0s</p><details id="activity"><summary id="summary">执行详情</summary></details></article></main>
<script>const state={me:{id:'fixture'},cid:'fixture',runs:new Map()};function element(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}const statusText={};
const ui={turn:document.querySelector('article'),activity:document.getElementById('activity'),summary:document.getElementById('summary'),elapsed:document.getElementById('elapsed'),status:'running',finished:false};state.runs.set('fixture',ui);</script>
<script src="/experience.js"></script><script>
const experience=window.GeoAgentExperience;experience.attach('fixture',ui);let seq=0,pending='',started=Date.now();
function send(data){experience.event('fixture',data,String(++seq));}
function reset(){ui.status='running';ui.finished=false;if(pending){send({kind:'tool_result',id:pending,result:{status:'ok'}});pending='';}}
function tool(name,args){reset();pending='call-'+(seq+1);send({kind:'tool_start',id:pending,name,arguments:args});}
document.getElementById('inspect').onclick=()=>tool('GeoImageInspect',{path:'jiapigou-sentinel-rgbnir.tif'});
document.getElementById('ndvi').onclick=()=>tool('GeoRasterIndexAnalysis',{path:'jiapigou-sentinel-rgbnir.tif',index:'NDVI'});
document.getElementById('review').onclick=()=>{reset();send({kind:'status',message:'Checking the result',phase:'final_answer',turn:3});};
document.getElementById('lost').onclick=()=>experience.event('fixture',{kind:'connection_lost'});
document.getElementById('hitl').onclick=()=>{reset();send({kind:'finished',status:'needs_input',turns:3});};
document.getElementById('complete').onclick=()=>{reset();send({kind:'finished',status:'completed',turns:3});};
setInterval(()=>{const seconds=Math.floor((Date.now()-started)/1000);ui.elapsed.textContent=(ui.finished?'Worked for ':'Working for ')+Math.floor(seconds/60)+'m '+seconds%60+'s';if(ui.finished)started+=1000;},1000);
send({kind:'status',message:'Model is working',phase:'intent',turn:1});
</script></html>`;
const assets = new Map(['style.css','images.css'].map(name=>['/assets/'+name, fs.readFileSync(path.join(web,name))]));
const server=http.createServer((req,res)=>{
  res.setHeader('Cache-Control','no-store');
  if(req.url==='/'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(html);}
  if(req.url==='/experience.js'){res.setHeader('Content-Type','text/javascript; charset=utf-8');return res.end(experienceSource.slice(marker));}
  if(assets.has(req.url)){res.setHeader('Content-Type','text/css; charset=utf-8');return res.end(assets.get(req.url));}
  res.statusCode=404;res.end('Not found');
});
server.listen(18016,'127.0.0.1',()=>console.log('Activity playback: http://127.0.0.1:18016/'));

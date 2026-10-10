'use strict';
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const web=path.resolve(__dirname,'../geological_agent/team/web');
const assets=new Map(['style.css','images.css','timeline.js','timeline.css'].map(name=>['/assets/'+name,fs.readFileSync(path.join(web,name))]));
const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GeoAgent timeline UI acceptance</title>
<link rel="stylesheet" href="/assets/style.css"><link rel="stylesheet" href="/assets/images.css"><link rel="stylesheet" href="/assets/timeline.css">
<style>body{display:block;overflow:auto;padding:clamp(18px,5vw,50px)}main{max-width:820px;margin:auto}.fixture-note{font-size:12px;color:var(--muted)}article{padding:26px;border-radius:22px;background:var(--surface);border:1px solid var(--line);margin:20px 0}.fixture-controls{display:flex;flex-wrap:wrap;gap:7px}.fixture-answer{padding:15px 0 0;border-top:1px solid var(--line)}h1{font-size:25px}h2{font-size:16px}</style>
<main><h1>GeoAgent</h1><p class="fixture-note">交互验收 · 以下为明确标记的合成事件，不是模型实测或科学结果。</p><div class="fixture-controls"><button id="next">追加工具结果</button><button id="finish">完成任务</button></div>
<article><div class="assistant-label">GeoAgent</div><p class="fixture-note">执行中 · UI 回放</p><details id="activity"><summary id="summary">执行过程</summary><div id="list"></div></details><div class="fixture-answer"><h2>结果与过程分开呈现</h2><p>展开模型过程、资料来源或专业工具，即可查看对应记录。</p></div></article></main>
<script>const state={runs:new Map()};function element(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}window.GeoAgentExperience={describeTool:(name,args)=>({title:name==='GeoRasterIndexAnalysis'?'正在计算 '+args.index+' 指数':name,detail:args.path||name})};</script><script src="/assets/timeline.js"></script><script>
const ui={activity:document.getElementById('activity'),summary:document.getElementById('summary'),list:document.getElementById('list'),tools:new Map(),finished:false};state.runs.set('fixture',ui);const timeline=window.GeoAgentTimeline;timeline.attach('fixture',ui);let seq=0;const send=data=>timeline.event('fixture',data,String(++seq));
send({kind:'status',message:'Model is working',phase:'execution',turn:1});
send({kind:'model_process',phase:'execution',turn:1,source:'provider_reasoning_content',verified:false,text:'这是合成的界面回放文本，不是模型推理。先核对影像的波段和掩膜，再检查指数计算所需输入。'});
send({kind:'tool_start',id:'search',name:'web_search',arguments:{query:'Sentinel-2 数据来源与波段说明'}});
send({kind:'tool_result',id:'search',name:'web_search',result:{status:'ok',data:{results:[{title:'USGS · 来源卡片展示示例',url:'https://www.usgs.gov/',snippet:'这是来源列表的合成测试摘录，不是检索结果。'},{title:'Copernicus · 来源卡片展示示例',url:'https://www.copernicus.eu/',snippet:'真实外链，内容为界面测试说明。'}]}}});
send({kind:'status',message:'Model is working',phase:'execution',turn:2});
send({kind:'tool_start',id:'ndvi',name:'GeoRasterIndexAnalysis',arguments:{path:'fixture-sentinel.tif',index:'NDVI',red_band:1,nir_band:4}});
document.getElementById('next').onclick=()=>send({kind:'tool_result',id:'ndvi',name:'GeoRasterIndexAnalysis',result:{status:'ok',data:{index:'NDVI',mean:0.42,valid_pixels:100},artifacts:[{path:'fixture-ndvi/preview.png'}]}});
document.getElementById('finish').onclick=()=>{ui.finished=true;send({kind:'finished',status:'completed'});};
</script></html>`;
http.createServer((req,res)=>{res.setHeader('Cache-Control','no-store');if(req.url==='/'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(html);}if(assets.has(req.url)){res.setHeader('Content-Type',req.url.endsWith('.js')?'text/javascript; charset=utf-8':'text/css; charset=utf-8');return res.end(assets.get(req.url));}res.statusCode=404;res.end('Fixture only; no model or receipt API');}).listen(18017,'127.0.0.1',()=>console.log('Timeline preview: http://127.0.0.1:18017/'));

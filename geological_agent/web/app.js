"use strict";
const $ = id => document.getElementById(id);
let session=null, operatorKey=sessionStorage.getItem("workspace-key")||"", controller=null;
let current=null, lastEvent=0, running=false, answer="";
const steps=new Map(), BT=String.fromCharCode(96);
const promptExample="The local calc.py has a numerical bug: 200 ore tonnes at grade_pct=1.5 should contain 3 tonnes of metal. Inspect and repair the saved file without changing contained_metal(ore_tonnes, grade_pct). Actually call the function from the saved file and assert (200,1.5)->3 and (100,1.2)->1.2. Preserve calc.py and explain what changed.";
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function inline(s){return esc(s).replace(new RegExp(BT+"([^"+BT+"]+)"+BT,"g"),"<code>$1</code>").replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");}
function codeBlock(lines){
 const text=lines.join("\n"),body="<pre><code>"+esc(text)+"</code></pre>";
 // Keep diagnostics accessible without dumping them into the default answer.
 const trace=/^\s*\{/.test(text)&&/["']checks["']\s*:/.test(text)&&/["']facts["']\s*:/.test(text);
 return trace?'<details class="verification-data"><summary>Verification details</summary>'+body+"</details>":body;
}
function renderAnswer(element,text){
 element.innerHTML=markdown(text);
 if(typeof renderMathInElement==="function")renderMathInElement(element,{
  output:"mathml",trust:false,throwOnError:false,strict:"ignore",maxSize:10,
  delimiters:[{left:"$",right:"$",display:true},{left:"$",right:"$",display:false},{left:"\\[",right:"\\]",display:true},{left:"\\(",right:"\\)",display:false}]
 });
}
function markdown(text){
 const lines=text.split("\n");let out="",code=null,fence=null,list=false;
 const close=()=>{if(list){out+="</ul>";list=false;}};
 const cells=s=>s.trim().replace(/^\||\|$/g,"").split("|").map(x=>x.trim());
 for(let i=0;i<lines.length;i++){
  const line=lines[i];
  const marker=/^\s{0,3}(`{3,}|~{3,})(.*)$/.exec(line);
  if(code!==null){
   if(marker&&marker[1][0]===fence[0]&&marker[1].length>=fence.length&&!marker[2].trim()){out+=codeBlock(code);code=null;fence=null;}
   else code.push(line);continue;
  }
  if(marker){close();code=[];fence=marker[1];continue;}
  if(/^\s*\|.*\|\s*$/.test(line)&&i+1<lines.length&&/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i+1])){
   close();out+="<table><thead><tr>"+cells(line).map(c=>"<th>"+inline(c)+"</th>").join("")+"</tr></thead><tbody>";i+=2;
   while(i<lines.length&&/^\s*\|.*\|\s*$/.test(lines[i])){out+="<tr>"+cells(lines[i]).map(c=>"<td>"+inline(c)+"</td>").join("")+"</tr>";i++;}
   i--;out+="</tbody></table>";continue;
  }
  const mathOpen=["$$",String.fromCharCode(92)+"["].includes(line.trim());
  if(mathOpen){
   close();const closing=line.trim()==="$$"?"$$":String.fromCharCode(92)+"]",parts=[line];
   while(i+1<lines.length){parts.push(lines[++i]);if(lines[i].trim()===closing)break;}
   out+='<div class="math-block">'+esc(parts.join("\n"))+"</div>";continue;
  }
  const h=/^(#{1,6})\s+(.+)$/.exec(line),b=/^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
  if(h){close();out+="<h"+h[1].length+">"+inline(h[2])+"</h"+h[1].length+">";continue;}
  if(b){if(!list){out+="<ul>";list=true;}out+="<li>"+inline(b[1])+"</li>";continue;}
  close();if(line.trim())out+="<p>"+inline(line)+"</p>";
 }
 close();if(code!==null)out+=codeBlock(code);return out;
}
function notice(text){$("notice").textContent=text||"";$("notice").classList.toggle("hidden",!text);}
function busy(value,label){running=value;$("status").textContent=label||(value?"Working":"Ready");$("status").classList.toggle("busy",value);$("send").disabled=value;$("stop").classList.toggle("hidden",!value);$("example").disabled=value;$("upload").disabled=value;if(value)$("resume").classList.add("hidden");}
const url=s=>"/api/sessions/"+session.id+s;
async function api(path,options={},operator=false){
 const headers=new Headers(options.headers||{});headers.set("Authorization","Bearer "+(operator?operatorKey:session?.token||""));
 if(typeof options.body==="string")headers.set("Content-Type","application/json");
 const response=await fetch(path,{...options,headers});
 if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(data.detail||"Request failed ("+response.status+")");}return response;
}
function turn(text){
 $("welcome")?.remove();current=document.createElement("article");current.className="turn";
 current.innerHTML='<div class="user-message"></div><div class="agent-label">GeoToolAgent</div><details class="activity" open><summary>Activity</summary><ol class="steps"></ol></details><div class="answer"></div><div class="downloads"></div>';
 current.querySelector(".user-message").textContent=text;$("conversation").append(current);answer="";
}
function detail(item,title,text){if(!text)return;const d=document.createElement("details"),s=document.createElement("summary"),p=document.createElement("pre");d.className="detail";s.textContent=title;p.textContent=text;d.append(s,p);item.append(d);}
function resultText(r){
 if(r.summary)return r.summary;const v=r.result||{};if(!r.ok)return r.message||r.error||"Exited "+r.exit_code;
 if(r.status==="running")return "Running · job "+r.job_id;
 if("exit_code" in r)return "Exited "+r.exit_code;
 if(v.sha256)return v.bytes.toLocaleString()+" bytes · SHA256 recorded";
 if(v.items)return v.items.length+" entries"+(v.next_offset!==null?" · more available":"");return "Completed";
}
async function download(a,button){
 button.disabled=true;
 try{
  await api(url("/download-access"),{method:"POST"});
  const link=document.createElement("a");
  link.href=url("/artifacts/"+a.id);link.download=a.name;
  document.body.append(link);link.click();link.remove();
 }catch(e){notice(e.message);}finally{button.disabled=false;}
}
function artifacts(items){
 if(!current)return;const area=current.querySelector(".downloads");area.replaceChildren();
 for(const a of items){const b=document.createElement("button"),n=document.createElement("strong"),s=document.createElement("small");b.className="download";n.textContent="Download "+a.name;s.textContent=a.bytes.toLocaleString()+" bytes · SHA256 "+a.sha256.slice(0,10);b.append(n,s);b.addEventListener("click",()=>download(a,b));area.append(b);}
}
function consume(event){
 if(event.id<=lastEvent)return;lastEvent=event.id;const box=$("conversation"),near=box.scrollHeight-box.scrollTop-box.clientHeight<180,d=event.data,k=event.kind;
 if(k==="user"){turn(d.text);notice("");}
 if(!current&&["tool_start","tool_result","answer_start","answer_delta","question"].includes(k))turn("Recovered workspace");
 if(k==="status")busy(true,d.message);
 if(k==="tool_start"){
  const item=document.createElement("li");item.className="step";
  item.innerHTML='<div class="step-head"><span class="tool"></span><span class="step-summary"></span></div><div class="result">Running</div>';
  item.querySelector(".tool").textContent=d.tool;item.querySelector(".step-summary").textContent=d.summary||d.arguments.path||d.tool;
  detail(item,d.tool==="exec"?"Command":"Target",d.arguments.command||d.arguments.code||d.arguments.path||d.arguments.query||"");
  current.querySelector(".steps").append(item);steps.set(d.id,item);current.querySelector(".activity>summary").textContent=current.querySelectorAll(".step").length+" actions";
 }
 if(k==="tool_result"){const item=steps.get(d.id);if(item){item.classList.toggle("failed",!d.result.ok);item.querySelector(".result").textContent=resultText(d.result);detail(item,"Output",d.result.output||d.result.result?.content||d.result.result?.diff||"");}}
 if(k==="notice"||k==="paused")notice(d.message);
 if(k==="verification"){
  const item=document.createElement("li");item.className="step"+(d.ok?"":" failed");
  const title=document.createElement("div");title.textContent=d.ok?"Read-only output checks passed":"Output checks need repair";item.append(title);
  for(const [name,passed] of Object.entries(d.checks||{})){const row=document.createElement("div");row.className="result";row.textContent=(passed?"Passed: ":"Failed: ")+name;item.append(row);}
  detail(item,"Check output",d.output||d.error||"");current.querySelector(".steps").append(item);
 }
 if(k==="answer_start"){answer="";current.querySelector(".answer").replaceChildren();if(d.provisional)notice("Draft answer is streaming. Completion will be confirmed after checking it against the files.");}
 if(k==="answer_retracted"){answer="";current.querySelector(".answer").replaceChildren();current.querySelector(".downloads").replaceChildren();notice(d.message);}
 if(k==="answer_delta"){answer+=d.text;renderAnswer(current.querySelector(".answer"),answer);}
 if(k==="question"){renderAnswer(current.querySelector(".answer"),d.text);busy(false,"Your input needed");}
 if(k==="finished"){busy(false,d.status);$("resume").classList.add("hidden");notice(d.message);if(d.artifacts)artifacts(d.artifacts);loadFiles().catch(()=>{});}
 if(k==="completed"){busy(false,"Completed");notice("");artifacts(d.artifacts);current.querySelector(".activity").open=false;loadFiles().catch(()=>{});}
 if(k==="paused"||k==="cancelled"){busy(false,k==="paused"?"Paused":"Stopped");$("resume").classList.add("hidden");notice(d.message);loadFiles().catch(()=>{});}
 if(near)box.scrollTop=box.scrollHeight;
}
async function stream(){
 controller?.abort();const c=new AbortController();controller=c;
 while(!c.signal.aborted){
  try{const response=await api(url("/events?after="+lastEvent),{signal:c.signal}),reader=response.body.getReader(),decoder=new TextDecoder();let buffer="";
   while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let at;
    while((at=buffer.indexOf("\n\n"))>=0){const block=buffer.slice(0,at);buffer=buffer.slice(at+2);const data=block.split("\n").filter(x=>x.startsWith("data:")).map(x=>x.slice(5).trim()).join("\n");if(data)consume(JSON.parse(data));}
   }
  }catch(e){if(c.signal.aborted)return;notice("Connection interrupted. Reconnecting to the saved event stream...");}
  if(!c.signal.aborted)await new Promise(resolve=>setTimeout(resolve,2000));
 }
}
async function loadFiles(){
 if(!session)return;const r=await api(url("/files")),data=await r.json();$("files").replaceChildren();
 if(!data.ok){$("files").textContent=data.message||data.error;return;}
 const items=data.result.items.filter(x=>!x.path.startsWith(".tmp/"));if(!items.length)$("files").textContent="No files yet.";
 for(const item of items){const row=document.createElement("div"),size=document.createElement("small");row.className="file";row.textContent=item.path;size.textContent=item.bytes.toLocaleString()+" bytes";row.append(size);$("files").append(row);}
}
async function connect(saved){
 controller?.abort();session=saved;lastEvent=0;steps.clear();current=null;answer="";
 if($("conversation").querySelector(".turn"))$("conversation").replaceChildren();
 localStorage.setItem("geotool-native-session-v1",JSON.stringify(session));
 const r=await api(url("")),state=await r.json();busy(state.status==="running",state.status==="idle"?"Ready":state.status);
 $("resume").classList.add("hidden");stream();await loadFiles();
}
async function newWorkspace(){
 if(!operatorKey){$("login").showModal();return;}
 if(running&&!confirm("The current task will keep running. Open a new workspace?"))return;
 const r=await api("/api/sessions",{method:"POST"},true);await connect(await r.json());notice("");
}
$("login-form").addEventListener("submit",async e=>{e.preventDefault();operatorKey=$("key").value.trim();try{await api("/api/auth",{method:"POST"},true);sessionStorage.setItem("workspace-key",operatorKey);$("login").close();$("key").value="";await newWorkspace();}catch(e){$("login-error").textContent=e.message;}});
$("new").addEventListener("click",()=>newWorkspace().catch(e=>notice(e.message)));
$("refresh").addEventListener("click",()=>loadFiles().catch(e=>notice(e.message)));
$("example").addEventListener("click",async()=>{try{if(!session){$("login").showModal();return;}$("example").disabled=true;await api(url("/example"),{method:"POST"});$("prompt").value=promptExample;await loadFiles();$("prompt").focus();}catch(e){notice(e.message);}finally{$("example").disabled=false;}});
$("try").addEventListener("click",()=>$("example").click());
$("upload").addEventListener("change",async()=>{const file=$("upload").files[0];if(!file||!session)return;try{await api(url("/upload?name="+encodeURIComponent(file.name)),{method:"POST",body:file});await loadFiles();}catch(e){notice(e.message);}finally{$("upload").value="";}});
$("composer").addEventListener("submit",async e=>{e.preventDefault();if(running||!$("prompt").value.trim())return;if(!session){$("login").showModal();return;}try{busy(true);notice("");await api(url("/messages"),{method:"POST",body:JSON.stringify({text:$("prompt").value})});$("prompt").value="";}catch(e){busy(false);notice(e.message);}});
$("prompt").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();$("composer").requestSubmit();}});
$("stop").addEventListener("click",async()=>{try{await api(url("/cancel"),{method:"POST"});notice("Stop requested. Waiting for the current operation to return.");}catch(e){notice(e.message);}});
$("resume").addEventListener("click",async()=>{try{await api(url("/resume"),{method:"POST"});busy(true);notice("");}catch(e){notice(e.message);}});
$("about-open").addEventListener("click",()=>$("about").showModal());$("about-close").addEventListener("click",()=>$("about").close());
(async()=>{const health=await fetch("/api/health").then(r=>r.json());$("release").textContent=health.release;const saved=localStorage.getItem("geotool-native-session-v1");if(saved){try{await connect(JSON.parse(saved));return;}catch(e){localStorage.removeItem("geotool-native-session-v1");notice(e.message);}}if(operatorKey){try{await api("/api/auth",{method:"POST"},true);await newWorkspace();return;}catch(e){notice(e.message);}}$("login").showModal();})().catch(e=>notice(e.message));

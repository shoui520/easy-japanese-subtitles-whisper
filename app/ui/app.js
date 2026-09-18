const token=location.hash.slice(1)||sessionStorage.getItem('appToken')||'';sessionStorage.setItem('appToken',token);history.replaceState(null,'',location.pathname);
const $=id=>document.getElementById(id);let state=null,renderKey='',busy=false,runtimeInfo=null;
function showError(message){$('error').textContent=message;$('error').hidden=false;}
async function api(path,body){const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'X-App-Token':token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||data.detail||'Request failed');return data;}
async function action(fn){try{$('error').hidden=true;await fn();await refresh();}catch(e){showError(e.message);}}
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function button(text,fn,cls='text-button'){const b=el('button',cls,text);b.onclick=()=>action(fn);return b;}
let logItem=null,logGeneration=0,logTimer=null;
async function refreshLog(generation,initial=false){
 const item=logItem;
 try{
  const data=await api('log/'+item);
  if(generation!==logGeneration||!$('logDialog').open)return;
  const box=$('logText');
  const follow=initial||box.scrollHeight-box.scrollTop-box.clientHeight<30;
  const position=box.scrollTop;
  if(box.textContent!==data.text)box.textContent=data.text;
  box.scrollTop=follow?box.scrollHeight:position;
  $('logStatus').textContent='Live · refreshes every second';
 }catch(e){
  if(generation===logGeneration&&$('logDialog').open)$('logStatus').textContent='Could not refresh: '+e.message+' · retrying…';
 }finally{
  if(generation===logGeneration&&$('logDialog').open)logTimer=setTimeout(()=>refreshLog(generation),1000);
 }
}
function openLog(item){
 clearTimeout(logTimer);logItem=item;const generation=++logGeneration;
 $('logText').textContent='Loading log…';$('logStatus').textContent='Connecting…';
 if(!$('logDialog').open)$('logDialog').showModal();
 return refreshLog(generation,true);
}
$('logDialog').addEventListener('close',()=>{++logGeneration;logItem=null;clearTimeout(logTimer);});
function trackSelect(item,key,tracks,empty){const select=el('select');const none=el('option','',empty);none.value='';select.append(none);for(const t of tracks){const o=el('option','',`#${t.index} · ${t.language} · ${t.title||t.codec}${t.channels?' · '+t.channels+'ch':''}`);o.value=t.index;select.append(o);}select.value=item[key]??'';select.disabled=['processing','inspecting'].includes(item.status);select.onchange=()=>action(()=>api('edit/'+item.id,{[key]:select.value===''?null:Number(select.value)}));return select;}
function duration(seconds){
 if(!Number.isFinite(seconds))return '—';
 seconds=Math.max(0,Math.round(seconds));
 return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
}
function selectedCompute(){
 const devices=runtimeInfo?.runtimes?.[0]?.devices||[];
 const requested=state?.settings?.device||'auto';
 return devices.find(d=>d.available&&(requested==='auto'||d.id===requested));
}
let modelSetup=null;
function renderModelSetup(items){
 const dialog=$('downloadSetup');
 if(!modelSetup){
  const item=items.find(i=>i.status==='processing'&&i.stage==='Downloading model');
  if(!item)return;
  modelSetup={id:item.id};
 }
 const item=items.find(i=>i.id===modelSetup.id);
 if(!item){if(dialog.open)dialog.close();modelSetup=null;return;}
 const pending=item.status==='processing'&&['Downloading model','Loading model'].includes(item.stage);
 const failed=['failed','cancelled','interrupted'].includes(item.status)||item.stage==='Failed';
 if(!pending&&!failed){if(dialog.open)dialog.close();modelSetup=null;return;}
 if(!dialog.open)dialog.showModal();
 $('downloadTitle').textContent=failed?(item.status==='cancelled'?'Download cancelled':'Model setup needs attention'):'Preparing your model';
 $('downloadStage').textContent=failed?(item.error||'The download could not finish. Retry when ready.'):
   item.stage==='Loading model'?'Download finished. Loading the model…':item.detail||'Downloading model files…';
 const bar=$('downloadProgress');bar.max=1;
 if(pending&&item.stage==='Downloading model'&&item.progress!=null)bar.value=item.progress;
 else bar.removeAttribute('value');
 bar.hidden=failed;
 $('downloadBytes').textContent=pending&&item.stage==='Downloading model'?
  ((item.downloaded_bytes||0)/1024/1024).toFixed(1)+' MB'+(item.download_bytes?' / '+(item.download_bytes/1024/1024).toFixed(1)+' MB':' downloaded'):'';
 $('downloadRetry').hidden=!failed;
 $('downloadRetry').disabled=state.running;
 $('downloadDismiss').textContent=failed?'Close':'Cancel queue';
}
$('downloadSetup').addEventListener('cancel',event=>{event.preventDefault();$('downloadDismiss').onclick();});
$('downloadDismiss').onclick=()=>action(async()=>{
 if(!modelSetup)return;
 const item=state.items.find(i=>i.id===modelSetup.id);
 if(item?.status==='processing'&&item.stage!=='Failed')await api('cancel',{});
 else {$('downloadSetup').close();modelSetup=null;}
});
$('downloadRetry').onclick=()=>action(async()=>{
 if(!modelSetup)return;
 const id=modelSetup.id;
 await api('edit/'+id,{});
 $('downloadSetup').close();modelSetup=null;
 await api('start',{});
});
function progressPanel(item){
 const panel=el('div','progress-panel');
 const heading=el('div','progress-heading');
 heading.append(el('strong','',item.stage));
 heading.append(el('strong','percent',item.progress==null?'Working…':Math.floor(item.progress*100)+'%'));
 panel.append(heading);
 const bar=el('progress');bar.max=1;bar.setAttribute('aria-label',item.stage);
 if(item.progress!=null)bar.value=item.progress;
 panel.append(bar);
 const details=el('div','progress-details');
 details.append(el('span','',item.detail||''));
 if(item.stage==='Downloading model'){
  const mb=value=>(value/1024/1024).toFixed(1)+' MB';
  details.append(el('span','',mb(item.downloaded_bytes||0)+(item.download_bytes?' / '+mb(item.download_bytes):' downloaded')+' · current file'));
 }
 if(item.total_seconds>0&&['Transcribing','Extracting Japanese audio'].includes(item.stage)){
  details.append(el('span','',duration(item.processed_seconds||0)+' / '+duration(item.total_seconds)+' of audio'));
 }
 panel.append(details);
 const timing=el('div','progress-details');
 const elapsed=(Date.now()/1000)-(item.started_at||Date.now()/1000);
 timing.append(el('span','','Elapsed '+duration(elapsed)));
 timing.append(el('span','',item.eta_seconds!=null?'About '+duration(item.eta_seconds)+' left in transcription':
  item.stage==='Transcribing'?'Estimating time remaining…':''));
 panel.append(timing);
 const steps=el('ol','steps');
 const phase=item.phase||1;
 for(const [index,name] of ['Prepare','Read timings','Extract audio','Load model','Transcribe','Save SRT'].entries()){
  steps.append(el('li',index+1<phase?'done':index+1===phase?'current':'',name));
 }
 panel.append(steps);
 return panel;
}
function render(){
 const items=state.items;
 renderModelSetup(items);
 const finished=items.filter(i=>['complete','skipped','failed','cancelled'].includes(i.status)).length;
 const saved=items.filter(i=>i.status==='complete').length;
 const failed=items.filter(i=>i.status==='failed').length;
 const active=items.find(i=>i.status==='processing');
 $('count').textContent=items.length;
 $('summary').textContent=finished+' / '+items.length+' finished · '+saved+' saved'+(failed?' · '+failed+' failed':'');
 // This bar counts completed files, not a made-up weighted percentage of unrelated stages.
 $('overall').value=items.length?finished/items.length:0;
 $('overall').setAttribute('aria-label','Finished files');
 const packages=runtimeInfo?.runtimes?.[0]?.packages||{};
 const ready=Boolean(selectedCompute()&&!runtimeInfo?.runtimes?.[0]?.error&&packages.torch&&(state.settings.model==='turbo'?packages.whisper:packages.transformers&&packages.accelerate)&&runtimeInfo?.ffmpeg&&runtimeInfo?.ffprobe);
 $('start').disabled=state.running||!items.some(i=>i.status==='ready')||!ready;
 $('stop').disabled=!state.running;
 $('model').disabled=state.running;
 $('model').value=state.settings.model;
 $('recursive').checked=state.settings.recursive;
 $('testBanner').hidden=!state.output_override;
 if(state.output_override)$('testBanner').textContent='TEST MODE — subtitles go to '+state.output_override+'. They will NOT appear beside your videos in this session.';
 const activity=$('activity');
 activity.hidden=!active;
 if(active){
  activity.replaceChildren(el('div','eyebrow','CURRENT EPISODE'),el('h2','',active.name),progressPanel(active));
 }
 const key=JSON.stringify(items);
 if(key===renderKey)return;
 if($('queue').contains(document.activeElement)&&document.activeElement.tagName==='SELECT')return;
 renderKey=key;
 const root=$('queue');root.replaceChildren();
 if(!items.length){root.append(el('div','empty','No episodes yet. Add files or a folder to get started.'));return;}
 const groups=new Map();
 for(const item of items){
  if(!groups.has(item.group))groups.set(item.group,[]);
  groups.get(item.group).push(item);
 }
 for(const [group,rows] of groups){
  const section=el('section','group');
  const head=el('div','group-head');
  const path=el('span','group-path',group);path.title=group;
  const removeGroup=button('Remove group from queue',()=>api('remove',{ids:rows.filter(i=>!['processing','inspecting'].includes(i.status)).map(i=>i.id)}));
  removeGroup.title='Removes non-running items in this group from the queue. Videos and subtitles on disk are never deleted.';
  head.append(path,removeGroup);
  section.append(head);
  for(const item of rows){
   const card=el('article','card');
   const top=el('div','card-top');
   top.append(el('div','filename',item.name),el('span','badge '+item.status,item.status.replace('_',' ')));
   card.append(top);
   if(item.audio){
    const tracks=el('div','tracks');
    const audio=el('label','','Japanese audio');
    audio.append(trackSelect(item,'audio_index',item.audio,'Choose Japanese audio'));
    const subtitles=el('label','','Timing source');
    subtitles.append(trackSelect(item,'subtitle_index',item.subtitles,item.needs_subtitle_choice?'Choose timing source':'Model timestamps · no subtitle guide'));
    tracks.append(audio,subtitles);card.append(tracks);
   }
   const destination=el('div','destination');
   destination.append(el('span','',item.status==='complete'?'Saved to':item.status==='skipped'?'Already exists':'Will save to'),
     el('span','output-path',item.output_error||item.output||'Checking destination…'));
   card.append(destination);
   const status=el('div','status-row');
   status.append(el('span','',item.stage+(item.status==='processing'&&item.progress!=null?' · '+Math.floor(item.progress*100)+'%':'')+(item.status==='complete'?' · '+(item.cues||0)+' subtitle cues'+(item.finished_at&&item.started_at?' · '+duration(item.finished_at-item.started_at):''):'')));
   const controls=el('div');
   if(item.status==='processing')controls.append(button('Cancel',()=>api('cancel',{id:item.id})));
   else if(item.status!=='inspecting'){
    if(['failed','cancelled','interrupted'].includes(item.status)&&item.audio)controls.append(button('Retry',()=>api('edit/'+item.id,{})));
    controls.append(button('Remove',()=>api('remove',{ids:[item.id]})));
   }
   if(['complete','skipped'].includes(item.status))controls.append(button('Open folder',()=>nativeOutputFolder(item.id)));
   controls.append(button('View log',()=>openLog(item.id)));
   status.append(controls);card.append(status);
   if(item.error)card.append(el('div','item-error',item.error));
   section.append(card);
  }
  root.append(section);
 }
}
async function nativeOutputFolder(id){
 if(!window.pywebview)throw Error('Open the desktop app to open a local output folder.');
 await window.pywebview.api.open_output_folder(id);
}
async function refresh(){if(busy)return;busy=true;try{state=await api('state');render();}catch(e){showError('Cannot reach the local app. '+e.message);}finally{busy=false;}}
async function nativePick(method){if(!window.pywebview)throw Error('Open the desktop app to choose local files and folders.');await window.pywebview.api[method]();}
$('addFiles').onclick=()=>action(()=>nativePick('pick_files'));$('addFolder').onclick=()=>action(()=>nativePick('pick_folder'));
$('start').onclick=()=>action(()=>api('start',{}));$('stop').onclick=()=>action(()=>api('cancel',{}));$('clear').onclick=()=>action(()=>api('remove',{ids:state.items.filter(i=>!['processing','inspecting'].includes(i.status)).map(i=>i.id)}));
$('model').onchange=()=>action(()=>api('settings',{model:$('model').value}));$('recursive').onchange=()=>action(()=>api('settings',{recursive:$('recursive').checked}));
$('setupButton').onclick=()=>{for(const k of ['python','ffmpeg','ffprobe','device'])$(k).value=state.settings[k];$('setup').showModal();};
$('changeRuntime').onclick=()=>action(async()=>{if(!window.pywebview)throw Error('Open the desktop app to change its runtime.');await window.pywebview.api.change_runtime();});
$('saveSetup').onclick=()=>action(async()=>{await api('settings',Object.fromEntries(['python','ffmpeg','ffprobe','device'].map(k=>[k,$(k).value])));$('setup').close();await checkRequirements();});
async function checkRequirements(){
 $('runtimeStatus').textContent='Checking the local transcription engine…';
 $('diagnostics').textContent='Checking packages and GPU…';$('check').disabled=true;
 try{
  runtimeInfo=await api('diagnostics',{});
  const runtime=runtimeInfo.runtimes[0]||{},packages=runtime.packages||{};
  const missing=[];
  if(!packages.torch)missing.push('PyTorch');
  if(!packages.transformers)missing.push('Transformers (Japanese models)');
  if(!packages.whisper)missing.push('Whisper (Turbo)');
  if(!packages.accelerate)missing.push('Accelerate');
  if(!runtimeInfo.ffmpeg||!runtimeInfo.ffprobe)missing.push('FFmpeg / FFprobe');
  const compute=selectedCompute();
  $('runtimeStatus').textContent=missing.length?'Setup needed: '+missing.join(', ')+'. Open Setup & diagnostics.':
   runtime.error?'The engine could not load. Open Setup & diagnostics.':
   !compute?'Selected processing device is unavailable. Choose a matching runtime in Setup or use CPU.':
   compute.id!=='cpu'?'Ready · '+compute.label+' · '+compute.name+(compute.vram_gb?' · '+compute.vram_gb+' GB GPU memory':''):
   'Ready · CPU processing (slower)';
  $('diagnostics').textContent=JSON.stringify(runtimeInfo,null,2);
  if(state)render();
 }catch(e){$('runtimeStatus').textContent='Could not check the engine. Open Setup & diagnostics.';throw e;}
 finally{$('check').disabled=false;}
}
$('check').onclick=()=>action(checkRequirements);
for(const name of ['dragenter','dragover'])document.addEventListener(name,e=>{e.preventDefault();$('dropzone').classList.add('dragging');});for(const name of ['drop','dragleave'])document.addEventListener(name,e=>{e.preventDefault();$('dropzone').classList.remove('dragging');});
refresh();action(checkRequirements);setInterval(refresh,1200);

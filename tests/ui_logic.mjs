// DOM-level unit checks; no native window/browser automation is required.
import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';

export async function verify(project) {
  const source=await fs.readFile(project+'/app/ui/app.js','utf8');
  new vm.Script(source);
  class Element {
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.textContent='';this.open=false;this.scrollHeight=1000;this.scrollTop=0;this.clientHeight=200;this.classList={add(){},remove(){}};}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=nodes;}
    addEventListener(name,fn){this.listeners[name]=fn;}
    setAttribute(name,value){this[name]=value;}
    removeAttribute(name){delete this[name];}
    contains(){return false;}
    showModal(){this.open=true;}
    close(){this.open=false;this.listeners.close?.();}
  }
  const nodes={};
  const node=id=>nodes[id]??=(new Element());
  let log='initial log',timers=0;
  const context=vm.createContext({console,Date,Map,Number,String,Math,JSON,Boolean,
    location:{hash:'#token',pathname:'/'},history:{replaceState(){}},sessionStorage:{getItem(){},setItem(){}},
    document:{getElementById:node,createElement:tag=>new Element(tag),activeElement:null,addEventListener(){}},
    window:{},setTimeout:()=>++timers,clearTimeout(){},setInterval(){},
    fetch:async()=>({ok:true,json:async()=>({text:log})})});
  // Suppress startup network checks; exercise functions against controlled data.
  vm.runInContext(source.replace('refresh();action(checkRequirements);setInterval(refresh,1200);',''),context);
  let runtimeChangeRequested=false;
  context.window.pywebview={api:{change_runtime:async()=>{runtimeChangeRequested=true;}}};
  await node('changeRuntime').onclick();
  assert.equal(runtimeChangeRequested,true);
  const flatten=element=>element.textContent+' '+element.children.map(flatten).join(' ');
  context.fixture={items:[{id:'a',name:'Episode 01.mkv',source:'C:/A/Episode 01.mkv',group:'C:/A',output:'C:/A/Episode 01.anime.ja.srt',status:'processing',stage:'Transcribing',phase:5,progress:.5,detail:'Dialogue section 4 of 8',processed_seconds:120,total_seconds:240,eta_seconds:30,started_at:Date.now()/1000-30},
    {id:'b',name:'Episode 01.mkv',source:'C:/B/Episode 01.mkv',group:'C:/B',output:'C:/B/Episode 01.anime.ja.srt',status:'complete',stage:'Complete',cues:10}],
    running:true,settings:{model:'anime',recursive:true},output_override:null};
  vm.runInContext('state=fixture;render()',context);
  assert.match(flatten(node('activity')),/50%/);
  assert.match(flatten(node('activity')),/2:00 \/ 4:00/);
  assert.match(flatten(node('activity')),/About 0:30 left/);
  assert.match(flatten(node('queue')),/C:\/A\/Episode 01.anime.ja.srt/);
  assert.match(flatten(node('queue')),/C:\/B\/Episode 01.anime.ja.srt/);
  assert.equal(node('testBanner').hidden,true);
  context.devices=[{id:'rocm',label:'ROCm / HIP',available:true,torch_device:'cuda'},
                   {id:'xpu',label:'XPU',available:true,torch_device:'xpu'},
                   {id:'cpu',label:'CPU',available:true,torch_device:'cpu'}];
  vm.runInContext('runtimeInfo={runtimes:[{devices}]};state.settings.device="auto"',context);
  assert.equal(vm.runInContext('selectedCompute().id',context),'rocm');
  vm.runInContext('state.settings.device="xpu"',context);
  assert.equal(vm.runInContext('selectedCompute().id',context),'xpu');
  vm.runInContext('state.settings.device="cpu"',context);
  assert.equal(vm.runInContext('selectedCompute().id',context),'cpu');
  vm.runInContext('state.settings.device="cuda";render()',context);
  assert.equal(vm.runInContext('selectedCompute()',context),undefined);
  assert.equal(node('start').disabled,true);
  const originalItems=context.fixture.items;
  context.fixture.items=[{id:'download',status:'processing',stage:'Downloading model',progress:.5,downloaded_bytes:1048576,download_bytes:2097152}];
  vm.runInContext('renderModelSetup(state.items)',context);
  assert.equal(node('downloadSetup').open,true);
  assert.equal(node('downloadProgress').value,.5);
  assert.match(node('downloadBytes').textContent,/1.0 MB \/ 2.0 MB/);
  context.fixture.items[0].stage='Loading model';
  vm.runInContext('renderModelSetup(state.items)',context);
  assert.equal(node('downloadSetup').open,true);
  assert.equal(node('downloadProgress').value,undefined);
  context.fixture.items[0].stage='Transcribing';
  vm.runInContext('renderModelSetup(state.items)',context);
  assert.equal(node('downloadSetup').open,false);
  context.fixture.items[0].stage='Downloading model';
  vm.runInContext('renderModelSetup(state.items)',context);
  Object.assign(context.fixture.items[0],{status:'failed',stage:'Failed',error:'Network interrupted'});
  vm.runInContext('renderModelSetup(state.items)',context);
  assert.equal(node('downloadSetup').open,true);
  assert.equal(node('downloadRetry').hidden,false);
  assert.match(node('downloadStage').textContent,/Network interrupted/);
  vm.runInContext('modelSetup=null',context);node('downloadSetup').close();
  context.fixture.items=originalItems;
  vm.runInContext("state.output_override='C:/test-output';render()",context);
  assert.equal(node('testBanner').hidden,false);
  assert.match(node('testBanner').textContent,/will NOT appear beside/);
  await vm.runInContext("openLog('a')",context);
  assert.equal(node('logText').textContent,'initial log');
  assert.equal(node('logText').scrollTop,1000);
  node('logText').scrollTop=50;log='updated log';
  await vm.runInContext('refreshLog(logGeneration)',context);
  assert.equal(node('logText').textContent,'updated log');
  assert.equal(node('logText').scrollTop,50);
  node('logDialog').close();const before=timers;
  await vm.runInContext('refreshLog(logGeneration)',context);
  assert.equal(timers,before);
  return 'PASS: progress/ETA rendering, mixed output paths, test-mode banner, live log updates, scroll preservation, close stops polling.';
}

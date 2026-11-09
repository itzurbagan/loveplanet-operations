'use strict';
let identityPromise;
async function identity(){
 if(!identityPromise)identityPromise=(async()=>{let s=await chrome.storage.local.get('installationId');if(!s.installationId){s.installationId=crypto.randomUUID();await chrome.storage.local.set({installationId:s.installationId})}return s.installationId})();
 return identityPromise;
}
async function localApi(body,tabId){
 const cfg=await(await fetch(chrome.runtime.getURL('bridge-config.json'))).json();
 const r=await fetch('http://127.0.0.1:8787/api/bridge',{method:'POST',signal:AbortSignal.timeout(10000),headers:{'Content-Type':'application/json','X-Bridge-Key':cfg.key},body:JSON.stringify({...body,client:(await identity())+':'+tabId})});
 const d=await r.json();if(!r.ok)return {status:'bridge_error',error:d.error||'HTTP '+r.status};return d;
}
chrome.runtime.onMessage.addListener((m,sender,reply)=>{
 if(sender.id!==chrome.runtime.id)return false;
 const popup=!sender.tab&&sender.url===chrome.runtime.getURL('popup.html');
 const content=sender.tab&&sender.url&&new URL(sender.url).origin==='https://loveplanet.ru';
 if(m.type==='health'&&popup){localApi({action:'status'},'popup').then(reply,()=>reply({status:'bridge_unavailable',error:'Локальный сервер 127.0.0.1:8787 недоступен'}));return true}
 if(m.type!=='bridge'||!content)return false;
 (async()=>{const s=await chrome.storage.local.get('enabled');if(!s.enabled)return {status:'disabled'};return localApi(m.body,sender.tab.id)})().then(reply,()=>reply({status:'bridge_unavailable',error:'Нет связи с локальным сервером'}));return true;
});

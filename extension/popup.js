'use strict';
const $=id=>document.getElementById(id);
async function draw(){
 const s=await chrome.storage.local.get('enabled');
 $('state').textContent=s.enabled?'Автоответы включены в этом профиле':'Автоответы выключены в этом профиле';
 let health;try{health=await chrome.runtime.sendMessage({type:'health'})}catch{health={status:'bridge_unavailable'}}
 const reachable=health&&!['bridge_unavailable','bridge_error'].includes(health.status);
 $('health').textContent=reachable?'Локальный сервер подключён · '+(health.model||'Ollama'):(health?.error||'Сервер не найден. Открой панель и проверь службу.');
 $('toggle').disabled=!reachable&&!s.enabled;$('toggle').textContent=s.enabled?'Остановить автобота':'Запустить автобота';
 $('accounts').replaceChildren(...Object.entries({adilya:'Адиля',lyubov:'Любовь',mexico:'Мексика'}).map(([id,name])=>{let row=document.createElement('div');let l=document.createElement('span');l.textContent=name;let r=document.createElement('span');r.textContent=health?.accounts?.[id]?.status==='connected'?'Подключена':'Ожидает браузер';row.append(l,r);return row}));
}
$('toggle').onclick=async()=>{const s=await chrome.storage.local.get('enabled');await chrome.storage.local.set({enabled:!s.enabled});draw()};draw();setInterval(draw,5000);

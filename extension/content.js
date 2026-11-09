'use strict';
(()=>{
 const accounts={banana0202:'adilya',lanabananad944:'lyubov',nicebanana:'mexico'};
 const nap=ms=>new Promise(r=>setTimeout(r,ms));
 const bridge=body=>chrome.runtime.sendMessage({type:'bridge',body});
 const visible=e=>e&&e.getClientRects().length>0;
 const findText=(selector,regex)=>[...document.querySelectorAll(selector)].find(e=>visible(e)&&regex.test(e.textContent.trim()));
 let running=false,active=false,visited=new Map(),lastError='';
 let lastPage=0,lastRefresh=Date.now(),pageCount=0,pageIdle=0;
 let badge=document.createElement('div');badge.id='lp-agent-indicator';badge.style.cssText='position:fixed;bottom:12px;left:12px;z-index:2147483647;padding:10px 14px;border-radius:8px;background:#173c29;color:white;font:12px system-ui;max-width:320px;box-shadow:0 2px 16px #0003';document.body.append(badge);
 const status=t=>{badge.textContent='Автобот · '+t;lastError=t};
 function account(){
  if(location.pathname!=='/a-myprofile')return null;
  for(const link of document.querySelectorAll('a[href]')){
   const url=new URL(link.getAttribute('href'),location.href);
   if(url.origin!==location.origin)continue;
   for(let [login,a] of Object.entries(accounts))if(url.pathname==='/page/'+login)return a;
  }
  return null;
 }
 function read(a){
  let selected=document.querySelector('li[id^="cnt_"].selected'),area=document.querySelector('#history_area'),info=document.querySelector('#contactinfo_area');
  if(!selected||!visible(area)||!info)return null;
  let contact=selected.id.slice(4),link=info.querySelector('a[href^="/page/'+contact+'/"]');if(!link)return null;
  let name=selected.querySelector('.chat_contact_name')?.textContent.trim()||contact;
  let messages=[...area.children].filter(e=>e.matches('li')&&/^\d+$/.test(e.id)&&e.querySelector('.chat_history_msg')).map(e=>({id:e.id,role:e.classList.contains('outbox')?'assistant':'user',text:e.querySelector('.chat_history_msg').innerText.trim(),date:e.querySelector('.date-row')?.innerText||''})).filter(m=>m.text&&!/Отправляется|Ошибка отправки/.test(m.date));
  return {account:a,contact,name,messages};
 }
 async function snapshot(a){let d=read(a);if(!d)return null;let r=await bridge({action:'snapshot',dialog:d});visited.set(d.contact,Date.now());return {d,r}}
 async function loadContacts(){
  const all=findText('#folders_area li',/^Все$/);
  if(all&&!all.classList.contains('selected1')){all.click();await nap(500);pageIdle=0;lastPage=0}
  const area=document.querySelector('#contacts_area');if(!area)return;
  const count=area.querySelectorAll('li[id^="cnt_"]').length;
  if(Date.now()-lastPage>(pageIdle>=2?30000:3000)){
   pageIdle=count>pageCount?0:pageIdle+1;pageCount=count;lastPage=Date.now();
   area.scrollTop=Math.max(0,area.scrollHeight-area.clientHeight);
   area.dispatchEvent(new Event('scroll',{bubbles:true}));
  }
  // Refresh the all-conversations folder after a complete reading pass, never every 15 seconds.
  const unseen=[...area.querySelectorAll('li[id^="cnt_"]')].some(r=>r.querySelector('.chat_contact_name')&& !visited.has(r.id.slice(4))&&/,\s*\d+/.test(r.querySelector('.chat_contact_name').textContent));
  if(all&&pageIdle>=2&&!unseen&&Date.now()-lastRefresh>180000){all.click();lastRefresh=Date.now();pageCount=0;pageIdle=0;lastPage=0}
 }
 async function openContact(contact){let row=document.getElementById('cnt_'+contact);if(!row)return false;row.querySelector('.chat_contact_name')?.click();await nap(1200);return document.querySelector('li[id^="cnt_"].selected')?.id==='cnt_'+contact}
 async function sendReady(a,turn){
  let result=await snapshot(a);if(!result||result.d.contact!==turn.contact||result.d.messages.at(-1)?.id!==turn.incoming)return;
  if(result.r.status!=='ready')return;
  let input=document.querySelector('#text_area'),button=document.querySelector('#send_button');if(!visible(input)||!visible(button)||input.innerText.trim()){status('пауза: в поле есть ручной текст');return}
  // Recheck after every await. Never send into a different conversation.
  const claim=await bridge({action:'claim',id:turn.id,incoming:turn.incoming});if(claim.status!=='send')return;
  const current=read(a);if(!current||current.contact!==claim.contact||current.messages.at(-1)?.id!==claim.incoming){status('отправка остановлена: диалог изменился');return}
  const enabled=await chrome.storage.local.get('enabled');if(!enabled.enabled)return;
  // User interaction between claim and delivery invalidates the attempt; do not guess or retry.
  if(read(a)?.contact!==claim.contact||read(a)?.messages.at(-1)?.id!==claim.incoming||input.innerText.trim())return;
  input.focus();input.textContent=claim.reply;input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:claim.reply}));
  if(read(a)?.contact!==claim.contact)return;
  button.click();status('проверка доставки · '+result.d.name);
  for(let i=0;i<16;i++){await nap(500);let checked=await snapshot(a);if(!checked||checked.d.contact!==claim.contact)break;if(checked.d.messages.some(m=>m.role==='assistant'&&m.text===claim.reply&&Number(m.id)>Number(claim.incoming))){status('ответ отправлен · '+result.d.name);return}}
  status('доставка не подтверждена; повтор заблокирован');
 }
 async function step(){
  if(running)return;running=true;
  try{
   const settings=await chrome.storage.local.get('enabled');active=!!settings.enabled;if(!active){status('выключен');return}
   const a=account();if(!a){
    const ownProfile=document.querySelector('a[href="/a-myprofile"]');
    if(ownProfile){status('открывает профиль');ownProfile.click()}else status('войти в аккаунт LovePlanet');
    return;
   }
   let poll=await bridge({action:'poll',account:a,scan:{version:'0.4.0',loaded:document.querySelectorAll('li[id^="cnt_"]').length,read:visited.size}});if(poll.status!=='connected'){status(poll.status==='other_tab_active'?'этот аккаунт обслуживается в другой вкладке':'нет связи с локальным сервером');return}
   if(!visible(document.querySelector('#history_area'))){findText('a[href="/a-message"]',/^Сообщения$/)?.click();await nap(1200)}
   let current=await snapshot(a);
   if(document.querySelector('#text_area')?.innerText.trim()){status('сохраняет ручной черновик; очисти поле для автоответа');return}
   await loadContacts();
   // The server's send interval does not block discovery or reading other chats.
   let ready=poll.turns.find(t=>LPScheduler.canSend(t,poll)&&document.getElementById('cnt_'+t.contact));
   if(ready&&await openContact(ready.contact)){await sendReady(a,ready);return}
   let rows=[...document.querySelectorAll('li[id^="cnt_"]')].filter(e=>{let t=e.textContent;return /,\s*\d+/.test(e.querySelector('.chat_contact_name')?.textContent||'')&&!/Анкета удалена/.test(t)});
   const blocked=new Set(poll.turns.filter(t=>t.status==='sending').map(t=>t.contact));
   let next=LPScheduler.nextContact(rows.map(e=>({contact:e.id.slice(4),unread:!!e.querySelector('.notify')})),visited,Date.now(),blocked);
   if(next){if(await openContact(next.contact)){let result=await snapshot(a);status('читает · '+(result?.d.name||next.contact)+' · загружено '+rows.length)}}
   else status('работает · '+a+' · в очереди '+poll.turns.length);
  }catch(e){status('ошибка связи; повтор проверки через 5 секунд')}finally{running=false}
 }
 status('подключение');setInterval(step,3000);step();
})();

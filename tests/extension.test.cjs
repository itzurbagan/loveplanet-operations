const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../extension');
const scheduler=require(path.join(root,'scheduler.js'));
test('waiting for a send interval leaves other dialogs available for reading',()=>{
 assert.equal(scheduler.canSend({status:'ready',due:90},{serverTime:100,nextSendAt:150}),false);
 assert.equal(scheduler.nextContact([{contact:'new',unread:true}],new Map(),100000).contact,'new');
 assert.equal(scheduler.canSend({status:'ready',due:90},{serverTime:150,nextSendAt:150}),true);
});
test('continuous unread traffic cannot starve older unread or unseen chats',()=>{
 const rows=[{contact:'busy',unread:true},{contact:'old',unread:false},{contact:'unseen',unread:false}];
 const visited=new Map([['busy',50000],['old',1000]]);
 assert.equal(scheduler.nextContact(rows,visited,100000).contact,'unseen');
 visited.set('unseen',100000);
 assert.equal(scheduler.nextContact(rows,visited,100000).contact,'old');
});
test('sending dialog excluded, other pending dialogs remain readable',()=>{
 assert.equal(scheduler.nextContact([{contact:'sending'},{contact:'queued'}],new Map(),100000,new Set(['sending'])).contact,'queued');
});
function runtime(enabled=true){let listener,stored={enabled},calls=[];let chrome={runtime:{id:'test-extension',getURL:p=>'chrome-extension://test-extension/'+p,onMessage:{addListener:f=>listener=f}},storage:{local:{get:async key=>({[key]:stored[key]}),set:async d=>Object.assign(stored,d)}}};let fetch=async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>String(url).startsWith('chrome-extension:')?{key:'fixture-key'}:{status:'offline',model:'fixture-model'}}};vm.runInNewContext(fs.readFileSync(path.join(root,'background.js'),'utf8'),{chrome,fetch,URL,AbortSignal,crypto:require('node:crypto').webcrypto});return {calls,stored,send:(msg,sender)=>new Promise(resolve=>{let pending=listener(msg,sender,resolve);if(!pending)resolve(undefined)})}}
const popup={id:'test-extension',url:'chrome-extension://test-extension/popup.html'},content={id:'test-extension',url:'https://loveplanet.ru/a-myprofile',tab:{id:1}};
test('manifest includes every script and has only required sites',()=>{let m=JSON.parse(fs.readFileSync(path.join(root,'manifest.json')));assert.equal(m.manifest_version,3);for(let f of [m.background.service_worker,m.action.default_popup,...m.content_scripts.flatMap(c=>c.js)])assert.ok(fs.existsSync(path.join(root,f)));assert.deepEqual(m.permissions,['storage']);assert.ok(!m.host_permissions.some(x=>x.includes('<all_urls>')))});
test('popup checks server while sending is disabled',async()=>{let r=runtime(false);assert.equal((await r.send({type:'health'},popup)).model,'fixture-model');assert.equal(r.calls.at(-1).url,'http://127.0.0.1:8787/api/bridge')});
test('disabled profile cannot submit messages',async()=>{let r=runtime(false);assert.equal((await r.send({type:'bridge',body:{action:'poll',account:'adilya'}},content)).status,'disabled');assert.equal(r.calls.length,0)});
test('foreign pages cannot use local bridge',async()=>{let r=runtime();assert.equal(await r.send({type:'bridge',body:{action:'poll'}},{...content,url:'https://evil.example/'}),undefined);assert.equal(r.calls.length,0)});
test('profiles receive distinct persistent IDs',async()=>{let a=runtime(),b=runtime();await a.send({type:'bridge',body:{action:'poll'}},content);await b.send({type:'bridge',body:{action:'poll'}},content);assert.notEqual(a.stored.installationId,b.stored.installationId);let id=a.stored.installationId;await a.send({type:'bridge',body:{action:'poll'}},content);assert.equal(a.stored.installationId,id);assert.equal(JSON.parse(a.calls.at(-1).opts.body).client,id+':1')});
function detectAccount(hrefs,pathname='/a-myprofile') {
 const source=fs.readFileSync(path.join(root,'content.js'),'utf8');
 const fn=source.slice(source.indexOf(' function account(){'),source.indexOf(' function read(a){'));
 return vm.runInNewContext(source.match(/const accounts=[^;]+;/)[0]+fn+'account()',{
  URL,location:{href:'https://loveplanet.ru'+pathname,origin:'https://loveplanet.ru',pathname},
  document:{querySelectorAll:()=>hrefs.map(href=>({getAttribute:()=>href}))}
 });
}
test('real relative profile links identify all three accounts',()=>{
 assert.equal(detectAccount(['/page/banana0202']),'adilya');
 assert.equal(detectAccount(['/page/lanabananad944']),'lyubov');
 assert.equal(detectAccount(['/page/nicebanana']),'mexico');
});
test('absolute links work but foreign profiles and other pages do not identify the account',()=>{
 assert.equal(detectAccount(['https://loveplanet.ru/page/banana0202']),'adilya');
 assert.equal(detectAccount(['https://example.org/page/banana0202']),null);
 assert.equal(detectAccount(['/page/banana0202'],'/page/someone'),null);
});

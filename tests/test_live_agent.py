import unittest,tempfile,types,sys,json,time,threading
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import live_agent as live
class BridgeTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.s=types.SimpleNamespace(DATA=self.root,CONFIG={'accounts':{a:{'telegram':'https://t.me/'+a} for a in ['adilya','lyubov','mexico']},'delay_min_seconds':0,'delay_max_seconds':0},MODEL='test',generate=lambda c,h:('привет)',{},'ollama'))
  live.HEARTBEATS.clear();live.init(self.s)
 def tearDown(self):self.temp.cleanup()
 def doc(self,a='adilya',messages=None):return {'account':a,'contact':'contact1','name':'Тест','messages':messages or [{'id':'100','role':'user','text':'привет','date':'сегодня'}]}
 def test_dedup_and_recovery_after_delivery(self):
  d=self.doc();t=live.snapshot(d,'client');self.assertEqual(live.snapshot(d,'client')['id'],t['id']);live.process('adilya');r=live.snapshot(d,'client');self.assertEqual(r['status'],'ready');self.assertEqual(live.claim(r['id'],'client','100')['status'],'send');self.assertEqual(live.claim(r['id'],'client','100')['status'],'stale')
  live.init(self.s)
  with live.db() as c:self.assertEqual(c.execute('SELECT status FROM live_turns').fetchone()[0],'uncertain')
  d['messages'].append({'id':'101','role':'assistant','text':'привет)','date':'сегодня'})
  live.snapshot(d,'client');live.snapshot(d,'client');self.assertEqual(len(live.ledger()['events']),1)
 def test_new_input_invalidates_old_reply(self):
  d=self.doc();t=live.snapshot(d,'client');live.process('adilya');d['messages'].append({'id':'102','role':'user','text':'ты тут?','date':''});live.snapshot(d,'client');self.assertEqual(live.claim(t['id'],'client','100')['status'],'stale')
 def test_new_inbound_after_uncertain_delivery_can_receive_new_reply(self):
  d=self.doc();old=live.snapshot(d,'client');live.process('adilya');live.claim(old['id'],'client','100');live.init(self.s)
  self.assertEqual(live.snapshot(d,'client')['status'],'delivery_uncertain')
  d['messages'].append({'id':'102','role':'user','text':'ты тут?','date':''})
  new=live.snapshot(d,'client');self.assertEqual(new['status'],'queued');self.assertNotEqual(new['id'],old['id'])
  with live.db() as c:self.assertEqual(c.execute('SELECT status FROM live_turns WHERE id=?',(old['id'],)).fetchone()[0],'uncertain')
  self.assertEqual(live.ledger()['events'],[])
 def test_ready_reply_is_normalized_and_persisted_before_send(self):
  self.s.generate=lambda c,h:('ну - привет)',{},'test')
  t=live.snapshot(self.doc(),'client');live.process('adilya')
  self.s.normalize_reply=lambda s:s.replace(' - ',' ')
  result=live.claim(t['id'],'client','100');self.assertEqual(result['reply'],'ну привет)')
  with live.db() as c:self.assertEqual(c.execute('SELECT reply FROM live_turns WHERE id=?',(t['id'],)).fetchone()[0],result['reply'])
 def test_emoji_image_does_not_make_delivery_uncertain(self):
  self.s.generate=lambda c,h:('привет, как твой день? 😊',{},'test')
  d=self.doc();t=live.snapshot(d,'client');live.process('adilya');live.claim(t['id'],'client','100')
  d['messages'].append({'id':'101','role':'assistant','text':'привет, как твой день?','date':''})
  live.snapshot(d,'client');self.assertEqual(len(live.ledger()['events']),1)
  self.assertFalse(live.delivered_text_matches('да 😊','да'))
  self.assertFalse(live.delivered_text_matches('привет, как твой день? 😊','привет, как мой день?'))
 def test_accounts_have_separate_queues(self):
  for a in self.s.CONFIG['accounts']:live.snapshot(self.doc(a),'client-'+a)
  live.process('lyubov')
  with live.db() as c:states={r['account']:r['status'] for r in c.execute('SELECT * FROM live_turns')}
  self.assertEqual(states,{'adilya':'queued','lyubov':'ready','mexico':'queued'})
 def test_send_gap_is_per_account_and_poll_exposes_delay(self):
  for a in ['adilya','lyubov']:
   live.snapshot(self.doc(a),'client-'+a);live.process(a)
  first=live.poll('adilya','client-adilya')['turns'][0]
  self.assertEqual(live.claim(first['id'],'client-adilya','100')['status'],'send')
  poll=live.poll('adilya','client-adilya',{'version':'0.4.0','loaded':120,'read':42})
  self.assertGreater(poll['nextSendAt'],poll['serverTime'])
  d=self.doc();d['contact']='contact2';t=live.snapshot(d,'client-adilya');live.process('adilya')
  self.assertEqual(live.claim(t['id'],'client-adilya','100')['status'],'waiting_delay')
  other=live.poll('lyubov','client-lyubov')['turns'][0]
  self.assertEqual(live.claim(other['id'],'client-lyubov','100')['status'],'send')
  self.assertEqual(live.status()['accounts']['adilya']['scan']['loaded'],120)
 def test_poll_does_not_hide_ready_turns_behind_eighty_uncertain(self):
  with live.db() as c:
   for i in range(90):c.execute('INSERT INTO live_turns(id,account,contact,incoming,status,due,created) VALUES(?,?,?,?,?,?,?)',(str(i),'adilya','c'+str(i),'100','uncertain',0,0))
  live.snapshot(self.doc(),'client');live.process('adilya')
  turns=live.poll('adilya','client')['turns']
  self.assertEqual(len(turns),91);self.assertTrue(any(t['status']=='ready' for t in turns))
 def test_policy_rechecked_before_claim(self):
  t=live.snapshot(self.doc(),'client');live.process('adilya')
  def reject(reply,history):raise ValueError('long_dash_guard')
  self.s.check_reply_policy=reject
  self.assertEqual(live.claim(t['id'],'client','100')['status'],'policy_requeued')
 def test_lost_site_connection_blocks_sending_but_not_local_queue(self):
  t=live.snapshot(self.doc(),'client');live.process('adilya')
  live.poll('adilya','client',{'siteStatus':'offline','version':'0.4.1'})
  self.assertEqual(live.claim(t['id'],'client','100')['status'],'site_unavailable')
  live.poll('adilya','client',{'siteStatus':'online','version':'0.4.1'})
  self.assertEqual(live.claim(t['id'],'client','100')['status'],'send')
  self.assertEqual(live.request({'action':'delivery_error','id':t['id'],'client':'stranger'})['status'],'lease_expired')
  self.assertEqual(live.request({'action':'delivery_error','id':t['id'],'client':'client'})['status'],'delivery_uncertain')
  with live.db() as c:self.assertEqual(c.execute('SELECT status FROM live_turns').fetchone()[0],'uncertain')
 def test_minute_gap_applies_to_chat_not_other_chats(self):
  self.s.CONFIG.update(send_gap_min_seconds=2,send_gap_max_seconds=2,chat_send_gap_seconds=60)
  now=time.time();d=self.doc();first=live.snapshot(d,'client');live.process('adilya');live.claim(first['id'],'client','100')
  d['messages'].append({'id':'101','role':'assistant','text':'привет)','date':''});live.snapshot(d,'client')
  d['messages'].append({'id':'102','role':'user','text':'как дела?','date':''});same=live.snapshot(d,'client');live.process('adilya')
  other=self.doc();other['contact']='other';next_turn=live.snapshot(other,'client');live.process('adilya')
  with patch.object(live.time,'time',return_value=now+5):
   self.assertEqual(live.claim(same['id'],'client','102')['status'],'waiting_delay')
   self.assertEqual(live.claim(next_turn['id'],'client','100')['status'],'send')
   row=next(t for t in live.poll('adilya','client')['turns'] if t['id']==same['id'])
   self.assertGreater(row['due'],now+55)
 def test_two_workers_generate_different_chats_concurrently(self):
  barrier=threading.Barrier(2)
  def generate(c,h):barrier.wait(timeout=3);return ('привет)',{},'test')
  self.s.generate=generate
  for contact in ['one','two']:
   d=self.doc();d['contact']=contact;live.snapshot(d,'client')
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(live.process,['adilya','adilya']))
  self.assertEqual(results,[True,True])
  self.assertEqual([t['status'] for t in live.poll('adilya','client')['turns']],['ready','ready'])
 def test_other_tab_cannot_send(self):
  d=self.doc();t=live.snapshot(d,'first');live.process('adilya');self.assertEqual(live.snapshot(d,'second')['status'],'other_tab_active');self.assertEqual(live.claim(t['id'],'second','100')['status'],'lease_expired')
 def test_manual_outgoing_cancels_reply(self):
  d=self.doc();t=live.snapshot(d,'first');live.process('adilya');d['messages'].append({'id':'103','role':'assistant','text':'Отвечаю вручную','date':''});live.snapshot(d,'first');self.assertEqual(live.claim(t['id'],'first','100')['status'],'stale')
 def test_no_message_no_outbound(self):
  d=self.doc();d['messages']=[];self.assertEqual(live.snapshot(d,'client')['status'],'empty');self.assertFalse(live.process('adilya'))
 def test_stop_acknowledgment_can_be_sent_once(self):
  self.s.generate=lambda c,h:('больше не буду писать',{'stopped':1},'rules')
  d=self.doc();live.snapshot(d,'client');live.process('adilya')
  t=live.snapshot(d,'client');self.assertEqual(t['status'],'ready')
  self.assertEqual(live.claim(t['id'],'client','100')['status'],'send')
  d['messages'].append({'id':'101','role':'assistant','text':'больше не буду писать','date':''});live.snapshot(d,'client')
  d['messages'].append({'id':'102','role':'user','text':'новое сообщение','date':''})
  self.assertEqual(live.snapshot(d,'client')['status'],'waiting_for_contact')
 def test_transient_failure_retries_but_quota_failure_stops(self):
  def fail(c,h):raise ValueError('openrouter_unreachable')
  self.s.generate=fail;live.snapshot(self.doc(),'client');live.process('adilya')
  with live.db() as c:
   t=dict(c.execute('SELECT * FROM live_turns').fetchone());self.assertEqual(t['status'],'queued');self.assertEqual(t['attempts'],1)
   c.execute('UPDATE live_turns SET due=0')
  def quota(c,h):raise ValueError('openrouter_quota_exhausted')
  self.s.generate=quota;live.process('adilya')
  with live.db() as c:self.assertEqual(c.execute('SELECT status FROM live_turns').fetchone()[0],'error')
if __name__=='__main__':unittest.main()

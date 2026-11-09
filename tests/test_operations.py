import importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

TMP=tempfile.TemporaryDirectory()
os.environ['DATA_DIR']=TMP.name
os.environ['TRANSPORT_MODE']='sandbox'
spec=importlib.util.spec_from_file_location('app',Path(__file__).resolve().parents[1]/'server.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)

class OperationsTest(unittest.TestCase):
    def setUp(self):
        with app.connect() as db:
            db.executescript('DELETE FROM jobs; DELETE FROM messages; DELETE FROM conversations; DELETE FROM audit;')
    def incoming(self,text='Привет',key='m1',account='adilya',contact='test'):
        return app.enqueue(dict(account=account,contact=contact,text=text,messageId=key))
    def finish(self,job):
        app.process_one(job['due']+1)
        with app.connect() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone())
    def test_delay_and_dedup(self):
        j=self.incoming();self.assertGreaterEqual(j['due']-j['created'],34.9)
        self.assertEqual(self.incoming()['id'],j['id'])
        self.assertFalse(app.process_one(j['due']-1))
    def test_no_price_and_account_routing(self):
        j=self.finish(self.incoming('Сколько стоит массаж?'))
        self.assertEqual(j['status'],'sandbox_delivered');self.assertNotRegex(j['reply'],r'\d|₽')
        pass
        k=self.finish(self.incoming('Дай ссылку на тг','m2'))
        self.assertIn(app.CONFIG['accounts']['adilya']['telegram'].rsplit('/',1)[-1],k['reply']);self.assertNotIn('t.me',k['reply']);self.assertNotIn('@',k['reply'])
    def test_identity_honesty(self):
        j=self.finish(self.incoming('Ты бот?'))
        self.assertIn('ИИ-помощник',j['reply'])
    def test_normal_replies_do_not_refer_to_profile_in_third_person(self):
        for reply in ['там ответит сама Адиля)', 'это лучше спросить у девушки']:
            with self.assertRaisesRegex(ValueError,'third_person_guard'):
                app.check_reply_policy(reply,[{'role':'user','content':'давай в тг'}])
        reply,_=app.policy_reply('Ты студентка?',{'declined':0,'invited':0})
        self.assertNotIn('девушка',reply)
    def test_profile_filter_contains_all_accounts(self):
        from html.parser import HTMLParser
        class Options(HTMLParser):
            values=[]
            def handle_starttag(self,tag,attrs):
                if tag=='option':self.values.append(dict(attrs).get('value'))
        parser=Options();parser.feed((app.ROOT/'dist/index.html').read_text())
        self.assertTrue({'all','adilya','lyubov','mexico'}.issubset(parser.values))
    def test_plain_telegram_username_and_wrong_account_guard(self):
        conv={'account':'adilya','invited':False,'declined':False}
        username=app.CONFIG['accounts']['adilya']['telegram'].rsplit('/',1)[-1]
        history=[{'role':'assistant','content':'привет)'},{'role':'user','content':'привет'},
                 {'role':'assistant','content':'массажем занимаюсь)'},{'role':'user','content':'понятно'},
                 {'role':'assistant','content':'да)'},{'role':'user','content':'хочу подробнее обсудить массаж'}]
        with patch.object(app.PROVIDER,'chat',return_value='можем в тг продолжить) мой ник: '+username):
            self.assertIn(username,app.generate(conv,history)[0])
        for reply in ['давай сюда https://t.me/adi83742','найди @adi83742',
                      'найди '+app.CONFIG['accounts']['lyubov']['telegram'].rsplit('/',1)[-1]]:
            with patch.object(app.PROVIDER,'chat',return_value=reply):
                with self.assertRaises(ValueError):app.generate(conv,history)
        conv['declined']=True
        with patch.object(app.PROVIDER,'chat',return_value='мой ник: '+username):
            with self.assertRaisesRegex(ValueError,'invitation_guard'):app.generate(conv,history)
    def test_refusal_and_stop(self):
        j=self.finish(self.incoming('Не хочу в телеграм'))
        pass
        k=self.finish(self.incoming('Сколько стоит?','m2'))
        self.assertNotIn('Telegram',k['reply'])
        pass
        self.finish(self.incoming('Не пиши больше','m3'))
        with self.assertRaises(ValueError):self.incoming('Привет','m4')
    def test_error_never_accepted(self):
        j=self.incoming()
        with patch.object(app.PROVIDER,'chat',side_effect=TimeoutError): j=self.finish(j)
        self.assertEqual(j['status'],'error')
        with self.assertRaises(ValueError):app.job_action(j['id'],'send')
    def test_account_isolation(self):
        a=self.incoming(account='adilya');b=self.incoming(account='mexico')
        self.assertNotEqual(a['conversation'],b['conversation'])
    def test_price_generation_block(self):
        j=self.incoming('Расскажи о массаже')
        with patch.object(app.PROVIDER,'chat',return_value='Массаж 15000 рублей'):j=self.finish(j)
        self.assertEqual(j['status'],'error')
    def test_automatic_reply_idempotent_and_restart(self):
        j=self.finish(self.incoming('Ты бот?'));app.process_one();app.init()
        with app.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM messages WHERE role='assistant'").fetchone()[0],1)
    def test_cancel_during_inference(self):
        j=self.incoming()
        def cancelled(*args,**kwargs):
            app.job_action(j['id'],'cancel');return 'привет)'
        with patch.object(app.PROVIDER,'chat',side_effect=cancelled):j=self.finish(j)
        self.assertEqual(j['status'],'cancelled')
    def test_metrics_only_local_confirmed_loveplanet(self):
        now=app.datetime.now(app.timezone.utc).isoformat()
        event={'eventId':'one','account':'adilya','contact':'person','at':now,'reply':'adi83742','confirmed':True,'autonomous':True}
        records=[event,event,dict(event,eventId='other',site='OtherSite'),dict(event,eventId='draft',confirmed=False),dict(event,eventId='sandbox',sandbox=True)]
        (app.DATA/'live-events.json').write_text(json.dumps({'events':records}))
        result=app.metrics(0)
        self.assertEqual(result['totals'],dict(dialogues=1,invited=1,sent=1,autonomous=1,session=0))
        self.assertEqual(result['mode'],'local_loveplanet')
        self.assertIsNone(result['sourceUrl'])
        self.assertNotIn('revenue',result['totals'])

app.init()
if __name__=='__main__':unittest.main()

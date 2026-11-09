"""Model transport; credentials stay in the private runtime data directory."""
import json
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

OLLAMA_LOCK = threading.Lock()

class ProviderError(ValueError):
    pass

class ModelProvider:
    def __init__(self, config, data, model, ollama):
        self.provider = config.get('provider', 'ollama')
        self.model, self.data, self.ollama = model, data, ollama
        self.last_status = 'not_tested'
        self.last_success = None
        self.fallback_model = config.get('fallback_model')
        self.openrouter_timeout = config.get('openrouter_timeout_seconds',25)
        self.local = threading.local()

    @property
    def engine(self):return getattr(self.local,'engine',self.provider)

    def chat(self,messages):
        try:
            reply=self.primary_chat(messages)
            self.local.engine=self.provider
            return reply
        except ProviderError as error:
            if self.provider!='openrouter' or not self.fallback_model or not str(error).startswith('openrouter_'):raise
            reason=str(error)
            try:reply=self.ollama_chat(messages,self.fallback_model)
            except (URLError,TimeoutError,HTTPError,ValueError):
                self.last_status='fallback_unavailable'
                raise ProviderError('ollama_fallback_unavailable') from None
            self.local.engine='ollama:'+self.fallback_model
            self.last_status='fallback_ready:'+reason
            self.last_success=time.time()
            return reply.strip()

    def ollama_chat(self,messages,model):
        req=Request(self.ollama+'/api/chat',data=json.dumps({'model':model,'stream':False,'messages':messages,'options':{'temperature':0.35,'num_predict':180,'num_ctx':8192}}).encode(),headers={'Content-Type':'application/json'})
        with OLLAMA_LOCK,urlopen(req,timeout=90) as r:
            result=json.load(r)
        if result.get('done_reason')=='length':raise ProviderError('generation_truncated')
        return result.get('message',{}).get('content','')

    def primary_chat(self, messages):
        if self.provider == 'openrouter':
            keypath = self.data / 'openrouter.key'
            if not keypath.exists():
                self.last_status = 'key_missing'
                raise ProviderError('openrouter_key_missing')
            key = keypath.read_text().strip()
            req = Request('https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps({'model': self.model, 'messages': messages,
                    'temperature': 0.35, 'max_tokens': 200,
                    'provider': {'data_collection': 'deny'}}).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
            try:
                with urlopen(req, timeout=self.openrouter_timeout) as r:
                    result = json.load(r)
                if result.get('error'):
                    raise ProviderError('openrouter_response_error')
                choice = result['choices'][0]
                if choice.get('finish_reason') == 'length':
                    raise ProviderError('generation_truncated')
                reply = choice['message'].get('content') or ''
            except HTTPError as e:
                self.last_status = {401:'invalid_key',402:'quota_exhausted',429:'rate_limited'}.get(e.code, 'http_' + str(e.code))
                # Never put provider response bodies or request headers in logs.
                raise ProviderError('openrouter_' + self.last_status) from None
            except (URLError, TimeoutError):
                self.last_status = 'unreachable'
                raise ProviderError('openrouter_unreachable') from None
        else:
            req = Request(self.ollama + '/api/chat', data=json.dumps({
                'model':self.model,'stream':False,'messages':messages,
                'options':{'temperature':0.35,'num_predict':100,'num_ctx':8192}}).encode(),
                headers={'Content-Type':'application/json'})
            with OLLAMA_LOCK, urlopen(req, timeout=120) as r:
                reply = json.load(r).get('message', {}).get('content', '')
        self.last_status, self.last_success = 'ready', time.time()
        return reply.strip()

    def status(self):
        return {'provider':self.provider,'status':self.last_status,'lastSuccess':self.last_success,'fallbackModel':self.fallback_model}

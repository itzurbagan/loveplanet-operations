import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from model_provider import ModelProvider, ProviderError

class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'openrouter.key').write_text('test-private-key')
        self.provider = ModelProvider({'provider':'openrouter'}, self.root, 'test/model', 'http://unused')

    def tearDown(self):
        self.tmp.cleanup()

    def test_authenticated_request_keeps_credentials_out_of_payload(self):
        def send(req, timeout):
            self.assertEqual(req.full_url, 'https://openrouter.ai/api/v1/chat/completions')
            self.assertEqual(req.get_header('Authorization'), 'Bearer test-private-key')
            self.assertNotIn(b'test-private-key', req.data)
            self.assertEqual(json.loads(req.data)['provider']['data_collection'], 'deny')
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'привет)'},'finish_reason':'stop'}]}).encode())
        with patch('model_provider.urlopen', side_effect=send):
            self.assertEqual(self.provider.chat([{'role':'user','content':'Привет'}]), 'привет)')
        self.assertEqual(self.provider.status()['status'], 'ready')

    def test_auth_failure_is_redacted_and_does_not_fallback(self):
        error = HTTPError('https://openrouter.ai',401,'secret provider body',{},io.BytesIO(b'private'))
        with patch('model_provider.urlopen', side_effect=error) as send:
            with self.assertRaisesRegex(ProviderError, '^openrouter_invalid_key$'):
                self.provider.chat([])
            self.assertEqual(send.call_count, 1)

    def test_truncated_generation_is_not_sent(self):
        response={'choices':[{'message':{'content':'unfinished'},'finish_reason':'length'}]}
        with patch('model_provider.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaisesRegex(ProviderError, 'generation_truncated'):
                self.provider.chat([])

    def test_enabled_fallback_uses_local_model_without_remote_key(self):
        self.provider.fallback_model='qwen2.5:7b'
        def send(req,timeout):
            if req.full_url.startswith('https://openrouter'):
                raise HTTPError(req.full_url,503,'down',{},None)
            self.assertEqual(req.full_url,'http://unused/api/chat')
            self.assertIsNone(req.get_header('Authorization'))
            self.assertEqual(json.loads(req.data)['model'],'qwen2.5:7b')
            return io.BytesIO(json.dumps({'message':{'content':'привет)'},'done_reason':'stop'}).encode())
        with patch('model_provider.urlopen',side_effect=send):
            self.assertEqual(self.provider.chat([]),'привет)')
            self.assertEqual(self.provider.engine,'ollama:qwen2.5:7b')

if __name__ == '__main__':
    unittest.main()

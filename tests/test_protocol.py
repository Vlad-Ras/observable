import gzip
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

TOKEN = "test_token_" + "a" * 32
os.environ["UPLOAD_TOKEN"] = TOKEN
os.environ["PUBLIC_URL"] = "https://observable.roften.ru"

from fastapi.testclient import TestClient
import app


def fixture():
    trace = {"className": "example.Tick", "methodName": "tick", "count": 10, "children": []}
    return {"data": {"ticks": 1200, "traces": trace, "entities": {}, "blocks": {"minecraft:overworld": [
        {"position": {"x": 100, "y": 64, "z": -20}, "type": "create:deployer", "rate": 120000, "ticks": 600, "traces": trace}
    ]}}, "diagnostics": {"test": True}}


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DATA = Path(self.tmp.name)
        self.client = TestClient(app.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def upload(self, obj=None):
        return self.client.post('/v1/add/' + TOKEN, content=gzip.compress(json.dumps(obj or fixture()).encode()))

    def test_stock_protocol_roundtrip(self):
        # Stock HttpURLConnection does not identify the gzip body with a header.
        r = self.upload()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers['content-type'], 'text/plain; charset=utf-8')
        self.assertRegex(r.text, r'^https://observable\.roften\.ru/report/[a-f0-9]{32}$')
        rid = r.text.rsplit('/', 1)[1]
        self.assertEqual(self.client.get('/api/report/' + rid).json(), fixture())
        self.assertEqual(self.client.get('/report/' + rid).status_code, 200)
        original = self.client.get('/download/' + rid)
        self.assertEqual(json.loads(gzip.decompress(original.content)), fixture())

    def test_invalid_auth_and_payload(self):
        self.assertEqual(self.client.post('/v1/add/wrong',content=b'{}').status_code,404)
        self.assertEqual(self.client.post('/v1/add/'+TOKEN,content=b'\x1f\x8bbroken').status_code,400)
        self.assertEqual(self.client.post('/v1/add/'+TOKEN,content=b'{}').status_code,400)
        self.assertEqual(self.client.post('/v1/add/'+TOKEN,content=b'NaN').status_code,400)
        self.assertEqual(list(app.DATA.iterdir()),[])

    def test_limits(self):
        original = app.MAX_JSON
        try:
            app.MAX_JSON=1024
            r=self.client.post('/v1/add/'+TOKEN,content=gzip.compress(b' '*2048))
            self.assertEqual(r.status_code,413)
        finally:
            app.MAX_JSON=original
        r=self.client.post('/v1/add/'+TOKEN,content=b'{}',headers={'content-length':str(app.MAX_UPLOAD+1)})
        self.assertEqual(r.status_code,413)

    def test_expiry_and_missing(self):
        rid=self.upload().text.rsplit('/',1)[1]
        p=app.DATA/(rid+'.json.gz')
        old=time.time()-31*86400
        os.utime(p,(old,old))
        self.assertEqual(self.client.get('/api/report/'+rid).status_code,410)
        app.cleanup()
        self.assertFalse(p.exists())
        self.assertEqual(self.client.get('/api/report/'+'f'*32).status_code,404)

    def test_headers_and_route_isolation(self):
        for path in ['/', '/static/app.js', '/static/style.css']:
            r=self.client.get(path)
            self.assertEqual(r.status_code,200)
            self.assertIn("script-src 'self'",r.headers['content-security-policy'])
            self.assertEqual(r.headers['referrer-policy'],'no-referrer')
        self.assertEqual(self.client.get('/static/app.py').status_code,404)
        self.assertEqual(self.client.get('/api/report/no').status_code,404)


if __name__ == '__main__':
    unittest.main()

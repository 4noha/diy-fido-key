#!/usr/bin/env python3
"""Minimal local WebAuthn RP for testing the DIY FIDO key in Chrome.

Serves a page on http://localhost:8787 with register/login buttons and logs
every attestation/assertion it receives to stdout and to
build/webauthn-test/report.jsonl.
"""
import base64
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8787
OUT = Path(__file__).resolve().parent.parent / 'build' / 'webauthn-test'
OUT.mkdir(parents=True, exist_ok=True)
LOG = OUT / 'report.jsonl'
CRED = OUT / 'credential.json'

state = {'challenge': None, 'user_id': secrets.token_bytes(16)}


def b64e(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def b64d(text):
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


PAGE = """<!doctype html>
<meta charset="utf-8">
<title>DIY FIDO local test</title>
<style>
body{font-family:-apple-system,sans-serif;background:#10131c;color:#e8eaf0;margin:0;padding:32px}
button{font-size:18px;padding:12px 20px;margin:8px 8px 8px 0;border-radius:10px;border:0;background:#3c5bd6;color:#fff}
pre{background:#1b2030;padding:16px;border-radius:10px;white-space:pre-wrap;min-height:6em}
h1{font-weight:600}
</style>
<h1>DIY FIDO local test</h1>
<p>Chrome で開いて「登録」→ デバイスが PRESS 表示になったら BOOT を押す。</p>
<button onclick="register()">登録 (create)</button>
<button onclick="login()">認証 (get)</button>
<pre id="out">ready</pre>
<script>
const out = (m)=>{document.getElementById('out').textContent = m;};
const b64u = (buf)=>btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');
const unb64u = (s)=>{s=s.replace(/-/g,'+').replace(/_/g,'/');const p='='.repeat((4-s.length%4)%4);return Uint8Array.from(atob(s+p),c=>c.charCodeAt(0));};
async function challenge(){const r=await fetch('/challenge');return unb64u((await r.json()).challenge);}
async function report(payload){await fetch('/report',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});}
async function register(){
  try{
    out('waiting for device... press BOOT when PRESS appears');
    const cred = await navigator.credentials.create({publicKey:{
      challenge: await challenge(),
      rp:{id:'localhost',name:'DIY FIDO Local Test'},
      user:{id:new Uint8Array(16).map((_,i)=>i+1),name:'test@local',displayName:'Local Test'},
      pubKeyCredParams:[{type:'public-key',alg:-7},{type:'public-key',alg:-257}],
      authenticatorSelection:{authenticatorAttachment:'cross-platform',userVerification:'discouraged',requireResidentKey:false},
      timeout:120000,
      attestation:'none'
    }});
    out('registered: '+cred.id);
    await report({type:'create',id:cred.id,clientData:JSON.stringify(cred.response.clientDataJSON?new Uint8Array(cred.response.clientDataJSON):null),rawIdLength:new Uint8Array(cred.rawId).length});
  }catch(e){out('error: '+e);}
}
async function login(){
  try{
    out('waiting for device... press BOOT when PRESS appears');
    const allow = (await (await fetch('/credential')).json()).credentials;
    const a = await navigator.credentials.get({publicKey:{
      challenge: await challenge(),
      rpId:'localhost',
      allowCredentials: allow.map(c=>({type:'public-key',id:unb64u(c)})),
      userVerification:'discouraged',
      timeout:120000
    }});
    out('assertion OK: signature '+new Uint8Array(a.response.signature).length+' bytes');
    await report({type:'get',id:a.id,signatureLength:new Uint8Array(a.response.signature).length});
  }catch(e){out('error: '+e);}
}
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/':
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('content-type', 'text/html; charset=utf-8')
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/challenge':
            state['challenge'] = secrets.token_bytes(32)
            self._json({'challenge': b64e(state['challenge'])})
        elif self.path == '/credential':
            creds = []
            if CRED.exists():
                creds = json.loads(CRED.read_text())['credentials']
            self._json({'credentials': creds})
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        if self.path != '/report':
            self._json({'error': 'not found'}, 404)
            return
        length = int(self.headers.get('content-length', 0))
        payload = json.loads(self.rfile.read(length) or b'{}')
        payload['ts'] = time.time()
        if payload.get('type') == 'create' and payload.get('id'):
            creds = []
            if CRED.exists():
                creds = json.loads(CRED.read_text())['credentials']
            if payload['id'] not in creds:
                creds.append(payload['id'])
            CRED.write_text(json.dumps({'credentials': creds}, indent=2))
        with LOG.open('a') as fh:
            fh.write(json.dumps(payload) + '\n')
        print('REPORT', payload, flush=True)
        self._json({'ok': True})


if __name__ == '__main__':
    print(f'serving http://localhost:{PORT}/  (log: {LOG})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()

"""Loopback-origin ingress for the unchanged, isolated candidate runtime.

No deployment, no credentials supplied by operators, no external provider calls.
The container must run on an internal network with a loopback-only published port.
"""
import http.client
import http.server
import os
import signal
import subprocess
import sys
import threading

SOURCE_TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'
ALLOWED_HOSTS = {'127.0.0.1:18440', 'localhost:18440'}
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade'}


class Ingress(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args):
        pass  # Never export request bodies, cookies, or credentials.

    def forward(self):
        if self.headers.get('Host') not in ALLOWED_HOSTS:
            self.send_error(403, 'LOOPBACK_ORIGIN_REQUIRED'); return
        if not self.path.startswith('/') or self.path.startswith('//'):
            self.send_error(400); return
        if self.headers.get('Transfer-Encoding'):
            self.send_error(400); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400); return
        if not 0 <= length <= 1024 * 1024:
            self.send_error(413); return
        # Preserve duplicate Set-Cookie headers and the original request Origin.
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP | {'host', 'content-length'}}
        headers['Host'] = '127.0.0.1:4186'
        conn = http.client.HTTPConnection('127.0.0.1', 4186, timeout=20)
        try:
            conn.request(self.command, self.path, body, headers)
            response = conn.getresponse()
            data = response.read(16 * 1024 * 1024 + 1)
            if len(data) > 16 * 1024 * 1024:
                self.send_error(502); return
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP | {'content-length', 'server', 'date'}:
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)
        except (OSError, http.client.HTTPException):
            self.send_error(503, 'ISOLATED_RUNTIME_NOT_READY')
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = forward


def main():
    command = [sys.executable, '-B', '/opt/go/source/scripts/acceptance_runtime.py',
               '--source', '/opt/go/source', '--fingerprint', '/opt/go/SOURCE_FINGERPRINT.json',
               '--expected-tree', SOURCE_TREE, '--state', '/state/session', '--port', '4186']
    child = subprocess.Popen(command, env={k: v for k, v in os.environ.items()
                             if k in {'PATH', 'LANG', 'LD_LIBRARY_PATH', 'PYTHONHOME',
                                      'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE'}})
    server = http.server.ThreadingHTTPServer(('0.0.0.0', 4187), Ingress)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def terminate(*_):
        child.terminate()
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        code = child.wait()
    finally:
        server.shutdown(); server.server_close()
    raise SystemExit(code)


if __name__ == '__main__':
    main()

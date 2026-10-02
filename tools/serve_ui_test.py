"""Local static-only browser-test host. Not a runtime/authentication substitute."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from soma.ui.assets import UiAssets

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=4174)
    args = parser.parse_args()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            resource = UiAssets().resolve('GET', self.path)
            if resource is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', resource.content_type)
            self.send_header('Content-Length', str(len(resource.body)))
            self.end_headers()
            self.wfile.write(resource.body)
        def log_message(self, *args):
            pass
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()

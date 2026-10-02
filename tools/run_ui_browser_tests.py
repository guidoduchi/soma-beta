"""Own both local test hosts explicitly, including Windows teardown."""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'src/web'


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--node')
    args, test_args = parser.parse_known_args()
    node = args.node or shutil.which('node.exe' if os.name == 'nt' else 'node')
    if not node:
        raise RuntimeError('The declared build-time Node toolchain is unavailable')
    for port in (4173, 4174):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    hosts = []
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    try:
        hosts.append(subprocess.Popen([node, 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '4173', '--strictPort'],
            cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options))
        hosts.append(subprocess.Popen([sys.executable, str(ROOT / 'tools/serve_ui_test.py'), '--port', '4174'],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options))
        for port, path in ((4173, '/static/ui/fixtures/harness.html'), (4174, '/tickets')):
            deadline = time.monotonic() + 10
            while True:
                if any(host.poll() is not None for host in hosts):
                    raise RuntimeError('A task-local browser test host exited during startup')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=1) as response:
                        response.read(1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Task-local browser test host readiness timed out') from None
                    time.sleep(0.05)
        return subprocess.call([node, 'node_modules/@playwright/test/cli.js', 'test', *test_args], cwd=WEB,
            env={**os.environ, 'SOMA_TEST_EXTERNAL_SERVER': '1'})
    finally:
        for host in hosts:
            if host.poll() is None:
                host.terminate()
        for host in hosts:
            try:
                host.wait(timeout=5)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait(timeout=5)


if __name__ == '__main__':
    raise SystemExit(run())

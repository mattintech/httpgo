#!/usr/bin/env python3
"""Local development server.

For production use the Docker image (gunicorn). This dev server listens on
127.0.0.1 only and runs without the debugger unless you opt in:

    python run.py                 # http://127.0.0.1:8080
    HTTPGO_DEBUG=1 python run.py  # auto-reload + debugger (never expose this)
    HOST=0.0.0.0 python run.py    # listen on all interfaces
"""

import os

from src.app import create_app

app = create_app()

if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8080'))
    debug = os.environ.get('HTTPGO_DEBUG', '').lower() in ('1', 'true', 'yes')
    if debug and host not in ('127.0.0.1', 'localhost', '::1'):
        raise SystemExit('Refusing to run the debugger on a non-local interface: '
                         'it allows arbitrary code execution.')
    app.run(host=host, port=port, debug=debug)

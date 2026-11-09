"""Gunicorn settings, overridable via environment variables."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = int(os.environ.get('WORKERS', '2'))
threads = int(os.environ.get('THREADS', '4'))
accesslog = '-'
errorlog = '-'
forwarded_allow_ips = os.environ.get('FORWARDED_ALLOW_IPS', '127.0.0.1')

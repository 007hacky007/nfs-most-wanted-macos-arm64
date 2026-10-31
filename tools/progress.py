"""Human progress lines plus, for NFSMW Builder, machine-readable NFSMW-EVENT lines.

Event mode is on when NFSMW_PROGRESS=1 (set by build_app.py --progress), so pipeline
modules can report steps without new parameters. Every event is one line:
`NFSMW-EVENT ` followed by one JSON object. Everything else on stdout is log text.
"""
import json
import os

PREFIX = 'NFSMW-EVENT '


def enabled():
    return os.environ.get('NFSMW_PROGRESS') == '1'


def emit(event):
    print(PREFIX + json.dumps(event), flush=True)


def step(ident, title, *, show=True):
    """Start a build step: print its title as today and, in event mode, emit the step id."""
    if show:
        print(title, flush=True)
    if enabled():
        emit({'step': ident, 'title': title})


def download(key, received, total):
    if enabled():
        emit({'download': key, 'received': int(received), 'total': int(total)})


def error(message, **extra):
    if enabled():
        emit({'error': message, **extra})

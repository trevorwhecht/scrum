#!/usr/bin/env python3
"""Verify local inference and native tool calls without executing a model's tools."""
import json
import os
import sys
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:11434'
MODEL = os.environ.get('SCRUM_LOCAL_MODEL', 'scrum-local')

def request(path, data=None):
    payload = None if data is None else json.dumps(data).encode()
    with urlopen(Request(BASE + path, data=payload, headers={'Content-Type': 'application/json'}), timeout=180) as response:
        return json.load(response)

try:
    print('Server:', request('/api/version'))
    print('Installed:', ', '.join(m['name'] for m in request('/api/tags')['models']))
    info = request('/api/show', {'model': MODEL})
    if 'tools' not in info.get('capabilities', []):
        raise ValueError('Selected model does not advertise tool support')
    print('Parameters:', info.get('parameters', ''))
    reply = request('/api/chat', {'model': MODEL, 'stream': False,
        'messages': [{'role': 'user', 'content': 'Call connection_probe with value local-ok. Do not answer in prose.'}],
        'tools': [{'type': 'function', 'function': {'name': 'connection_probe', 'description': 'Verify local tool calling',
            'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']}}}]})
    calls = reply['message'].get('tool_calls', [])
    if not any(c['function']['name'] == 'connection_probe' and c['function']['arguments'].get('value') == 'local-ok' for c in calls):
        raise ValueError('Model failed the tool-call probe; do not start autonomous pipelines yet')
    print('PASS: local inference and tool-call probe. No tools were executed.')
    print('Allocation:', json.dumps(request('/api/ps'), indent=2))
except Exception as error:
    print(f'FAIL: {error}', file=sys.stderr)
    sys.exit(1)

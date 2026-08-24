import json
import os
import sys
import urllib.request

job_url = (os.environ.get('MSD_WORKER_URL') or '').strip()
secret = (os.environ.get('MSD_WORKER_SECRET') or '').strip()
out = os.environ.get('GITHUB_OUTPUT') or ''


def emit(key, value):
    if out:
        with open(out, 'a', encoding='utf-8') as f:
            f.write(f'{key}={value}\n')


if not job_url or not secret:
    emit('has_work', 'false')
    print('MSD worker config missing')
    sys.exit(0)

work_url = job_url.replace('/youtube-job', '/youtube-work')
req = urllib.request.Request(work_url, headers={
    'X-MSD-Worker-Secret': secret,
    'User-Agent': 'MS-Discovery-YouTube-Preflight/1.0',
})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode('utf-8'))
    has_work = bool(data.get('has_work'))
    emit('has_work', 'true' if has_work else 'false')
    emit('priority', str(data.get('priority') or 'none'))
    print('YouTube work available:', has_work, 'priority:', data.get('priority') or data.get('reason') or 'none')
except Exception as e:
    # Bei einem vorübergehenden Preflight-Fehler lieber keinen schweren Renderer starten.
    emit('has_work', 'false')
    emit('priority', 'preflight-error')
    print('Preflight warning:', repr(e))

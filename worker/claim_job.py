import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

job_url = (os.environ.get('MSD_WORKER_URL') or '').strip()
secret = (os.environ.get('MSD_WORKER_SECRET') or '').strip()
out = os.environ.get('GITHUB_OUTPUT') or ''
claim_path = Path(os.environ.get('MSD_CLAIM_FILE') or 'worker/claimed_job.json')


def emit(key, value):
    if out:
        with open(out, 'a', encoding='utf-8') as f:
            f.write(f'{key}={value}\n')


def fetch_json(url, timeout, label):
    req = urllib.request.Request(url, headers={
        'X-MSD-Worker-Secret': secret,
        'User-Agent': 'MS-Discovery-YouTube-Worker/1.3',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:1600]
        print(f'{label} HTTP {e.code}: {body}')
        raise


if not job_url or not secret:
    print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen.')
    sys.exit(2)

# 5.5.0: erst den sehr kleinen /youtube-work-Preflight fragen. Dadurch werden bei
# erreichtem Tagesziel oder Zufallsabstand keine Quellseiten gescannt und GitHub
# installiert auch keinen Renderer. Der Preflight dient zugleich als Heartbeat.
work_url = job_url.replace('/youtube-job', '/youtube-work')
try:
    status = fetch_json(work_url, 20, 'YouTube preflight')
except Exception as e:
    print('YouTube preflight failed:', repr(e))
    sys.exit(3)

if isinstance(status, dict) and not status.get('has_work'):
    emit('has_work', 'false')
    emit('urgent', 'false')
    print('Kein YouTube-Job nötig:', status.get('reason') or status.get('message') or 'kein freier Slot')
    sys.exit(0)

try:
    data = fetch_json(job_url, 65, 'YouTube job endpoint')
except Exception as e:
    print('YouTube job endpoint failed:', repr(e))
    sys.exit(4)

job = data.get('job') if isinstance(data, dict) else None
if not job:
    emit('has_work', 'false')
    emit('urgent', 'false')
    print('Kein YouTube-Job:', (data.get('message') if isinstance(data, dict) else '') or 'Queue leer')
    sys.exit(0)

claim_path.parent.mkdir(parents=True, exist_ok=True)
claim_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
emit('has_work', 'true')
emit('job_kind', 'remake' if job.get('remake') else 'normal')
emit('urgent', 'true' if job.get('urgent') else 'false')
print('YouTube-Job geholt:', 'URGENT' if job.get('urgent') else 'NORMAL', '-', job.get('title', '')[:120])

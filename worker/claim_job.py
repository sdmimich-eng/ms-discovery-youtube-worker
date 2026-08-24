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


if not job_url or not secret:
    print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen.')
    sys.exit(2)

req = urllib.request.Request(job_url, headers={
    'X-MSD-Worker-Secret': secret,
    'User-Agent': 'MS-Discovery-YouTube-Claim/1.0',
})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode('utf-8')
        data = json.loads(raw)
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='replace')[:1200]
    print(f'YouTube job endpoint HTTP {e.code}: {body}')
    sys.exit(3)
except Exception as e:
    print('YouTube job endpoint failed:', repr(e))
    sys.exit(4)

job = data.get('job') if isinstance(data, dict) else None
if not job:
    emit('has_work', 'false')
    print('Kein YouTube-Job:', (data.get('message') if isinstance(data, dict) else '') or 'Queue leer')
    sys.exit(0)

claim_path.parent.mkdir(parents=True, exist_ok=True)
claim_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
emit('has_work', 'true')
emit('job_kind', 'remake' if job.get('remake') else 'normal')
print('YouTube-Job geholt:', 'REMAKE' if job.get('remake') else 'NORMAL', '-', job.get('title', '')[:120])

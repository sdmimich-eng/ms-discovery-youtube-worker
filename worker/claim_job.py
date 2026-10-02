import json
import os
import sys
import time
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


# Normal code pushes must not consume a media slot. A deliberately marked
# recovery push may claim exactly one due job.
is_push = (os.environ.get('GITHUB_EVENT_NAME') or '').strip().lower() == 'push'
allow_push_claim = (os.environ.get('MSD_ALLOW_PUSH_CLAIM') or '').strip() == '1'
if is_push and not allow_push_claim:
    emit('has_work', 'false'); emit('urgent', 'false'); emit('is_youtube', 'false'); emit('is_social', 'false')
    print('Push-Lauf: nur Code-Update, kein Media-Job wird beansprucht.')
    sys.exit(0)


def fetch_json(url, timeout, label):
    req = urllib.request.Request(url, headers={
        'X-MSD-Worker-Secret': secret,
        'User-Agent': 'MS-Discovery-Media-Worker/1.6',
        'Accept': 'application/json',
        'Connection': 'close',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:1600]
        print(f'{label} HTTP {e.code}: {body}')
        raise


def retry_fetch(url, label, attempts=3, timeout=18):
    last = None
    for n in range(1, attempts + 1):
        try:
            data = fetch_json(url, timeout, f'{label} attempt {n}/{attempts}')
            return data, True
        except Exception as e:
            last = e
            print(f'{label} attempt {n}/{attempts} failed:', repr(e))
            if n < attempts:
                time.sleep(3 if n == 1 else 7)
    print(label, 'all attempts failed:', repr(last))
    return {}, False


if not job_url or not secret:
    print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen.')
    sys.exit(2)

base_job_url = job_url
youtube_work_url = job_url.replace('/youtube-job', '/youtube-work')
social_work_url = job_url.replace('/youtube-job', '/social-media-work')
social_job_url = job_url.replace('/youtube-job', '/social-media-job')

youtube_status, youtube_reached = retry_fetch(youtube_work_url, 'YouTube preflight', attempts=3, timeout=18)
youtube_has = bool(isinstance(youtube_status, dict) and youtube_status.get('has_work'))
youtube_urgent = bool(isinstance(youtube_status, dict) and youtube_status.get('urgent'))

kind = ''
claim_url = ''
social_urgent = False

if youtube_has:
    kind = 'youtube'
    claim_url = base_job_url
elif not youtube_reached:
    print('YouTube preflight unreachable; trying one direct YouTube recovery claim.')
    data, claim_reached = retry_fetch(base_job_url, 'YouTube recovery claim', attempts=2, timeout=28)
    job = data.get('job') if isinstance(data, dict) else None
    if job:
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        emit('has_work', 'true'); emit('job_kind', 'youtube'); emit('is_youtube', 'true'); emit('is_social', 'false'); emit('urgent', 'true' if job.get('urgent') else 'false')
        print('YouTube recovery job claimed:', str(job.get('title') or '')[:120])
        sys.exit(0)
    emit('has_work', 'false'); emit('urgent', 'false'); emit('is_youtube', 'false'); emit('is_social', 'false')
    print('YouTube endpoint remains unavailable; skip Social so YouTube keeps priority. Next scheduler run retries.')
    sys.exit(0)
else:
    social_status, social_reached = retry_fetch(social_work_url, 'Social preflight', attempts=2, timeout=15)
    social_has = bool(isinstance(social_status, dict) and social_status.get('has_work'))
    social_urgent = bool(isinstance(social_status, dict) and social_status.get('urgent'))
    if social_reached and social_has:
        kind = 'social'
        claim_url = social_job_url
    else:
        emit('has_work', 'false'); emit('urgent', 'false'); emit('is_youtube', 'false'); emit('is_social', 'false')
        print('Kein Media-Job nötig:', (youtube_status.get('reason') if isinstance(youtube_status, dict) else '') or (social_status.get('reason') if isinstance(social_status, dict) else '') or 'kein freier Slot')
        sys.exit(0)

data, claim_reached = retry_fetch(claim_url, f'{kind} job endpoint', attempts=3 if kind == 'youtube' else 2, timeout=32)
job = data.get('job') if isinstance(data, dict) else None
if not job:
    emit('has_work', 'false'); emit('urgent', 'false'); emit('is_youtube', 'false'); emit('is_social', 'false')
    print('Kein Job:', (data.get('message') if isinstance(data, dict) else '') or ('Endpoint nicht erreichbar' if not claim_reached else 'Queue leer'))
    sys.exit(0)

claim_path.parent.mkdir(parents=True, exist_ok=True)
claim_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
emit('has_work', 'true')
if kind == 'social':
    fmt = str(job.get('format') or 'story').lower()
    emit('job_kind', f'social_{fmt}'); emit('is_youtube', 'false'); emit('is_social', 'true'); emit('urgent', 'true' if social_urgent else 'false')
    print('Instagram-Job geholt:', fmt.upper(), '-', str(job.get('title') or '')[:120])
else:
    emit('job_kind', 'youtube'); emit('is_youtube', 'true'); emit('is_social', 'false'); emit('urgent', 'true' if job.get('urgent') else ('true' if youtube_urgent else 'false'))
    print('YouTube-Job geholt:', 'URGENT' if job.get('urgent') else 'NORMAL', '-', str(job.get('title') or '')[:120])

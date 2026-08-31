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


# 5.7.11: Ein Push aktualisiert nur Worker-Code. Er darf keinen echten Media-Job
# aus der WordPress-Queue ziehen und damit einen spaeteren Scheduler-Slot blockieren.
if (os.environ.get('GITHUB_EVENT_NAME') or '').strip().lower() == 'push':
    emit('has_work', 'false')
    emit('urgent', 'false')
    emit('is_youtube', 'false')
    emit('is_social', 'false')
    print('Push-Lauf: nur Code-Update, kein Media-Job wird beansprucht.')
    sys.exit(0)


def fetch_json(url, timeout, label):
    req = urllib.request.Request(url, headers={
        'X-MSD-Worker-Secret': secret,
        'User-Agent': 'MS-Discovery-Media-Worker/1.4',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:1600]
        print(f'{label} HTTP {e.code}: {body}')
        raise


def safe_fetch(url, timeout, label):
    try:
        return fetch_json(url, timeout, label)
    except Exception as e:
        print(label, 'nicht erreichbar:', repr(e))
        return {}


if not job_url or not secret:
    print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen.')
    sys.exit(2)

base_job_url = job_url
youtube_work_url = job_url.replace('/youtube-job', '/youtube-work')
social_work_url = job_url.replace('/youtube-job', '/social-media-work')
social_job_url = job_url.replace('/youtube-job', '/social-media-job')

youtube_status = safe_fetch(youtube_work_url, 20, 'YouTube preflight')
social_status = safe_fetch(social_work_url, 20, 'Social preflight')

youtube_has = bool(isinstance(youtube_status, dict) and youtube_status.get('has_work'))
youtube_urgent = bool(isinstance(youtube_status, dict) and youtube_status.get('urgent'))
social_has = bool(isinstance(social_status, dict) and social_status.get('has_work'))
social_urgent = bool(isinstance(social_status, dict) and social_status.get('urgent'))

# Dringende YouTube-Pflichtvideos bleiben unangetastet. Danach bekommen faellige
# Stories/Reels einen freien Worker-Slot; erst danach optionales YouTube.
kind = ''
claim_url = ''
if youtube_has and youtube_urgent:
    kind = 'youtube'
    claim_url = base_job_url
elif social_has:
    kind = 'social'
    claim_url = social_job_url
elif youtube_has:
    kind = 'youtube'
    claim_url = base_job_url
else:
    emit('has_work', 'false')
    emit('urgent', 'false')
    emit('is_youtube', 'false')
    emit('is_social', 'false')
    print('Kein Media-Job nötig:', (social_status.get('reason') if isinstance(social_status, dict) else '') or (youtube_status.get('reason') if isinstance(youtube_status, dict) else '') or 'kein freier Slot')
    sys.exit(0)

try:
    data = fetch_json(claim_url, 65, f'{kind} job endpoint')
except Exception as e:
    # 5.7.12: Ein kurzer WordPress-/Netzwerk-Aussetzer ist kein fehlgeschlagener
    # Media-Job. Der naechste Scheduler-Lauf versucht es erneut; GitHub bleibt gruen.
    emit('has_work', 'false')
    emit('urgent', 'false')
    emit('is_youtube', 'false')
    emit('is_social', 'false')
    print(f'{kind} job endpoint temporaer nicht erreichbar:', repr(e), '- naechster Lauf versucht erneut.')
    sys.exit(0)

job = data.get('job') if isinstance(data, dict) else None
if not job:
    emit('has_work', 'false')
    emit('urgent', 'false')
    emit('is_youtube', 'false')
    emit('is_social', 'false')
    print('Kein Job:', (data.get('message') if isinstance(data, dict) else '') or 'Queue leer')
    sys.exit(0)

claim_path.parent.mkdir(parents=True, exist_ok=True)
claim_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
emit('has_work', 'true')
if kind == 'social':
    fmt = str(job.get('format') or 'story').lower()
    emit('job_kind', f'social_{fmt}')
    emit('is_youtube', 'false')
    emit('is_social', 'true')
    emit('urgent', 'true' if social_urgent else 'false')
    print('Instagram-Job geholt:', fmt.upper(), '-', str(job.get('title') or '')[:120])
else:
    emit('job_kind', 'youtube')
    emit('is_youtube', 'true')
    emit('is_social', 'false')
    emit('urgent', 'true' if job.get('urgent') else 'false')
    print('YouTube-Job geholt:', 'URGENT' if job.get('urgent') else 'NORMAL', '-', str(job.get('title') or '')[:120])

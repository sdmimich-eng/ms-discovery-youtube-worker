import json
import os
import re

import render_and_upload_v2 as worker
import run_v5_dynamic as v5
import run_v6_dynamic as v6
import run_v9_dynamic as v9
import run_v12_dynamic as v12

_NARRATION = ''
_ORIGINAL_BUILD = None
_ORIGINAL_COMPLETE = None


def _clean(value):
    return v6.clean_text(value)


def build_narration_capture(title, text):
    global _NARRATION
    narration = _ORIGINAL_BUILD(title, text)
    _NARRATION = _clean(narration)
    return narration


def _caption_units(text, max_words=10):
    """Split exact narration into readable caption chunks without changing spelling."""
    text = _clean(text)
    if not text:
        return []
    units = []
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        sentence = _clean(sentence)
        if not sentence:
            continue
        words = sentence.split()
        if len(words) <= max_words:
            units.append(sentence)
            continue

        start = 0
        while start < len(words):
            end = min(len(words), start + max_words)
            # Prefer a punctuation boundary in the second half of the chunk.
            for j in range(end - 1, start + max(3, max_words // 2) - 1, -1):
                if re.search(r'[,;:]$', words[j]):
                    end = j + 1
                    break
            part = ' '.join(words[start:end]).strip()
            if part:
                units.append(part)
            start = end
    return units


def _srt_time(seconds):
    ms = max(0, int(round(float(seconds) * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def build_exact_srt(text, duration):
    """Create a deterministic, exact-spelling SRT track.

    Piper speaks at a very stable pace. Timing is apportioned by spoken-text weight
    (characters plus punctuation pauses), which is much better than asking YouTube
    to transcribe the synthetic voice and keeps compounds/umlauts exactly as written.
    """
    units = _caption_units(text, 10)
    if not units:
        return ''
    duration = max(1.0, float(duration))
    start_pad = 0.12
    end_pad = 0.18
    usable = max(0.8, duration - start_pad - end_pad)

    weights = []
    for u in units:
        letters = len(re.sub(r'\s+', '', u))
        pause = 0
        pause += 8 * len(re.findall(r'[,;:]', u))
        pause += 18 * len(re.findall(r'[.!?]', u))
        weights.append(max(12, letters + pause))
    total = float(sum(weights)) or 1.0

    cues = []
    cursor = start_pad
    for i, (u, w) in enumerate(zip(units, weights), 1):
        span = usable * (w / total)
        end = cursor + span
        if i == len(units):
            end = max(cursor + 0.45, duration - end_pad)
        cues.append(f'{i}\n{_srt_time(cursor)} --> {_srt_time(min(duration - 0.02, end))}\n{u}\n')
        cursor = end
    return '\n'.join(cues).strip() + '\n'


def upload_caption_track(video_id, token, srt_text):
    if not video_id or not token or not srt_text.strip():
        return ''
    payload = srt_text.encode('utf-8')
    meta = {
        'snippet': {
            'videoId': video_id,
            'language': 'de',
            'name': 'Deutsch',
            'isDraft': False,
        }
    }
    url = 'https://www.googleapis.com/upload/youtube/v3/captions?uploadType=resumable&part=snippet'
    r = worker.requests.post(
        url,
        headers={
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': 'application/x-subrip; charset=UTF-8',
            'X-Upload-Content-Length': str(len(payload)),
        },
        data=json.dumps(meta, ensure_ascii=False).encode('utf-8'),
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError('Caption init HTTP %s: %s' % (r.status_code, r.text[:500]))
    loc = r.headers.get('Location')
    if not loc:
        raise RuntimeError('Caption resumable upload URL fehlt')
    up = worker.requests.put(
        loc,
        headers={
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/x-subrip; charset=UTF-8',
            'Content-Length': str(len(payload)),
        },
        data=payload,
        timeout=90,
    )
    if up.status_code not in (200, 201):
        raise RuntimeError('Caption upload HTTP %s: %s' % (up.status_code, up.text[:700]))
    try:
        return str(up.json().get('id') or '')
    except Exception:
        return ''


def upload_youtube_v13(video, job):
    """V9 uploader + German audio language + exact manual captions."""
    token = job['youtube_access_token']
    tags = [_clean(x)[:60] for x in (job.get('tags') or []) if _clean(x)]
    compact_tags = []
    used = 0
    for tag in tags:
        if used + len(tag) + 1 > 420:
            break
        compact_tags.append(tag)
        used += len(tag) + 1

    snippet = {
        'title': _clean(job.get('title', ''))[:100],
        'description': v9._description_for_upload(job),
        'categoryId': str(job.get('youtube_category_id') or '26'),
        'defaultLanguage': 'de',
        'defaultAudioLanguage': 'de',
    }
    if compact_tags:
        snippet['tags'] = compact_tags
    meta = {
        'snippet': snippet,
        'status': {
            'privacyStatus': job.get('privacy', 'public'),
            'selfDeclaredMadeForKids': False,
            'containsSyntheticMedia': bool(job.get('contains_synthetic_media', True)),
        },
    }
    url = 'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status'
    size = os.path.getsize(video)
    r = worker.requests.post(
        url,
        headers={
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': 'video/mp4',
            'X-Upload-Content-Length': str(size),
        },
        data=json.dumps(meta, ensure_ascii=False).encode('utf-8'),
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError('YouTube init HTTP %s: %s' % (r.status_code, r.text[:600]))
    loc = r.headers.get('Location')
    if not loc:
        raise RuntimeError('YouTube resumable upload URL fehlt')
    with open(video, 'rb') as f:
        up = worker.requests.put(
            loc,
            headers={
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'video/mp4',
                'Content-Length': str(size),
            },
            data=f,
            timeout=600,
        )
    if up.status_code not in (200, 201):
        raise RuntimeError('YouTube upload HTTP %s: %s' % (up.status_code, up.text[:900]))
    video_id = up.json().get('id', '')
    if not video_id:
        return ''

    # Captions are a quality enhancement, never a reason to lose an otherwise
    # successful upload. Exact spelling comes from the narration source itself.
    try:
        duration = worker.ffprobe_duration(video)
        srt = build_exact_srt(_NARRATION, duration)
        cap_id = upload_caption_track(video_id, token, srt)
        print('Uploaded exact German caption track:', cap_id or 'ok')
    except Exception as exc:
        print('Caption upload warning:', repr(exc))
    return video_id


def complete_v13(url, job_id, ok, **extra):
    extra['renderer'] = 'v13-captions'
    return _ORIGINAL_COMPLETE(url, job_id, ok, **extra)


def install_v13():
    global _ORIGINAL_BUILD, _ORIGINAL_COMPLETE
    v12.install_v12()
    _ORIGINAL_BUILD = v5.build_narration
    _ORIGINAL_COMPLETE = worker.complete
    v5.build_narration = build_narration_capture
    v6.upload_youtube_v6 = upload_youtube_v13
    worker.complete = complete_v13


def main():
    install_v13()
    return v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

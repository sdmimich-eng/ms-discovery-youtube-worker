import json
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

import render_and_upload_v2 as worker
import run_v4_dynamic as base
import run_v5_dynamic as v5
import run_v6_dynamic as v6
import run_v7_dynamic as v7
import run_v8_dynamic as v8

W, H = base.W, base.H
TW, TH = base.TW, base.TH
_CURRENT_JOB = {}
_ORIGINAL_SANITIZE = v6.sanitize_job
_ORIGINAL_COMPLETE = worker.complete
_ORIGINAL_CTA = v6.make_cta_overlay_v6


def _clean(value):
    return v6.clean_text(value)


def sanitize_job_v9(raw):
    job = _ORIGINAL_SANITIZE(raw)
    _CURRENT_JOB.clear()
    _CURRENT_JOB.update(job)
    return job


def _similar_to_title(sentence, title):
    sw = set(re.findall(r'[a-zäöüß0-9-]{4,}', _clean(sentence).casefold()))
    tw = set(re.findall(r'[a-zäöüß0-9-]{4,}', _clean(title).casefold()))
    if not sw or not tw:
        return False
    return len(sw & tw) / max(1, len(sw)) > 0.72


def build_narration_v9(title, text):
    """Front-load the answer. The first 15-25 seconds must promise and deliver value."""
    title = _clean(title).rstrip(' .')
    domain = _clean(_CURRENT_JOB.get('domain', '')).lower()
    sentences = [s for s in base.sentences(text) if _clean(s)]
    first = ''
    rest = []
    for sentence in sentences:
        sentence = _clean(sentence)
        if not first and not _similar_to_title(sentence, title):
            first = sentence
        else:
            rest.append(sentence)
    if not first and sentences:
        first = _clean(sentences[0])
        rest = [_clean(s) for s in sentences[1:]]
    if not first:
        first = 'Die wichtigsten Punkte und die konkrete Lösung schauen wir uns jetzt direkt an.'

    question = bool(re.match(r'^(wie|warum|wieso|weshalb|was|welche|welcher|welches|wann|wo)\b', title, re.I))
    if domain == 'wassollichheutekochen.de':
        hook = f'{title}. Das Wichtigste zuerst: {first}'
    elif question:
        hook = f'{title.rstrip("?")}? Die kurze Antwort zuerst: {first}'
    else:
        hook = f'{title}. Das Wichtigste zuerst: {first}'

    picked = []
    chars = 0
    for sentence in rest:
        sentence = _clean(sentence)
        if not sentence or _similar_to_title(sentence, title):
            continue
        if chars + len(sentence) > 3150:
            break
        picked.append(sentence)
        chars += len(sentence)

    transitions = []
    for i in range(0, len(picked), 4):
        part = picked[i:i + 4]
        if i == 4:
            part.insert(0, 'Als Nächstes kommt der Punkt, der in der Praxis oft den Unterschied macht.')
        elif i == 8:
            part.insert(0, 'Zum Schluss noch die wichtigsten Details, damit du typische Fehler vermeidest.')
        transitions.append(' '.join(part))

    next_title = _clean(_CURRENT_JOB.get('next_video_title', ''))
    if next_title:
        outro = f'Wenn du danach weitermachen möchtest, findest du in der Beschreibung auch das passende nächste Video: {next_title}.'
    else:
        outro = 'Alle Schritte und weitere Details findest du über den Link ganz oben in der Videobeschreibung.'
    return _clean(hook + ' ' + ' '.join(transitions) + ' ' + outro)


def thumbnail_phrase(title, domain=''):
    text = _clean(title)
    text = re.sub(r'^(wie\s+(?:kann\s+(?:ich|man)|kannst\s+du|du)|warum|wieso|weshalb)\s+', '', text, flags=re.I)
    clauses = [x.strip(' ?!.,:;–—-') for x in re.split(r'\s+[–—-]\s+|:\s+', text) if x.strip()]
    if clauses:
        text = min(clauses, key=lambda x: (0 if 2 <= len(x.split()) <= 6 else 1, abs(len(x.split()) - 4)))

    m = re.search(r'([\wÄÖÜäöüß-]+(?:\s+[\wÄÖÜäöüß-]+){0,2})\s+(?:geht|funktioniert)\s+nicht(?:\s+([\wÄÖÜäöüß-]+))?', text, re.I)
    if m:
        phrase = (m.group(1) + ' geht nicht' + ((' ' + m.group(2)) if m.group(2) else '')).strip()
        words = phrase.split()
        return ' '.join(words[-5:])

    stop = {
        'der','die','das','den','dem','des','ein','eine','einen','einem','einer','und','oder','aber',
        'mit','ohne','für','fuer','von','vom','zum','zur','bei','auf','im','in','am','an','ist','sind',
        'kann','kannst','ich','du','man','welche','welcher','welches','was','wann','wo','sich','es'
    }
    words = re.findall(r'[\wÄÖÜäöüß0-9+.-]+', text)
    kept = [w for w in words if w.casefold() not in stop]
    if len(kept) < 2:
        kept = words
    if len(kept) > 5:
        kept = kept[:4] + [kept[-1]]
    return ' '.join(kept[:5]).strip() or 'Kurz erklärt'


def _fit_big(draw, text, max_width, max_lines, start=92, minimum=54):
    return v7.strict_fit(draw, text, max_width, max_lines, start, minimum, True)


def _thumbnail_blue_gradient(im, box, left=(25, 137, 238, 238), mid=(11, 69, 158, 232), right=(3, 14, 45, 228)):
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    grad = Image.new('RGBA', (w, 1), (0, 0, 0, 0))
    px = grad.load()
    for x in range(w):
        t = x / max(1, w - 1)
        if t < 0.55:
            u = t / 0.55
            a, b = left, mid
        else:
            u = (t - 0.55) / 0.45
            a, b = mid, right
        px[x, 0] = tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(4))
    grad = grad.resize((w, h))
    im.paste(grad, (x0, y0), grad)


def make_thumbnail_v9(bg_path, title, domain, out):
    try:
        bg = Image.open(bg_path).convert('RGB') if bg_path and Path(bg_path).exists() else Image.new('RGB', (TW, TH), (11, 24, 44))
        ratio = max(TW / bg.width, TH / bg.height)
        bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
        bg = bg.crop(((bg.width - TW) // 2, (bg.height - TH) // 2, (bg.width - TW) // 2 + TW, (bg.height - TH) // 2 + TH))
        bg = ImageEnhance.Contrast(bg).enhance(1.06)
    except Exception:
        bg = Image.new('RGB', (TW, TH), (11, 24, 44))

    d = ImageDraw.Draw(bg, 'RGBA')
    phrase = thumbnail_phrase(title, domain)
    variant = int(_CURRENT_JOB.get('thumbnail_variant', 0) or 0) % 2
    cat = v5.category_label(domain)

    if variant == 0:
        _thumbnail_blue_gradient(bg, (0, 0, 790, TH))
        d.rounded_rectangle((42, 40, 520, 112), radius=20, fill=(42, 207, 246, 246))
        cfont, clines = v7.strict_fit(d, cat, 410, 1, 30, 23, True)
        d.text((72, 57), clines[0], font=cfont, fill=(3, 16, 30, 255))
        tfont, lines = _fit_big(d, phrase, 690, 4, 94, 56)
        y = max(160, 375 - int(len(lines) * getattr(tfont, 'size', 72) * .58))
        for line in lines:
            d.text((55, y + 4), line, font=tfont, fill=(0, 0, 0, 180))
            d.text((50, y), line, font=tfont, fill='white')
            y += int(getattr(tfont, 'size', 72) * 1.08)
    else:
        _thumbnail_blue_gradient(bg, (0, 420, TW, TH), left=(28, 146, 244, 238), mid=(13, 77, 174, 233), right=(3, 14, 45, 230))
        d.rounded_rectangle((42, 42, 470, 112), radius=20, fill=(42, 207, 246, 246))
        cfont, clines = v7.strict_fit(d, cat, 360, 1, 29, 22, True)
        d.text((70, 58), clines[0], font=cfont, fill=(3, 16, 30, 255))
        tfont, lines = _fit_big(d, phrase, 1170, 2, 88, 55)
        line_h = int(getattr(tfont, 'size', 70) * 1.08)
        y = 462 + max(0, (210 - len(lines) * line_h) // 2)
        for line in lines:
            d.text((62, y + 4), line, font=tfont, fill=(0, 0, 0, 170))
            d.text((58, y), line, font=tfont, fill='white')
            y += line_h

    d.rounded_rectangle((1042, 42, 1238, 102), radius=18, fill=(3, 12, 25, 210))
    d.text((1070, 58), 'MS RATGEBER', font=v5.font(23, True), fill=(235, 243, 250, 255))
    bg.save(out, quality=96)


def make_cta_v9(article_url, domain, out):
    next_title = _clean(_CURRENT_JOB.get('next_video_title', ''))
    next_url = _clean(_CURRENT_JOB.get('next_video_url', ''))
    if not next_title or not next_url:
        return _ORIGINAL_CTA(article_url, domain, out)

    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((145, 160, 1775, 920), radius=54, fill=(4, 10, 22, 228))
    d.rounded_rectangle((145, 160, 169, 920), radius=10, fill=(42, 207, 246, 255))
    d.rounded_rectangle((235, 235, 615, 307), radius=21, fill=(42, 207, 246, 248))
    d.text((274, 252), 'ALS NÄCHSTES', font=v5.font(30, True), fill=(3, 15, 28, 255))

    hfont, lines = v7.strict_fit(d, next_title, 1350, 4, 68, 42, True)
    y = 365
    for line in lines:
        d.text((235, y), line, font=hfont, fill='white')
        y += int(getattr(hfont, 'size', 58) * 1.16)
    d.text((235, 735), 'Das passende nächste Video findest du direkt im MS-Ratgeber-Kanal.', font=v5.font(32, False), fill=(226, 238, 248, 255))
    d.text((235, 805), 'Die ausführliche Anleitung zum aktuellen Thema steht weiterhin in der Beschreibung.', font=v5.font(28, False), fill=(195, 215, 230, 255))
    d.text((235, 865), domain, font=v5.font(27, True), fill=(103, 221, 255, 255))
    im.save(out)


def _description_for_upload(job):
    article_url = v6.clickable_url(job.get('article_url', ''))
    domain = worker.domain_label(article_url) if article_url else ''
    home_url = f'https://{domain}/' if domain and '.' in domain else ''
    raw = v6.clean_multiline(job.get('description', ''))
    lines = []
    if article_url:
        lines.extend(['🔗 DIREKT ZUM VOLLSTÄNDIGEN RATGEBER:', article_url, ''])
    for line in raw.splitlines():
        stripped = line.strip()
        low = stripped.casefold()
        if not stripped:
            if lines and lines[-1] != '':
                lines.append('')
            continue
        if article_url and article_url in stripped:
            continue
        if low.startswith(('► vollständige anleitung', '🔗 direkt zum vollständigen ratgeber')):
            continue
        lines.append(stripped)
    next_title = _clean(job.get('next_video_title', ''))
    next_url = v6.clickable_url(job.get('next_video_url', '')) if job.get('next_video_url') else ''
    if next_title and next_url and next_url not in '\n'.join(lines):
        lines.extend(['', '▶ ALS NÄCHSTES AUF MS RATGEBER:', next_title, next_url])
    if home_url and home_url != article_url:
        lines.extend(['', 'Weitere hilfreiche Ratgeber:', home_url])
    return '\n'.join(lines).strip()[:5000]


def upload_youtube_v9(video, job):
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
        'description': _description_for_upload(job),
        'categoryId': str(job.get('youtube_category_id') or '26'),
        'defaultLanguage': 'de',
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
        data=json.dumps(meta, ensure_ascii=False).encode('utf-8'), timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError('YouTube init HTTP %s: %s' % (r.status_code, r.text[:600]))
    loc = r.headers.get('Location')
    if not loc:
        raise RuntimeError('YouTube resumable upload URL fehlt')
    with open(video, 'rb') as f:
        up = worker.requests.put(
            loc,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'video/mp4', 'Content-Length': str(size)},
            data=f, timeout=600,
        )
    if up.status_code not in (200, 201):
        raise RuntimeError('YouTube upload HTTP %s: %s' % (up.status_code, up.text[:900]))
    return up.json().get('id', '')


def complete_v9(url, job_id, ok, **extra):
    extra.setdefault('renderer', 'v9-growth')
    extra.setdefault('thumbnail_variant', int(_CURRENT_JOB.get('thumbnail_variant', 0) or 0))
    return _ORIGINAL_COMPLETE(url, job_id, ok, **extra)


def install_v9():
    v8.install_v8()
    v6.sanitize_job = sanitize_job_v9
    v5.build_narration = build_narration_v9
    v5.make_thumbnail = make_thumbnail_v9
    v6.make_cta_overlay_v6 = make_cta_v9
    v6.upload_youtube_v6 = upload_youtube_v9
    worker.complete = complete_v9


def main():
    install_v9()
    return v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

import render_and_upload_v2 as worker
import run_v5_dynamic as v5
import run_v6_dynamic as v6
import run_v9_dynamic as v9
import run_v12_dynamic as v12

_NARRATION = ''
_ORIGINAL_BUILD = None
_ORIGINAL_COMPLETE = None
_ORIGINAL_SYNTH = None


def _clean(value):
    return v6.clean_text(value)



_BAD_SENTENCE_START = re.compile(
    r'^(?:und|oder|aber|sowie|beziehungsweise|bzw\.?|wobei|während|waehrend|obwohl)\b',
    re.I,
)

_TTS_REPLACEMENTS = [
    (r'\bz\.\s*B\.\b', 'zum Beispiel'),
    (r'\bbzw\.\b', 'beziehungsweise'),
    (r'\bca\.\b', 'etwa'),
    (r'\bu\.\s*a\.\b', 'unter anderem'),
    (r'\bCPU\b', 'C P U'),
    (r'\bUEFI\b', 'U E F I'),
    (r'\bBIOS\b', 'Bios'),
    (r'\bWLAN\b', 'W-LAN'),
    (r'\bUSB\b', 'U S B'),
    (r'\bSSD\b', 'S S D'),
    (r'\bHDD\b', 'H D D'),
    (r'\bNAS\b', 'N A S'),
    (r'\bOBD\s*2\b', 'O B D zwei'),
    (r'\bWildbienen\b', 'Wild-Bienen'),
    (r'\bLehmstelle\b', 'Lehm-Stelle'),
    (r'\bBaumaterial\b', 'Bau-Material'),
    (r'\bBrotaufstrich\b', 'Brot-Aufstrich'),
    (r'\bOfengemüse\b', 'Ofen-Gemüse'),
    (r'\bChilischärfe\b', 'Chili-Schärfe'),
    (r'\bDruckerfreigabe\b', 'Drucker-Freigabe'),
    (r'\bWerkseinstellungen\b', 'Werks-Einstellungen'),
    (r'\bNamensfehler\b', 'Namens-Fehler'),
    (r'\bFehlercode\b', 'Fehler-Code'),
    (r'\bAllradantrieb\b', 'Allrad-Antrieb'),
]


def _sentence_fingerprint(sentence):
    words = re.findall(r'[a-zäöüß0-9]{4,}', _clean(sentence).casefold())
    return ' '.join(words[:18])


def polish_narration(text):
    """Light editorial pass: preserve facts, remove run-ons/duplicates/fragments."""
    t = _clean(text)
    if not t:
        return ''

    t = re.sub(r'\s+([,.;:!?])', r'\1', t)
    t = re.sub(r'([,.;:!?])(?=[A-Za-zÄÖÜäöüß])', r'\1 ', t)
    t = re.sub(r'(?<=\w)-\s+(?=\w)', '-', t)
    t = re.sub(r'\.{4,}', '…', t)

    raw_sentences = [
        _clean(x).strip(' -–—•')
        for x in re.split(r'(?<=[.!?…])\s+', t)
        if _clean(x)
    ]
    out = []
    seen = set()
    for sentence in raw_sentences:
        words = sentence.split()
        if len(words) < 4 and not sentence.endswith('?'):
            continue
        if _BAD_SENTENCE_START.search(sentence) and len(words) < 10:
            continue
        fp = _sentence_fingerprint(sentence)
        if fp and fp in seen:
            continue
        if fp:
            seen.add(fp)
        if sentence[-1:] not in '.!?…':
            sentence += '.'
        out.append(sentence)

    polished = _clean(' '.join(out))
    return polished or t


_NARRATION_ACTION = re.compile(
    r'\b(?:musst|muss|sollt|sollte|kannst|kann|prüf|pruef|kontroll|achte|öffn|oeffn|'
    r'setz|stell|entfern|vermeid|reinige|starte|schalt|melde|hilft|wichtig|ursache|'
    r'problem|fehler|risiko|lösung|loesung|schritt)\w*\b',
    re.I,
)
_NARRATION_WEAK = re.compile(
    r'^(?:hier|dort|dabei|dadurch|damit|deshalb|daher|dies(?:e|er|es|en|em)?|'
    r'auch|zudem|außerdem|ausserdem|dann)\b',
    re.I,
)


def _title_terms(title):
    stop = {
        'aber','alle','auch','auf','aus','bei','das','dass','dem','den','der','des','die','ein','eine','einen',
        'einer','einem','für','fuer','ich','im','in','ist','kann','man','mit','nicht','oder','sich','so','und',
        'von','vom','was','wie','wird','werden','zur','zum'
    }
    return {
        w for w in re.findall(r'[a-zäöüß0-9-]{4,}', _clean(title).casefold())
        if w not in stop
    }


def _narration_sentence_score(sentence, title_terms, index):
    s = _clean(sentence)
    words = set(re.findall(r'[a-zäöüß0-9-]{4,}', s.casefold()))
    score = len(words & title_terms) * 6
    if _NARRATION_ACTION.search(s):
        score += 7
    if re.search(r'\b\d+(?:[.,]\d+)?\b', s):
        score += 2
    if 55 <= len(s) <= 185:
        score += 5
    elif len(s) > 245:
        score -= 6
    if _NARRATION_WEAK.search(s):
        score -= 3
    if index < 5:
        score += 2
    return score


def build_quality_narration(title, text):
    """Turn article prose into a tighter spoken script instead of reading the page verbatim."""
    title = _clean(title).strip()
    body = polish_narration(text)
    raw = [
        _clean(x).strip(' -–—•')
        for x in re.split(r'(?<=[.!?…])\s+', body)
        if _clean(x)
    ]

    terms = _title_terms(title)
    candidates = []
    seen = set()
    for i, sentence in enumerate(raw):
        if len(sentence) < 38:
            continue
        if re.search(r'https?://|www\.', sentence, re.I):
            continue
        fp = _sentence_fingerprint(sentence)
        if fp and fp in seen:
            continue
        if fp:
            seen.add(fp)
        if sentence[-1:] not in '.!?…':
            sentence += '.'
        candidates.append((i, _narration_sentence_score(sentence, terms, i), sentence))

    if not candidates:
        return polish_narration(_ORIGINAL_BUILD(title, text))

    # The first spoken answer should be highly relevant, not merely the first paragraph.
    first_pool = candidates[:min(10, len(candidates))]
    first_i, _score, first = max(first_pool, key=lambda row: (row[1], -row[0]))

    question = bool(re.match(
        r'^(?:wie|warum|wieso|weshalb|was|welche|welcher|welches|wann|wo|kann|muss|soll|bin)\b',
        title, re.I,
    ))
    domain = _clean(v9._CURRENT_JOB.get('domain', '')).casefold()
    if domain == 'wassollichheutekochen.de':
        intro = f'{title.rstrip(".!?")}. Das Wichtigste zuerst: {first}'
    elif question:
        intro = f'Die kurze Antwort zuerst: {first}'
    else:
        intro = f'{title.rstrip(".!?")}. Das Wichtigste zuerst: {first}'

    # Select the most useful sentences, then restore their editorial order.
    rest = [row for row in candidates if row[0] != first_i]
    ranked = sorted(rest, key=lambda row: (-row[1], row[0]))
    selected = []
    chars = len(intro)
    # Around 2.4-2.9 minutes with the clearer V13 voice instead of rigid ~3:20 videos.
    budget = 2450
    for row in ranked:
        sentence = row[2]
        if chars + len(sentence) + 1 > budget:
            continue
        selected.append(row)
        chars += len(sentence) + 1
        if len(selected) >= 11:
            break
    selected.sort(key=lambda row: row[0])

    body_sentences = [row[2] for row in selected]
    outro = 'Die vollständige Schritt-für-Schritt-Anleitung findest du direkt über den ersten Link in der Videobeschreibung.'
    narration = polish_narration(' '.join([intro] + body_sentences + [outro]))

    # Final hard gate: a script should have enough substance but no obvious malformed punctuation.
    if len(narration) < 420 or re.search(r'\s[,.;:!?]', narration):
        narration = polish_narration(_ORIGINAL_BUILD(title, text))
    return narration


def build_narration_capture(title, text):
    global _NARRATION
    narration = build_quality_narration(title, text)
    _NARRATION = narration
    print('Narration quality:', len(narration), 'chars,', len(re.split(r'(?<=[.!?])\\s+', narration)), 'sentences')
    return narration


def speech_pronunciation_text(text):
    """Speech-only pronunciation hints. Captions keep the original spelling."""
    t = polish_narration(text)
    for pattern, replacement in _TTS_REPLACEMENTS:
        t = re.sub(pattern, replacement, t, flags=re.I)
    # A dash is visually elegant, but a short spoken pause is clearer.
    t = re.sub(r'\s+[–—]\s+', '. ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def quality_tts_chunks(text, max_chars=420):
    """Short sentence groups reduce Piper slurring words together."""
    sentences = [
        _clean(x)
        for x in re.split(r'(?<=[.!?])\s+', speech_pronunciation_text(text))
        if _clean(x)
    ]
    out = []
    cur = ''
    for sentence in sentences:
        test = (cur + ' ' + sentence).strip()
        if cur and len(test) > max_chars:
            out.append(cur)
            cur = sentence
        else:
            cur = test
    if cur:
        out.append(cur)
    return out or [speech_pronunciation_text(text)]


def synthesize_voice_quality(text, out_wav, td):
    """Slightly slower, calmer German Piper voice with tiny phrase-group pauses."""
    model = Path(__file__).resolve().parent / 'voices' / 'de_DE-thorsten-medium.onnx'
    try:
        from piper import PiperVoice, SynthesisConfig
        if not model.exists():
            raise FileNotFoundError(str(model))

        voice = PiperVoice.load(str(model))
        # A touch slower and less noisy than the old profile. This makes long
        # German compounds and technical terms noticeably easier to understand.
        syn = SynthesisConfig(
            length_scale=1.10,
            noise_scale=0.54,
            noise_w_scale=0.70,
            normalize_audio=True,
        )
        parts = []
        for i, chunk in enumerate(quality_tts_chunks(text)):
            wavp = Path(td) / f'voice_quality_{i:02d}.wav'
            with wave.open(str(wavp), 'wb') as wf:
                voice.synthesize_wav(chunk, wf, syn_config=syn)
            parts.append(wavp)

        if len(parts) == 1:
            shutil.copyfile(parts[0], out_wav)
        else:
            pause = Path(td) / 'voice_pause.wav'
            with wave.open(str(parts[0]), 'rb') as rf:
                channels = rf.getnchannels()
                width = rf.getsampwidth()
                rate = rf.getframerate()
            with wave.open(str(pause), 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(width)
                wf.setframerate(rate)
                silence_frames = int(rate * 0.16)
                wf.writeframes(b'\x00' * silence_frames * channels * width)

            listing = Path(td) / 'voice_quality_concat.txt'
            lines = []
            for i, part in enumerate(parts):
                lines.append("file '%s'\n" % str(part).replace("'", "'\\''"))
                if i < len(parts) - 1:
                    lines.append("file '%s'\n" % str(pause).replace("'", "'\\''"))
            listing.write_text(''.join(lines), encoding='utf-8')
            subprocess.run(
                ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
                 '-c:a', 'pcm_s16le', str(out_wav)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        print('TTS quality profile: Piper de_DE-thorsten-medium, slower/clearer')
        return
    except Exception as exc:
        print('Quality TTS fallback:', repr(exc))
        return _ORIGINAL_SYNTH(speech_pronunciation_text(text), out_wav, td)


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



_YOUTUBE_DOMAIN_CATEGORIES = {
    'win-tipps.de': '28',
    'drucker-tipps.de': '28',
    'router-tipps.de': '28',
    'app-fix.de': '28',
    'nashilfe.de': '28',
    'server-preis.de': '28',
    'pv-tipps.de': '28',
    'ebike-hilfe.de': '28',
    'fahrzeug-hilfe.de': '2',
    'kastenwagentipps.de': '2',
    'wassollichheutekochen.de': '26',
    'gartenpapst.de': '26',
    'zahnersatz-hilfe.de': '27',
    'entsorgungshelfer.de': '27',
    'spielanleitungen.de': '20',
}


def youtube_category_for_job(job):
    domain = _job_domain(job)
    mapped = _YOUTUBE_DOMAIN_CATEGORIES.get(domain)
    if mapped:
        return mapped
    return str(job.get('youtube_category_id') or '26')


_SEO_DOMAIN_HASHTAGS = {
    'win-tipps.de': ['Windows', 'Windows11', 'PC', 'Technik'],
    'fahrzeug-hilfe.de': ['Auto', 'KFZ', 'Fahrzeug', 'Autotipps'],
    'wassollichheutekochen.de': ['Kochen', 'Rezepte', 'Rezeptideen', 'Kochideen'],
    'gartenpapst.de': ['Garten', 'Gartentipps', 'Pflanzen', 'Gartenpflege'],
    'drucker-tipps.de': ['Drucker', 'Druckerhilfe', 'Scanner', 'Technik'],
    'router-tipps.de': ['Router', 'WLAN', 'Netzwerk', 'Internet'],
    'app-fix.de': ['Apps', 'Smartphone', 'Android', 'AppTipps'],
    'ebike-hilfe.de': ['EBike', 'Fahrrad', 'EBikeTipps', 'Technik'],
    'nashilfe.de': ['NAS', 'Speicher', 'Festplatte', 'Technik'],
    'server-preis.de': ['Server', 'Hosting', 'Webhosting', 'Technik'],
    'kastenwagentipps.de': ['Camper', 'Wohnmobil', 'Camping', 'CamperTipps'],
    'pv-tipps.de': ['Photovoltaik', 'Solar', 'PVAnlage', 'Energie'],
    'entsorgungshelfer.de': ['Entsorgen', 'Recycling', 'Abfall', 'Umwelt'],
    'zahnersatz-hilfe.de': ['Zahnersatz', 'Zaehne', 'Gesundheit', 'Ratgeber'],
    'spielanleitungen.de': ['Spielanleitung', 'Brettspiele', 'Spielregeln', 'Spiele'],
}

_SEO_TOPIC_RULES = [
    (r'\b(cpu|prozessor|uebertakt|übertakt|overclock|bios|uefi)\w*', ['CPU', 'Prozessor', 'Overclocking', 'BIOS', 'UEFI'], ['CPU zurücksetzen', 'CPU Übertaktung', 'Overclocking rückgängig machen', 'BIOS Einstellungen', 'UEFI Einstellungen']),
    (r'\b(windows\s*11|windows|registry|druckerfreigabe)\b', ['Windows', 'Windows11', 'PC', 'WindowsTipps'], ['Windows 11', 'Windows Hilfe', 'Windows Einstellungen', 'PC Tipps']),
    (r'\b(drucker|scanner|druckerfehler|fehlercode)\w*', ['Drucker', 'Druckerhilfe', 'Druckerfehler', 'Scanner'], ['Drucker Fehler', 'Drucker Hilfe', 'Fehlercode lösen']),
    (r'\b(router|wlan|wifi|netzwerk|internet)\w*', ['Router', 'WLAN', 'Netzwerk', 'Internet'], ['Router Hilfe', 'WLAN Probleme', 'Netzwerk Tipps']),
    (r'\b(auto|fahrzeug|motor|obd|allrad|reifen|bremse|subaru|forester)\w*', ['Auto', 'KFZ', 'Autotipps', 'Fahrzeug'], ['Auto Hilfe', 'KFZ Tipps', 'Fahrzeug Ratgeber']),
    (r'\b(rezept|kochen|feta|dip|pasta|kartoffel|blumenkohl|salat|ofen|kueche|küche)\w*', ['Kochen', 'Rezepte', 'Rezeptideen', 'Kochideen'], ['Rezept', 'schnelle Rezepte', 'Kochideen', 'Essen']),
    (r'\b(garten|pflanze|blume|insekt|wildblume|rasen|hecke)\w*', ['Garten', 'Gartentipps', 'Pflanzen', 'Gartenpflege'], ['Garten Tipps', 'Pflanzen Tipps', 'Gartenpflege']),
    (r'\b(e-?bike|fahrrad|akku|shimano|bosch)\w*', ['EBike', 'Fahrrad', 'EBikeTipps'], ['E-Bike Hilfe', 'E-Bike Tipps', 'Fahrrad Technik']),
    (r'\b(nas|festplatte|speicher|synology|qnap)\w*', ['NAS', 'Festplatte', 'Speicher', 'Datenspeicher'], ['NAS Hilfe', 'Festplatte prüfen', 'Speicher Tipps']),
    (r'\b(server|hosting|joomla|wordpress)\w*', ['Server', 'Hosting', 'Webhosting', 'Technik'], ['Server Tipps', 'Hosting Hilfe', 'Webserver']),
    (r'\b(app|android|iphone|smartphone)\w*', ['Apps', 'Smartphone', 'Android', 'AppTipps'], ['App Hilfe', 'Smartphone Tipps', 'Android Hilfe']),
    (r'\b(solaranlage|photovoltaik|pv-anlage|wechselrichter)\w*', ['Photovoltaik', 'Solar', 'PVAnlage', 'Energie'], ['Photovoltaik Tipps', 'PV Anlage', 'Solar Hilfe']),
    (r'\b(zahn|zahnersatz|prothese|implantat)\w*', ['Zahnersatz', 'Zaehne', 'Zahntipps'], ['Zahnersatz Ratgeber', 'Zahnprothese', 'Zahn Hilfe']),
    (r'\b(camper|wohnmobil|kastenwagen|camping)\w*', ['Camper', 'Wohnmobil', 'Camping', 'CamperTipps'], ['Camper Tipps', 'Wohnmobil Hilfe', 'Camping Ratgeber']),
    (r'\b(entsorg|recycl|abfall|muell|müll)\w*', ['Entsorgen', 'Recycling', 'Abfall', 'Umwelt'], ['richtig entsorgen', 'Recycling Tipps', 'Abfall entsorgen']),
]

_SEO_STOPWORDS = {
    'aber','alle','alles','auch','auf','aus','bei','bin','das','dass','dem','den','der','des','die','dies','diese',
    'einer','einem','einen','eine','ein','fuer','für','geht','ich','ist','kann','kannst','machen','man','mehr','mit',
    'nach','nicht','noch','oder','richtig','setzen','sich','sind','so','und','vom','von','was','wie','wird','werden',
    'welche','welcher','welches','zur','zum','zurueck','zurück'
}


def _job_domain(job):
    domain = _clean(job.get('domain', '')).casefold().replace('www.', '')
    if domain:
        return domain
    url = _clean(job.get('article_url', ''))
    m = re.match(r'^https?://([^/]+)', url, re.I)
    return (m.group(1).casefold().replace('www.', '') if m else '')


def _add_unique(target, values, limit=99):
    seen = {str(x).casefold() for x in target}
    for value in values:
        value = _clean(value)
        if not value or value.casefold() in seen:
            continue
        target.append(value)
        seen.add(value.casefold())
        if len(target) >= limit:
            break
    return target


def _significant_title_tokens(title, limit=4):
    out = []
    for raw in re.findall(r'[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9+-]{2,}', _clean(title)):
        low = raw.casefold().strip('+-')
        if low in _SEO_STOPWORDS:
            continue
        token = re.sub(r'[^A-Za-zÄÖÜäöüß0-9]', '', raw)
        if not token:
            continue
        if len(token) < 4 and not token.isupper():
            continue
        if token.casefold() not in {x.casefold() for x in out}:
            out.append(token[:28])
        if len(out) >= limit:
            break
    return out


def build_youtube_hashtags(job):
    """8-12 relevant visible hashtags; topic-specific first, never a generic hashtag dump."""
    title = _clean(job.get('title', ''))
    description = _clean(job.get('description', ''))
    haystack = f'{title} {description}'.casefold()
    domain = _job_domain(job)
    tags = []

    for pattern, hashtags, _search_tags in _SEO_TOPIC_RULES:
        if re.search(pattern, haystack, re.I):
            _add_unique(tags, hashtags, 12)

    _add_unique(tags, _significant_title_tokens(title, 3), 12)
    _add_unique(tags, _SEO_DOMAIN_HASHTAGS.get(domain, []), 12)
    _add_unique(tags, ['Ratgeber', 'Tipps', 'MSRatgeber'], 12)

    cleaned = []
    for tag in tags:
        token = re.sub(r'[^A-Za-zÄÖÜäöüß0-9_]', '', tag)
        if len(token) >= 2:
            cleaned.append('#' + token[:40])
    return cleaned[:12]


def build_youtube_search_tags(job):
    """Broaden the normal YouTube tag metadata without keyword stuffing."""
    title = _clean(job.get('title', ''))
    description = _clean(job.get('description', ''))
    haystack = f'{title} {description}'.casefold()
    domain = _job_domain(job)
    tags = []

    _add_unique(tags, job.get('tags') or [], 30)
    if title:
        _add_unique(tags, [title[:60]], 30)

    for pattern, hashtags, search_tags in _SEO_TOPIC_RULES:
        if re.search(pattern, haystack, re.I):
            _add_unique(tags, search_tags, 30)
            _add_unique(tags, hashtags, 30)

    _add_unique(tags, _SEO_DOMAIN_HASHTAGS.get(domain, []), 30)
    _add_unique(tags, _significant_title_tokens(title, 6), 30)
    _add_unique(tags, ['MS Ratgeber', 'Ratgeber deutsch', 'Tipps und Hilfe'], 30)
    return tags


def build_youtube_description(job):
    description = v9._description_for_upload(job)
    kept = []
    for line in description.splitlines():
        stripped = line.strip()
        # Replace old tiny hashtag-only lines such as "#Technik #Ratgeber".
        if stripped and all(part.startswith('#') for part in stripped.split()):
            continue
        kept.append(line)
    description = '\n'.join(kept).strip()
    hashtags = build_youtube_hashtags(job)
    if hashtags:
        description = (description + '\n\n' + ' '.join(hashtags)).strip()
    return description[:5000]


def upload_youtube_v13(video, job):
    """V9 uploader + German audio language + exact manual captions."""
    token = job['youtube_access_token']
    tags = [_clean(x)[:60] for x in build_youtube_search_tags(job) if _clean(x)]
    compact_tags = []
    used = 0
    for tag in tags:
        if used + len(tag) + 1 > 450:
            break
        compact_tags.append(tag)
        used += len(tag) + 1

    snippet = {
        'title': _clean(job.get('title', ''))[:100],
        'description': build_youtube_description(job),
        'categoryId': youtube_category_for_job(job),
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
    extra['renderer'] = 'v13-quality-captions-seo'
    return _ORIGINAL_COMPLETE(url, job_id, ok, **extra)


def install_v13():
    global _ORIGINAL_BUILD, _ORIGINAL_COMPLETE, _ORIGINAL_SYNTH
    v12.install_v12()
    _ORIGINAL_BUILD = v5.build_narration
    _ORIGINAL_COMPLETE = worker.complete
    _ORIGINAL_SYNTH = worker.synthesize_voice
    v5.build_narration = build_narration_capture
    worker.synthesize_voice = synthesize_voice_quality
    v6.upload_youtube_v6 = upload_youtube_v13
    worker.complete = complete_v13


def main():
    install_v13()
    return v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

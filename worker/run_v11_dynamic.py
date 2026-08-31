import re

import render_and_upload_v2 as worker
import run_v7_dynamic as v7
import run_v9_dynamic as v9
import run_v10_dynamic as v10

_ARTICLE_TEXT = ''
_ORIGINAL_FETCH = None

_DANGLING = re.compile(
    r'\b(?:von|vom|mit|bei|auf|in|im|am|an|zu|zum|zur|für|fuer|und|oder|aber|dass|weil|wenn|so|als|einer|einem|einen|der|die|das|den|dem|des)$',
    re.I,
)
_GENERIC = re.compile(
    r'^(?:tipps?|ratgeber|anleitung|kurz erklärt|kurz erklaert|wissen|alltag|praktische tipps?)$',
    re.I,
)
_ACTION = re.compile(
    r'\b(?:entfernen|prüfen|pruefen|melden|einstellen|einrichten|konfigurieren|anpassen|reparieren|lösen|loesen|beheben|vermeiden|einschalten|ausschalten|reinigen|spielanleitung|sonderregeln|fehler|problem|schimmel)\b',
    re.I,
)


def _clean(value):
    return v7.display_clean(value)


def _segment_score(segment, index, total):
    text = _clean(segment).strip(' ?!.,:;–—-')
    words = text.split()
    n = len(words)
    if not text:
        return -999
    score = 0
    if 2 <= n <= 7:
        score += 18
    elif n <= 10:
        score += 10
    elif n > 13:
        score -= 12
    if _ACTION.search(text):
        score += 10
    if _GENERIC.match(text):
        score -= 25
    if re.search(r'\bTipps?\b', text, re.I):
        score -= 6
    if _DANGLING.search(text):
        score -= 30
    if index == 0:
        score += 2
    if total > 1 and index > 0 and re.search(r'\b(?:prüfen|pruefen|entfernen|sonderregeln|fehler|problem)\b', text, re.I):
        score += 3
    return score


def _article_fallback(title):
    """Pick one complete, title-related article sentence only when the source title is unusable."""
    units = v10.standalone_units(_ARTICLE_TEXT)
    if not units:
        return ''
    title_words = set(re.findall(r'[a-zäöüß0-9-]{4,}', _clean(title).casefold()))
    ranked = []
    for idx, sentence in enumerate(units[:40]):
        words = set(re.findall(r'[a-zäöüß0-9-]{4,}', sentence.casefold()))
        overlap = len(title_words & words)
        n = len(sentence)
        score = overlap * 12
        if 45 <= n <= 125:
            score += 12
        elif n > 180:
            score -= 15
        if v10._WEAK_START.search(sentence):
            score -= 20
        ranked.append((score, -idx, sentence))
    ranked.sort(reverse=True)
    if ranked and ranked[0][0] >= 12:
        return ranked[0][2]
    return ''


def semantic_thumbnail_phrase(title, domain=''):
    """Grammar-first thumbnail hook. Never build a bag of keywords by deleting stopwords."""
    source = _clean(v9._CURRENT_JOB.get('source_title') or title).strip(' –—-|')
    source = re.sub(r'\s*([,;:.!?])\s*', r'\1 ', source).strip()
    source = re.sub(r'\s+', ' ', source)
    if not source:
        return 'Kurz erklärt'

    m = re.match(r'^Bin ich verpflichtet,\s*(.+?)\s+zu\s+([\wÄÖÜäöüß-]+)\??$', source, re.I)
    if m:
        phrase = f'Muss ich {_clean(m.group(1))} {m.group(2)}?'
        if len(phrase) <= 92:
            return phrase

    m = re.match(r'^Wie kann ich\s+(.+?)\s+so\s+(einstellen|einrichten|konfigurieren|anpassen)\b', source, re.I)
    if m:
        subject = re.sub(
            r'^(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+',
            '', _clean(m.group(1)), flags=re.I,
        )
        if subject:
            subject = subject[:1].upper() + subject[1:]
            return f'{subject} richtig {m.group(2).lower()}'

    parts = [
        p.strip(' ?!.,:;–—-')
        for p in re.split(r'\s+[–—-]\s+|:\s+', source)
        if p.strip()
    ]
    if len(parts) > 1:
        ranked = sorted(
            enumerate(parts),
            key=lambda item: (-_segment_score(item[1], item[0], len(parts)), item[0]),
        )
        best_i, best = ranked[0]
        if _segment_score(best, best_i, len(parts)) > 0:
            return best

    plain = source.rstrip('?!')
    if len(plain.split()) <= 11 and not _DANGLING.search(plain):
        return source

    first = re.split(r'[,;]\s+', source, 1)[0].strip()
    if 4 <= len(first.split()) <= 10 and not _DANGLING.search(first):
        if source.endswith('?') and not first.endswith('?'):
            first += '?'
        return first

    if _DANGLING.search(plain) or len(source) > 115:
        article = _article_fallback(source)
        if article:
            return article

    return source


def fetch_article_capture(url, fallback):
    global _ARTICLE_TEXT
    text, images = _ORIGINAL_FETCH(url, fallback)
    _ARTICLE_TEXT = _clean(text)
    return text, images


def install_v11():
    global _ORIGINAL_FETCH
    v10.install_v10()
    _ORIGINAL_FETCH = worker.fetch_article
    worker.fetch_article = fetch_article_capture
    v9.thumbnail_phrase = semantic_thumbnail_phrase


def main():
    install_v11()
    return v10.v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

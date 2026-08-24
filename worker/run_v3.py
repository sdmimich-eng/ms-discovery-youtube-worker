import re
import sys

import render_and_upload_v2 as worker
import run_v2_filtered as filtered

# Den bereits eingebauten Artikel-/KI-Hinweis-Filter weiterhin verwenden.
worker.fetch_article = filtered.fetch_article_filtered


def concise_sentences(text):
    return [worker.clean_text(x) for x in re.split(r'(?<=[.!?])\s+', worker.clean_text(text)) if len(worker.clean_text(x)) > 25]


def sentence_chunks_v3(text, n=8):
    # Maximal acht Inhaltsfolien: weniger Stillstand, schnellerer Rhythmus.
    s = concise_sentences(text)
    if not s:
        return [worker.clean_text(text)]
    n = min(8, max(4, n))
    import math
    target = max(1, math.ceil(len(s) / n))
    return [' '.join(s[i:i + target]) for i in range(0, len(s), target)][:8]


def slide_points_v3(text, max_points=2):
    # Auf dem Fernseher/Handy müssen die Folien auf einen Blick lesbar bleiben.
    pts = []
    for s in concise_sentences(text):
        s = re.sub(r'^[-–•]\s*', '', s)
        if len(s) > 112:
            cut = s[:109].rsplit(' ', 1)[0]
            s = cut + '…'
        if s and s not in pts:
            pts.append(s)
        if len(pts) >= 2:
            break
    if not pts and worker.clean_text(text):
        pts = [worker.clean_text(text)[:109] + ('…' if len(worker.clean_text(text)) > 109 else '')]
    return pts


def thumbnail_hook_v3(title):
    t = worker.clean_text(title)
    parts = re.split(r'\s+[–—-]\s+', t)
    t = parts[0] if parts else t
    words = t.split()
    if len(words) > 6:
        t = ' '.join(words[:6])
    return t


def build_narration_v3(title, text):
    # Nicht den ganzen Beitrag vorlesen: YouTube soll eine kompakte Lösung liefern
    # und für Details gezielt zum Originalartikel führen.
    s = concise_sentences(text)
    useful = ' '.join(s)
    if len(useful) > 4300:
        useful = useful[:4300].rsplit(' ', 1)[0]
    intro = f'{title}. Hier sind die wichtigsten Ursachen und die sinnvollsten Schritte, die du jetzt prüfen solltest. '
    outro = ' Wenn du alle Schritte, ergänzende Hinweise und Aktualisierungen brauchst, findest du die vollständige Anleitung über den Link ganz oben in der Videobeschreibung.'
    return worker.clean_text(intro + useful + outro)


worker.sentence_chunks = sentence_chunks_v3
worker.slide_points = slide_points_v3
worker.thumbnail_hook = thumbnail_hook_v3
worker.build_narration = build_narration_v3

if __name__ == '__main__':
    sys.exit(worker.main())

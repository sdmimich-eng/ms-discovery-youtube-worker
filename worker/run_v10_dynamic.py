import re

from PIL import Image, ImageDraw

import run_v4_dynamic as base
import run_v5_dynamic as v5
import run_v6_dynamic as v6
import run_v7_dynamic as v7
import run_v8_dynamic as v8
import run_v9_dynamic as v9

W, H = base.W, base.H

_WEAK_START = re.compile(
    r'^(?:hier|dort|dabei|dadurch|damit|deshalb|daher|diese(?:r|s|n|m)?|dies|so|auch|zudem|außerdem|dann)\b',
    re.I,
)


_FRAGMENT_START = re.compile(
    r'^(?:und|oder|aber|sowie|beziehungsweise|bzw\.?|wobei|während|waehrend|obwohl|welche|welcher|welches)\b',
    re.I,
)
_SPEECHLIKE_VERB = re.compile(
    r'\b(?:ist|sind|war|wird|werden|hat|haben|kann|können|koennen|muss|müssen|muessen|soll|sollte|'
    r'prüf|pruef|öffn|oeffn|stell|setz|entfern|vermeid|hilft|brauch|entsteh|führ|fuehr|'
    r'funktionier|meld|achte|gibt|lässt|laesst|start|schalt|reinig|verwend|nutz)\w*\b',
    re.I,
)


def _clean(value):
    return v7.display_clean(value)


def standalone_units(text):
    """Return complete, self-contained sentences for visible YouTube cards."""
    text = _clean(text)
    if not text:
        return []

    units = []
    for raw in re.split(r'(?<=[.!?])\s+', text):
        sentence = _clean(raw).strip(' -–—•')
        if len(sentence) < 42:
            continue
        # Obvious dependent-clause fragments should never be used as standalone cards.
        if _FRAGMENT_START.search(sentence):
            continue
        # Longer card text should contain a real predicate/action instead of noun soup.
        if len(sentence.split()) >= 8 and not _SPEECHLIKE_VERB.search(sentence):
            continue
        # Never split at commas/semicolons and never cut by character count.
        # Visible cards must contain complete statements rather than fragments.
        if sentence[-1:] not in '.!?':
            sentence += '.'
        units.append(sentence)

    if not units and len(text) >= 35:
        sentence = text
        if sentence[-1:] not in '.!?':
            sentence += '.'
        units = [sentence]
    return units


def _statement_score(sentence):
    s = _clean(sentence)
    if not s:
        return -999
    score = 0
    n = len(s)
    if 60 <= n <= 190:
        score += 20
    elif 42 <= n <= 235:
        score += 10
    elif n > 280:
        score -= 25
    if _WEAK_START.search(s):
        score -= 45
    if re.search(r'\b(?:sollt|kannst|muss|prüf|kontroll|hilft|vermeid|wichtig|risiko|ursache|grund|fehler|problem)\w*\b', s, re.I):
        score += 8
    return score


def best_statement(text):
    units = standalone_units(text)
    if not units:
        return ''
    ranked = sorted(enumerate(units), key=lambda item: (-_statement_score(item[1]), item[0]))
    # Prefer a reasonably compact complete sentence if one exists.
    for _, sentence in ranked:
        if len(sentence) <= 235:
            return sentence
    return ranked[0][1]


def safe_bullets(text, limit=2, chars=105):
    """Compatibility replacement for base.bullets without mid-sentence truncation."""
    units = standalone_units(text)
    if not units:
        return []

    strong = [u for u in units if not _WEAK_START.search(u)]
    pool = strong if strong else units
    pool = sorted(enumerate(pool), key=lambda item: (-_statement_score(item[1]), item[0]))
    picked = [s for _, s in pool[:max(1, int(limit))]]
    return picked


def core_chunks_v10(text, target=5):
    """Use four or five complete article statements instead of chopped micro-clauses."""
    units = standalone_units(text)
    if not units:
        return [_clean(text)] if _clean(text) else ['']

    strong = [u for u in units if not _WEAK_START.search(u) and len(u) <= 250]
    pool = strong if len(strong) >= 4 else units
    wanted = 5 if len(pool) >= 8 else min(4, len(pool))
    wanted = max(1, wanted)

    picks = []
    n = len(pool)
    for i in range(wanted):
        idx = round(i * (n - 1) / max(1, wanted - 1))
        sentence = pool[idx]
        if sentence not in picks:
            picks.append(sentence)

    if len(picks) < wanted:
        for sentence in pool:
            if sentence not in picks:
                picks.append(sentence)
            if len(picks) >= wanted:
                break
    return picks[:5]


def semantic_heading(statement, idx=1, total=1):
    s = _clean(statement).casefold()
    if idx <= 1:
        return 'Das Wichtigste zuerst'
    if re.search(r'\b(?:ursache|grund|risiko|entsteht|führt|fuehrt|weil|wenn|dadurch)\b', s):
        return 'Wichtiger Zusammenhang'
    if re.search(r'\b(?:prüf|pruef|kontroll|achte|überprüf|ueberpruef|vergewisser)\w*\b', s):
        return 'Das solltest du prüfen'
    if re.search(r'\b(?:sollt|kannst|musst|melde|öffne|oeffne|wähle|waehle|ändere|aendere|starte|entferne|setze)\w*\b', s):
        return 'So gehst du vor'
    if re.search(r'\b(?:fehler|problem|nicht|vermeid|achtung|gefähr|gefaehr)\w*\b', s):
        return 'Darauf solltest du achten'
    if idx >= max(2, total - 1):
        return 'Kurz zusammengefasst'
    return 'Praktischer Hinweis'


def make_content_overlay_v10(title, heading, pts, domain, idx, total, out, compact=False):
    """V8 card layout with one full standalone statement and matching heading."""
    if compact:
        # Transition scenes remain image-led. This avoids competing text while narration
        # and YouTube captions are already visible.
        return v8.minimal_visual_overlay('', domain, idx, total, out, idx)

    candidates = []
    for p in pts or []:
        candidates.extend(standalone_units(p))
    statement = best_statement(' '.join(candidates)) if candidates else ''
    if not statement:
        statement = 'Die wichtigsten Schritte und Details findest du im vollständigen Ratgeber.'

    heading = semantic_heading(statement, idx, total)

    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)

    if idx % 2:
        box = (80, 160, 940, 880)
        tx = 145
    else:
        box = (980, 160, 1840, 880)
        tx = 1045

    d.rounded_rectangle(box, radius=38, fill=(4, 10, 22, 200))
    d.rounded_rectangle((box[0], box[1], box[0] + 20, box[3]), radius=10, fill=(42, 207, 246, 250))
    d.rounded_rectangle((tx, 215, tx + 360, 275), radius=18, fill=(42, 207, 246, 245))
    cfont, clines = v7.strict_fit(d, cat, 305, 1, 27, 22, True)
    d.text((tx + 26, 230), clines[0], font=cfont, fill=(4, 15, 28, 255))
    d.text((box[2] - 70, 232), f'{idx}/{total}', font=v5.font(26, True), fill=(115, 224, 255, 255), anchor='ra')

    hfont, hlines = v7.strict_fit(d, heading, 690, 2, 52, 39, True)
    y = 345
    for line in hlines:
        d.text((tx, y), line, font=hfont, fill='white')
        y += int(getattr(hfont, 'size', 48) * 1.18)

    y += 34
    start_size = 39 if len(statement) <= 150 else 36
    pfont, plines = v7.strict_fit(d, statement, 690, 6, start_size, 26, False)
    for line in plines:
        d.text((tx, y), line, font=pfont, fill=(239, 245, 250, 255))
        y += int(getattr(pfont, 'size', 34) * 1.30)

    d.text((tx, 815), domain, font=v5.font(25, True), fill=(198, 217, 232, 255))
    im.save(out)


def install_v10():
    # Keep every V9 growth/thumbnail/upload improvement and replace only the
    # visible editorial-card selection/presentation layer.
    v9.install_v9()
    base.bullets = safe_bullets
    v6.lively_chunks = core_chunks_v10
    v5.make_content_overlay = make_content_overlay_v10


def main():
    install_v10()
    return v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

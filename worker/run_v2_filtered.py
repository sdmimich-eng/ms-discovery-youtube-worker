import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import render_and_upload_v2 as worker


EDITORIAL_IMAGE_RE = re.compile(
    r'(?:^|[\W_])('
    r'author|autor|autorin|avatar|gravatar|byline|contributor|editor|editorial|'
    r'redaktion|redakteur|redakteurin|team|staff|mitarbeiter|mitarbeiterin|'
    r'profile|profil|portrait|person|user[-_ ]?(pic|photo|avatar)|bio|about[-_ ]?author|'
    r'wp[-_ ]?user[-_ ]?avatar'
    r')(?:$|[\W_])',
    re.I,
)

DECORATIVE_IMAGE_RE = re.compile(
    r'(?:^|[\W_])(favicon|site[-_ ]?logo|custom[-_ ]?logo|author[-_ ]?logo|'
    r'cookie|consent|adsense|advert|tracking[-_ ]?pixel)(?:$|[\W_])',
    re.I,
)

EDITORIAL_TEXT_RE = re.compile(
    r'\b(über\s+(den\s+autor|die\s+autorin)|ueber\s+(den\s+autor|die\s+autorin)|'
    r'geschrieben\s+von|verfasst\s+von|autor(?:in)?|redaktion|redakteur(?:in)?|'
    r'unser\s+team|das\s+team|mitarbeiter(?:in)?)\b',
    re.I,
)


def is_boilerplate(text: str) -> bool:
    t = worker.clean_text(text).casefold()
    if not t:
        return True

    if t.startswith((
        'werbung', 'anzeige', 'autor:', 'autor ', 'redaktion:',
        'veröffentlicht am ', 'veroeffentlicht am ',
        'zuletzt aktualisiert', 'letzte aktualisierung',
    )):
        return True

    exact_markers = (
        'ki-hinweis', 'ki hinweis', 'transparenzhinweis',
        'hinweis zur ki', 'hinweis zu ki',
        'ki-generiert', 'ki generiert',
        'ki-unterstützt', 'ki unterstützt',
        'ki-unterstuetzt', 'ki unterstuetzt',
        'mithilfe generativer ki', 'mit hilfe generativer ki',
        'mithilfe von generativer ki', 'mit hilfe von generativer ki',
        'mithilfe künstlicher intelligenz', 'mit hilfe künstlicher intelligenz',
        'mithilfe kuenstlicher intelligenz', 'mit hilfe kuenstlicher intelligenz',
    )
    if any(m in t for m in exact_markers):
        return True

    if re.search(r'\b(dieser|der)\s+(beitrag|text|inhalt|artikel)\b.*\b(ki|künstliche[rn]? intelligenz|kuenstliche[rn]? intelligenz)\b.*\b(erstellt|überarbeitet|ueberarbeitet|generiert|unterstützt|unterstuetzt)\b', t):
        return True
    if re.search(r'\b(ki|künstliche[rn]? intelligenz|kuenstliche[rn]? intelligenz)\b.*\b(beitrag|text|inhalt|artikel)\b.*\b(erstellt|überarbeitet|ueberarbeitet|generiert|unterstützt|unterstuetzt)\b', t):
        return True

    return False


def filter_text(text: str) -> str:
    parts = re.split(r'(?<=[.!?])\s+', worker.clean_text(text))
    kept = [p for p in parts if p and not is_boilerplate(p)]
    return worker.clean_text(' '.join(kept))


def image_metadata(im, src=''):
    bits = [src]
    for attr in ('id', 'alt', 'title', 'name', 'data-image-title', 'data-caption'):
        value = im.get(attr)
        if value:
            bits.append(str(value))
    bits.extend(im.get('class') or [])
    return ' '.join(bits)


def image_parent_metadata(im):
    bits = []
    parent = im.parent
    depth = 0
    while parent is not None and depth < 4:
        name = getattr(parent, 'name', '')
        if name in ('article', 'main', 'body'):
            break
        if hasattr(parent, 'get'):
            bits.append(str(parent.get('id') or ''))
            bits.extend(parent.get('class') or [])
        parent = getattr(parent, 'parent', None)
        depth += 1
    return ' '.join(bits)


def image_nearby_text(im):
    parent = im.parent
    depth = 0
    while parent is not None and depth < 3:
        name = getattr(parent, 'name', '')
        if name in ('article', 'main', 'body'):
            break
        if hasattr(parent, 'get_text'):
            txt = worker.clean_text(parent.get_text(' ', strip=True))
            if txt:
                return txt[:500]
        parent = getattr(parent, 'parent', None)
        depth += 1
    return ''


def image_is_editorial_or_decorative(im, src=''):
    meta = image_metadata(im, src)
    parent_meta = image_parent_metadata(im)
    nearby = image_nearby_text(im)

    if EDITORIAL_IMAGE_RE.search(meta) or EDITORIAL_IMAGE_RE.search(parent_meta):
        return True
    if DECORATIVE_IMAGE_RE.search(meta) or DECORATIVE_IMAGE_RE.search(parent_meta):
        return True
    if nearby and EDITORIAL_TEXT_RE.search(nearby):
        return True

    # Kleine, quadratische Bilder in Personen-/Autorennähe sind fast immer Avatare.
    try:
        width = int(str(im.get('width') or '0').replace('px', '').strip() or 0)
        height = int(str(im.get('height') or '0').replace('px', '').strip() or 0)
        if width and height and width <= 600 and height <= 600:
            ratio = width / max(1, height)
            if 0.78 <= ratio <= 1.28 and (EDITORIAL_TEXT_RE.search(nearby) or EDITORIAL_IMAGE_RE.search(parent_meta)):
                return True
    except Exception:
        pass

    return False


def url_is_editorial_or_decorative(image_url):
    value = worker.clean_text(image_url)
    if not value:
        return True
    return bool(EDITORIAL_IMAGE_RE.search(value) or DECORATIVE_IMAGE_RE.search(value))


def fetch_article_filtered(url, fallback):
    try:
        r = requests.get(
            url,
            timeout=25,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; MS-Ratgeber/1.3)'},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            tag.decompose()

        disclosure_re = re.compile(
            r'(ki[-_ ]?(hinweis|transparenz)|ai[-_ ]?(disclosure|notice)|'
            r'transparenz[-_ ]?(hinweis|ki)|content[-_ ]?disclosure)',
            re.I,
        )
        for tag in soup.find_all(True):
            ident = ' '.join([
                str(tag.get('id') or ''),
                ' '.join(tag.get('class') or []),
            ])
            if disclosure_re.search(ident):
                tag.decompose()

        root = soup.find('article') or soup.find('main') or soup.body
        paras = []
        if root:
            for p in root.find_all(['p', 'li']):
                tx = worker.clean_text(p.get_text(' ', strip=True))
                if len(tx) >= 45 and not is_boilerplate(tx):
                    paras.append(tx)

        text = filter_text(' '.join(paras))
        if len(text) < 500:
            text = filter_text(fallback)
        text = text[:7000]

        imgs = []
        og = soup.find('meta', attrs={'property': 'og:image'})
        if og and og.get('content'):
            og_url = urljoin(url, og['content'])
            if not url_is_editorial_or_decorative(og_url):
                imgs.append(og_url)

        if root:
            for im in root.find_all('img'):
                src = im.get('data-src') or im.get('data-lazy-src') or im.get('src')
                if not src:
                    continue
                u = urljoin(url, src)
                if not u.startswith('http') or u in imgs:
                    continue
                if image_is_editorial_or_decorative(im, u):
                    print('Skip editorial/decorative image:', u[:180])
                    continue
                imgs.append(u)
                if len(imgs) >= 10:
                    break

        return text, imgs
    except Exception as e:
        print('Article fetch/filter warning:', e)
        return filter_text(fallback), []


worker.fetch_article = fetch_article_filtered

if __name__ == '__main__':
    sys.exit(worker.main())

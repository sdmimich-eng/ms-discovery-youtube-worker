import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import render_and_upload_v2 as worker


def is_boilerplate(text: str) -> bool:
    t = worker.clean_text(text).casefold()
    if not t:
        return True

    # Klassische Meta-/Werbezeilen, die nicht in Sprechertext/Folien gehören.
    if t.startswith((
        'werbung', 'anzeige', 'autor:', 'autor ', 'redaktion:',
        'veröffentlicht am ', 'veroeffentlicht am ',
        'zuletzt aktualisiert', 'letzte aktualisierung',
    )):
        return True

    # KI-Transparenzhinweise der MS-Seiten: bewusst eng gefasst, damit
    # echte Artikel über KI/AI nicht versehentlich herausgefiltert werden.
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

    # Typische vollständige Disclosure-Sätze, z. B. "Dieser Beitrag wurde ... KI ... erstellt".
    if re.search(r'\b(dieser|der)\s+(beitrag|text|inhalt|artikel)\b.*\b(ki|künstliche[rn]? intelligenz|kuenstliche[rn]? intelligenz)\b.*\b(erstellt|überarbeitet|ueberarbeitet|generiert|unterstützt|unterstuetzt)\b', t):
        return True
    if re.search(r'\b(ki|künstliche[rn]? intelligenz|kuenstliche[rn]? intelligenz)\b.*\b(beitrag|text|inhalt|artikel)\b.*\b(erstellt|überarbeitet|ueberarbeitet|generiert|unterstützt|unterstuetzt)\b', t):
        return True

    return False


def filter_text(text: str) -> str:
    # Falls ein Fallback-Text verwendet wird, ebenfalls satzweise säubern.
    parts = re.split(r'(?<=[.!?])\s+', worker.clean_text(text))
    kept = [p for p in parts if p and not is_boilerplate(p)]
    return worker.clean_text(' '.join(kept))


def fetch_article_filtered(url, fallback):
    try:
        r = requests.get(
            url,
            timeout=25,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; MS-Ratgeber/1.2)'},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            tag.decompose()

        # Bekannte/naheliegende Disclosure-Container komplett entfernen, bevor Text gesammelt wird.
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
            imgs.append(urljoin(url, og['content']))
        if root:
            for im in root.find_all('img'):
                src = im.get('data-src') or im.get('src')
                if src:
                    u = urljoin(url, src)
                    if u.startswith('http') and u not in imgs:
                        imgs.append(u)
                if len(imgs) >= 8:
                    break

        return text, imgs
    except Exception as e:
        print('Article fetch/filter warning:', e)
        return filter_text(fallback), []


worker.fetch_article = fetch_article_filtered

if __name__ == '__main__':
    sys.exit(worker.main())

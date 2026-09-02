import sys
from PIL import Image, ImageDraw

import social_media_worker as base

_ORIGINAL_STORY = base.make_story
_ORIGINAL_SCENE = base.make_scene


def make_story_click_first(job, source, out):
    _ORIGINAL_STORY(job, source, out)
    with Image.open(out).convert('RGB') as im:
        draw = ImageDraw.Draw(im, 'RGBA')
        # Alte scheinbare Direktlink-CTA sauber ueberdecken. Vollautomatische Story-
        # Link-Sticker sind API-seitig nicht verfuegbar; deshalb klar zum Profil-Link fuehren.
        draw.rounded_rectangle((95, 1588, 985, 1692), radius=30, fill=(235, 244, 252, 250))
        draw.text((132, 1605), 'LINK IM PROFIL', font=base.font(37, True), fill=(8, 28, 48, 255))
        draw.text((132, 1652), 'Aktueller Ratgeber', font=base.font(29, False), fill=(8, 28, 48, 255))
        im.save(out, 'JPEG', quality=92, optimize=True)


def make_scene_click_first(job, source, kind):
    im = _ORIGINAL_SCENE(job, source, kind)
    if kind == 3 and not base.is_tiktok_clean(job):
        draw = ImageDraw.Draw(im, 'RGBA')
        # Finale Reel-Szene: keine unanklickbare URL versprechen, sondern einen
        # eindeutigen Profil-CTA. Feed/Reel-Link wird parallel als Buffer-Linkziel gesetzt.
        draw.rounded_rectangle((88, 1200, 1002, 1665), radius=38, fill=(7, 16, 29, 246))
        draw.text((125, 1250), 'ZUM VOLLSTAENDIGEN RATGEBER', font=base.font(31, True), fill=(151, 219, 255, 255))
        draw.text((125, 1330), 'LINK IM PROFIL', font=base.font(55, True), fill='white')
        draw.text((125, 1410), 'Aktueller Ratgeber', font=base.font(42, True), fill=(170, 224, 255, 255))
        draw.text((125, 1500), 'Einmal tippen und direkt zur Website.', font=base.font(31, False), fill=(239, 245, 251, 255))
        draw.text((125, 1570), base.domain_label(job), font=base.font(30, False), fill=(203, 225, 242, 255))
    return im


base.make_story = make_story_click_first
base.make_scene = make_scene_click_first

if __name__ == '__main__':
    raise SystemExit(base.main())

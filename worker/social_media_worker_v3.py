"""MS Discovery 5.7.16: Instagram-only social worker entrypoint.

The retired direct TikTok developer path must never be selected by the active
media worker. WordPress only emits Instagram Story/Reel jobs; this wrapper also
forces any legacy renderer compatibility flag off before publishing.
"""
import social_media_worker_v2 as v2

if hasattr(v2.base, 'is_tiktok_clean'):
    v2.base.is_tiktok_clean = lambda job: False

if __name__ == '__main__':
    raise SystemExit(v2.base.main())

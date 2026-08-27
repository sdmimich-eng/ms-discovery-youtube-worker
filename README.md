# MS Discovery YouTube Worker (kostenlos)

Der Worker fragt etwa alle 10 Minuten genau einen Job von MS Discovery ab. Er rendert auf einem Standard-GitHub-Runner mit FFmpeg und der lokalen, kostenlosen deutschen Piper-Neuralstimme `de_DE-thorsten-medium`, erstellt ein eigenes Thumbnail und lädt direkt zu dem in WordPress per OAuth verbundenen YouTube-Kanal hoch. `espeak-ng` ist nur ein technischer Fallback.

## Einrichtung

Unter **Settings → Secrets and variables → Actions** zwei Repository-Secrets anlegen:

- `MSD_WORKER_URL` = die im MS-Discovery-Tab „YouTube“ angezeigte Worker-Job-URL
- `MSD_WORKER_SECRET` = der dort angezeigte Worker-Secret

Danach unter **Actions** den Workflow einmal manuell starten. Anschließend läuft er automatisch und verarbeitet pro Lauf höchstens einen bereitstehenden Job. MS Discovery steuert zentral ein flexibles Tagesziel von **3–6 Videos pro Tag**, verhindert Doppelveröffentlichungen und verteilt zusätzliche Uploads nach dem Tagesminimum mit wechselnden Abständen.

Das Repository enthält keine YouTube-Refresh-Tokens und keine Google-Client-Secrets. MS Discovery gibt dem Worker pro Job nur einen kurzlebigen YouTube-Access-Token.

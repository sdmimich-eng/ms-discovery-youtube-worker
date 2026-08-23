# MS Discovery YouTube Worker (kostenlos)

Der Worker fragt alle zwei Stunden genau einen Job von MS Discovery ab. Er rendert auf einem Standard-GitHub-Runner mit FFmpeg und der lokalen, kostenlosen deutschen Piper-Neuralstimme `de_DE-thorsten-medium`, erstellt ein eigenes Thumbnail und lädt direkt zu dem in WordPress per OAuth verbundenen YouTube-Kanal hoch. `espeak-ng` ist nur noch ein technischer Fallback.

## Einrichtung

Unter **Settings → Secrets and variables → Actions** zwei Repository-Secrets anlegen:

- `MSD_WORKER_URL` = die im MS-Discovery-Tab „YouTube“ angezeigte Worker-Job-URL
- `MSD_WORKER_SECRET` = der dort angezeigte Worker-Secret

Danach unter **Actions** den Workflow einmal manuell starten. Anschließend läuft er alle zwei Stunden automatisch und verarbeitet höchstens einen bereitstehenden Job. MS Discovery begrenzt die Veröffentlichung zentral auf maximal zwei Videos pro Tag.

Das Repository enthält keine YouTube-Refresh-Tokens und keine Google-Client-Secrets. MS Discovery gibt dem Worker pro Job nur einen kurzlebigen YouTube-Access-Token.

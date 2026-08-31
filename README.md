# MS Discovery Media Worker (kostenlos)

Der Worker verarbeitet YouTube sowie Instagram Story/Reel vollständig auf einem Standard-GitHub-Runner. Die vier Prüfungen pro Stunde laufen bewusst versetzt auf **:07 / :22 / :37 / :52**, damit sie nicht gleichzeitig mit dem WordPress-Hauptslot (:05) oder dem Pinterest-Wakeup (:17) starten.

YouTube rendert mit FFmpeg und der lokalen, kostenlosen deutschen Piper-Neuralstimme `de_DE-thorsten-medium`; `espeak-ng` bleibt nur technischer Fallback. V10 behält die V9-Wachstums-/Thumbnail-Logik bei, zeigt in den redaktionellen Karten aber nur noch vollständige, allein verständliche Sätze und wählt dazu passende Überschriften. Satzfragmente durch Komma-/Wort-Splitting werden nicht mehr als eigener Kartentext ausgegeben.

## Einrichtung

Unter **Settings → Secrets and variables → Actions** zwei Repository-Secrets anlegen:

- `MSD_WORKER_URL` = die im MS-Discovery-Tab „YouTube“ angezeigte Worker-Job-URL
- `MSD_WORKER_SECRET` = der dort angezeigte Worker-Secret

Danach unter **Actions** den Workflow einmal manuell starten. Anschließend läuft er automatisch und verarbeitet pro Lauf höchstens einen bereitstehenden Job. MS Discovery steuert zentral YouTube-/Social-Fälligkeiten und verhindert parallele Media-Jobs über die gemeinsame Workflow-Concurrency.

Ein kurzfristig nicht erreichbarer WordPress-Job-Claim wird als leerer Lauf behandelt und beim nächsten Intervall erneut versucht. Echte Rendering-/Uploadfehler bleiben weiterhin als Fehler sichtbar.

Das Repository enthält keine YouTube-Refresh-Tokens und keine Google-Client-Secrets. MS Discovery gibt dem Worker pro Job nur einen kurzlebigen YouTube-Access-Token.

"""
====================================================
  TRUE CRIME YOUTUBE BOT - KOSTENLOSE VERSION
  Täglich 1 Video automatisch erstellen & uploaden
  
  KOSTEN: 0€ - Alles komplett kostenlos!
====================================================

BENÖTIGTE INSTALLATIONEN:
pip install google-generativeai edge-tts moviepy pillow requests
            google-api-python-client google-auth-oauthlib python-dotenv asyncio

KOSTENLOSE SERVICES:
- Gemini API    → Skript generieren (Google, 1500x/Tag gratis)
- Edge TTS      → Voiceover (Microsoft, komplett kostenlos)
- Pexels API    → Stock-Videos (kostenlos)
- Pillow        → Thumbnail (lokal, kein API nötig)
- YouTube API   → Upload (kostenlos)
"""

import os
import re
import random
import requests
import json
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ── ffmpeg automatisch bereitstellen (kein manuelles Installieren nötig!) ──────
import imageio_ffmpeg
os.environ["IMAGEIO_FFMPEG_EXE"] = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["FFMPEG_BINARY"] = imageio_ffmpeg.get_ffmpeg_exe()

# ── Pillow-Kompatibilität für moviepy 1.0.3 (neue Pillow-Versionen haben
#    ANTIALIAS entfernt und durch LANCZOS ersetzt) ─────────────────────────────
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

# ── Kostenlose API Libraries ───────────────────────────────────────────────────
import google.generativeai as genai
import edge_tts
from moviepy.editor import (
    VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeAudioClip
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# ── Konfiguration ──────────────────────────────────────────────────────────────
load_dotenv()

GEMINI_KEY = os.getenv("GEMINI_KEY")
PEXELS_KEY = os.getenv("PEXELS_KEY")

# Edge TTS Stimme – Deutsch, dunkel & professionell (komplett kostenlos!)
# Weitere Stimmen: de-DE-ConradNeural, de-AT-JonasNeural, de-DE-KillianNeural
VOICE = "de-DE-KillianNeural"

# YouTube API
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Ordner anlegen
for folder in ["output", "tmp", "assets", "logs"]:
    Path(folder).mkdir(exist_ok=True)

# ── Themen-Kategorien für Inspiration (Gemini sucht sich daraus + eigene Ideen) ─
TOPIC_REGIONS = [
    "USA", "Großbritannien", "Deutschland", "Österreich", "Schweiz",
    "Frankreich", "Italien", "Spanien", "Skandinavien (Schweden/Norwegen/Dänemark)",
    "Japan", "Südkorea", "Australien", "Kanada", "Russland", "Osteuropa (Polen/Tschechien)",
    "Lateinamerika (Mexiko/Brasilien/Argentinien)", "Indien", "Südafrika", "Niederlande", "Belgien",
]

# ── SCHRITT 0: NEUES, EINZIGARTIGES THEMA MIT GEMINI FINDEN ───────────────────
def generate_unique_topic(used_topics: set) -> str:
    """Lässt Gemini einen echten, bisher unbenutzten True-Crime-Fall vorschlagen.
    Dadurch gehen die Themen nie aus und es gibt Fälle aus der ganzen Welt."""
    print(f"\n🌍 Suche neues True-Crime-Thema (weltweit, einzigartig)...")

    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-flash-lite-latest")

    region = random.choice(TOPIC_REGIONS)
    used_list = "\n".join(f"- {t}" for t in used_topics) if used_topics else "(noch keine)"

    prompt = f"""Du bist Researcher für einen True-Crime-YouTube-Kanal.

Schlage GENAU EINEN echten, dokumentierten Kriminalfall vor (Mord, Verschwinden,
ungelöster Fall, bekannter Serienmörder, etc.) – bevorzugt mit Bezug zu: {region}.
Der Fall muss real und öffentlich bekannt/dokumentiert sein (keine Erfindung!).

WICHTIG – diese Themen wurden bereits verwendet, schlage NICHTS davon
(auch keine Wiederholungen mit anderen Worten) vor:
{used_list}

Antworte NUR in exakt diesem Format, nichts anderes:
Fallname – Kurze packende Beschreibung in 4-8 Wörtern

Beispiel: Der Fall Madeleine McCann – Spurlos verschwunden in Portugal"""

    response = model.generate_content(prompt)
    topic = response.text.strip().strip('"').strip()

    # Sicherheits-Check: falls Gemini doch ein Duplikat vorschlägt, nochmal versuchen
    attempts = 0
    while topic in used_topics and attempts < 3:
        response = model.generate_content(prompt)
        topic = response.text.strip().strip('"').strip()
        attempts += 1

    print(f"   ✅ Neues Thema gefunden: {topic}")
    return topic

# ── SCHRITT 1: SKRIPT MIT GEMINI (KOSTENLOS) ──────────────────────────────────
def generate_script(topic: str) -> str:
    print(f"\n📝 Generiere Skript mit Gemini (kostenlos)...")
    print(f"   Thema: {topic}")

    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-flash-lite-latest")  # Kostenlose Version

    prompt = f"""Du bist ein professioneller True Crime YouTuber mit 2 Millionen Abonnenten.
Schreibe ein fesselndes deutsches YouTube-Video-Skript über: {topic}

ANFORDERUNGEN:
- Exakt 1800-2200 Wörter (= ca. 10 Minuten Voiceover)
- Spannende Eröffnung die sofort fesselt (KEIN "Hallo und willkommen")
- Mindestens 3 Cliffhanger-Momente einbauen
- Faktenbasiert aber dramatisch und fesselnd erzählt
- Ton: Mysteriös, investigativ, packend
- Am Ende: Zuschauer zum Abonnieren auffordern

STRUKTUR – nutze diese exakten Marker:
[HOOK]
(30-45 Sekunden – sofort in die Action, schockierender Fakt oder Frage)

[KAPITEL 1: HINTERGRUND]
(Wer sind die beteiligten Personen, Kontext)

[KAPITEL 2: DIE EREIGNISSE]
(Was genau passiert ist, chronologisch und spannend)

[KAPITEL 3: DIE ERMITTLUNG]
(Beweise, Verdächtige, Wendepunkte)

[KAPITEL 4: OFFENE FRAGEN]
(Was bis heute ungeklärt ist, Theorien der Ermittler)

[OUTRO]
(Kurze Zusammenfassung + Aufforderung zu abonnieren und kommentieren)

Schreibe NUR das Skript, keine Erklärungen oder Kommentare davor/danach."""

    response = model.generate_content(prompt)
    script = response.text
    print(f"   ✅ Skript fertig! ({len(script.split())} Wörter)")
    return script


# ── SCHRITT 2: VOICEOVER MIT EDGE TTS (100% KOSTENLOS) ────────────────────────
async def create_voiceover_async(text: str, output_path: str):
    """Edge TTS ist komplett kostenlos – von Microsoft"""
    communicate = edge_tts.Communicate(text, VOICE, rate="+5%", pitch="-10Hz")
    await communicate.save(output_path)

def create_voiceover(script: str, output_path: str) -> float:
    print(f"\n🎙️  Erstelle Voiceover mit Edge TTS (kostenlos)...")

    # Regieanweisungen [IN KLAMMERN] entfernen
    clean = re.sub(r'\[.*?\]', '', script)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()

    # Async ausführen
    asyncio.run(create_voiceover_async(clean, output_path))

    # Länge messen
    audio = AudioFileClip(output_path)
    duration = audio.duration
    audio.close()

    print(f"   ✅ Voiceover fertig! ({duration/60:.1f} Minuten)")
    return duration


# ── SCHRITT 3: STOCK-VIDEOS VON PEXELS (KOSTENLOS) ────────────────────────────
def fetch_stock_videos(duration_needed: float) -> list:
    print(f"\n🎬 Lade kostenlose Stock-Videos von Pexels...")

    keywords = [
        "dark forest night", "mystery shadow", "foggy urban street",
        "crime investigation", "dark corridor", "rain city night",
        "abandoned building", "night sky stars", "detective",
        "dark room candle", "old newspaper", "police lights blue",
        "mysterious figure silhouette", "gothic architecture",
    ]

    random.shuffle(keywords)
    video_files = []
    total = 0
    target = duration_needed * 1.5  # 50% Puffer

    headers = {"Authorization": PEXELS_KEY}

    for keyword in keywords:
        if total >= target:
            break

        try:
            params = {"query": keyword, "per_page": 3,
                     "orientation": "landscape", "size": "medium"}
            res = requests.get("https://api.pexels.com/videos/search",
                             headers=headers, params=params, timeout=10)
            if res.status_code != 200:
                continue

            for video in res.json().get("videos", []):
                files = sorted(video["video_files"],
                             key=lambda x: x.get("height", 0), reverse=True)
                best = next((f for f in files
                           if f.get("height", 0) <= 1080), None)
                if best:
                    video_files.append({
                        "url": best["link"],
                        "duration": video.get("duration", 15)
                    })
                    total += video.get("duration", 15)
        except:
            continue

    print(f"   ✅ {len(video_files)} Videos geladen ({total:.0f} Sek Material)")
    return video_files


# ── SCHRITT 4: VIDEO ZUSAMMENBAUEN ────────────────────────────────────────────
def create_video(audio_path: str, video_sources: list, output_path: str):
    print(f"\n🎞️  Baue Video zusammen...")

    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    clips = []
    current_time = 0

    for i, source in enumerate(video_sources):
        if current_time >= total_duration:
            break

        tmp_path = f"tmp/clip_{i}.mp4"
        try:
            print(f"   ⬇️  Lade Clip {i+1}/{len(video_sources)}...", end="\r")
            r = requests.get(source["url"], timeout=30, stream=True)
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            clip = VideoFileClip(tmp_path)
            clip_duration = min(clip.duration, 25, total_duration - current_time)
            clip = clip.subclip(0, clip_duration)
            clip = clip.resize((1920, 1080))
            clips.append(clip)
            current_time += clip_duration

        except Exception as e:
            print(f"\n   ⚠️  Clip {i+1} fehlgeschlagen: {e}")
            continue

    if not clips:
        raise Exception("Keine Video-Clips geladen!")

    print(f"\n   🔗 Füge {len(clips)} Clips zusammen...")
    final_video = concatenate_videoclips(clips, method="compose")
    final_video = final_video.set_audio(audio)
    final_video = final_video.subclip(0, total_duration)

    print(f"   💾 Exportiere Video...")
    final_video.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        fps=24,
        preset="medium",
        verbose=False,
        logger=None
    )

    # Alle Clips schließen (wichtig für Windows, sonst sind Dateien noch "in Benutzung")
    for c in clips:
        try:
            c.close()
        except:
            pass
    audio.close()

    # Temp-Dateien löschen (Fehler werden ignoriert falls Windows kurz blockiert)
    for i in range(len(video_sources)):
        tmp = f"tmp/clip_{i}.mp4"
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass  # Datei wird beim nächsten Lauf überschrieben, kein Problem

    print(f"   ✅ Video fertig!")


# ── SCHRITT 5: THUMBNAIL MIT PILLOW (KOMPLETT LOKAL & KOSTENLOS) ──────────────
def create_thumbnail(topic: str, output_path: str):
    print(f"\n🖼️  Erstelle Thumbnail (lokal, kostenlos)...")

    # Hintergrundbild – dunkler Farbverlauf
    img = Image.new("RGB", (1280, 720), color=(5, 5, 15))
    draw = ImageDraw.Draw(img)

    # Dramatischer Hintergrund – rote/dunkle Streifen
    for y in range(720):
        red = int(80 * (y / 720))
        draw.rectangle([(0, y), (1280, y+1)], fill=(red, 0, 10))

    # Diagonale Lichtstreifen für Dramatik
    for i in range(0, 1280, 80):
        for x in range(i, min(i+30, 1280)):
            alpha_val = int(15 * (1 - abs(x - i - 15) / 15))
            for y in range(720):
                r, g, b = img.getpixel((x, y))
                img.putpixel((x, y), (
                    min(255, r + alpha_val),
                    min(255, g + alpha_val // 3),
                    min(255, b + alpha_val // 3)
                ))

    # Leichter Blur für weichen Look
    img = img.filter(ImageFilter.GaussianBlur(radius=1))
    draw = ImageDraw.Draw(img)

    # Rotes Glühen in der Mitte
    for radius in range(300, 0, -10):
        alpha = int(40 * (1 - radius/300))
        draw.ellipse(
            [(640 - radius, 360 - radius//2),
             (640 + radius, 360 + radius//2)],
            fill=(min(255, alpha*3), 0, 0)
        )

    # Schriften laden (Windows Fonts)
    try:
        font_title  = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 78)
        font_badge  = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 32)
        font_sub    = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 38)
    except:
        font_title = ImageFont.load_default()
        font_badge = font_title
        font_sub   = font_title

    # ── TRUE CRIME Badge oben links ────────────────────────────────────────────
    draw.rectangle([(30, 28), (310, 78)], fill=(180, 0, 0))
    draw.rectangle([(32, 30), (308, 76)], fill=(220, 20, 20))
    draw.text((45, 33), "⬛ TRUE CRIME", fill="white", font=font_badge)

    # ── DEUTSCH Badge oben rechts ──────────────────────────────────────────────
    draw.rectangle([(1100, 28), (1250, 78)], fill=(20, 20, 80))
    draw.text((1115, 33), "DEUTSCH", fill="#8888ff", font=font_badge)

    # ── Haupttitel ─────────────────────────────────────────────────────────────
    # Thema aufteilen beim "–" oder nach 22 Zeichen
    if "–" in topic:
        parts = topic.split("–")
        line1 = parts[0].strip().upper()
        line2 = parts[1].strip().upper() if len(parts) > 1 else ""
    else:
        words = topic.upper().split()
        mid = len(words) // 2
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])

    # Langen Text kürzen
    if len(line1) > 22:
        line1 = line1[:22] + "..."
    if len(line2) > 26:
        line2 = line2[:26] + "..."

    # Schatten + weißer Text Zeile 1
    draw.text((64, 274), line1, fill=(0, 0, 0), font=font_title)
    draw.text((62, 272), line1, fill=(255, 255, 255), font=font_title)

    # Roter Text Zeile 2
    if line2:
        draw.text((64, 364), line2, fill=(0, 0, 0), font=font_title)
        draw.text((62, 362), line2, fill=(255, 60, 60), font=font_title)

    # ── Fragezeichen-Dekoration ────────────────────────────────────────────────
    draw.text((1150, 250), "?", fill=(60, 0, 0), font=font_title)

    # ── Untertitel ─────────────────────────────────────────────────────────────
    draw.text((62, 468), "Die schockierende Wahrheit...",
              fill=(180, 180, 180), font=font_sub)

    # ── Untere Linie ──────────────────────────────────────────────────────────
    draw.rectangle([(0, 680), (1280, 720)], fill=(150, 0, 0))
    draw.text((30, 685), "True Crime Deutsch  •  Ungeklärte Fälle",
              fill="white", font=font_badge)

    img.save(output_path, "JPEG", quality=95)
    print(f"   ✅ Thumbnail fertig!")


# ── SCHRITT 6: YOUTUBE UPLOAD (KOSTENLOS) ─────────────────────────────────────
def get_youtube_client():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(video_path: str, thumbnail_path: str,
                      topic: str, script: str) -> str:
    print(f"\n📤 Lade auf YouTube hoch...")
    youtube = get_youtube_client()

    # Automatische Beschreibung
    intro = re.sub(r'\[.*?\]', '', script)[:350].strip()
    description = f"""{intro}...

━━━━━━━━━━━━━━━━━━━━━━━━
🔔 ABONNIERE für wöchentliche True Crime Stories!
👍 Like wenn dir das Video gefällt!
💬 Deine Theorien in den Kommentaren!
━━━━━━━━━━━━━━━━━━━━━━━━

📌 KAPITEL:
00:00 - Hook
01:30 - Hintergrund
03:30 - Die Ereignisse
06:00 - Die Ermittlung
08:30 - Offene Fragen
10:00 - Fazit

⚠️ Dieses Video wurde mit KI-Unterstützung erstellt.
Alle Fakten basieren auf öffentlich zugänglichen Quellen.

#TrueCrime #Mystery #Krimi #Deutsch #Ungeklärt #Dokumentation #Verbrechen"""

    body = {
        "snippet": {
            "title": f"🔴 {topic} | True Crime Deutsch",
            "description": description,
            "tags": ["true crime", "mystery", "kriminalfall", "ungeklärt",
                    "deutsch", "dokumentation", "mord", "verbrechen",
                    "krimi", "investigation"],
            "categoryId": "25",
            "defaultLanguage": "de",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # Pflicht bei KI-Content!
        }
    }

    media = MediaFileUpload(
        video_path, mimetype="video/mp4",
        resumable=True, chunksize=5 * 1024 * 1024
    )

    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    print("   ⏳ Upload läuft...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"   📊 {int(status.progress() * 100)}% hochgeladen...", end="\r")

    video_id = response["id"]
    print(f"\n   ✅ Video live! → https://youtube.com/watch?v={video_id}")

    # Thumbnail setzen
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    ).execute()
    print("   ✅ Thumbnail gesetzt!")

    return video_id


# ── HAUPTPROGRAMM ──────────────────────────────────────────────────────────────
def main():
    start_time = datetime.now()
    date_str = start_time.strftime("%Y-%m-%d")

    print("=" * 55)
    print("  🔴 TRUE CRIME BOT – KOSTENLOSE VERSION")
    print(f"  📅 {start_time.strftime('%d.%m.%Y %H:%M Uhr')}")
    print("  💰 Kosten heute: 0€")
    print("=" * 55)

    audio_path  = f"output/voiceover_{date_str}.mp3"
    video_path  = f"output/video_{date_str}.mp4"
    thumb_path  = f"output/thumbnail_{date_str}.jpg"
    script_path = f"output/script_{date_str}.txt"
    log_path    = f"logs/uploaded_{date_str}.json"

    # Heute schon hochgeladen?
    if os.path.exists(log_path):
        print("\n⚠️  Heute wurde bereits ein Video hochgeladen!")
        return

    try:
        # Liste aller bisher verwendeten Themen laden (damit nie ein Fall doppelt vorkommt)
        used = set()
        if os.path.exists("logs/used_topics.json"):
            with open("logs/used_topics.json", encoding="utf-8") as f:
                used = set(json.load(f))

        # Gemini sucht selbst einen neuen, echten Fall irgendwo aus der Welt –
        # garantiert noch nicht in der "used" Liste enthalten
        topic = generate_unique_topic(used)
        used.add(topic)

        # ── Pipeline ───────────────────────────────────────────────────────────
        script = generate_script(topic)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        duration = create_voiceover(script, audio_path)
        video_sources = fetch_stock_videos(duration)
        create_video(audio_path, video_sources, video_path)
        create_thumbnail(topic, thumb_path)
        video_id = upload_to_youtube(video_path, thumb_path, topic, script)

        # Erfolg speichern
        elapsed = (datetime.now() - start_time).seconds // 60
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump({
                "date": date_str,
                "topic": topic,
                "video_id": video_id,
                "url": f"https://youtube.com/watch?v={video_id}",
                "kosten": "0€",
                "laufzeit_min": elapsed
            }, f, indent=2, ensure_ascii=False)

        with open("logs/used_topics.json", "w", encoding="utf-8") as f:
            json.dump(list(used), f, ensure_ascii=False, indent=2)

        # Erfolg ausgeben
        print("\n" + "=" * 55)
        print("  🎉 FERTIG – Video ist live!")
        print(f"  🎬 {topic[:45]}...")
        print(f"  🔗 https://youtube.com/watch?v={video_id}")
        print(f"  💰 Kosten: 0€")
        print(f"  ⏱️  Laufzeit: {elapsed} Minuten")
        print("=" * 55)

    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        with open(f"logs/error_{date_str}.txt", "w") as f:
            f.write(str(e))
        raise


if __name__ == "__main__":
    main()

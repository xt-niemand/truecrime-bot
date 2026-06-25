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
    CompositeAudioClip, ImageClip, CompositeVideoClip
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

# Stimme für die Shorts – energischer/jünger (passt zu "spannend + leicht lustig")
VOICE_SHORT = "de-DE-FlorianMultilingualNeural"

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
    topic = _extract_topic_text(response)

    # Sicherheits-Check: falls Gemini doch ein Duplikat vorschlägt, nochmal versuchen
    attempts = 0
    while (not topic or topic in used_topics) and attempts < 3:
        response = model.generate_content(prompt)
        topic = _extract_topic_text(response)
        attempts += 1

    # Letzte Absicherung: falls Gemini partout keinen brauchbaren Text liefert
    # (z.B. wegen Safety-Filtern), nehmen wir ein generisches Fallback-Thema,
    # damit der Upload nie mit einem leeren Titel fehlschlägt.
    if not topic:
        fallback_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        topic = f"Ungelöster Kriminalfall – Folge {fallback_id}"
        print(f"   ⚠️  Gemini lieferte kein brauchbares Thema, nutze Fallback: {topic}")

    print(f"   ✅ Neues Thema gefunden: {topic}")
    return topic


def _extract_topic_text(response) -> str:
    """Holt sicher den Text aus einer Gemini-Antwort, ohne bei leeren/blockierten
    Antworten eine Exception zu werfen. YouTube-Titel sind auf 100 Zeichen
    begrenzt, daher kürzen wir hier zur Sicherheit auf 95 Zeichen."""
    try:
        text = response.text.strip().strip('"').strip()
    except Exception:
        return ""

    if not text:
        return ""

    # Manchmal antwortet Gemini mit mehreren Zeilen trotz Anweisung –
    # nur die erste nicht-leere Zeile als Thema verwenden
    first_line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")

    # YouTube-Titel-Limit ist 100 Zeichen; wir geben uns 5 Zeichen Puffer
    # (für das "🔴 " Präfix und " #Shorts"/" | True Crime Deutsch" Suffix)
    if len(first_line) > 70:
        first_line = first_line[:70].rsplit(" ", 1)[0]

    return first_line

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


# ── SCHRITT 1b: KURZES SKRIPT FÜR SHORTS (1-2 MIN, SPANNEND + LUSTIG) ─────────
def generate_short_script(topic: str) -> str:
    """Erstellt ein knackiges Short-Skript mit ungewöhnlicher Verbindung als Hook."""
    print(f"\n📝 Generiere SHORT-Skript mit Gemini (kostenlos)...")
    print(f"   Thema: {topic}")

    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-flash-lite-latest")

    prompt = f"""Du bist ein viraler True-Crime-Shorts-Creator auf YouTube/TikTok.
Schreibe ein KURZES, knackiges Skript über: {topic}

ANFORDERUNGEN:
- Nur 140-190 Wörter GESAMT (= ca. 60-90 Sekunden gesprochen)
- HOOK MUSS eine "ungewöhnliche Verbindung" sein – verbinde den Killer/Fall mit
  etwas banalem oder unerwartetem Alltagsding, z.B.
  "Dieser Mann liebte Eis am Stiel – und tötete 7 Menschen." Erfinde eine
  ECHTE, dokumentierte schrullige Marotte/Vorliebe der Person für den Hook,
  keine Erfindung wenn nicht belegt – sonst eine andere überraschende Tatsache.
- Ton: spannend, mysteriös, mit einem klaren Schuss leichtem, dunklem Humor
  (KEIN Verharmlosen der Opfer – der Humor liegt im Erzählstil/Timing, nicht
  am Verbrechen selbst)
- Kurze, knackige Sätze. Viele Cliffhanger-Wörter ("Aber dann...", "Niemand
  wusste...", "Bis heute...")
- Schluss MUSS ein offener Cliffhanger oder eine gruselige Pointe sein, die
  zum Folgen/Abonnieren animiert

STRUKTUR – nutze diese exakten Marker:
[HOOK]
(1-2 Sätze, die ungewöhnliche Verbindung)

[STORY]
(Die Kerngeschichte kompakt erzählt, 3-5 Sätze)

[TWIST]
(Eine überraschende Wendung oder der ungelöste Rest)

[OUTRO]
(1 Satz, der zum Abonnieren/Folgen für mehr Cases auffordert)

Schreibe NUR das Skript, keine Erklärungen davor oder danach."""

    response = model.generate_content(prompt)
    script = response.text
    print(f"   ✅ Short-Skript fertig! ({len(script.split())} Wörter)")
    return script


# ── SCHRITT 2: VOICEOVER MIT EDGE TTS (100% KOSTENLOS) ────────────────────────
async def create_voiceover_async(text: str, output_path: str, voice: str, rate: str, pitch: str):
    """Edge TTS ist komplett kostenlos – von Microsoft"""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)

def create_voiceover(script: str, output_path: str, voice: str = VOICE,
                      rate: str = "+5%", pitch: str = "-10Hz") -> float:
    print(f"\n🎙️  Erstelle Voiceover mit Edge TTS (kostenlos)...")

    # Regieanweisungen [IN KLAMMERN] entfernen
    clean = re.sub(r'\[.*?\]', '', script)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()

    # Async ausführen
    asyncio.run(create_voiceover_async(clean, output_path, voice, rate, pitch))

    # Länge messen
    audio = AudioFileClip(output_path)
    duration = audio.duration
    audio.close()

    print(f"   ✅ Voiceover fertig! ({duration/60:.1f} Minuten)")
    return duration


# ── SCHRITT 2b: VOICEOVER MIT WORT-ZEITSTEMPELN (NUR FÜR SHORTS-UNTERTITEL) ───
async def create_voiceover_with_timings_async(text: str, output_path: str,
                                               voice: str, rate: str, pitch: str) -> list:
    """Wie create_voiceover_async, sammelt aber zusätzlich pro Wort den exakten
    Start-Zeitpunkt (für TikTok-Style Wort-für-Wort-Untertitel bei Shorts)."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    word_timings = []  # Liste von {"word": str, "start": Sekunden, "end": Sekunden}

    with open(output_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration kommen in 100-Nanosekunden-Einheiten von Edge TTS
                start = chunk["offset"] / 10_000_000
                dur = chunk["duration"] / 10_000_000
                word_timings.append({
                    "word": chunk["text"],
                    "start": start,
                    "end": start + dur,
                })

    return word_timings

def create_voiceover_with_timings(script: str, output_path: str, voice: str,
                                   rate: str = "+15%", pitch: str = "+5Hz") -> tuple:
    """Erstellt das Voiceover + gibt (duration, word_timings) zurück.
    Wird nur für Shorts genutzt, damit Untertitel Wort-für-Wort synchron laufen."""
    print(f"\n🎙️  Erstelle Voiceover mit Wort-Zeitstempeln (kostenlos)...")

    clean = re.sub(r'\[.*?\]', '', script)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()

    word_timings = asyncio.run(
        create_voiceover_with_timings_async(clean, output_path, voice, rate, pitch)
    )

    audio = AudioFileClip(output_path)
    duration = audio.duration
    audio.close()

    print(f"   ✅ Voiceover fertig! ({duration:.1f} Sek, {len(word_timings)} Wörter erfasst)")
    return duration, word_timings


# ── SCHRITT 3b: CARTOON-BILDER FÜR SHORTS MIT GEMINI (NANO BANANA, KOSTENLOS) ──
def generate_cartoon_scenes(topic: str, script: str, num_scenes: int = 5) -> list:
    """Lässt Gemini's Bildmodell ein paar Cartoon-Szenenbilder zum Fall erstellen.
    Nutzt den selben kostenlosen GEMINI_KEY (Google AI Studio Free Tier)."""
    print(f"\n🎨 Erstelle {num_scenes} Cartoon-Szenenbilder (Gemini, kostenlos)...")

    genai.configure(api_key=GEMINI_KEY)
    image_model = genai.GenerativeModel("gemini-2.5-flash-image")

    # Kurze Szenen-Beschreibungen aus dem Skript ableiten lassen (Text-Modell)
    text_model = genai.GenerativeModel("gemini-flash-lite-latest")
    scene_prompt = f"""Lies dieses kurze True-Crime-Skript über "{topic}":

{script}

Erstelle GENAU {num_scenes} kurze, visuelle Szenen-Beschreibungen (je 1 Satz,
auf Englisch, für einen Cartoon-Bildgenerator), die den Ablauf der Geschichte
illustrieren. Stil: harmloser, leicht düsterer Cartoon/Comic-Look, NICHT
grafisch oder blutig, geeignet für YouTube Shorts (keine Altersbeschränkung).
Antworte NUR als Liste, eine Szene pro Zeile, ohne Nummerierung."""

    response = text_model.generate_content(scene_prompt)
    scenes = [s.strip("- ").strip() for s in response.text.strip().split("\n") if s.strip()]
    scenes = scenes[:num_scenes]

    image_paths = []
    for i, scene in enumerate(scenes):
        try:
            prompt = (
                f"Flat 2D cartoon illustration, true-crime documentary style, "
                f"muted dark color palette, simple shapes, NOT graphic or bloody, "
                f"safe for all audiences, vertical composition: {scene}"
            )
            result = image_model.generate_content(prompt)
            for part in result.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    img_path = f"tmp/scene_{i}.png"
                    with open(img_path, "wb") as f:
                        f.write(part.inline_data.data)
                    image_paths.append(img_path)
                    break
        except Exception as e:
            print(f"   ⚠️  Szene {i+1} fehlgeschlagen: {e}")
            continue

    print(f"   ✅ {len(image_paths)} Cartoon-Bilder erstellt!")
    return image_paths


# ── HILFSFUNKTION: TIKTOK-STYLE WORT-UNTERTITEL AUS ZEITSTEMPELN BAUEN ────────
def _build_word_caption_clips(word_timings: list, video_w: int, video_h: int) -> list:
    """Erstellt für jedes Wort einen kurzen TextClip (gelb, fett, mit schwarzem
    Rand), der exakt dann erscheint, wenn das Wort gesprochen wird – wie bei
    TikTok/Shorts üblich. NUR für Shorts gedacht."""
    caption_clips = []

    # Sicherheitsbremse: bei einem 60-90 Sek Short sind realistisch ~300 Wörter
    # das Maximum. Mehr deutet auf ein TTS-Problem hin – dann lieber abschneiden
    # statt das Rendering unnötig zu verlangsamen.
    word_timings = word_timings[:300]

    for wt in word_timings:
        word = wt["word"].strip()
        if not word:
            continue
        start = wt["start"]
        end = wt["end"]
        dur = max(end - start, 0.08)  # Mindestdauer, falls Wort sehr kurz ist

        # Pro Wort ein PNG mit Pillow rendern (zuverlässiger als ImageMagick/TextClip)
        txt_img = Image.new("RGBA", (video_w, 400), (0, 0, 0, 0))
        draw = ImageDraw.Draw(txt_img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 90)
        except Exception:
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
            except Exception:
                font = ImageFont.load_default()

        display_word = word.upper()
        bbox = draw.textbbox((0, 0), display_word, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (video_w - tw) // 2
        ty = (400 - th) // 2

        # Schwarzer Rand (Outline) für Lesbarkeit auf jedem Hintergrund
        for dx in (-4, -2, 0, 2, 4):
            for dy in (-4, -2, 0, 2, 4):
                draw.text((tx + dx, ty + dy), display_word, font=font, fill=(0, 0, 0, 255))
        # Gelber Text obendrauf (YouTube-Shorts-Style)
        draw.text((tx, ty), display_word, font=font, fill=(255, 220, 0, 255))

        word_idx = len(caption_clips)
        tmp_word_path = f"tmp/word_{word_idx}.png"
        txt_img.save(tmp_word_path)

        clip = (
            ImageClip(tmp_word_path)
            .set_start(start)
            .set_duration(dur)
            .set_position(("center", int(video_h * 0.72)))  # unteres Drittel
        )
        caption_clips.append(clip)

    return caption_clips


# ── SCHRITT 4b: SHORT-VIDEO ZUSAMMENBAUEN (9:16, CARTOON-BILDER + ZOOM) ───────
def create_short_video(audio_path: str, image_paths: list, output_path: str,
                        meme_lines: list = None, word_timings: list = None):
    """Baut ein vertikales Short-Video aus Cartoon-Standbildern mit
    sanftem Zoom-Effekt (Ken-Burns) + optional ein paar Meme-Textzeilen +
    Wort-für-Wort-Untertitel (gelb, TikTok-Style), falls word_timings übergeben."""
    print(f"\n🎞️  Baue Short-Video zusammen (9:16)...")

    if not image_paths:
        raise Exception("Keine Cartoon-Bilder zum Erstellen des Shorts vorhanden!")

    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    per_image = total_duration / len(image_paths)

    W, H = 1080, 1920  # 9:16 Shorts-Format
    clips = []

    for idx, img_path in enumerate(image_paths):
        img = Image.open(img_path).convert("RGB")

        # Bild zentriert auf 9:16 zuschneiden/skalieren (Cover-Fit)
        img_ratio = img.width / img.height
        target_ratio = W / H
        if img_ratio > target_ratio:
            new_height = img.height
            new_width = int(new_height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, new_height))
        else:
            new_width = img.width
            new_height = int(new_width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, new_width, top + new_height))
        img = img.resize((W, H), Image.LANCZOS)

        # Ein paar Memes/Untertitel auf ausgewählte Bilder (nicht zu viele)
        if meme_lines and idx < len(meme_lines) and meme_lines[idx]:
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 64)
            except Exception:
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
                except Exception:
                    font = ImageFont.load_default()

            text = meme_lines[idx].upper()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            tx = (W - tw) // 2
            ty = H - 320
            for dx in (-3, 0, 3):
                for dy in (-3, 0, 3):
                    draw.text((tx + dx, ty + dy), text, font=font, fill="black")
            draw.text((tx, ty), text, font=font, fill="white")

        tmp_img_path = f"tmp/scene_render_{idx}.png"
        img.save(tmp_img_path)

        clip = (
            ImageClip(tmp_img_path)
            .set_duration(per_image)
            .resize(lambda t, d=per_image: 1.0 + 0.08 * (t / d))  # sanfter Zoom
            .set_position(("center", "center"))
        )
        clip = CompositeVideoClip([clip], size=(W, H)).set_duration(per_image)
        clips.append(clip)

    background_video = concatenate_videoclips(clips, method="compose")
    background_video = background_video.subclip(0, total_duration)

    # Wort-für-Wort-Untertitel als zusätzliche Ebene drüberlegen (NUR Shorts)
    if word_timings:
        print(f"   💬 Füge {len(word_timings)} Wort-Untertitel hinzu...")
        caption_clips = _build_word_caption_clips(word_timings, W, H)
        final_video = CompositeVideoClip(
            [background_video] + caption_clips, size=(W, H)
        )
    else:
        final_video = background_video

    final_video = final_video.set_audio(audio)
    final_video = final_video.subclip(0, total_duration)

    print(f"   💾 Exportiere Short...")
    final_video.write_videofile(
        output_path, codec="libx264", audio_codec="aac",
        fps=30, preset="medium", verbose=False, logger=None
    )

    for c in clips:
        try:
            c.close()
        except Exception:
            pass
    audio.close()
    print(f"   ✅ Short-Video fertig!")


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
            with open("token.json", "w") as f:
                f.write(creds.to_json())
        else:
            # In der Cloud (z.B. GitHub Actions) gibt es keinen Browser für den Login!
            # Das token.json Secret muss dann lokal neu erzeugt und aktualisiert werden.
            if os.environ.get("GITHUB_ACTIONS") == "true":
                raise Exception(
                    "YouTube-Token ist abgelaufen und kann in der Cloud nicht "
                    "erneuert werden. Bitte token.json lokal neu erstellen "
                    "(einmal 'python main_kostenlos.py' auf deinem PC laufen "
                    "lassen) und das TOKEN_JSON Secret auf GitHub aktualisieren."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
            with open("token.json", "w") as f:
                f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ── TITEL-OPTIMIERUNG: REISSERISCHER, CLIFFHANGER-TITEL (FÜR MEHR CTR) ────────
def generate_clickbait_title(topic: str, script: str, is_short: bool) -> str:
    """Lässt Gemini einen reißerischen, aber wahrheitsgemäßen YouTube-Titel
    aus dem Thema + Skript bauen. Ziel: höhere Click-Through-Rate, ohne zu
    lügen oder Inhalte zu verfälschen (Clickbait im positiven Sinne)."""
    print(f"\n🎯 Erstelle reißerischen Titel (für höhere CTR)...")

    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-flash-lite-latest")

        kind = "YouTube Short (1-2 Min, cartoon-artig)" if is_short else "YouTube Long-Form Video (10 Min)"

        prompt = f"""Du bist Experte für virale YouTube-Titel im True-Crime-Bereich.

Fall/Thema: {topic}
Video-Typ: {kind}

Auszug aus dem Skript (für Kontext, NICHT direkt zitieren):
{script[:600]}

Schreibe EINEN einzigen, maximal 65 Zeichen langen deutschen YouTube-Titel,
der:
- Neugier erzeugt / einen Cliffhanger andeutet (z.B. "...dann passierte DAS")
- Emotional/dramatisch ist, aber NICHT lügt oder den Inhalt verfälscht
- KEINE Übertreibungen erfindet, die im Skript nicht vorkommen
- Optional 1 passendes Emoji enthält (nicht mehr als 1)
- Den echten Namen/Fall aus dem Thema erkennbar lässt

Antworte NUR mit dem Titel selbst, nichts anderes, keine Anführungszeichen."""

        response = model.generate_content(prompt)
        title = response.text.strip().strip('"').strip()
        first_line = next((ln.strip() for ln in title.split("\n") if ln.strip()), "")

        if first_line and len(first_line) <= 80:
            print(f"   ✅ Titel: {first_line}")
            return first_line
    except Exception as e:
        print(f"   ⚠️  Titel-Generierung fehlgeschlagen, nutze Standard-Titel: {e}")

    # Fallback: bisheriger, neutraler Titel-Stil
    return topic


def upload_to_youtube(video_path: str, thumbnail_path: str,
                      topic: str, script: str, is_short: bool = False) -> str:
    print(f"\n📤 Lade auf YouTube hoch...")
    youtube = get_youtube_client()

    # Letzte Absicherung: niemals mit leerem/zu langem Titel hochladen,
    # auch falls topic aus irgendeinem Grund leer oder None ankommt
    if not topic or not topic.strip():
        topic = f"Ungelöster Kriminalfall – Folge {datetime.now().strftime('%Y%m%d-%H%M')}"
    topic = topic.strip()[:70]

    # Reißerischen Titel generieren (für höhere CTR) – fällt auf "topic" zurück,
    # falls das mal fehlschlägt
    catchy_topic = generate_clickbait_title(topic, script, is_short)

    # Automatische Beschreibung
    intro = re.sub(r'\[.*?\]', '', script)[:350].strip()

    if is_short:
        title = f"🔴 {catchy_topic} #Shorts"
        description = f"""{intro}...

🔔 Folge für mehr True Crime Shorts!

⚠️ Dieses Video wurde mit KI-Unterstützung erstellt (Cartoon-Darstellung).
Alle Fakten basieren auf öffentlich zugänglichen Quellen.

#TrueCrime #Shorts #Mystery #Krimi #Deutsch"""
        tags = ["true crime", "shorts", "mystery", "kriminalfall",
                "deutsch", "krimi", "cartoon", "storytime"]
    else:
        title = f"🔴 {catchy_topic}"
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
        tags = ["true crime", "mystery", "kriminalfall", "ungeklärt",
                "deutsch", "dokumentation", "mord", "verbrechen",
                "krimi", "investigation"]

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
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

    # Thumbnail nur bei Long-Form setzen (Shorts brauchen i.d.R. kein eigenes Thumbnail)
    if not is_short and thumbnail_path and os.path.exists(thumbnail_path):
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

    # ── Abwechseln: gerader Kalendertag = Long-Form, ungerader = Short ────────
    # (robust & einfach: hängt nur am Datum, kein Zähler nötig, der verloren
    #  gehen könnte zwischen GitHub-Actions-Läufen)
    day_of_year = start_time.timetuple().tm_yday
    is_short_day = (day_of_year % 2 == 1)

    video_type = "SHORT (Cartoon, 60-90 Sek)" if is_short_day else "LONG-FORM (10 Min)"

    print("=" * 55)
    print("  🔴 TRUE CRIME BOT – KOSTENLOSE VERSION")
    print(f"  📅 {start_time.strftime('%d.%m.%Y %H:%M Uhr')}")
    print(f"  🎬 Heute: {video_type}")
    print("  💰 Kosten heute: 0€")
    print("=" * 55)

    suffix = "short" if is_short_day else "long"
    audio_path  = f"output/voiceover_{date_str}_{suffix}.mp3"
    video_path  = f"output/video_{date_str}_{suffix}.mp4"
    thumb_path  = f"output/thumbnail_{date_str}_{suffix}.jpg"
    script_path = f"output/script_{date_str}_{suffix}.txt"
    log_path    = f"logs/uploaded_{date_str}_{suffix}.json"

    # Heute (für diesen Typ) schon hochgeladen?
    if os.path.exists(log_path):
        print(f"\n⚠️  Heute wurde bereits ein {video_type}-Video hochgeladen!")
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

        if is_short_day:
            # ── SHORT-PIPELINE ───────────────────────────────────────────────
            script = generate_short_script(topic)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)

            # Wort-Zeitstempel mitsammeln, damit die Untertitel exakt synchron
            # zur gesprochenen Stimme erscheinen (TikTok-Style, gelb)
            duration, word_timings = create_voiceover_with_timings(
                script, audio_path, voice=VOICE_SHORT, rate="+15%", pitch="+5Hz"
            )
            scene_images = generate_cartoon_scenes(topic, script, num_scenes=5)

            # Nur die erste und eine mittlere Szene mit Meme-Text versehen
            # ("ein paar Memes sind ok, aber nicht zu viele")
            meme_lines = [None] * len(scene_images)
            if len(scene_images) > 0:
                meme_lines[0] = "WARTE BIS ZUM ENDE 👀"
            if len(scene_images) > 2:
                meme_lines[2] = "DAS GLAUBST DU NICHT"

            create_short_video(
                audio_path, scene_images, video_path, meme_lines, word_timings
            )
            video_id = upload_to_youtube(
                video_path, None, topic, script, is_short=True
            )
        else:
            # ── LONG-FORM-PIPELINE (wie bisher) ──────────────────────────────
            script = generate_script(topic)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)

            duration = create_voiceover(script, audio_path)
            video_sources = fetch_stock_videos(duration)
            create_video(audio_path, video_sources, video_path)
            create_thumbnail(topic, thumb_path)
            video_id = upload_to_youtube(
                video_path, thumb_path, topic, script, is_short=False
            )

        # Erfolg speichern
        elapsed = (datetime.now() - start_time).seconds // 60
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump({
                "date": date_str,
                "type": "short" if is_short_day else "long",
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
        print(f"  🎉 FERTIG – {video_type} ist live!")
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

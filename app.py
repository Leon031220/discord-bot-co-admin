import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Select, Modal, TextInput
import random
import os
import asyncio
import datetime
import yt_dlp as youtube_dl
import aiohttp
import json
from dotenv import load_dotenv

# ========== FLASK WEBSERVER (mit Admin Panel) ==========
from flask import Flask, render_template, request, jsonify
from threading import Thread

flask_app = Flask(__name__)

activity_log = []


def add_log(msg):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    activity_log.append(f"[{now}] {msg}")
    if len(activity_log) > 100:
        activity_log.pop(0)


# HTML Seiten
@flask_app.route("/")
def index():
    return render_template("index.html")


@flask_app.route("/admin")
def admin_panel_web():
    return render_template("admin.html")


# API Endpoints (für Admin Panel)
@flask_app.route("/api/spawn_admin_machine", methods=["POST"])
def api_spawn_admin_machine():
    result = generate_admin_machine()
    embed = create_admin_machine_embed(result)
    channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
    if channel:
        asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
    return jsonify({"status": "success", "brainrot": result["brainrot"]})


@flask_app.route("/api/preview_machine", methods=["POST"])
def api_preview_machine():
    result = generate_admin_machine()
    return jsonify(
        {
            "status": "success",
            "brainrot": result["brainrot"],
            "event": result["event"],
            "boost": result["boost"],
            "traits": result["traits"],
        }
    )


@flask_app.route("/api/get_brainrots", methods=["GET"])
def api_get_brainrots():
    return jsonify({"brainrots": [{"name": n, "rate": r} for n, r in _brainrots]})


@flask_app.route("/api/add_brainrot", methods=["POST"])
def api_add_brainrot():
    data = request.json
    name = data.get("name")
    rate = data.get("rate")
    if name and rate:
        _brainrots.append((name, float(rate)))
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Missing data"})


@flask_app.route("/api/remove_brainrot", methods=["POST"])
def api_remove_brainrot():
    global _brainrots
    name = request.json.get("name")
    for i, (n, r) in enumerate(_brainrots):
        if n == name:
            _brainrots.pop(i)
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Nicht gefunden"})


@flask_app.route("/api/bot_status", methods=["GET"])
def api_bot_status():
    # Prüft, ob latency unendlich oder NaN ist
    import math

    latency = bot.latency
    if math.isinf(latency) or math.isnan(latency):
        display_latency = 0
    else:
        display_latency = round(latency * 1000)

    return jsonify(
        {
            "status": "online",
            "latency": display_latency,
            "guilds": len(bot.guilds),
            "commands": len(bot.tree.get_commands()),
        }
    )


@flask_app.route("/api/set_spawn_times", methods=["POST"])
def api_set_spawn_times():
    global TARGET_HOURS
    try:
        hours_str = request.json.get("hours", "")
        TARGET_HOURS = sorted(
            list(
                set(
                    [
                        int(h.strip())
                        for h in hours_str.split(",")
                        if h.strip().isdigit() and 0 <= int(h.strip()) <= 23
                    ]
                )
            )
        )
        return jsonify({"status": "success", "hours": TARGET_HOURS})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/set_channel", methods=["POST"])
def api_set_channel():
    global ADMIN_MACHINE_CHANNEL_ID
    try:
        ADMIN_MACHINE_CHANNEL_ID = int(request.json.get("channel_id"))
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/post_update", methods=["POST"])
def api_post_update():
    data = request.json
    version = data.get("version")
    text = data.get("text")
    image_url = data.get("image_url", "")
    if not version or not text:
        return jsonify({"status": "error", "message": "Version und Text fehlen"})
    channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
    if not channel:
        return jsonify({"status": "error", "message": "Channel nicht gefunden"})
    embed = discord.Embed(
        title=f"🚀 **UPDATE v{version}** 🚀",
        description=text,
        color=discord.Color.green(),
    )
    if image_url:
        embed.set_image(url=image_url)
    asyncio.run_coroutine_threadsafe(channel.send("@everyone", embed=embed), bot.loop)
    return jsonify({"status": "success"})


@flask_app.route("/api/music_skip", methods=["POST"])
def api_music_skip():
    for guild in bot.guilds:
        vc = guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Kein Song aktiv"})


@flask_app.route("/api/music_stop", methods=["POST"])
def api_music_stop():
    for guild in bot.guilds:
        vc = guild.voice_client
        if vc:
            queues.pop(guild.id, None)
            current_songs.pop(guild.id, None)
            vc.stop()
            asyncio.run_coroutine_threadsafe(vc.disconnect(), bot.loop)
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Kein Bot im Voice-Channel"})


@flask_app.route("/api/current_song", methods=["GET"])
def api_current_song():
    for guild in bot.guilds:
        if guild.id in current_songs:
            song = current_songs[guild.id]
            return jsonify(
                {
                    "title": song.title,
                    "requester": str(song.requester) if song.requester else None,
                }
            )
    return jsonify({"title": None})


@flask_app.route("/api/next_spawn", methods=["GET"])
def api_next_spawn():
    now = datetime.datetime.now()
    future = sorted(
        [h for h in TARGET_HOURS if h > now.hour]
        + [h + 24 for h in TARGET_HOURS if h <= now.hour]
    )
    if future:
        next_h = future[0] % 24
        next_day = "morgen " if future[0] >= 24 else ""
        return jsonify(
            {"next_spawn": f"{next_day}{next_h:02d}:00 Uhr", "hours": TARGET_HOURS}
        )
    return jsonify({"next_spawn": "unbekannt", "hours": TARGET_HOURS})


@flask_app.route("/api/start_event", methods=["POST"])
def api_start_event():
    global event_cycle_task
    data = request.json
    duration = data.get("duration", 60)
    interval = data.get("interval", 10)
    if event_cycle_task and not event_cycle_task.done():
        return jsonify({"status": "error", "message": "Event läuft bereits"})
    channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
    if not channel:
        return jsonify({"status": "error", "message": "Channel nicht gefunden"})
    event_cycle_task = asyncio.run_coroutine_threadsafe(
        run_event_cycle(channel, duration, interval), bot.loop
    )
    add_log(f"Event gestartet ({duration}min, alle {interval}min)")
    return jsonify({"status": "success"})


@flask_app.route("/api/stop_event", methods=["POST"])
def api_stop_event():
    global event_cycle_task
    if event_cycle_task and not event_cycle_task.done():
        event_cycle_task.cancel()
        add_log("Event gestoppt")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Kein Event aktiv"})


@flask_app.route("/api/event_status", methods=["GET"])
def api_event_status():
    running = bool(event_cycle_task and not event_cycle_task.done())
    return jsonify({"running": running})


@flask_app.route("/api/get_traits", methods=["GET"])
def api_get_traits():
    return jsonify(
        {"traits": [{"name": n, "mult": m, "rate": r} for n, m, r in _traits]}
    )


@flask_app.route("/api/add_trait", methods=["POST"])
def api_add_trait():
    data = request.json
    name, mult, rate = data.get("name"), data.get("mult"), data.get("rate")
    if name and mult and rate:
        _traits.append((name, float(mult), float(rate)))
        add_log(f"Trait hinzugefügt: {name}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Fehlende Daten"})


@flask_app.route("/api/remove_trait", methods=["POST"])
def api_remove_trait():
    name = request.json.get("name")
    for i, (n, m, r) in enumerate(_traits):
        if n == name:
            _traits.pop(i)
            add_log(f"Trait entfernt: {name}")
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Nicht gefunden"})


@flask_app.route("/api/get_events_list", methods=["GET"])
def api_get_events_list():
    return jsonify({"events": [{"name": n, "rate": r} for n, r in _events]})


@flask_app.route("/api/add_event_item", methods=["POST"])
def api_add_event_item():
    data = request.json
    name, rate = data.get("name"), data.get("rate")
    if name and rate:
        _events.append((name, float(rate)))
        add_log(f"Event-Typ hinzugefügt: {name}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Fehlende Daten"})


@flask_app.route("/api/remove_event_item", methods=["POST"])
def api_remove_event_item():
    name = request.json.get("name")
    for i, (n, r) in enumerate(_events):
        if n == name:
            _events.pop(i)
            add_log(f"Event-Typ entfernt: {name}")
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Nicht gefunden"})


@flask_app.route("/api/get_boosts", methods=["GET"])
def api_get_boosts():
    return jsonify({"boosts": [{"name": n, "rate": r} for n, r in _boosts]})


@flask_app.route("/api/add_boost", methods=["POST"])
def api_add_boost():
    data = request.json
    name, rate = data.get("name"), data.get("rate")
    if name and rate:
        _boosts.append((name, float(rate)))
        add_log(f"Boost hinzugefügt: {name}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Fehlende Daten"})


@flask_app.route("/api/remove_boost", methods=["POST"])
def api_remove_boost():
    name = request.json.get("name")
    for i, (n, r) in enumerate(_boosts):
        if n == name:
            _boosts.pop(i)
            add_log(f"Boost entfernt: {name}")
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Nicht gefunden"})


@flask_app.route("/api/get_queue", methods=["GET"])
def api_get_queue():
    queue_data = []
    for guild in bot.guilds:
        if guild.id in queues:
            for s in queues[guild.id]:
                queue_data.append(
                    {
                        "title": s.title,
                        "requester": str(s.requester) if s.requester else "?",
                    }
                )
    return jsonify({"queue": queue_data})


@flask_app.route("/api/set_volume", methods=["POST"])
def api_set_volume():
    level = request.json.get("level", 50)
    for guild in bot.guilds:
        vc = guild.voice_client
        if vc and vc.source:
            vc.source.volume = max(0, min(200, int(level))) / 100
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Kein Song aktiv"})


@flask_app.route("/api/activity_log", methods=["GET"])
def api_activity_log():
    return jsonify({"log": list(reversed(activity_log[-50:]))})


@flask_app.route("/api/get_servers", methods=["GET"])
def api_get_servers():
    servers = [
        {"name": g.name, "members": g.member_count, "id": str(g.id)} for g in bot.guilds
    ]
    return jsonify({"servers": servers})


@flask_app.route("/api/get_members", methods=["GET"])
def api_get_members():
    guild_id = request.args.get("guild_id")
    members = []
    for g in bot.guilds:
        if not guild_id or str(g.id) == guild_id:
            for m in g.members:
                members.append(
                    {
                        "id": str(m.id),
                        "name": m.display_name,
                        "discriminator": str(m.discriminator),
                        "bot": m.bot,
                        "avatar": str(m.display_avatar.url) if m.display_avatar else "",
                        "roles": [r.name for r in m.roles if r.name != "@everyone"],
                    }
                )
    return jsonify({"members": members})


@flask_app.route("/api/send_dm", methods=["POST"])
def api_send_dm():
    user_id = int(request.json.get("user_id", 0))
    content = request.json.get("content", "").strip()
    if not content:
        return jsonify({"status": "error", "message": "Leere Nachricht"})

    async def send():
        user = bot.get_user(user_id)
        if not user:
            user = await bot.fetch_user(user_id)
        await user.send(content)

    try:
        asyncio.run_coroutine_threadsafe(send(), bot.loop).result(timeout=5)
        add_log(f"DM gesendet an {user_id}")
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/delete_message", methods=["POST"])
def api_delete_message():
    channel_id = int(request.json.get("channel_id", 0))
    message_id = int(request.json.get("message_id", 0))

    async def delete():
        ch = bot.get_channel(channel_id)
        msg = await ch.fetch_message(message_id)
        await msg.delete()

    try:
        asyncio.run_coroutine_threadsafe(delete(), bot.loop).result(timeout=5)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/add_reaction", methods=["POST"])
def api_add_reaction():
    channel_id = int(request.json.get("channel_id", 0))
    message_id = int(request.json.get("message_id", 0))
    emoji = request.json.get("emoji", "👍")

    async def react():
        ch = bot.get_channel(channel_id)
        msg = await ch.fetch_message(message_id)
        await msg.add_reaction(emoji)

    try:
        asyncio.run_coroutine_threadsafe(react(), bot.loop).result(timeout=5)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/pin_message", methods=["POST"])
def api_pin_message():
    channel_id = int(request.json.get("channel_id", 0))
    message_id = int(request.json.get("message_id", 0))

    async def pin():
        ch = bot.get_channel(channel_id)
        msg = await ch.fetch_message(message_id)
        await msg.pin()

    try:
        asyncio.run_coroutine_threadsafe(pin(), bot.loop).result(timeout=5)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/send_embed", methods=["POST"])
def api_send_embed():
    data = request.json
    channel_id = int(data.get("channel_id", 0))
    title = data.get("title", "")
    description = data.get("description", "")
    color_name = data.get("color", "blue")
    image_url = data.get("image_url", "")
    footer = data.get("footer", "")
    color_map = {
        "blue": discord.Color.blue(),
        "green": discord.Color.green(),
        "red": discord.Color.red(),
        "gold": discord.Color.gold(),
        "purple": discord.Color.purple(),
        "orange": discord.Color.orange(),
    }
    color = color_map.get(color_name, discord.Color.blue())
    channel = bot.get_channel(channel_id)
    if not channel:
        return jsonify({"status": "error", "message": "Channel nicht gefunden"})

    async def send():
        embed = discord.Embed(title=title, description=description, color=color)
        if image_url:
            embed.set_image(url=image_url)
        if footer:
            embed.set_footer(text=footer)
        await channel.send(embed=embed)

    try:
        asyncio.run_coroutine_threadsafe(send(), bot.loop).result(timeout=5)
        add_log(f"Embed gesendet in #{channel.name}")
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/get_discord_events", methods=["GET"])
def api_get_discord_events():
    events = []

    async def fetch():
        for g in bot.guilds:
            for ev in await g.fetch_scheduled_events():
                events.append(
                    {
                        "id": str(ev.id),
                        "name": ev.name,
                        "guild": g.name,
                        "start": ev.start_time.strftime("%d.%m %H:%M")
                        if ev.start_time
                        else "?",
                        "description": ev.description or "",
                        "status": str(ev.status),
                    }
                )

    try:
        asyncio.run_coroutine_threadsafe(fetch(), bot.loop).result(timeout=8)
    except Exception as e:
        pass
    return jsonify({"events": events})


@flask_app.route("/api/create_discord_event", methods=["POST"])
def api_create_discord_event():
    data = request.json
    guild_id = int(data.get("guild_id", 0))
    name = data.get("name", "")
    description = data.get("description", "")
    start_str = data.get("start", "")
    location = data.get("location", "Discord")
    if not name or not start_str:
        return jsonify(
            {"status": "error", "message": "Name und Startzeit erforderlich"}
        )

    async def create():
        guild = bot.get_guild(guild_id) or bot.guilds[0]
        start_time = datetime.datetime.fromisoformat(start_str).astimezone(
            datetime.timezone.utc
        )
        end_time = start_time + datetime.timedelta(hours=1)
        await guild.create_scheduled_event(
            name=name,
            description=description,
            start_time=start_time,
            end_time=end_time,
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only,
            location=location,
        )

    try:
        asyncio.run_coroutine_threadsafe(create(), bot.loop).result(timeout=8)
        add_log(f"Discord Event erstellt: {name}")
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/delete_discord_event", methods=["POST"])
def api_delete_discord_event():
    event_id = int(request.json.get("event_id", 0))

    async def delete():
        for g in bot.guilds:
            for ev in await g.fetch_scheduled_events():
                if ev.id == event_id:
                    await ev.delete()
                    return

    try:
        asyncio.run_coroutine_threadsafe(delete(), bot.loop).result(timeout=8)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@flask_app.route("/api/clear_messages", methods=["POST"])
def api_clear_messages():
    channel_id = int(request.json.get("channel_id", 0))
    amount = min(int(request.json.get("amount", 5)), 100)

    async def clear():
        ch = bot.get_channel(channel_id)
        deleted = await ch.purge(limit=amount)
        return len(deleted)

    try:
        count = asyncio.run_coroutine_threadsafe(clear(), bot.loop).result(timeout=10)
        add_log(f"{count} Nachrichten gelöscht in Channel {channel_id}")
        return jsonify({"status": "success", "deleted": count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ========== DISCORD CHAT ENDPOINTS ==========
message_cache = {}  # channel_id -> list of message dicts


@flask_app.route("/api/get_channels", methods=["GET"])
def api_get_channels():
    result = []
    for guild in bot.guilds:
        channels = []
        for ch in guild.channels:
            if isinstance(ch, discord.TextChannel):
                channels.append({"id": str(ch.id), "name": ch.name, "type": "text"})
            elif isinstance(ch, discord.VoiceChannel):
                channels.append(
                    {
                        "id": str(ch.id),
                        "name": ch.name,
                        "type": "voice",
                        "members": [m.name for m in ch.members],
                    }
                )
        result.append(
            {"guild": guild.name, "guild_id": str(guild.id), "channels": channels}
        )
    return jsonify({"servers": result})


@flask_app.route("/api/get_messages", methods=["GET"])
def api_get_messages():
    channel_id = request.args.get("channel_id")
    if not channel_id:
        return jsonify({"messages": []})
    msgs = message_cache.get(int(channel_id), [])
    return jsonify({"messages": msgs[-50:]})


@flask_app.route("/api/fetch_messages", methods=["POST"])
def api_fetch_messages():
    channel_id = int(request.json.get("channel_id", 0))
    channel = bot.get_channel(channel_id)
    if not channel:
        return jsonify({"status": "error", "message": "Channel nicht gefunden"})

    async def fetch():
        msgs = []
        async for m in channel.history(limit=30):
            msgs.append(
                {
                    "id": str(m.id),
                    "author": m.author.display_name,
                    "avatar": str(m.author.display_avatar.url)
                    if m.author.display_avatar
                    else "",
                    "content": m.content,
                    "time": m.created_at.strftime("%H:%M"),
                    "bot": m.author.bot,
                }
            )
        message_cache[channel_id] = list(reversed(msgs))

    future = asyncio.run_coroutine_threadsafe(fetch(), bot.loop)
    future.result(timeout=8)
    return jsonify({"status": "success", "messages": message_cache.get(channel_id, [])})


@flask_app.route("/api/send_message", methods=["POST"])
def api_send_message():
    channel_id = int(request.json.get("channel_id", 0))
    content = request.json.get("content", "").strip()
    if not content:
        return jsonify({"status": "error", "message": "Leere Nachricht"})
    channel = bot.get_channel(channel_id)
    if not channel:
        return jsonify({"status": "error", "message": "Channel nicht gefunden"})

    async def send():
        await channel.send(content)

    asyncio.run_coroutine_threadsafe(send(), bot.loop).result(timeout=5)
    add_log(f"Nachricht gesendet in #{channel.name}: {content[:40]}")
    return jsonify({"status": "success"})


@flask_app.route("/api/play_web", methods=["POST"])
def api_play_web():
    search = request.json.get("search", "").strip()
    channel_id = request.json.get("voice_channel_id")
    if not search:
        return jsonify({"status": "error", "message": "Kein Suchbegriff"})

    async def play():
        vc_channel = bot.get_channel(int(channel_id)) if channel_id else None
        if not vc_channel:
            for guild in bot.guilds:
                for ch in guild.voice_channels:
                    if ch.members:
                        vc_channel = ch
                        break
        if not vc_channel:
            raise Exception("Kein Voice-Channel gefunden (niemand ist drin)")
        guild = vc_channel.guild
        voice_client = guild.voice_client
        if not voice_client:
            voice_client = await vc_channel.connect()
        query = search if search.startswith("http") else f"ytsearch:{search}"
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        if voice_client.is_playing():
            queues.setdefault(guild.id, []).append(player)
            return f"Queue: {player.title}"
        else:
            current_songs[guild.id] = player
            voice_client.play(
                player, after=lambda e: check_queue(guild.id, voice_client)
            )
            return f"Spielt: {player.title}"

    try:
        result = asyncio.run_coroutine_threadsafe(play(), bot.loop).result(timeout=20)
        add_log(f"Web-Play: {search}")
        return jsonify({"status": "success", "message": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


def run_flask():
    """Startet Flask im Hintergrund"""
    flask_app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


def start_webserver():
    """Startet Flask in einem separaten Thread"""
    thread = Thread(target=run_flask)
    thread.daemon = True
    thread.start()
    print("✅ Flask Webserver gestartet auf Port 8080")


# ========== GOOGLE / GEMINI IMPORTS ==========
try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ Google Generative AI nicht installiert.")

load_dotenv()

# ========== GEMINI AI SETUP (MIT FUNKTIONIERENDEM MODELL) ==========
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_ENGINE_ID = os.getenv("GOOGLE_ENGINE_ID")

if GOOGLE_API_KEY and GEMINI_AVAILABLE:
    genai.configure(api_key=GOOGLE_API_KEY)
    # Verwende das aktuell verfügbare Modell
    try:
        ai_model = genai.GenerativeModel("gemini-2.0-flash")
        print("✅ Gemini AI (2.0 Flash) ist bereit!")
    except Exception as e:
        try:
            ai_model = genai.GenerativeModel("gemini-1.5-flash")
            print("✅ Gemini AI (1.5 Flash) ist bereit!")
        except:
            ai_model = None
            print("❌ Kein Gemini-Modell verfügbar!")
else:
    ai_model = None
    print("⚠️ Kein Google API Key - KI-Funktionen deaktiviert")

# Konversationsverlauf pro User
conversation_history = {}

# ========== YOUTUBE OPTIONS ==========
youtube_dl.utils.bug_reports_message = lambda *args, **kwargs: ""

ytdl_format_options = {
    "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "noprogress": True,
    "extractor_retries": 3,
    "js_runtimes": {
        "nodejs": {
            "path": "/nix/store/1lagpgadaybvs1n2312gysg2phjk89y8-nodejs-20.20.0-wrapped/bin/node"
        }
    },
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    },
}

ffmpeg_options = {
    "options": "-vn -loglevel quiet",
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, requester=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("webpage_url") or data.get("url")
        self.requester = requester

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True, requester=None):
        import traceback

        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(url, download=not stream)
            )
            if data is None:
                raise Exception(
                    "Keine Daten von YouTube erhalten (möglicherweise altersbeschränkt oder nicht verfügbar)"
                )
            if "entries" in data:
                data = data["entries"][0]
            if data is None:
                raise Exception("Kein Suchergebnis gefunden")
            filename = data["url"] if stream else ytdl.prepare_filename(data)
            audio = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
            return cls(audio, data=data, requester=requester, volume=0.5)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"YTDL Error: {type(e).__name__}: {e}\n{tb}")
            raise Exception(f"{type(e).__name__}: {e}") from e


# ========== ADMIN MACHINE DATA ==========
_brainrots = [
    ("67", 10),
    ("Los Esok Sekolitos", 10),
    ("Coccoblade", 8),
    ("Chicleteira Bicicleteira", 7),
    ("Chop Chop Chop Sahur", 6),
    ("Dilly Pickle", 6),
    ("Ketupat Kepat Prekupat", 6),
    ("Coccobladina", 5),
    ("Catino Timeno", 5),
    ("Dul Dul Dul", 5),
    ("Rang Rang Kelerang", 5),
    ("W or L", 4),
    ("Nooo my Gold", 4),
    ("Krr Krr Kataking", 4),
    ("Aquanaut", 3),
    ("Moonnaut", 3),
    ("McPenne Dougal", 3),
    ("Bau Wang Wolf Monarca", 2),
    ("La Esok Sekolah", 2),
    ("Pitiata Baem", 1),
    ("Flyini Fishini", 1),
]

_events = [
    ("Lucky Rot", 12),
    ("Galaxy", 9),
    ("Cyber", 10),
    ("Divine", 9),
    ("Rainbow", 10),
    ("Neon", 10),
]

_boosts = [
    ("2x Luck", 20),
    ("BoxRot", 25),
    ("Llama Rot", 30),
    ("4x Luck", 15),
    ("10x Luck", 10),
]

_trait_counts = [(2, 27), (3, 39), (4, 16.8), (5, 7.2)]

_traits = [
    ("Lightning", 1.5, 15),
    ("Frozen", 2, 12.5),
    ("Fireworks", 2, 10),
    ("Cupid", 1.5, 8),
    ("Wave", 2, 7),
    ("Glitch", 2, 6),
    ("Pumpkin", 3, 5),
    ("Bunny", 3.5, 5.5),
    ("Skibidi", 4, 5.25),
    ("St. Patrick", 3, 4.5),
    ("Fire", 3.25, 4),
    ("Cyber", 3, 4),
    ("Astroid", 2.75, 3),
    ("Carps", 3, 3),
    ("Neon", 2.75, 2),
    ("Harp", 4.75, 1),
]


def random_choice_weighted(items):
    total = sum(weight for _, weight in items)
    r = random.uniform(0, total)
    cumulative = 0
    for item, weight in items:
        cumulative += weight
        if r < cumulative:
            return item
    return items[0][0]


def generate_admin_machine():
    brainrot = random_choice_weighted(_brainrots)
    event = random_choice_weighted(_events)
    boost = random_choice_weighted(_boosts)
    trait_count = random_choice_weighted(_trait_counts)
    selected = random.sample(_traits, min(trait_count, len(_traits)))
    traits = [(name, mult) for name, mult, _ in selected]
    return {"brainrot": brainrot, "event": event, "boost": boost, "traits": traits}


# ========== OPUS LADEN ==========
if not discord.opus.is_loaded():
    try:
        discord.opus.load_opus("libopus.so.0")
        print("✅ Opus geladen!")
    except Exception:
        try:
            discord.opus.load_opus("libopus.so")
            print("✅ Opus geladen!")
        except Exception as e:
            print(f"⚠️ Opus konnte nicht geladen werden: {e}")

# ========== BOT SETUP ==========
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)

queues = {}
current_songs = {}
event_cycle_task = None

# ⚠️ DEINE IDs HIER EINTRAGEN!
ADMIN_IDS = [1419366554516193483]
ADMIN_MACHINE_CHANNEL_ID = 1503366868155633736

TARGET_HOURS = [0, 6, 12, 18]


def is_admin(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.id in ADMIN_IDS
        or interaction.user.guild_permissions.administrator
    )


# ========== ADMIN MACHINE SCHEDULER (alle 6 Stunden) ==========
@tasks.loop(hours=6)
async def admin_machine_scheduler():
    channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
    if channel:
        result = generate_admin_machine()
        embed = create_admin_machine_embed(result)
        await channel.send(embed=embed)
        print(f"✅ Admin Machine gespawnt: {result['brainrot']}")


@admin_machine_scheduler.before_loop
async def before_scheduler():
    await bot.wait_until_ready()
    print("✅ Scheduler gestartet! (alle 6 Stunden)")


def create_admin_machine_embed(result):
    traits_text = "\n".join(
        [f"• **{name}** → `{mult}×`" for name, mult in result["traits"]]
    )
    return discord.Embed(
        title="🎰 **ADMIN MACHINE 24/7** 🎰",
        description=f"**🧠 Brainrot:** `{result['brainrot']}`\n**🎉 Event:** `{result['event']}`\n**⚡ Boost:** `{result['boost']}`\n\n**🎲 Traits ({len(result['traits'])} aktiv):**\n{traits_text}",
        color=discord.Color.purple(),
    )


# ========== UI COMPONENTS ==========


class AddBrainrotModal(Modal, title="Brainrot hinzufügen"):
    name = TextInput(label="Name", placeholder="z.B. Crystal Elephant", required=True)
    rate = TextInput(label="Rate (%)", placeholder="z.B. 5", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rate = float(self.rate.value)
            _brainrots.append((self.name.value, rate))
            await interaction.response.send_message(
                f"✅ `{self.name.value}` mit {rate}% hinzugefügt!", ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Ungültige Rate!", ephemeral=True
            )


class RemoveBrainrotSelect(View):
    def __init__(self):
        super().__init__(timeout=60)
        select = Select(placeholder="Wähle ein Brainrot zum Entfernen...")
        for name, rate in _brainrots[:25]:
            select.add_option(label=f"{name} ({rate}%)", value=name)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        global _brainrots
        name = interaction.data["values"][0]
        for i, (n, r) in enumerate(_brainrots):
            if n == name:
                _brainrots.pop(i)
                await interaction.response.send_message(
                    f"✅ `{name}` entfernt!", ephemeral=True
                )
                return
        await interaction.response.send_message("❌ Nicht gefunden!", ephemeral=True)


class SetTimesView(View):
    def __init__(self):
        super().__init__(timeout=60)
        times = ["0,6,12,18", "2,8,14,20", "4,10,16,22", "Benutzerdefiniert"]
        select = Select(
            placeholder="Wähle Spawn-Zeiten...",
            options=[discord.SelectOption(label=t) for t in times],
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        global TARGET_HOURS, next_spawn_time
        choice = interaction.data["values"][0]
        if choice == "Benutzerdefiniert":
            await interaction.response.send_message(
                "❌ Nutze `/set_machine_times 0,6,12,18`", ephemeral=True
            )
            return
        TARGET_HOURS = [int(h) for h in choice.split(",")]
        next_spawn_time = None
        await interaction.response.send_message(
            f"✅ Zeiten auf {choice} Uhr gesetzt!", ephemeral=True
        )


class AdminPanelView(View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(
        label="➕ Brainrot hinzufügen", style=discord.ButtonStyle.green, row=0
    )
    async def add_brainrot_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(AddBrainrotModal())

    @discord.ui.button(
        label="➖ Brainrot entfernen", style=discord.ButtonStyle.red, row=0
    )
    async def remove_brainrot_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "**Wähle ein Brainrot zum Entfernen:**",
            view=RemoveBrainrotSelect(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="📋 Raten anzeigen", style=discord.ButtonStyle.blurple, row=0
    )
    async def show_rates_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        text = "\n".join(
            [
                f"• `{n}`: {r}%"
                for n, r in sorted(_brainrots, key=lambda x: x[1], reverse=True)[:15]
            ]
        )
        embed = discord.Embed(
            title="📊 Top 15 Brainrots",
            description=text or "Keine",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="⚙️ Zeiten ändern", style=discord.ButtonStyle.blurple, row=1
    )
    async def set_times_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "**Wähle Spawn-Zeiten:**", view=SetTimesView(), ephemeral=True
        )

    @discord.ui.button(label="🚀 Update posten", style=discord.ButtonStyle.green, row=1)
    async def post_update_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        modal = UpdateModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="🎰 Manueller Spawn", style=discord.ButtonStyle.blurple, row=1
    )
    async def manual_spawn_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        result = generate_admin_machine()
        embed = create_admin_machine_embed(result)
        await interaction.response.send_message(
            "🔄 **Neue Admin Machine:**", embed=embed
        )

    @discord.ui.button(label="📡 Event starten", style=discord.ButtonStyle.red, row=2)
    async def start_event_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "❌ Nutze `/start_event_cycle` für Events", ephemeral=True
        )

    @discord.ui.button(
        label="🔄 Channel setzen", style=discord.ButtonStyle.blurple, row=2
    )
    async def set_channel_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "❌ Nutze `/set_channel [ID]`", ephemeral=True
        )


class UpdateModal(Modal, title="Update posten"):
    text = TextInput(
        label="Update Text", style=discord.TextStyle.paragraph, required=True
    )
    version = TextInput(label="Version", placeholder="z.B. 1.0.0", required=True)
    image_url = TextInput(label="Bild-URL (optional)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title=f"🚀 **UPDATE v{self.version.value}** 🚀",
                description=self.text.value,
                color=discord.Color.green(),
            )
            if self.image_url.value:
                embed.set_image(url=self.image_url.value)
            await channel.send("@everyone", embed=embed)
            await interaction.response.send_message(
                "✅ Update gepostet!", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Channel nicht gefunden!", ephemeral=True
            )


# ========== GOOGLE SEARCH FUNCTION ==========
async def google_search(query: str) -> str:
    """Führt eine Google-Suche durch"""
    if not GOOGLE_ENGINE_ID or not GOOGLE_API_KEY:
        return "❌ Google Search nicht konfiguriert! (GOOGLE_API_KEY oder GOOGLE_ENGINE_ID fehlt)"

    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_API_KEY, "cx": GOOGLE_ENGINE_ID, "q": query, "num": 3}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return f"❌ API-Fehler: Status {resp.status}"
                data = await resp.json()

                if "items" not in data:
                    return f"❌ Keine Ergebnisse gefunden für: {query}"

                results = []
                for i, item in enumerate(data["items"][:3], 1):
                    title = item.get("title", "Kein Titel")
                    link = item.get("link", "#")
                    snippet = item.get("snippet", "Keine Beschreibung")
                    results.append(f"**{i}. {title}**\n{snippet}\n<{link}>")

                return "\n\n".join(results)
    except Exception as e:
        return f"❌ Fehler bei der Suche: {str(e)}"


# ========== AI CHAT FUNCTION ==========
async def ai_chat(user_id: int, message: str) -> str:
    """Unterhält sich mit dem Benutzer"""
    if not ai_model:
        return "❌ KI nicht verfügbar (kein API Key oder Modell nicht geladen)"

    global conversation_history

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    history = conversation_history[user_id]
    history.append(f"User: {message}")

    if len(history) > 10:
        history = history[-10:]

    context = "\n".join(history)
    prompt = f"""Du bist ein freundlicher Discord-Bot namens Co-Admin. Du hilfst bei einem Spiel namens "Steal the Brainrot".
Hier ist die bisherige Konversation:
{context}

Antworte kurz und hilfreich auf die letzte Nachricht: {message}"""

    try:
        response = ai_model.generate_content(prompt)
        reply = response.text

        history.append(f"Bot: {reply}")
        conversation_history[user_id] = history[-10:]

        return reply
    except Exception as e:
        return f"❌ KI-Fehler: {str(e)}"


def reset_chat_history(user_id: int):
    if user_id in conversation_history:
        del conversation_history[user_id]


# ========== COMMANDS ==========


@bot.tree.command(
    name="admin_panel", description="[ADMIN] Öffnet das Admin Control Panel mit UI"
)
async def admin_panel(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ Keine Berechtigung!", ephemeral=True
        )
        return
    embed = discord.Embed(
        title="🛠️ **Admin Control Panel**",
        description="Verwalte deinen Bot mit diesen Buttons:",
        color=discord.Color.dark_gold(),
    )
    embed.set_footer(text="Co-Admin Bot • Steal the Brainrot")
    await interaction.response.send_message(
        embed=embed, view=AdminPanelView(), ephemeral=True
    )


@bot.tree.command(name="google", description="Sucht bei Google")
@app_commands.describe(query="Was möchtest du suchen?")
async def google_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    result = await google_search(query)
    await interaction.followup.send(result[:2000])


@bot.tree.command(name="ask", description="Frag die KI etwas")
@app_commands.describe(question="Deine Frage an die KI")
async def ask_cmd(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    answer = await ai_chat(interaction.user.id, question)
    await interaction.followup.send(answer[:2000])


@bot.tree.command(name="reset_chat", description="Setzt den KI-Chat-Verlauf zurück")
async def reset_chat(interaction: discord.Interaction):
    await interaction.response.defer()
    reset_chat_history(interaction.user.id)
    await interaction.followup.send(
        "✅ Dein Chat-Verlauf wurde zurückgesetzt!", ephemeral=True
    )


@bot.tree.command(name="analyze", description="Analysiert ein Bild mit KI")
@app_commands.describe(bild="Das Bild, das analysiert werden soll")
async def analyze_image(interaction: discord.Interaction, bild: discord.Attachment):
    await interaction.response.defer()

    if not ai_model:
        await interaction.followup.send("❌ KI nicht verfügbar!")
        return

    try:
        img_data = await bild.read()
        response = ai_model.generate_content(
            [
                "Beschreibe dieses Bild kurz und präzise.",
                {"mime_type": "image/jpeg", "data": img_data},
            ]
        )
        await interaction.followup.send(response.text[:2000])
    except Exception as e:
        await interaction.followup.send(f"❌ Fehler: {str(e)}")


@bot.tree.command(name="play", description="Spielt Musik von YouTube")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    if not interaction.user.voice:
        await interaction.followup.send("❌ Du musst in einem Voice-Channel sein!")
        return
    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client
    if not voice_client:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)
    if not (search.startswith("http://") or search.startswith("https://")):
        search = f"ytsearch:{search}"
    try:
        player = await YTDLSource.from_url(
            search, loop=bot.loop, stream=True, requester=interaction.user
        )
        if interaction.guild.id not in queues:
            queues[interaction.guild.id] = []
        if not voice_client.is_playing():
            current_songs[interaction.guild.id] = player
            voice_client.play(
                player, after=lambda e: check_queue(interaction.guild.id, voice_client)
            )
            embed = discord.Embed(
                title="🎵 **Jetzt spielt** 🎵",
                description=f"[{player.title}]({player.url})",
                color=discord.Color.green(),
            )
            if player.requester:
                embed.add_field(
                    name="Angefragt von", value=player.requester.mention, inline=True
                )
            await interaction.followup.send(embed=embed)
        else:
            queues[interaction.guild.id].append(player)
            await interaction.followup.send(
                f"➕ **Zur Queue hinzugefügt:** {player.title}"
            )
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        print(f"[PLAY ERROR] {type(e).__name__}: {repr(str(e))}\n{tb}")
        msg = str(e) or repr(e) or type(e).__name__
        await interaction.followup.send(f"❌ Fehler: `{msg}`")


def check_queue(guild_id, voice_client):
    if guild_id in current_songs:
        current_songs.pop(guild_id, None)
    if guild_id in queues and queues[guild_id]:
        player = queues[guild_id].pop(0)
        current_songs[guild_id] = player
        voice_client.play(player, after=lambda e: check_queue(guild_id, voice_client))


@bot.tree.command(name="skip", description="Überspringt den Song")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("⏭️ Song übersprungen!")
    else:
        await interaction.response.send_message("❌ Nichts spielt!")


@bot.tree.command(name="stop", description="Stoppt Musik")
async def stop(interaction: discord.Interaction):
    await interaction.response.defer()
    vc = interaction.guild.voice_client
    guild_id = interaction.guild.id
    if guild_id in queues:
        queues[guild_id] = []
    if guild_id in current_songs:
        current_songs.pop(guild_id, None)
    if vc:
        vc.stop()
        await vc.disconnect()
        await interaction.followup.send("⏹️ Musik gestoppt!")
    else:
        await interaction.followup.send("❌ Bot nicht im Voice-Channel!")


@bot.tree.command(name="queue", description="Zeigt die Warteschlange")
async def queue(interaction: discord.Interaction):
    if interaction.guild.id in queues and queues[interaction.guild.id]:
        qlist = queues[interaction.guild.id]
        text = "\n".join([f"{i + 1}. {s.title}" for i, s in enumerate(qlist[:10])])
        await interaction.response.send_message(f"**📋 Queue:**\n{text}")
    else:
        await interaction.response.send_message("📭 Queue ist leer!")


@bot.tree.command(name="pause", description="Pausiert Musik")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Pausiert!")
    else:
        await interaction.response.send_message("❌ Nichts spielt!")


@bot.tree.command(name="resume", description="Setzt Musik fort")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Fortgesetzt!")
    else:
        await interaction.response.send_message("❌ Nichts ist pausiert!")


@bot.tree.command(name="volume", description="Lautstärke (0-200)")
async def volume(interaction: discord.Interaction, level: int):
    vc = interaction.guild.voice_client
    if vc and vc.source:
        level = max(0, min(200, level))
        vc.source.volume = level / 100
        await interaction.response.send_message(f"🔊 Lautstärke: {level}%")
    else:
        await interaction.response.send_message("❌ Nichts spielt!")


@bot.tree.command(name="adminmachine", description="Zeigt eine zufällige Admin Machine")
async def adminmachine(interaction: discord.Interaction):
    result = generate_admin_machine()
    embed = create_admin_machine_embed(result)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ping", description="Checkt den Bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! `{round(bot.latency * 1000)}ms`")


@bot.tree.command(name="set_machine_times", description="[ADMIN] Ändert Spawn-Stunden")
async def set_machine_times(interaction: discord.Interaction, stunden: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    global TARGET_HOURS, next_spawn_time
    try:
        neue_zeiten = [
            int(h.strip()) for h in stunden.split(",") if 0 <= int(h.strip()) <= 23
        ]
        TARGET_HOURS = sorted(list(set(neue_zeiten)))
        next_spawn_time = None
        await interaction.response.send_message(
            f"✅ Zeiten: {', '.join(map(str, TARGET_HOURS))} Uhr"
        )
    except:
        await interaction.response.send_message(
            "❌ Ungültiges Format! Beispiel: 0,6,12,18"
        )


@bot.tree.command(name="set_channel", description="[ADMIN] Setzt den Channel")
async def set_channel(interaction: discord.Interaction, channel_id: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    global ADMIN_MACHINE_CHANNEL_ID
    try:
        ADMIN_MACHINE_CHANNEL_ID = int(channel_id)
        await interaction.response.send_message(f"✅ Channel gesetzt!")
    except ValueError:
        await interaction.response.send_message("❌ Ungültige ID!")


@bot.tree.command(name="release_update", description="[ADMIN] Postet Update")
async def release_update(
    interaction: discord.Interaction, text: str, version: str, image_url: str = None
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title=f"🚀 **UPDATE v{version}** 🚀",
            description=text,
            color=discord.Color.green(),
        )
        if image_url:
            embed.set_image(url=image_url)
        await channel.send("@everyone", embed=embed)
        await interaction.response.send_message("✅ Update gepostet!", ephemeral=True)
    else:
        await interaction.response.send_message(
            "❌ Channel nicht gefunden!", ephemeral=True
        )


@bot.tree.command(name="start_event_cycle", description="[ADMIN] Startet Kette-Event")
async def start_event_cycle(
    interaction: discord.Interaction, dauer_minuten: int, intervall_minuten: int
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    global event_cycle_task
    if event_cycle_task and not event_cycle_task.done():
        await interaction.response.send_message("❌ Event läuft bereits!")
        return
    channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message("❌ Channel nicht gefunden!")
        return
    event_cycle_task = bot.loop.create_task(
        run_event_cycle(channel, dauer_minuten, intervall_minuten)
    )
    await interaction.response.send_message("✅ Event gestartet!")


async def run_event_cycle(channel, total_duration_minutes, interval_minutes):
    end_time = datetime.datetime.now() + datetime.timedelta(
        minutes=total_duration_minutes
    )
    while datetime.datetime.now() < end_time:
        result = generate_admin_machine()
        embed = create_admin_machine_embed(result)
        embed.title = "💥 **EVENT SPAWN** 💥"
        embed.color = discord.Color.gold()
        await channel.send(embed=embed)
        await asyncio.sleep(interval_minutes * 60)
    await channel.send(
        embed=discord.Embed(title="🏁 EVENT BEENDET", color=discord.Color.blue())
    )


# ========== MODERATION COMMANDS ==========
@bot.tree.command(name="warn", description="Verwarnt einen User")
@app_commands.describe(user="Der User", grund="Grund der Verwarnung")
async def warn(
    interaction: discord.Interaction,
    user: discord.Member,
    grund: str = "Kein Grund angegeben",
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    embed = discord.Embed(title="⚠️ Verwarnung", color=discord.Color.yellow())
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Grund", value=grund)
    embed.add_field(name="Von", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed)
    try:
        await user.send(
            f"⚠️ Du wurdest auf **{interaction.guild.name}** verwarnt.\n**Grund:** {grund}"
        )
    except:
        pass


@bot.tree.command(name="kick", description="Kickt einen User")
@app_commands.describe(user="Der User", grund="Grund")
async def kick(
    interaction: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    try:
        await user.send(
            f"👢 Du wurdest von **{interaction.guild.name}** gekickt.\n**Grund:** {grund}"
        )
    except:
        pass
    await user.kick(reason=grund)
    await interaction.response.send_message(
        f"👢 **{user.display_name}** wurde gekickt. Grund: {grund}"
    )


@bot.tree.command(name="ban", description="Bannt einen User")
@app_commands.describe(user="Der User", grund="Grund")
async def ban(
    interaction: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    try:
        await user.send(
            f"🔨 Du wurdest von **{interaction.guild.name}** gebannt.\n**Grund:** {grund}"
        )
    except:
        pass
    await user.ban(reason=grund)
    await interaction.response.send_message(
        f"🔨 **{user.display_name}** wurde gebannt. Grund: {grund}"
    )


@bot.tree.command(name="timeout", description="Gibt einem User einen Timeout")
@app_commands.describe(user="Der User", minuten="Dauer in Minuten", grund="Grund")
async def timeout_user(
    interaction: discord.Interaction,
    user: discord.Member,
    minuten: int = 10,
    grund: str = "Kein Grund",
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    duration = datetime.timedelta(minutes=minuten)
    await user.timeout(duration, reason=grund)
    await interaction.response.send_message(
        f"🔇 **{user.display_name}** wurde für {minuten} Minuten getimeoutet. Grund: {grund}"
    )


@bot.tree.command(name="clear", description="Löscht Nachrichten")
@app_commands.describe(anzahl="Anzahl der Nachrichten (max 100)")
async def clear(interaction: discord.Interaction, anzahl: int = 10):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=min(anzahl, 100))
    await interaction.followup.send(
        f"🗑️ {len(deleted)} Nachrichten gelöscht!", ephemeral=True
    )


@bot.tree.command(name="userinfo", description="Infos über einen User")
@app_commands.describe(user="Der User")
async def userinfo(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    embed = discord.Embed(title=f"👤 {user.display_name}", color=user.color)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="ID", value=user.id)
    embed.add_field(name="Account erstellt", value=user.created_at.strftime("%d.%m.%Y"))
    embed.add_field(
        name="Beigetreten",
        value=user.joined_at.strftime("%d.%m.%Y") if user.joined_at else "?",
    )
    embed.add_field(
        name="Rollen", value=", ".join([r.mention for r in user.roles[1:]]) or "Keine"
    )
    embed.add_field(name="Bot", value="Ja" if user.bot else "Nein")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="Infos über den Server")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"🏠 {g.name}", color=discord.Color.blurple())
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Owner", value=g.owner.mention if g.owner else "?")
    embed.add_field(name="Mitglieder", value=g.member_count)
    embed.add_field(name="Channels", value=len(g.channels))
    embed.add_field(name="Rollen", value=len(g.roles))
    embed.add_field(name="Erstellt am", value=g.created_at.strftime("%d.%m.%Y"))
    embed.add_field(name="Boosts", value=g.premium_subscription_count)
    await interaction.response.send_message(embed=embed)


# ========== FUN COMMANDS ==========
@bot.tree.command(name="poll", description="Erstellt eine Umfrage")
@app_commands.describe(
    frage="Die Frage",
    option1="Option 1",
    option2="Option 2",
    option3="Option 3 (optional)",
    option4="Option 4 (optional)",
)
async def poll(
    interaction: discord.Interaction,
    frage: str,
    option1: str,
    option2: str,
    option3: str = None,
    option4: str = None,
):
    options = [o for o in [option1, option2, option3, option4] if o]
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    desc = "\n".join([f"{emojis[i]} {opt}" for i, opt in enumerate(options)])
    embed = discord.Embed(
        title=f"📊 {frage}", description=desc, color=discord.Color.blue()
    )
    embed.set_footer(text=f"Umfrage von {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    for i in range(len(options)):
        await msg.add_reaction(emojis[i])


@bot.tree.command(name="8ball", description="Frag die magische 8-Kugel")
@app_commands.describe(frage="Deine Frage")
async def eightball(interaction: discord.Interaction, frage: str):
    answers = [
        "Ja!",
        "Definitiv!",
        "Sicher!",
        "Sehr wahrscheinlich.",
        "Eher ja.",
        "Schwer zu sagen.",
        "Frag später nochmal.",
        "Kann sein.",
        "Eher nicht.",
        "Nein.",
        "Definitiv nicht!",
        "Vergiss es.",
    ]
    embed = discord.Embed(
        title="🎱 Magische 8-Kugel", color=discord.Color.dark_purple()
    )
    embed.add_field(name="Frage", value=frage, inline=False)
    embed.add_field(name="Antwort", value=random.choice(answers), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="roll", description="Würfelt einen Würfel")
@app_commands.describe(seiten="Anzahl der Seiten (Standard: 6)")
async def roll(interaction: discord.Interaction, seiten: int = 6):
    result = random.randint(1, max(2, seiten))
    await interaction.response.send_message(
        f"🎲 Du hast eine **{result}** gewürfelt! (W{seiten})"
    )


@bot.tree.command(name="coin", description="Wirft eine Münze")
async def coin(interaction: discord.Interaction):
    result = random.choice(["Kopf 👑", "Zahl 🔢"])
    await interaction.response.send_message(f"🪙 **{result}**!")


@bot.tree.command(name="giveaway", description="Startet ein Giveaway")
@app_commands.describe(preis="Was wird verlost?", dauer="Dauer in Minuten")
async def giveaway(interaction: discord.Interaction, preis: str, dauer: int = 60):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    end_time = datetime.datetime.now() + datetime.timedelta(minutes=dauer)
    embed = discord.Embed(title="🎉 GIVEAWAY 🎉", color=discord.Color.gold())
    embed.add_field(name="Preis", value=preis)
    embed.add_field(name="Endet um", value=end_time.strftime("%H:%M Uhr"))
    embed.add_field(name="Teilnehmen", value="Reagiere mit 🎉")
    embed.set_footer(text=f"Gestartet von {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("🎉")

    async def end_giveaway():
        await asyncio.sleep(dauer * 60)
        updated = await interaction.channel.fetch_message(msg.id)
        reaction = discord.utils.get(updated.reactions, emoji="🎉")
        if reaction and reaction.count > 1:
            users = [u async for u in reaction.users() if not u.bot]
            winner = random.choice(users) if users else None
            if winner:
                await interaction.channel.send(
                    f"🎉 Glückwunsch {winner.mention}! Du hast **{preis}** gewonnen!"
                )
            else:
                await interaction.channel.send("❌ Keine Teilnehmer für das Giveaway.")
        else:
            await interaction.channel.send("❌ Keine Teilnehmer für das Giveaway.")

    bot.loop.create_task(end_giveaway())


@bot.tree.command(name="announce", description="Sendet eine Ankündigung")
@app_commands.describe(nachricht="Die Ankündigung", channel="Ziel-Channel (optional)")
async def announce(
    interaction: discord.Interaction,
    nachricht: str,
    channel: discord.TextChannel = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    target = channel or interaction.channel
    embed = discord.Embed(
        title="📢 Ankündigung", description=nachricht, color=discord.Color.orange()
    )
    embed.set_footer(text=f"Von {interaction.user.display_name}")
    await target.send("@everyone", embed=embed)
    await interaction.response.send_message(
        f"✅ Ankündigung in {target.mention} gesendet!", ephemeral=True
    )


@bot.tree.command(name="embed", description="Sendet ein Embed")
@app_commands.describe(
    titel="Titel", inhalt="Inhalt", farbe="Farbe (blue/green/red/gold/purple)"
)
async def send_embed_cmd(
    interaction: discord.Interaction, titel: str, inhalt: str, farbe: str = "blue"
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    color_map = {
        "blue": discord.Color.blue(),
        "green": discord.Color.green(),
        "red": discord.Color.red(),
        "gold": discord.Color.gold(),
        "purple": discord.Color.purple(),
    }
    embed = discord.Embed(
        title=titel,
        description=inhalt,
        color=color_map.get(farbe, discord.Color.blue()),
    )
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Embed gesendet!", ephemeral=True)


@bot.tree.command(name="help_bot", description="Alle Befehle")
async def help_bot(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Co-Admin Bot – Alle Commands", color=discord.Color.gold()
    )
    embed.add_field(
        name="🛡️ Moderation",
        value="`/warn` `/kick` `/ban` `/timeout` `/clear`",
        inline=False,
    )
    embed.add_field(
        name="ℹ️ Info", value="`/userinfo` `/serverinfo` `/ping`", inline=False
    )
    embed.add_field(
        name="🎉 Fun",
        value="`/poll` `/8ball` `/roll` `/coin` `/giveaway` `/announce` `/embed`",
        inline=False,
    )
    embed.add_field(
        name="🛠️ Admin",
        value="`/admin_panel` `/set_machine_times` `/set_channel` `/release_update` `/start_event_cycle`",
        inline=False,
    )
    embed.add_field(
        name="🎰 Admin Machine",
        value="`/adminmachine` `/reload_machine` `/show_rates` `/add_brainrot` `/remove_brainrot`",
        inline=False,
    )
    embed.add_field(
        name="🤖 KI & Suche",
        value="`/google` `/ask` `/reset_chat` `/analyze`",
        inline=False,
    )
    embed.add_field(
        name="🎵 Musik",
        value="`/play` `/skip` `/stop` `/queue` `/pause` `/resume` `/volume`",
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="show_rates", description="[ADMIN] Zeigt Raten")
async def show_rates(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    text = "\n".join(
        [
            f"• `{n}`: {r}%"
            for n, r in sorted(_brainrots, key=lambda x: x[1], reverse=True)[:15]
        ]
    )
    embed = discord.Embed(
        title="📊 Top 15 Brainrots", description=text, color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="reload_machine", description="[ADMIN] Erzwingt Spawn")
async def reload_machine(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    result = generate_admin_machine()
    embed = create_admin_machine_embed(result)
    await interaction.response.send_message("🔄 Neue Admin Machine:", embed=embed)


@bot.tree.command(name="add_brainrot", description="[ADMIN] Fügt Brainrot hinzu")
async def add_brainrot(interaction: discord.Interaction, name: str, rate: float):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    _brainrots.append((name, rate))
    await interaction.response.send_message(
        f"✅ `{name}` mit {rate}% hinzugefügt!", ephemeral=True
    )


@bot.tree.command(name="remove_brainrot", description="[ADMIN] Entfernt Brainrot")
async def remove_brainrot(interaction: discord.Interaction, name: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Keine Rechte!", ephemeral=True)
        return
    global _brainrots
    for i, (n, r) in enumerate(_brainrots):
        if n.lower() == name.lower():
            _brainrots.pop(i)
            await interaction.response.send_message(
                f"✅ `{name}` entfernt!", ephemeral=True
            )
            return
    await interaction.response.send_message("❌ Nicht gefunden!", ephemeral=True)


# ========== BOT START ==========
start_webserver()


@bot.event
async def on_ready():
    print(f"✅ Bot {bot.user} ist online!")
    admin_machine_scheduler.start()
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Commands synchronisiert")
    except Exception as e:
        print(f"❌ Sync-Fehler: {e}")


@bot.event
async def on_message(message):
    ch_id = message.channel.id
    if ch_id not in message_cache:
        message_cache[ch_id] = []
    message_cache[ch_id].append(
        {
            "id": str(message.id),
            "author": message.author.display_name,
            "avatar": str(message.author.display_avatar.url)
            if message.author.display_avatar
            else "",
            "content": message.content,
            "time": message.created_at.strftime("%H:%M"),
            "bot": message.author.bot,
        }
    )
    if len(message_cache[ch_id]) > 100:
        message_cache[ch_id] = message_cache[ch_id][-100:]
    await bot.process_commands(message)


def run():
    flask_app.run(host="0.0.0.0", port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()


if __name__ == "__main__":
    keep_alive()  # Startet den Webserver
    token = os.getenv("DISCORD_TOKEN")
    bot.run(token)  # Startet den Bot

import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import random
import os
import asyncio
import datetime
import yt_dlp as youtube_dl
import aiohttp
from dotenv import load_dotenv

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_ENGINE_ID = os.getenv("GOOGLE_ENGINE_ID")

if GOOGLE_API_KEY and GEMINI_AVAILABLE:
    genai.configure(api_key=GOOGLE_API_KEY)
    try:
        ai_model = genai.GenerativeModel('gemini-2.0-flash')
    except:
        try:
            ai_model = genai.GenerativeModel('gemini-1.5-flash')
        except:
            ai_model = None
else:
    ai_model = None

conversation_history = {}

youtube_dl.utils.bug_reports_message = lambda *args, **kwargs: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'noprogress': True,
    'socket_timeout': 30,
    'extractor_args': {'youtube': {'skip': ['dash', 'hls']}},
}
ffmpeg_options = {
    'options': '-vn -loglevel quiet',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, requester=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url') or data.get('url')
        self.requester = requester

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True, requester=None):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            if 'entries' in data:
                data = data['entries'][0]
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            audio = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
            return cls(audio, data=data, requester=requester, volume=0.5)
        except Exception as e:
            print(f"YTDL Error: {e}")
            raise e

_brainrots = [
    ("67", 10), ("Los Esok Sekolitos", 10), ("Coccoblade", 8),
    ("Chicleteira Bicicleteira", 7), ("Chop Chop Chop Sahur", 6),
    ("Dilly Pickle", 6), ("Ketupat Kepat Prekupat", 6),
    ("Coccobladina", 5), ("Catino Timeno", 5), ("Dul Dul Dul", 5),
    ("Rang Rang Kelerang", 5), ("W or L", 4), ("Nooo my Gold", 4),
    ("Krr Krr Kataking", 4), ("Aquanaut", 3), ("Moonnaut", 3),
    ("McPenne Dougal", 3), ("Bau Wang Wolf Monarca", 2),
    ("La Esok Sekolah", 2), ("Pitiata Baem", 1), ("Flyini Fishini", 1),
]
_events = [
    ("Lucky Rot", 12), ("Galaxy", 9), ("Cyber", 10),
    ("Divine", 9), ("Rainbow", 10), ("Neon", 10),
]
_boosts = [
    ("2x Luck", 20), ("BoxRot", 25), ("Llama Rot", 30),
    ("4x Luck", 15), ("10x Luck", 10),
]
_trait_counts = [(2, 27), (3, 39), (4, 16.8), (5, 7.2)]
_traits = [
    ("Lightning", 1.5, 15), ("Frozen", 2, 12.5), ("Fireworks", 2, 10),
    ("Cupid", 1.5, 8), ("Wave", 2, 7), ("Glitch", 2, 6),
    ("Pumpkin", 3, 5), ("Bunny", 3.5, 5.5), ("Skibidi", 4, 5.25),
    ("St. Patrick", 3, 4.5), ("Fire", 3.25, 4), ("Cyber", 3, 4),
    ("Astroid", 2.75, 3), ("Carps", 3, 3), ("Neon", 2.75, 2),
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

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)
queues = {}
current_songs = {}

ADMIN_IDS = [1419366554516193483]
ADMIN_MACHINE_CHANNEL_ID = 1503366868155633736
TARGET_HOURS = [0, 6, 12, 18]
next_spawn_time = None
last_triggered_hour = -1

def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.administrator

@tasks.loop(minutes=1)
async def admin_machine_scheduler():
    global next_spawn_time, last_triggered_hour
    now = datetime.datetime.now()
    current_hour = now.hour
    current_minute = now.minute
    
    if current_hour in TARGET_HOURS and last_triggered_hour != current_hour:
        if next_spawn_time is None:
            random_minute = random.randint(0, 20)
            next_spawn_time = random_minute
        if current_minute >= next_spawn_time:
            channel = bot.get_channel(ADMIN_MACHINE_CHANNEL_ID)
            if channel:
                result = generate_admin_machine()
                embed = create_admin_machine_embed(result)
                await channel.send(embed=embed)
            last_triggered_hour = current_hour
            next_spawn_time = None
    
    if current_hour not in TARGET_HOURS:
        last_triggered_hour = -1
        next_spawn_time = None

@admin_machine_scheduler.before_loop
async def before_scheduler():
    await bot.wait_until_ready()
    print("✅ Scheduler gestartet!")

def create_admin_machine_embed(result):
    traits_text = "\n".join([f"• **{name}** → `{mult}×`" for name, mult in result["traits"]])
    return discord.Embed(
        title="🎰 **ADMIN MACHINE 24/7** 🎰",
        description=f"**🧠 Brainrot:** `{result['brainrot']}`\n**🎉 Event:** `{result['event']}`\n**⚡ Boost:** `{result['boost']}`\n\n**🎲 Traits ({len(result['traits'])} aktiv):**\n{traits_text}",
        color=discord.Color.purple()
    )

async def google_search(query: str) -> str:
    if not GOOGLE_ENGINE_ID or not GOOGLE_API_KEY:
        return "❌ Google Search nicht konfiguriert!"
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_API_KEY,
        'cx': GOOGLE_ENGINE_ID,
        'q': query,
        'num': 3
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return f"❌ API-Fehler: Status {resp.status}"
                data = await resp.json()
                
                if 'items' not in data:
                    return f"❌ Keine Ergebnisse gefunden für: {query}"
                
                results = []
                for i, item in enumerate(data['items'][:3], 1):
                    title = item.get('title', 'Kein Titel')
                    link = item.get('link', '#')
                    snippet = item.get('snippet', 'Keine Beschreibung')
                    results.append(f"**{i}. {title}**\n{snippet}\n<{link}>")
                
                return "\n\n".join(results)
    except Exception as e:
        return f"❌ Fehler bei der Suche: {str(e)}"

async def ai_chat(user_id: int, message: str) -> str:
    if not ai_model:
        return "❌ KI nicht verfügbar"
    
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

class AdminPanelView(ui.View):
    def __init__(self):
        super().__init__()
    
    @ui.button(label="Channel ID", style=discord.ButtonStyle.primary)
    async def channel_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"📍 Admin Machine Channel ID: `{ADMIN_MACHINE_CHANNEL_ID}`", ephemeral=True)
    
    @ui.button(label="Target Hours", style=discord.ButtonStyle.primary)
    async def hours_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"⏰ Target Hours: `{TARGET_HOURS}`", ephemeral=True)
    
    @ui.button(label="Bot Status", style=discord.ButtonStyle.success)
    async def status_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"✅ Bot ist online! Latenz: `{round(interaction.client.latency * 1000)}ms`", ephemeral=True)

@bot.tree.command(name="ping", description="Checkt den Bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! `{round(bot.latency * 1000)}ms`")

@bot.tree.command(name="adminmachine", description="Zeigt eine zufällige Admin Machine")
async def adminmachine(interaction: discord.Interaction):
    result = generate_admin_machine()
    embed = create_admin_machine_embed(result)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="admin_panel", description="Admin Panel für Bot-Einstellungen")
async def admin_panel(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Du hast keine Berechtigung!", ephemeral=True)
        return
    
    embed = discord.Embed(title="⚙️ Admin Panel", description="Verwalte die Bot-Einstellungen", color=discord.Color.red())
    embed.add_field(name="📍 Channel ID", value=f"`{ADMIN_MACHINE_CHANNEL_ID}`", inline=False)
    embed.add_field(name="⏰ Target Hours", value=f"`{TARGET_HOURS}`", inline=False)
    embed.add_field(name="✅ Status", value="Bot läuft", inline=False)
    
    await interaction.response.send_message(embed=embed, view=AdminPanelView())

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
    await interaction.followup.send("✅ Dein Chat-Verlauf wurde zurückgesetzt!", ephemeral=True)

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
        player = await YTDLSource.from_url(search, loop=bot.loop, stream=True, requester=interaction.user)
        if interaction.guild.id not in queues:
            queues[interaction.guild.id] = []
        if not voice_client.is_playing():
            current_songs[interaction.guild.id] = player
            voice_client.play(player, after=lambda e: check_queue(interaction.guild.id, voice_client))
            embed = discord.Embed(title="🎵 **Jetzt spielt** 🎵", description=f"[{player.title}]({player.url})", color=discord.Color.green())
            if player.requester:
                embed.add_field(name="Angefragt von", value=player.requester.mention, inline=True)
            await interaction.followup.send(embed=embed)
        else:
            queues[interaction.guild.id].append(player)
            await interaction.followup.send(f"➕ **Zur Queue hinzugefügt:** {player.title}")
    except Exception as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "bot" in error_msg.lower():
            await interaction.followup.send("❌ YouTube blockiert den Bot momentan. Versuche es später nochmal!")
        else:
            await interaction.followup.send(f"❌ Fehler: {error_msg[:100]}")

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
        text = "\n".join([f"{i+1}. {s.title}" for i, s in enumerate(qlist[:10])])
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

@bot.tree.command(name="help_bot", description="Alle Befehle")
async def help_bot(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Co-Admin Bot", color=discord.Color.gold())
    embed.add_field(name="🎰 Admin Machine", value="`/adminmachine` - Zufällige Machine", inline=False)
    embed.add_field(name="⚙️ Admin", value="`/admin_panel` - Bot-Einstellungen", inline=False)
    embed.add_field(name="🤖 KI & Suche", value="`/google <frage>` - Google Suche\n`/ask <frage>` - KI Chat\n`/reset_chat` - Chat-Verlauf löschen", inline=False)
    embed.add_field(name="🎵 Musik", value="`/play`\n`/skip`\n`/stop`\n`/queue`\n`/pause`\n`/resume`\n`/volume`", inline=False)
    embed.add_field(name="i️ Info", value="`/ping`\n`/help_bot`", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Bot {bot.user} ist online!")
    admin_machine_scheduler.start()
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Commands synchronisiert")
    except Exception as e:
        print(f"❌ Sync-Fehler: {e}")

TOKEN = os.getenv("DISCORD_TOKEN")
if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN fehlt!")
    else:
        bot.run(TOKEN)

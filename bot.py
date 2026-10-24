import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import asyncio
import random
import os
import io
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from dotenv import load_dotenv
from datetime import datetime, timedelta
import traceback

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# ── INTENTS ─────────────────────────────────────────────
intents = discord.Intents.all()

bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)
bot.game_prefix = "AT"

DB = "bot.db"

# ── ANTINUKE TRACKING ────────────────────────────────────
antinuke_actions = {}   # guild_id -> {user_id: [timestamps]}
ANTINUKE_THRESHOLD = 3
ANTINUKE_WINDOW = 10    # seconds

raid_join_log = {}      # guild_id -> [timestamps]
RAID_THRESHOLD = 10
RAID_WINDOW = 8

spam_log = {}           # guild_id -> {user_id: [timestamps]}
SPAM_THRESHOLD = 6
SPAM_WINDOW = 5

# ── DB SETUP ─────────────────────────────────────────────
async def db_setup():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS levels (
                guild_id INTEGER, user_id INTEGER,
                xp INTEGER DEFAULT 0, level INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS welcome (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                message TEXT DEFAULT 'Welcome {user} to {server}!',
                banner_url TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leaver (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                message TEXT DEFAULT 'Goodbye {user}!',
                banner_url TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS triggers (
                guild_id INTEGER, trigger TEXT,
                response TEXT,
                PRIMARY KEY (guild_id, trigger)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS antinuke (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS antilink (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS antispam (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS antiraid (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                guild_id INTEGER PRIMARY KEY,
                category_id INTEGER,
                support_role_id INTEGER,
                log_channel_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER, user_id INTEGER,
                reason TEXT, moderator_id INTEGER,
                timestamp TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS economy (
                guild_id INTEGER, user_id INTEGER,
                coins INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER, key TEXT, value TEXT,
                PRIMARY KEY (guild_id, key)
            )
        """)
        await db.commit()

# ── HELPERS ──────────────────────────────────────────────
def success_embed(title, desc):
    e = discord.Embed(title=f"✅ {title}", description=desc, color=0x57F287)
    e.timestamp = datetime.utcnow()
    return e

def error_embed(title, desc):
    e = discord.Embed(title=f"❌ {title}", description=desc, color=0xED4245)
    e.timestamp = datetime.utcnow()
    return e

def info_embed(title, desc):
    e = discord.Embed(title=f"ℹ️ {title}", description=desc, color=0x5865F2)
    e.timestamp = datetime.utcnow()
    return e

async def get_coins(guild_id, user_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT coins FROM economy WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def set_coins(guild_id, user_id, amount):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO economy (guild_id, user_id, coins) VALUES (?,?,?)",
            (guild_id, user_id, max(0, amount))
        )
        await db.commit()

async def add_coins(guild_id, user_id, amount):
    current = await get_coins(guild_id, user_id)
    await set_coins(guild_id, user_id, current + amount)

# ── WELCOME CARD ─────────────────────────────────────────
async def make_welcome_card(member, banner_url=None):
    W, H = 800, 300
    img = Image.new("RGBA", (W, H), (15, 15, 25, 255))
    draw = ImageDraw.Draw(img)

    # gradient bg
    for y in range(H):
        r = int(15 + (40 - 15) * y / H)
        g = int(15 + (20 - 15) * y / H)
        b = int(25 + (60 - 25) * y / H)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # banner
    if banner_url:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(banner_url) as resp:
                    if resp.status == 200:
                        banner_data = await resp.read()
                        banner = Image.open(io.BytesIO(banner_data)).convert("RGBA")
                        banner = banner.resize((W, H))
                        banner.putalpha(100)
                        img.paste(banner, (0, 0), banner)
        except:
            pass

    draw = ImageDraw.Draw(img)

    # avatar circle
    try:
        avatar_url = member.display_avatar.replace(size=256).url
        async with aiohttp.ClientSession() as s:
            async with s.get(avatar_url) as resp:
                av_data = await resp.read()
        av = Image.open(io.BytesIO(av_data)).convert("RGBA").resize((130, 130))
        mask = Image.new("L", (130, 130), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 130, 130), fill=255)
        av_pos = (50, H // 2 - 65)
        # ring
        ring = Image.new("RGBA", (138, 138), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((0, 0, 137, 137), fill=(88, 101, 242, 255))
        img.paste(ring, (av_pos[0] - 4, av_pos[1] - 4), ring)
        img.paste(av, av_pos, mask)
    except:
        pass

    # text
    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_mid = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        font_sm  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except:
        font_big = font_mid = font_sm = ImageFont.load_default()

    tx = 210
    draw.text((tx, 80), "WELCOME", font=font_sm, fill=(150, 150, 255, 200))
    draw.text((tx, 110), member.display_name[:20], font=font_big, fill=(255, 255, 255, 255))
    draw.text((tx, 158), f"@{str(member)[:30]}", font=font_mid, fill=(180, 180, 255, 200))
    draw.text((tx, 195), f"Member #{member.guild.member_count}", font=font_sm, fill=(130, 130, 200, 180))

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf

# ── ON READY ─────────────────────────────────────────────
@bot.event
async def on_ready():
    await db_setup()
    await bot.change_presence(
        activity=discord.Streaming(
            name="JOIN 60AT",
            url="https://www.twitch.tv/60at"
        )
    )
    try:
        synced = await bot.tree.sync()
        print(f"[60AT] synced {len(synced)} slash commands")
    except Exception as e:
        print(f"sync error: {e}")
    print(f"[60AT] online as {bot.user}")

# ─────────────────────────────────────────────────────────
# SECURITY EVENTS
# ─────────────────────────────────────────────────────────

def track_action(guild_id, user_id):
    now = datetime.utcnow()
    antinuke_actions.setdefault(guild_id, {}).setdefault(user_id, [])
    antinuke_actions[guild_id][user_id] = [
        t for t in antinuke_actions[guild_id][user_id]
        if (now - t).total_seconds() < ANTINUKE_WINDOW
    ]
    antinuke_actions[guild_id][user_id].append(now)
    return len(antinuke_actions[guild_id][user_id])

async def antinuke_punish(guild, user_id, reason):
    member = guild.get_member(user_id)
    if member:
        try:
            await member.ban(reason=f"[AntiNuke] {reason}")
        except:
            pass
    log_ch = None
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT value FROM config WHERE guild_id=? AND key='log_channel'",
            (guild.id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                log_ch = guild.get_channel(int(row[0]))
    if log_ch:
        e = discord.Embed(
            title="🛡️ AntiNuke Triggered",
            description=f"**User:** <@{user_id}>\n**Reason:** {reason}",
            color=0xFF0000
        )
        e.timestamp = datetime.utcnow()
        await log_ch.send(embed=e)

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT enabled FROM antinuke WHERE guild_id=?", (guild.id,)
        ) as cur:
            row = await cur.fetchone()
    if not row or not row[0]:
        return
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        if entry.user.bot:
            return
        count = track_action(guild.id, entry.user.id)
        if count >= ANTINUKE_THRESHOLD:
            await antinuke_punish(guild, entry.user.id, f"Mass channel delete ({count} actions)")

@bot.event
async def on_guild_channel_create(channel):
    guild = channel.guild
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT enabled FROM antinuke WHERE guild_id=?", (guild.id,)
        ) as cur:
            row = await cur.fetchone()
    if not row or not row[0]:
        return
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        if entry.user.bot:
            return
        count = track_action(guild.id, entry.user.id)
        if count >= ANTINUKE_THRESHOLD:
            await antinuke_punish(guild, entry.user.id, f"Mass channel create ({count} actions)")

@bot.event
async def on_member_ban(guild, user):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT enabled FROM antinuke WHERE guild_id=?", (guild.id,)
        ) as cur:
            row = await cur.fetchone()
    if not row or not row[0]:
        return
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.user.bot:
            return
        count = track_action(guild.id, entry.user.id)
        if count >= ANTINUKE_THRESHOLD:
            await antinuke_punish(guild, entry.user.id, f"Mass ban ({count} bans)")

@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT enabled FROM antinuke WHERE guild_id=?", (guild.id,)
        ) as cur:
            row = await cur.fetchone()
    if not row or not row[0]:
        return
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        if entry.user.bot:
            return
        count = track_action(guild.id, entry.user.id)
        if count >= ANTINUKE_THRESHOLD:
            await antinuke_punish(guild, entry.user.id, f"Mass role delete ({count} actions)")

@bot.event
async def on_member_join(member):
    guild = member.guild
    now = datetime.utcnow()

    # anti-raid
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT enabled FROM antiraid WHERE guild_id=?", (guild.id,)
        ) as cur:
            row = await cur.fetchone()
    if row and row[0]:
        raid_join_log.setdefault(guild.id, [])
        raid_join_log[guild.id] = [
            t for t in raid_join_log[guild.id]
            if (now - t).total_seconds() < RAID_WINDOW
        ]
        raid_join_log[guild.id].append(now)
        if len(raid_join_log[guild.id]) >= RAID_THRESHOLD:
            try:
                await member.kick(reason="[AntiRaid] Raid detected")
            except:
                pass
            return

    # welcome
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT channel_id, message, banner_url FROM welcome WHERE guild_id=?",
            (guild.id,)
        ) as cur:
            wrow = await cur.fetchone()

    if wrow:
        ch = guild.get_channel(wrow[0])
        if ch:
            msg = wrow[1].replace("{user}", member.mention).replace("{server}", guild.name)
            banner_url = wrow[2]
            card = await make_welcome_card(member, banner_url)
            e = discord.Embed(description=msg, color=0x5865F2)
            e.timestamp = datetime.utcnow()
            f = discord.File(card, filename="welcome.png")
            e.set_image(url="attachment://welcome.png")
            await ch.send(embed=e, file=f)

@bot.event
async def on_member_remove(member):
    guild = member.guild
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT channel_id, message, banner_url FROM leaver WHERE guild_id=?",
            (guild.id,)
        ) as cur:
            row = await cur.fetchone()
    if row:
        ch = guild.get_channel(row[0])
        if ch:
            msg = row[1].replace("{user}", str(member)).replace("{server}", guild.name)
            card = await make_welcome_card(member, row[2])
            e = discord.Embed(description=msg, color=0xED4245)
            e.timestamp = datetime.utcnow()
            f = discord.File(card, filename="goodbye.png")
            e.set_image(url="attachment://goodbye.png")
            await ch.send(embed=e, file=f)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    guild_id = message.guild.id
    user_id = message.author.id
    content = message.content.lower()

    # anti-link
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT enabled FROM antilink WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    if row and row[0]:
        if not message.author.guild_permissions.manage_messages:
            import re
            if re.search(r"(https?://|discord\.gg/|www\.)", content):
                await message.delete()
                await message.channel.send(
                    embed=error_embed("Anti-Link", f"{message.author.mention} links are not allowed here."),
                    delete_after=4
                )
                return

    # anti-spam
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT enabled FROM antispam WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    if row and row[0]:
        if not message.author.guild_permissions.manage_messages:
            now = datetime.utcnow()
            spam_log.setdefault(guild_id, {}).setdefault(user_id, [])
            spam_log[guild_id][user_id] = [
                t for t in spam_log[guild_id][user_id]
                if (now - t).total_seconds() < SPAM_WINDOW
            ]
            spam_log[guild_id][user_id].append(now)
            if len(spam_log[guild_id][user_id]) >= SPAM_THRESHOLD:
                await message.author.timeout(timedelta(minutes=5), reason="Anti-Spam")
                await message.channel.send(
                    embed=error_embed("Anti-Spam", f"{message.author.mention} muted 5 minutes for spamming."),
                    delete_after=5
                )
                spam_log[guild_id][user_id] = []
                return

    # triggers
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT trigger, response FROM triggers WHERE guild_id=?", (guild_id,)
        ) as cur:
            trows = await cur.fetchall()
    for trig, resp in trows:
        if trig.lower() in content:
            await message.channel.send(resp)
            break

    # XP
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT xp, level FROM levels WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ) as cur:
            lrow = await cur.fetchone()
        xp = (lrow[0] if lrow else 0) + random.randint(5, 15)
        level = lrow[1] if lrow else 0
        needed = 100 * (level + 1)
        if xp >= needed:
            level += 1
            xp = 0
            await message.channel.send(
                embed=discord.Embed(
                    title="⬆️ Level Up!",
                    description=f"{message.author.mention} reached **Level {level}**!",
                    color=0xFFD700
                ).set_thumbnail(url=message.author.display_avatar.url)
            )
        await db.execute(
            "INSERT OR REPLACE INTO levels (guild_id, user_id, xp, level) VALUES (?,?,?,?)",
            (guild_id, user_id, xp, level)
        )
        await db.commit()

    await bot.process_commands(message)

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — SECURITY
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="antinuke", description="Toggle AntiNuke protection")
@app_commands.describe(enabled="Enable or disable")
@app_commands.choices(enabled=[
    app_commands.Choice(name="enable", value=1),
    app_commands.Choice(name="disable", value=0)
])
@app_commands.checks.has_permissions(administrator=True)
async def antinuke_cmd(interaction: discord.Interaction, enabled: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO antinuke (guild_id, enabled) VALUES (?,?)",
            (interaction.guild_id, enabled)
        )
        await db.commit()
    state = "enabled" if enabled else "disabled"
    await interaction.response.send_message(embed=success_embed("AntiNuke", f"AntiNuke {state}."))

@bot.tree.command(name="antiraid", description="Toggle AntiRaid protection")
@app_commands.describe(enabled="Enable or disable")
@app_commands.choices(enabled=[
    app_commands.Choice(name="enable", value=1),
    app_commands.Choice(name="disable", value=0)
])
@app_commands.checks.has_permissions(administrator=True)
async def antiraid_cmd(interaction: discord.Interaction, enabled: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO antiraid (guild_id, enabled) VALUES (?,?)",
            (interaction.guild_id, enabled)
        )
        await db.commit()
    state = "enabled" if enabled else "disabled"
    await interaction.response.send_message(embed=success_embed("AntiRaid", f"AntiRaid {state}."))

@bot.tree.command(name="antispam", description="Toggle AntiSpam protection")
@app_commands.describe(enabled="Enable or disable")
@app_commands.choices(enabled=[
    app_commands.Choice(name="enable", value=1),
    app_commands.Choice(name="disable", value=0)
])
@app_commands.checks.has_permissions(administrator=True)
async def antispam_cmd(interaction: discord.Interaction, enabled: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO antispam (guild_id, enabled) VALUES (?,?)",
            (interaction.guild_id, enabled)
        )
        await db.commit()
    state = "enabled" if enabled else "disabled"
    await interaction.response.send_message(embed=success_embed("AntiSpam", f"AntiSpam {state}."))

@bot.tree.command(name="antilink", description="Toggle AntiLink protection")
@app_commands.describe(enabled="Enable or disable")
@app_commands.choices(enabled=[
    app_commands.Choice(name="enable", value=1),
    app_commands.Choice(name="disable", value=0)
])
@app_commands.checks.has_permissions(administrator=True)
async def antilink_cmd(interaction: discord.Interaction, enabled: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO antilink (guild_id, enabled) VALUES (?,?)",
            (interaction.guild_id, enabled)
        )
        await db.commit()
    state = "enabled" if enabled else "disabled"
    await interaction.response.send_message(embed=success_embed("AntiLink", f"AntiLink {state}."))

@bot.tree.command(name="setlogchannel", description="Set log channel for security events")
@app_commands.describe(channel="Channel to log events")
@app_commands.checks.has_permissions(administrator=True)
async def setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO config (guild_id, key, value) VALUES (?,?,?)",
            (interaction.guild_id, "log_channel", str(channel.id))
        )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Log Channel", f"Log channel set to {channel.mention}."))

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — WELCOME / LEAVER
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="setwelcome", description="Set welcome channel")
@app_commands.describe(channel="Welcome channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setwelcome(interaction: discord.Interaction, channel: discord.TextChannel):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO welcome (guild_id) VALUES (?)", (interaction.guild_id,)
        )
        await db.execute(
            "UPDATE welcome SET channel_id=? WHERE guild_id=?",
            (channel.id, interaction.guild_id)
        )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Welcome", f"Welcome channel set to {channel.mention}."))

@bot.tree.command(name="configwelcome", description="Configure welcome message and banner")
@app_commands.describe(message="Welcome message. Use {user} and {server}", banner="Banner image URL")
@app_commands.checks.has_permissions(manage_guild=True)
async def configwelcome(interaction: discord.Interaction, message: str = None, banner: str = None):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO welcome (guild_id) VALUES (?)", (interaction.guild_id,)
        )
        if message:
            await db.execute(
                "UPDATE welcome SET message=? WHERE guild_id=?", (message, interaction.guild_id)
            )
        if banner:
            await db.execute(
                "UPDATE welcome SET banner_url=? WHERE guild_id=?", (banner, interaction.guild_id)
            )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Welcome Config", "Welcome updated."))

@bot.tree.command(name="setleave", description="Set leave channel")
@app_commands.describe(channel="Leave channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setleave(interaction: discord.Interaction, channel: discord.TextChannel):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO leaver (guild_id) VALUES (?)", (interaction.guild_id,)
        )
        await db.execute(
            "UPDATE leaver SET channel_id=? WHERE guild_id=?",
            (channel.id, interaction.guild_id)
        )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Leave", f"Leave channel set to {channel.mention}."))

@bot.tree.command(name="configleave", description="Configure leave message and banner")
@app_commands.describe(message="Leave message. Use {user} and {server}", banner="Banner image URL")
@app_commands.checks.has_permissions(manage_guild=True)
async def configleave(interaction: discord.Interaction, message: str = None, banner: str = None):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO leaver (guild_id) VALUES (?)", (interaction.guild_id,)
        )
        if message:
            await db.execute(
                "UPDATE leaver SET message=? WHERE guild_id=?", (message, interaction.guild_id)
            )
        if banner:
            await db.execute(
                "UPDATE leaver SET banner_url=? WHERE guild_id=?", (banner, interaction.guild_id)
            )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Leave Config", "Leave updated."))

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — TRIGGERS
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="settrigger", description="Set a trigger-response pair")
@app_commands.describe(trigger="Word/phrase to trigger on", message="Response message")
@app_commands.checks.has_permissions(manage_messages=True)
async def settrigger(interaction: discord.Interaction, trigger: str, message: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO triggers (guild_id, trigger, response) VALUES (?,?,?)",
            (interaction.guild_id, trigger.lower(), message)
        )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Trigger Set", f"Trigger `{trigger}` → `{message}`"))

@bot.tree.command(name="removetrigger", description="Remove a trigger")
@app_commands.describe(trigger="Trigger to remove")
@app_commands.checks.has_permissions(manage_messages=True)
async def removetrigger(interaction: discord.Interaction, trigger: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "DELETE FROM triggers WHERE guild_id=? AND trigger=?",
            (interaction.guild_id, trigger.lower())
        )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Trigger Removed", f"Removed `{trigger}`."))

@bot.tree.command(name="listtriggers", description="List all triggers")
async def listtriggers(interaction: discord.Interaction):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT trigger, response FROM triggers WHERE guild_id=?", (interaction.guild_id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message(embed=info_embed("Triggers", "No triggers set."))
    desc = "\n".join([f"`{t}` → {r}" for t, r in rows])
    await interaction.response.send_message(embed=info_embed("Triggers", desc))

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — MODERATION
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(member="Member to ban", reason="Reason")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    await member.ban(reason=reason)
    await interaction.response.send_message(embed=success_embed("Banned", f"{member.mention} banned.\n**Reason:** {reason}"))

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(member="Member to kick", reason="Reason")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    await member.kick(reason=reason)
    await interaction.response.send_message(embed=success_embed("Kicked", f"{member.mention} kicked.\n**Reason:** {reason}"))

@bot.tree.command(name="mute", description="Timeout a member")
@app_commands.describe(member="Member", minutes="Minutes to mute", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int = 10, reason: str = "No reason"):
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(embed=success_embed("Muted", f"{member.mention} muted {minutes}m.\n**Reason:** {reason}"))

@bot.tree.command(name="unmute", description="Remove timeout from member")
@app_commands.describe(member="Member to unmute")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(embed=success_embed("Unmuted", f"{member.mention} unmuted."))

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Member", reason="Reason")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO warnings (guild_id, user_id, reason, moderator_id, timestamp) VALUES (?,?,?,?,?)",
            (interaction.guild_id, member.id, reason, interaction.user.id, datetime.utcnow().isoformat())
        )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Warned", f"{member.mention} warned.\n**Reason:** {reason}"))

@bot.tree.command(name="warnings", description="View warnings for a member")
@app_commands.describe(member="Member")
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT reason, moderator_id, timestamp FROM warnings WHERE guild_id=? AND user_id=?",
            (interaction.guild_id, member.id)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message(embed=info_embed("Warnings", f"{member.mention} has no warnings."))
    desc = "\n".join([f"**{i+1}.** {r} — by <@{m}> @ {t[:10]}" for i, (r, m, t) in enumerate(rows)])
    e = info_embed(f"Warnings for {member.display_name}", desc)
    e.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member")
@app_commands.describe(member="Member")
@app_commands.checks.has_permissions(manage_messages=True)
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?",
            (interaction.guild_id, member.id)
        )
        await db.commit()
    await interaction.response.send_message(embed=success_embed("Cleared", f"Warnings cleared for {member.mention}."))

@bot.tree.command(name="purge", description="Delete messages in bulk")
@app_commands.describe(amount="Amount of messages to delete (max 100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    amount = min(amount, 100)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(embed=success_embed("Purge", f"Deleted {len(deleted)} messages."), ephemeral=True)

@bot.tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.describe(seconds="Slowmode seconds (0 to disable)")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int):
    await interaction.channel.edit(slowmode_delay=seconds)
    await interaction.response.send_message(embed=success_embed("Slowmode", f"Set to {seconds}s."))

@bot.tree.command(name="lock", description="Lock a channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message(embed=success_embed("Locked", f"{interaction.channel.mention} locked."))

@bot.tree.command(name="unlock", description="Unlock a channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message(embed=success_embed("Unlocked", f"{interaction.channel.mention} unlocked."))

@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_id="User ID to unban")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(embed=success_embed("Unbanned", f"{user.mention} unbanned."))
    except:
        await interaction.response.send_message(embed=error_embed("Error", "User not found or not banned."))

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — LEVELS
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="profile", description="View your or someone's profile")
@app_commands.describe(member="Member (leave empty for yourself)")
async def profile(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT xp, level FROM levels WHERE guild_id=? AND user_id=?",
            (interaction.guild_id, member.id)
        ) as cur:
            row = await cur.fetchone()
    xp = row[0] if row else 0
    level = row[1] if row else 0
    needed = 100 * (level + 1)
    coins = await get_coins(interaction.guild_id, member.id)

    bar_filled = int((xp / needed) * 20)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    e = discord.Embed(color=0x5865F2)
    e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 User", value=member.mention, inline=True)
    e.add_field(name="⭐ Level", value=str(level), inline=True)
    e.add_field(name="✨ XP", value=f"{xp}/{needed}", inline=True)
    e.add_field(name="📊 Progress", value=f"`[{bar}]`", inline=False)
    e.add_field(name="🪙 Coins", value=str(coins), inline=True)
    e.add_field(name="📅 Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
    e.set_footer(text=f"ID: {member.id}")
    e.timestamp = datetime.utcnow()
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="leaderboard", description="View XP leaderboard")
async def leaderboard(interaction: discord.Interaction):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT user_id, xp, level FROM levels WHERE guild_id=? ORDER BY level DESC, xp DESC LIMIT 10",
            (interaction.guild_id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message(embed=info_embed("Leaderboard", "No data yet."))
    medals = ["🥇","🥈","🥉"]
    desc = ""
    for i, (uid, xp, lvl) in enumerate(rows):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        desc += f"{medal} <@{uid}> — Level **{lvl}** ({xp} XP)\n"
    e = discord.Embed(title="🏆 XP Leaderboard", description=desc, color=0xFFD700)
    e.timestamp = datetime.utcnow()
    await interaction.response.send_message(embed=e)

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — TICKETS
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="setupticket", description="Setup ticket system")
@app_commands.describe(
    category="Category for ticket channels",
    support_role="Support role",
    log_channel="Log channel"
)
@app_commands.checks.has_permissions(administrator=True)
async def setupticket(
    interaction: discord.Interaction,
    category: discord.CategoryChannel,
    support_role: discord.Role,
    log_channel: discord.TextChannel
):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tickets (guild_id, category_id, support_role_id, log_channel_id) VALUES (?,?,?,?)",
            (interaction.guild_id, category.id, support_role.id, log_channel.id)
        )
        await db.commit()
    e = success_embed("Ticket Setup", "Ticket system configured.")
    e.add_field(name="Category", value=category.name)
    e.add_field(name="Support Role", value=support_role.mention)
    e.add_field(name="Log Channel", value=log_channel.mention)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="ticket", description="Open a support ticket")
@app_commands.describe(reason="Reason for ticket")
async def ticket(interaction: discord.Interaction, reason: str = "No reason provided"):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT category_id, support_role_id, log_channel_id FROM tickets WHERE guild_id=?",
            (interaction.guild_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message(embed=error_embed("Tickets", "Ticket system not set up."), ephemeral=True)

    category = interaction.guild.get_channel(row[0])
    support_role = interaction.guild.get_role(row[1])
    log_ch = interaction.guild.get_channel(row[2])

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    ch = await interaction.guild.create_text_channel(
        f"ticket-{interaction.user.name}",
        category=category,
        overwrites=overwrites,
        reason=f"Ticket by {interaction.user}"
    )

    e = discord.Embed(
        title="🎫 Ticket Opened",
        description=f"**User:** {interaction.user.mention}\n**Reason:** {reason}\n\nA staff member will assist you shortly.",
        color=0x5865F2
    )
    e.set_thumbnail(url=interaction.user.display_avatar.url)
    e.timestamp = datetime.utcnow()

    close_view = discord.ui.View()
    close_btn = discord.ui.Button(label="Close Ticket", style=discord.ButtonStyle.red, emoji="🔒")

    async def close_cb(btn_interaction: discord.Interaction):
        await btn_interaction.response.send_message("Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        await ch.delete(reason="Ticket closed")
        if log_ch:
            log_e = discord.Embed(
                title="🎫 Ticket Closed",
                description=f"**Ticket:** {ch.name}\n**Closed by:** {btn_interaction.user.mention}",
                color=0xED4245
            )
            log_e.timestamp = datetime.utcnow()
            await log_ch.send(embed=log_e)

    close_btn.callback = close_cb
    close_view.add_item(close_btn)

    await ch.send(embed=e, view=close_view)
    await interaction.response.send_message(embed=success_embed("Ticket", f"Ticket opened: {ch.mention}"), ephemeral=True)

    if log_ch:
        log_e = discord.Embed(
            title="🎫 Ticket Created",
            description=f"**User:** {interaction.user.mention}\n**Channel:** {ch.mention}\n**Reason:** {reason}",
            color=0x57F287
        )
        log_e.timestamp = datetime.utcnow()
        await log_ch.send(embed=log_e)

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — INFO
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="serverinfo", description="View server information")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    e = discord.Embed(title=g.name, color=0x5865F2)
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    if g.banner:
        e.set_image(url=g.banner.url)
    e.add_field(name="👑 Owner", value=f"<@{g.owner_id}>", inline=True)
    e.add_field(name="👥 Members", value=str(g.member_count), inline=True)
    e.add_field(name="💬 Channels", value=str(len(g.channels)), inline=True)
    e.add_field(name="🎭 Roles", value=str(len(g.roles)), inline=True)
    e.add_field(name="😀 Emojis", value=str(len(g.emojis)), inline=True)
    e.add_field(name="📅 Created", value=f"<t:{int(g.created_at.timestamp())}:R>", inline=True)
    e.add_field(name="🔒 Verification", value=str(g.verification_level).title(), inline=True)
    e.add_field(name="🚀 Boosts", value=str(g.premium_subscription_count), inline=True)
    e.set_footer(text=f"ID: {g.id}")
    e.timestamp = datetime.utcnow()
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="userinfo", description="View user information")
@app_commands.describe(member="Member to view")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles = [r.mention for r in member.roles[1:]][:10]
    e = discord.Embed(title=member.display_name, color=member.color)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="🆔 ID", value=str(member.id), inline=True)
    e.add_field(name="🏷️ Tag", value=str(member), inline=True)
    e.add_field(name="🤖 Bot", value=str(member.bot), inline=True)
    e.add_field(name="📅 Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
    e.add_field(name="🗓️ Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
    e.add_field(name="🎭 Top Role", value=member.top_role.mention, inline=True)
    if roles:
        e.add_field(name=f"🔰 Roles ({len(member.roles)-1})", value=" ".join(roles), inline=False)
    e.set_footer(text=f"ID: {member.id}")
    e.timestamp = datetime.utcnow()
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="avatar", description="View someone's avatar")
@app_commands.describe(member="Member")
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    e = discord.Embed(title=f"{member.display_name}'s Avatar", color=0x5865F2)
    e.set_image(url=member.display_avatar.url)
    e.set_footer(text=f"ID: {member.id}")
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    lat = round(bot.latency * 1000)
    e = discord.Embed(title="🏓 Pong!", color=0x57F287)
    e.add_field(name="Latency", value=f"{lat}ms")
    e.add_field(name="Status", value="🟢 Online")
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="botinfo", description="View bot information")
async def botinfo(interaction: discord.Interaction):
    e = discord.Embed(title="60AT Bot", color=0x5865F2)
    e.set_thumbnail(url=bot.user.display_avatar.url)
    e.add_field(name="👥 Servers", value=str(len(bot.guilds)), inline=True)
    e.add_field(name="👤 Users", value=str(len(set(bot.get_all_members()))), inline=True)
    e.add_field(name="📡 Latency", value=f"{round(bot.latency*1000)}ms", inline=True)
    e.add_field(name="🎮 Prefix", value="/  |  AT (games)", inline=True)
    e.add_field(name="🔗 Streaming", value="JOIN 60AT", inline=True)
    e.timestamp = datetime.utcnow()
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="help", description="View all commands")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="📖 60AT Bot Commands", color=0x5865F2)
    e.add_field(name="🛡️ Security", value="`/antinuke` `/antiraid` `/antispam` `/antilink` `/setlogchannel`", inline=False)
    e.add_field(name="🔨 Moderation", value="`/ban` `/kick` `/mute` `/unmute` `/warn` `/warnings` `/clearwarnings` `/purge` `/slowmode` `/lock` `/unlock` `/unban`", inline=False)
    e.add_field(name="👋 Welcome/Leave", value="`/setwelcome` `/configwelcome` `/setleave` `/configleave`", inline=False)
    e.add_field(name="💬 Triggers", value="`/settrigger` `/removetrigger` `/listtriggers`", inline=False)
    e.add_field(name="⭐ Levels", value="`/profile` `/leaderboard`", inline=False)
    e.add_field(name="🎫 Tickets", value="`/setupticket` `/ticket`", inline=False)
    e.add_field(name="ℹ️ Info", value="`/serverinfo` `/userinfo` `/avatar` `/ping` `/botinfo`", inline=False)
    e.add_field(name="🪙 Economy", value="`/balance` `/daily` `/give` `/richlist`", inline=False)
    e.add_field(name="🎰 Games (AT prefix)", value="`ATBLACKJACK` `ATMINES` `ATCOINFLIP` `ATRPS` `ATROLL` `ATSLOTS` `ATCRASH`", inline=False)
    e.add_field(name="🔧 Utility", value="`/embed` `/poll` `/remind` `/rolepersist` `/rolemembers` `/giveaway`", inline=False)
    e.set_footer(text="60AT Bot • Streaming: JOIN 60AT")
    e.timestamp = datetime.utcnow()
    await interaction.response.send_message(embed=e)

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — ECONOMY
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="balance", description="Check your coin balance")
@app_commands.describe(member="Member (leave empty for yourself)")
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    coins = await get_coins(interaction.guild_id, member.id)
    e = discord.Embed(title="🪙 Balance", color=0xFFD700)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="User", value=member.mention)
    e.add_field(name="Coins", value=f"**{coins:,}** 🪙")
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="daily", description="Claim daily coins")
async def daily(interaction: discord.Interaction):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT value FROM config WHERE guild_id=? AND key=?",
            (interaction.guild_id, f"daily_{interaction.user.id}")
        ) as cur:
            row = await cur.fetchone()
    if row:
        last = datetime.fromisoformat(row[0])
        if (datetime.utcnow() - last).total_seconds() < 86400:
            remaining = 86400 - (datetime.utcnow() - last).total_seconds()
            h, m = divmod(int(remaining) // 60, 60)
            return await interaction.response.send_message(
                embed=error_embed("Daily", f"Already claimed! Next in **{h}h {m}m**.")
            )
    amount = random.randint(100, 500)
    await add_coins(interaction.guild_id, interaction.user.id, amount)
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO config (guild_id, key, value) VALUES (?,?,?)",
            (interaction.guild_id, f"daily_{interaction.user.id}", datetime.utcnow().isoformat())
        )
        await db.commit()
    await interaction.response.send_message(
        embed=success_embed("Daily", f"{interaction.user.mention} claimed **{amount:,}** 🪙!\nTotal: **{await get_coins(interaction.guild_id, interaction.user.id):,}** 🪙")
    )

@bot.tree.command(name="give", description="Give coins to another member")
@app_commands.describe(member="Who to give to", amount="Amount")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        return await interaction.response.send_message(embed=error_embed("Give", "Amount must be positive."))
    coins = await get_coins(interaction.guild_id, interaction.user.id)
    if coins < amount:
        return await interaction.response.send_message(embed=error_embed("Give", f"You only have {coins:,} 🪙."))
    await set_coins(interaction.guild_id, interaction.user.id, coins - amount)
    await add_coins(interaction.guild_id, member.id, amount)
    await interaction.response.send_message(
        embed=success_embed("Give", f"{interaction.user.mention} gave **{amount:,}** 🪙 to {member.mention}.")
    )

@bot.tree.command(name="richlist", description="Top 10 richest members")
async def richlist(interaction: discord.Interaction):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT user_id, coins FROM economy WHERE guild_id=? ORDER BY coins DESC LIMIT 10",
            (interaction.guild_id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message(embed=info_embed("Rich List", "No data."))
    medals = ["🥇","🥈","🥉"]
    desc = "\n".join([
        f"{medals[i] if i < 3 else f'`#{i+1}`'} <@{uid}> — **{c:,}** 🪙"
        for i, (uid, c) in enumerate(rows)
    ])
    await interaction.response.send_message(embed=discord.Embed(title="💰 Rich List", description=desc, color=0xFFD700))

# ─────────────────────────────────────────────────────────
# SLASH COMMANDS — UTILITY
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="embed", description="Send a custom embed")
@app_commands.describe(title="Title", description="Description", color="Hex color (e.g. 5865F2)")
@app_commands.checks.has_permissions(manage_messages=True)
async def embed_cmd(interaction: discord.Interaction, title: str, description: str, color: str = "5865F2"):
    try:
        col = int(color.strip("#"), 16)
    except:
        col = 0x5865F2
    e = discord.Embed(title=title, description=description, color=col)
    e.set_footer(text=f"Posted by {interaction.user.display_name}")
    e.timestamp = datetime.utcnow()
    await interaction.channel.send(embed=e)
    await interaction.response.send_message("✅ Sent.", ephemeral=True)

@bot.tree.command(name="poll", description="Create a poll")
@app_commands.describe(question="Poll question", option1="Option 1", option2="Option 2", option3="Option 3", option4="Option 4")
async def poll(interaction: discord.Interaction, question: str, option1: str, option2: str, option3: str = None, option4: str = None):
    options = [o for o in [option1, option2, option3, option4] if o]
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣"]
    desc = "\n".join([f"{emojis[i]} {o}" for i, o in enumerate(options)])
    e = discord.Embed(title=f"📊 {question}", description=desc, color=0x5865F2)
    e.set_footer(text=f"Poll by {interaction.user.display_name}")
    e.timestamp = datetime.utcnow()
    await interaction.response.send_message(embed=e)
    msg = await interaction.original_response()
    for i in range(len(options)):
        await msg.add_reaction(emojis[i])

@bot.tree.command(name="remind", description="Set a reminder")
@app_commands.describe(minutes="Minutes until reminder", message="Reminder message")
async def remind(interaction: discord.Interaction, minutes: int, message: str):
    await interaction.response.send_message(embed=success_embed("Reminder", f"I'll remind you in **{minutes}** minutes."))
    await asyncio.sleep(minutes * 60)
    await interaction.user.send(embed=info_embed("⏰ Reminder", message))

@bot.tree.command(name="rolemembers", description="List members with a role")
@app_commands.describe(role="Role to list")
async def rolemembers(interaction: discord.Interaction, role: discord.Role):
    members = role.members[:30]
    if not members:
        return await interaction.response.send_message(embed=info_embed("Role Members", "No members with this role."))
    desc = " ".join([m.mention for m in members])
    e = info_embed(f"Members with {role.name} ({len(role.members)})", desc)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(prize="Prize", minutes="Duration in minutes", winners="Number of winners")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, prize: str, minutes: int, winners: int = 1):
    end_time = datetime.utcnow() + timedelta(minutes=minutes)
    e = discord.Embed(
        title="🎉 GIVEAWAY",
        description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(end_time.timestamp())}:R>\n\nReact with 🎉 to enter!",
        color=0xFFD700
    )
    e.set_footer(text=f"Hosted by {interaction.user.display_name}")
    e.timestamp = end_time
    await interaction.response.send_message(embed=e)
    msg = await interaction.original_response()
    await msg.add_reaction("🎉")
    await asyncio.sleep(minutes * 60)
    msg = await interaction.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        return await interaction.channel.send(embed=error_embed("Giveaway", "No valid entries."))
    picked = random.sample(users, min(winners, len(users)))
    mentions = " ".join([u.mention for u in picked])
    await interaction.channel.send(
        embed=success_embed("🎉 Giveaway Ended", f"**Prize:** {prize}\n**Winners:** {mentions}")
    )

@bot.tree.command(name="say", description="Make the bot say something")
@app_commands.describe(message="Message to send")
@app_commands.checks.has_permissions(manage_messages=True)
async def say(interaction: discord.Interaction, message: str):
    await interaction.channel.send(message)
    await interaction.response.send_message("✅", ephemeral=True)

@bot.tree.command(name="roleadd", description="Add a role to a member")
@app_commands.describe(member="Member", role="Role to add")
@app_commands.checks.has_permissions(manage_roles=True)
async def roleadd(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await interaction.response.send_message(embed=success_embed("Role Added", f"Added {role.mention} to {member.mention}."))

@bot.tree.command(name="roleremove", description="Remove a role from a member")
@app_commands.describe(member="Member", role="Role to remove")
@app_commands.checks.has_permissions(manage_roles=True)
async def roleremove(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await interaction.response.send_message(embed=success_embed("Role Removed", f"Removed {role.mention} from {member.mention}."))

@bot.tree.command(name="nick", description="Change a member's nickname")
@app_commands.describe(member="Member", nickname="New nickname (leave empty to reset)")
@app_commands.checks.has_permissions(manage_nicknames=True)
async def nick(interaction: discord.Interaction, member: discord.Member, nickname: str = None):
    await member.edit(nick=nickname)
    await interaction.response.send_message(embed=success_embed("Nickname", f"Updated {member.mention}'s nickname."))

# ─────────────────────────────────────────────────────────
# PREFIX COMMANDS — GAMES (AT prefix)
# ─────────────────────────────────────────────────────────

class GameBot(commands.Bot):
    pass

@bot.listen("on_message")
async def game_listener(message):
    if message.author.bot or not message.guild:
        return
    content = message.content.upper().strip()

    # ── BLACKJACK ────────────────────────────────────────
    if content.startswith("ATBLACKJACK"):
        parts = content.split()
        bet = 50
        if len(parts) > 1:
            try:
                bet = max(1, int(parts[1]))
            except:
                pass
        coins = await get_coins(message.guild.id, message.author.id)
        if coins < bet:
            await message.channel.send(embed=error_embed("Blackjack", f"Not enough coins. You have **{coins:,}** 🪙."))
            return

        def make_deck():
            suits = ["♠","♥","♦","♣"]
            ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
            return [(r, s) for s in suits for r in ranks]

        def card_value(rank):
            if rank in ["J","Q","K"]:
                return 10
            if rank == "A":
                return 11
            return int(rank)

        def hand_value(hand):
            total = sum(card_value(r) for r, s in hand)
            aces = sum(1 for r, s in hand if r == "A")
            while total > 21 and aces:
                total -= 10
                aces -= 1
            return total

        def fmt_hand(hand):
            return " ".join([f"`{r}{s}`" for r, s in hand])

        deck = make_deck()
        random.shuffle(deck)
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]

        def bj_embed(title, color=0x5865F2, result=None):
            e = discord.Embed(title=f"🃏 Blackjack — {title}", color=color)
            e.add_field(name=f"Your Hand ({hand_value(player)})", value=fmt_hand(player), inline=False)
            d_show = fmt_hand([dealer[0]]) + " `?`" if not result else fmt_hand(dealer)
            e.add_field(name=f"Dealer Hand ({hand_value(dealer) if result else '?'})", value=d_show, inline=False)
            e.add_field(name="Bet", value=f"**{bet:,}** 🪙")
            if result:
                e.add_field(name="Result", value=result, inline=False)
            e.set_footer(text=f"Player: {message.author.display_name}")
            return e

        view = discord.ui.View(timeout=30)
        hit_btn = discord.ui.Button(label="Hit", style=discord.ButtonStyle.green, emoji="🃏")
        stand_btn = discord.ui.Button(label="Stand", style=discord.ButtonStyle.red, emoji="✋")

        msg_obj = await message.channel.send(embed=bj_embed("Your Turn"), view=view)

        async def hit_cb(i: discord.Interaction):
            if i.user.id != message.author.id:
                return await i.response.defer()
            player.append(deck.pop())
            pv = hand_value(player)
            if pv > 21:
                view.stop()
                await set_coins(message.guild.id, message.author.id, coins - bet)
                await i.response.edit_message(embed=bj_embed("Bust! You lose 💸", 0xED4245, f"Bust! Lost **{bet:,}** 🪙"), view=None)
            elif pv == 21:
                await stand_cb(i)
            else:
                await i.response.edit_message(embed=bj_embed("Your Turn"), view=view)

        async def stand_cb(i: discord.Interaction):
            if i.user.id != message.author.id:
                return await i.response.defer()
            view.stop()
            while hand_value(dealer) < 17:
                dealer.append(deck.pop())
            pv = hand_value(player)
            dv = hand_value(dealer)
            if dv > 21 or pv > dv:
                await add_coins(message.guild.id, message.author.id, bet)
                result = f"You win **{bet:,}** 🪙! 🎉"
                col = 0x57F287
            elif pv == dv:
                result = "Push! Bet returned."
                col = 0xFEE75C
            else:
                await set_coins(message.guild.id, message.author.id, coins - bet)
                result = f"Dealer wins. Lost **{bet:,}** 🪙."
                col = 0xED4245
            try:
                await i.response.edit_message(embed=bj_embed("Result", col, result), view=None)
            except:
                await msg_obj.edit(embed=bj_embed("Result", col, result), view=None)

        hit_btn.callback = hit_cb
        stand_btn.callback = stand_cb
        view.add_item(hit_btn)
        view.add_item(stand_btn)
        await msg_obj.edit(embed=bj_embed("Your Turn"), view=view)

    # ── MINES ─────────────────────────────────────────────
    elif content.startswith("ATMINES"):
        parts = content.split()
        bet = 50
        bombs = 3
        if len(parts) > 1:
            try:
                bet = max(1, int(parts[1]))
            except:
                pass
        if len(parts) > 2:
            try:
                bombs = max(1, min(int(parts[2]), 20))
            except:
                pass

        coins = await get_coins(message.guild.id, message.author.id)
        if coins < bet:
            await message.channel.send(embed=error_embed("Mines", f"Not enough coins. You have **{coins:,}** 🪙."))
            return

        GRID = 25
        bomb_positions = set(random.sample(range(GRID), bombs))
        revealed = set()
        cashed_out = [False]
        lost = [False]

        def multiplier():
            k = len(revealed)
            n = GRID
            m = bombs
            if k == 0:
                return 1.0
            mult = 1.0
            for i in range(k):
                mult *= (n - m - i) / (n - i)
            return round(1.0 / mult * 0.97, 2)

        def grid_view():
            view = discord.ui.View(timeout=60)
            for i in range(GRID):
                if i in revealed:
                    btn = discord.ui.Button(
                        label="💎", style=discord.ButtonStyle.success,
                        row=i // 5, disabled=True, custom_id=str(i)
                    )
                else:
                    btn = discord.ui.Button(
                        label="·", style=discord.ButtonStyle.secondary,
                        row=i // 5, custom_id=str(i)
                    )

                async def make_cb(idx=i):
                    async def cb(inter: discord.Interaction):
                        if inter.user.id != message.author.id:
                            return await inter.response.defer()
                        if idx in bomb_positions:
                            lost[0] = True
                            cashed_out[0] = True
                            await set_coins(message.guild.id, message.author.id, coins - bet)
                            e = discord.Embed(title="💣 BOOM! You hit a mine!", color=0xED4245)
                            e.add_field(name="Bet", value=f"**{bet:,}** 🪙 lost")
                            e.add_field(name="Mines hit", value=f"Position {idx}")
                            await inter.response.edit_message(embed=e, view=None)
                        else:
                            revealed.add(idx)
                            mult = multiplier()
                            potential = int(bet * mult)
                            e = discord.Embed(title="💎 Mines", color=0x57F287)
                            e.add_field(name="Revealed", value=f"**{len(revealed)}** gems found")
                            e.add_field(name="Multiplier", value=f"**{mult}x**")
                            e.add_field(name="Potential Win", value=f"**{potential:,}** 🪙")
                            e.add_field(name="Bombs Left", value=f"**{bombs}** 💣")
                            e.set_footer(text="Keep going or cash out!")
                            new_view = grid_view()
                            await inter.response.edit_message(embed=e, view=new_view)
                    return cb

                btn.callback = await make_cb(i)
                view.add_item(btn)

            cashout_btn = discord.ui.Button(
                label=f"Cash Out ({int(bet * multiplier()):,} 🪙)",
                style=discord.ButtonStyle.blurple, row=4
            )

            async def cashout_cb(inter: discord.Interaction):
                if inter.user.id != message.author.id:
                    return await inter.response.defer()
                if not revealed:
                    return await inter.response.send_message("Reveal at least one gem first!", ephemeral=True)
                mult = multiplier()
                winnings = int(bet * mult)
                await set_coins(message.guild.id, message.author.id, coins - bet + winnings)
                e = discord.Embed(title="💰 Cashed Out!", color=0xFFD700)
                e.add_field(name="Multiplier", value=f"**{mult}x**")
                e.add_field(name="Won", value=f"**{winnings:,}** 🪙")
                e.add_field(name="Gems Found", value=f"**{len(revealed)}**")
                await inter.response.edit_message(embed=e, view=None)

            cashout_btn.callback = cashout_cb
            view.add_item(cashout_btn)
            return view

        e = discord.Embed(title="💣 Mines", description=f"Bet: **{bet:,}** 🪙 | Bombs: **{bombs}** 💣\nClick tiles to find gems!", color=0x5865F2)
        await message.channel.send(embed=e, view=grid_view())

    # ── COINFLIP ──────────────────────────────────────────
    elif content.startswith("ATCOINFLIP"):
        parts = content.split()
        bet = 50
        choice = "heads"
        if len(parts) > 1:
            try:
                bet = max(1, int(parts[1]))
            except:
                choice = parts[1].lower()
        if len(parts) > 2:
            choice = parts[2].lower()

        coins = await get_coins(message.guild.id, message.author.id)
        if coins < bet:
            await message.channel.send(embed=error_embed("Coinflip", f"Not enough coins. You have **{coins:,}** 🪙."))
            return

        result = random.choice(["heads", "tails"])
        won = result == choice
        coin_emoji = "🪙 Heads" if result == "heads" else "🪙 Tails"

        if won:
            await add_coins(message.guild.id, message.author.id, bet)
            e = discord.Embed(title="🪙 Coinflip — WIN!", color=0x57F287)
            e.add_field(name="Result", value=coin_emoji)
            e.add_field(name="Won", value=f"**{bet:,}** 🪙")
        else:
            await set_coins(message.guild.id, message.author.id, coins - bet)
            e = discord.Embed(title="🪙 Coinflip — LOSE", color=0xED4245)
            e.add_field(name="Result", value=coin_emoji)
            e.add_field(name="Lost", value=f"**{bet:,}** 🪙")
        e.add_field(name="Your pick", value=choice.title())
        e.set_footer(text=f"{message.author.display_name} • Balance: {await get_coins(message.guild.id, message.author.id):,} 🪙")
        await message.channel.send(embed=e)

    # ── RPS ───────────────────────────────────────────────
    elif content.startswith("ATRPS"):
        parts = content.split()
        bet = 50
        choice = ""
        if len(parts) > 1:
            try:
                bet = max(1, int(parts[1]))
                if len(parts) > 2:
                    choice = parts[2].lower()
            except:
                choice = parts[1].lower()

        valid = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        if choice not in valid:
            await message.channel.send(embed=error_embed("RPS", "Usage: `ATRPS [bet] rock/paper/scissors`"))
            return

        coins = await get_coins(message.guild.id, message.author.id)
        if coins < bet:
            await message.channel.send(embed=error_embed("RPS", f"Not enough coins."))
            return

        bot_choice = random.choice(list(valid.keys()))
        wins = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

        if choice == bot_choice:
            result, col = "Push! Tie game.", 0xFEE75C
        elif wins[choice] == bot_choice:
            await add_coins(message.guild.id, message.author.id, bet)
            result, col = f"You win **{bet:,}** 🪙!", 0x57F287
        else:
            await set_coins(message.guild.id, message.author.id, coins - bet)
            result, col = f"You lose **{bet:,}** 🪙.", 0xED4245

        e = discord.Embed(title="🪨📄✂️ Rock Paper Scissors", color=col)
        e.add_field(name="You", value=f"{valid[choice]} {choice.title()}")
        e.add_field(name="Bot", value=f"{valid[bot_choice]} {bot_choice.title()}")
        e.add_field(name="Result", value=result, inline=False)
        await message.channel.send(embed=e)

    # ── ROLL ──────────────────────────────────────────────
    elif content.startswith("ATROLL"):
        parts = content.split()
        sides = 6
        if len(parts) > 1:
            try:
                sides = max(2, int(parts[1]))
            except:
                pass
        result = random.randint(1, sides)
        e = discord.Embed(title="🎲 Dice Roll", color=0x5865F2)
        e.add_field(name="Sides", value=str(sides))
        e.add_field(name="Result", value=f"**{result}**")
        await message.channel.send(embed=e)

    # ── SLOTS ─────────────────────────────────────────────
    elif content.startswith("ATSLOTS"):
        parts = content.split()
        bet = 50
        if len(parts) > 1:
            try:
                bet = max(1, int(parts[1]))
            except:
                pass

        coins = await get_coins(message.guild.id, message.author.id)
        if coins < bet:
            await message.channel.send(embed=error_embed("Slots", f"Not enough coins."))
            return

        symbols = ["🍒","🍋","🍇","7️⃣","💎","🃏"]
        weights = [30, 25, 20, 15, 8, 2]
        reels = [random.choices(symbols, weights=weights)[0] for _ in range(3)]

        if reels[0] == reels[1] == reels[2]:
            if reels[0] == "💎":
                mult, label = 50, "JACKPOT 💎💎💎"
            elif reels[0] == "7️⃣":
                mult, label = 20, "TRIPLE 7s! 🎰"
            else:
                mult, label = 10, "Three of a Kind!"
        elif reels[0] == reels[1] or reels[1] == reels[2]:
            mult, label = 2, "Two of a Kind"
        else:
            mult, label = 0, "No match"

        winnings = bet * mult
        new_bal = coins - bet + winnings
        await set_coins(message.guild.id, message.author.id, new_bal)

        col = 0x57F287 if mult > 0 else 0xED4245
        e = discord.Embed(title="🎰 Slots", color=col)
        e.add_field(name="Reels", value=f"[ {' | '.join(reels)} ]", inline=False)
        e.add_field(name="Result", value=label)
        e.add_field(name="Multiplier", value=f"**{mult}x**")
        if mult > 0:
            e.add_field(name="Won", value=f"**{winnings:,}** 🪙")
        else:
            e.add_field(name="Lost", value=f"**{bet:,}** 🪙")
        e.add_field(name="Balance", value=f"**{new_bal:,}** 🪙")
        await message.channel.send(embed=e)

    # ── CRASH ─────────────────────────────────────────────
    elif content.startswith("ATCRASH"):
        parts = content.split()
        bet = 50
        if len(parts) > 1:
            try:
                bet = max(1, int(parts[1]))
            except:
                pass

        coins = await get_coins(message.guild.id, message.author.id)
        if coins < bet:
            await message.channel.send(embed=error_embed("Crash", f"Not enough coins."))
            return

        crash_at = round(random.uniform(1.0, 10.0), 2)
        current = [1.0]
        cashed = [False]

        view = discord.ui.View(timeout=30)
        cashout_btn = discord.ui.Button(label="Cash Out 1.00x", style=discord.ButtonStyle.green, emoji="💰")

        async def cashout_cb(inter: discord.Interaction):
            if inter.user.id != message.author.id:
                return await inter.response.defer()
            if cashed[0]:
                return
            cashed[0] = True
            mult = current[0]
            winnings = int(bet * mult)
            await set_coins(message.guild.id, message.author.id, coins - bet + winnings)
            e = discord.Embed(title="💰 Cashed Out!", color=0x57F287)
            e.add_field(name="Multiplier", value=f"**{mult}x**")
            e.add_field(name="Won", value=f"**{winnings:,}** 🪙")
            await inter.response.edit_message(embed=e, view=None)

        cashout_btn.callback = cashout_cb
        view.add_item(cashout_btn)

        e = discord.Embed(title="🚀 CRASH", description=f"Bet: **{bet:,}** 🪙\nCash out before it crashes!", color=0x5865F2)
        e.add_field(name="Multiplier", value="**1.00x** 🚀")
        msg_obj = await message.channel.send(embed=e, view=view)

        step = 0.1
        while current[0] < crash_at:
            if cashed[0]:
                return
            await asyncio.sleep(0.8)
            current[0] = round(current[0] + random.uniform(0.05, 0.3), 2)
            current[0] = min(current[0], crash_at)
            if not cashed[0]:
                cashout_btn.label = f"Cash Out {current[0]:.2f}x"
                try:
                    e2 = discord.Embed(title="🚀 CRASH", color=0x5865F2)
                    e2.add_field(name="Multiplier", value=f"**{current[0]:.2f}x** 🚀")
                    e2.add_field(name="Bet", value=f"**{bet:,}** 🪙")
                    await msg_obj.edit(embed=e2, view=view)
                except:
                    break

        if not cashed[0]:
            await set_coins(message.guild.id, message.author.id, coins - bet)
            e = discord.Embed(title=f"💥 CRASHED at {crash_at}x!", color=0xED4245)
            e.add_field(name="Lost", value=f"**{bet:,}** 🪙")
            await msg_obj.edit(embed=e, view=None)

    # ── ATHELP ────────────────────────────────────────────
    elif content == "ATHELP":
        e = discord.Embed(title="🎮 Game Commands (AT prefix)", color=0x5865F2)
        e.add_field(name="🃏 ATBLACKJACK [bet]", value="Classic blackjack", inline=False)
        e.add_field(name="💣 ATMINES [bet] [bombs]", value="Mine sweeper game", inline=False)
        e.add_field(name="🪙 ATCOINFLIP [bet] [heads/tails]", value="50/50 coinflip", inline=False)
        e.add_field(name="✂️ ATRPS [bet] [rock/paper/scissors]", value="Rock paper scissors", inline=False)
        e.add_field(name="🎲 ATROLL [sides]", value="Roll a dice", inline=False)
        e.add_field(name="🎰 ATSLOTS [bet]", value="Slot machine", inline=False)
        e.add_field(name="🚀 ATCRASH [bet]", value="Crash game, cash out before it crashes!", inline=False)
        e.set_footer(text="Win coins and climb the rich list!")
        await message.channel.send(embed=e)

# ─────────────────────────────────────────────────────────
# ERROR HANDLER
# ─────────────────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=error_embed("No Permission", "You don't have permission to use this command."),
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            embed=error_embed("Error", str(error)),
            ephemeral=True
        )

# ─────────────────────────────────────────────────────────
bot.run(TOKEN)

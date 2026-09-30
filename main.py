import discord
from discord.ext import commands
import datetime
import asyncio
from collections import defaultdict, deque
import os
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.bans = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Hafıza Yapıları
spam_tracker = defaultdict(lambda: deque(maxlen=5))
dup_tracker = defaultdict(lambda: deque(maxlen=7))
channel_logs = defaultdict(list)
ban_logs = defaultdict(list)

# AFK Hafızası
afk_users = {}
spam_koruma_aktif = True

# Helper: Log Gönderme
async def send_log(guild: discord.Guild, embed: discord.Embed):
    if not LOG_CHANNEL_ID:
        return
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        try:
            await log_channel.send(embed=embed)
        except Exception as e:
            print(f"[LOG HATA] Mesaj gönderilemedi: {e}")

# Guard Rol Alma Fonksiyonu
async def remove_all_roles(member: discord.Member, reason: str):
    try:
        roles_to_remove = [r for r in member.roles if r != member.guild.default_role and not r.managed]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=reason)
            
            embed = discord.Embed(title="🛡️ Guard Tetiklendi!", color=discord.Color.dark_red(), timestamp=datetime.datetime.utcnow())
            embed.add_field(name="Kullanıcı", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="İşlem", value="Tüm Rolleri Alındı", inline=True)
            embed.add_field(name="Sebep", value=reason, inline=True)
            await send_log(member.guild, embed)
    except Exception as e:
        print(f"[GUARD HATA] {e}")

@bot.event
async def on_ready():
    print(f'{bot.user} sıfırdan başarıyla başlatıldı ve aktif!')

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    content_lower = message.content.lower().strip()

    # SA-AS
    if content_lower in ('sa', 'sa.', 'sa!'):
        await message.channel.send('Aleyküm selam')

    # AFK Çıkış & İsmi Eski Haline Getirme
    author_id = message.author.id
    if author_id in afk_users:
        data = afk_users.pop(author_id)
        try:
            await message.author.edit(nick=data["old_nick"])
        except Exception:
            pass
        await message.channel.send(f'{message.author.mention}, artık AFK değilsin! İsmin eski haline getirildi.')

    # AFK Etiketlenme
    if message.mentions:
        for mention in message.mentions:
            if mention.id in afk_users:
                info = afk_users[mention.id]
                await message.channel.send(f'**{mention.display_name}** şu anda AFK. (Sebep: {info["reason"]})')

    # Anti-Spam Koruma
    global spam_koruma_aktif
    if spam_koruma_aktif:
        now_ts = datetime.datetime.utcnow().timestamp()

        u_times = spam_tracker[author_id]
        u_times.append(now_ts)
        if len(u_times) == 5 and (u_times[-1] - u_times[0]) <= 5:
            u_times.clear()
            asyncio.create_task(message.author.timeout(datetime.timedelta(minutes=10), reason="Spam Hız Limit"))
            await message.channel.send(f'{message.author.mention}, 5 saniyede 5 mesaj attığın için 10 dk mute yedin!')

        u_msgs = dup_tracker[author_id]
        u_msgs.append(message.content)
        if len(u_msgs) == 7 and len(set(u_msgs)) == 1:
            u_msgs.clear()
            asyncio.create_task(message.author.timeout(datetime.timedelta(minutes=10), reason="Spam Tekrar Limit"))
            await message.channel.send(f'{message.author.mention}, aynı cümleyi 7 kere yazdığın için 10 dk mute yedin!')

    await bot.process_commands(message)

# ==========================================
# LOG OLAYLARI (EVENTS)
# ==========================================

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    embed = discord.Embed(title="🗑️ Mesaj Silindi", color=discord.Color.red(), timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Yazan", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
    embed.add_field(name="Kanal", value=message.channel.mention, inline=True)
    embed.add_field(name="İçerik", value=message.content or "*(Görsel/Embed)*", inline=False)
    await send_log(message.guild, embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    embed = discord.Embed(title="✏️ Mesaj Düzenlendi", color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Kullanıcı", value=f"{before.author.mention} (`{before.author.id}`)", inline=True)
    embed.add_field(name="Kanal", value=before.channel.mention, inline=True)
    embed.add_field(name="Eski", value=before.content or "Yok", inline=False)
    embed.add_field(name="Yeni", value=after.content or "Yok", inline=False)
    await send_log(before.guild, embed)

@bot.event
async def on_member_join(member):
    embed = discord.Embed(title="📥 Üye Katıldı", color=discord.Color.green(), timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Kullanıcı", value=f"{member.mention} ({member.name})", inline=True)
    embed.add_field(name="Hesap Açılış", value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    await send_log(member.guild, embed)

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(title="📤 Üye Ayrıldı", color=discord.Color.dark_grey(), timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Kullanıcı", value=f"{member.name} ({member.id})", inline=False)
    await send_log(member.guild, embed)

async def check_channel_limit(guild):
    now_ts = datetime.datetime.utcnow().timestamp()
    try:
        async for entry in guild.audit_logs(limit=1):
            if entry.action in (discord.AuditLogAction.channel_create, discord.AuditLogAction.channel_delete):
                user = entry.user
                if user and not user.bot:
                    logs = channel_logs[user.id]
                    logs.append(now_ts)
                    channel_logs[user.id] = [t for t in logs if (now_ts - t) <= 86400]
                    if len(channel_logs[user.id]) >= 10:
                        member = guild.get_member(user.id)
                        if member:
                            asyncio.create_task(remove_all_roles(member, "24 saatte 10 kanal limiti"))
    except Exception:
        pass

@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(title="➕ Kanal Oluşturuldu", color=discord.Color.blue(), timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Kanal", value=f"{channel.name} ({channel.mention})", inline=False)
    await send_log(channel.guild, embed)
    asyncio.create_task(check_channel_limit(channel.guild))

@bot.event
async def on_guild_channel_delete(channel):
    embed = discord.Embed(title="➖ Kanal Silindi", color=discord.Color.dark_red(), timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Kanal", value=channel.name, inline=False)
    await send_log(channel.guild, embed)
    asyncio.create_task(check_channel_limit(channel.guild))

@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="🔨 Üye Banlandı", color=discord.Color.dark_red(), timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Üye", value=f"{user.name} ({user.id})", inline=False)
    await send_log(guild, embed)

    now_ts = datetime.datetime.utcnow().timestamp()
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
            mod = entry.user
            if mod and not mod.bot:
                logs = ban_logs[mod.id]
                logs.append(now_ts)
                ban_logs[mod.id] = [t for t in logs if (now_ts - t) <= 86400]
                if len(ban_logs[mod.id]) >= 5:
                    member = guild.get_member(mod.id)
                    if member:
                        asyncio.create_task(remove_all_roles(member, "24 saatte 5 ban limiti"))
    except Exception:
        pass

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    embed = None
    if before.channel is None and after.channel is not None:
        embed = discord.Embed(title="🔊 Sese Katıldı", color=discord.Color.green(), timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Kullanıcı", value=member.mention, inline=True)
        embed.add_field(name="Kanal", value=after.channel.name, inline=True)
    elif before.channel is not None and after.channel is None:
        embed = discord.Embed(title="🔇 Sesten Ayrıldı", color=discord.Color.red(), timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Kullanıcı", value=member.mention, inline=True)
        embed.add_field(name="Kanal", value=before.channel.name, inline=True)
    elif before.channel != after.channel:
        embed = discord.Embed(title="🔀 Ses Kanalı Değiştirdi", color=discord.Color.yellow(), timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Kullanıcı", value=member.mention, inline=False)
        embed.add_field(name="Eski Kanal", value=before.channel.name, inline=True)
        embed.add_field(name="Yeni Kanal", value=after.channel.name, inline=True)

    if embed:
        await send_log(member.guild, embed)

# ==========================================
# KOMUTLAR
# ==========================================

@bot.command()
async def ses(ctx, channel_id: int = None):
    target_channel = bot.get_channel(channel_id) if channel_id else (ctx.author.voice.channel if ctx.author.voice else None)
    if not target_channel:
        await ctx.send("Lütfen bir ses kanalına girip `!ses` yazın veya kanal ID'si belirtin!")
        return
    try:
        if ctx.voice_client:
            await ctx.voice_client.move_to(target_channel)
        else:
            await target_channel.connect(reconnect=True, timeout=20.0)
        await ctx.send(f"Başarıyla **{target_channel.name}** ses kanalına bağlandım!")
    except Exception as e:
        await ctx.send(f"Sese bağlanırken hata oluştu: `{e}`")

@bot.command(name="ses-cik")
async def ses_cik(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Ses kanalından ayrıldım.")
    else:
        await ctx.send("Ses kanalında değilim!")

@bot.command()
async def afk(ctx, *, reason="Belirtilmedi"):
    old_nick = ctx.author.display_name
    afk_users[ctx.author.id] = {"reason": reason, "old_nick": old_nick}
    new_nick = f"[AFK] {old_nick}"[:32]
    try:
        await ctx.author.edit(nick=new_nick)
        await ctx.send(f'{ctx.author.mention}, AFK moduna geçtin ve ismin **{new_nick}** oldu. Sebep: {reason}')
    except Exception:
        await ctx.send(f'{ctx.author.mention}, AFK moduna geçtin. Sebep: {reason}')

@bot.command()
@commands.has_permissions(manage_roles=True)
async def rol(ctx, member: discord.Member, role: discord.Role):
    if role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f'{member.mention} kullanıcısından **{role.name}** alındı.')
    else:
        await member.add_roles(role)
        await ctx.send(f'{member.mention} kullanıcısına **{role.name}** verildi.')

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, dakika: int = 10):
    await member.timeout(datetime.timedelta(minutes=dakika))
    await ctx.send(f'{member.mention} **{dakika} dakika** susturuldu.')

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f'{member.mention} susturması kaldırıldı.')

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Belirtilmedi"):
    await member.ban(reason=reason)
    await ctx.send(f'{member.mention} banlandı. Sebep: {reason}')

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user)
    await ctx.send(f'**{user.name}** yasaklaması kaldırıldı.')

@bot.command(name="sunucu-bilgi")
async def sunucu_bilgi(ctx):
    g = ctx.guild
    embed = discord.Embed(title=f"{g.name} Bilgileri", color=discord.Color.blue())
    embed.add_field(name="Üye Sayısı", value=str(g.member_count))
    embed.add_field(name="Sunucu Sahibi", value=str(g.owner))
    embed.add_field(name="Kuruluş", value=g.created_at.strftime("%d/%m/%Y"))
    await ctx.send(embed=embed)

@bot.command(name="kisi-bilgi")
async def kisi_bilgi(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"{member.name} Bilgileri", color=discord.Color.green())
    embed.add_field(name="Sunucuya Katılım", value=member.joined_at.strftime("%d/%m/%Y"))
    embed.add_field(name="Hesap Açılış", value=member.created_at.strftime("%d/%m/%Y"))
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def spamkoruma(ctx, durum: str):
    global spam_koruma_aktif
    spam_koruma_aktif = (durum.lower() == "acik")
    await ctx.send(f"Spam koruması: **{'AÇIK' if spam_koruma_aktif else 'KAPALI'}**")

keep_alive()

# ==========================================
# LOG KANAL ID'Sİ VE BOT BAŞLATMA
# ==========================================
LOG_CHANNEL_ID = 1549798214209769543  # <--- KANAL ID'SİNİ TAM BURADAKİ 0 YERİNE YAZ KANKA

token = os.getenv('DISCORD_TOKEN')
if token:
    bot.run(token)

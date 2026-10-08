import asyncio
import io
import os
import re
from typing import Optional

import discord
from aiohttp import web
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ----------------
TOKEN = os.getenv("DISCORD_TOKEN", "")
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID") or 0)  # 0 = create tickets with no category
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID") or 0)            # 0 = no staff role

BRAND = "[ASTRE] MARKET"
STORE_URL = "https://astre-market.mysellauth.com/"
EMBED_COLOR = 0x7C5CFF

MAX_OPEN_TICKETS_PER_USER = 3
RESPONSE_TIMEOUT = 600  # seconds the bot waits for files / serials after /createproduct
# ----------------------------------------

KIND_LABEL = {"serial": "Serials", "files": "Files"}


# ---------- tickets live entirely in Discord (nothing is saved on disk) ----------
# kind + number come from the channel name, owner + submitted flag from the channel topic.
TICKET_NAME = re.compile(r"^(serial|files)-ticket-(\d+)$")


def read_ticket(channel) -> Optional[dict]:
    if not isinstance(channel, discord.TextChannel):
        return None
    name = TICKET_NAME.match(channel.name)
    topic = channel.topic or ""
    owner = re.search(r"owner: (\d+)", topic)
    if not (name and owner):
        return None
    return {
        "kind": name[1],
        "number": int(name[2]),
        "owner_id": int(owner[1]),
        "submitted": "submitted: yes" in topic,
    }


async def start_web_server():
    """Render web services must listen on $PORT. UptimeRobot pings this so the free instance doesn't sleep."""
    async def handle(request):
        return web.Response(text=f"{BRAND} bot is running")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ["PORT"])).start()


class AstreBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # needed to read the serials the seller sends
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.ticket_lock: Optional[asyncio.Lock] = None
        self.mentions: dict[str, str] = {}  # command name -> clickable mention
        self.awaiting: set[int] = set()     # ticket channels currently waiting for files / serials

    async def setup_hook(self):
        self.ticket_lock = asyncio.Lock()
        if os.getenv("PORT"):  # set automatically by Render
            await start_web_server()
        self.add_view(DashboardView())
        self.add_view(CloseTicketView())
        synced = await self.tree.sync()
        self.mentions = {c.name: c.mention for c in synced}

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")


client = AstreBot()


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.manage_channels:
        return True
    return bool(STAFF_ROLE_ID) and any(r.id == STAFF_ROLE_ID for r in member.roles)


# ---------- dashboard ----------
def build_dashboard_embed() -> discord.Embed:
    embed = discord.Embed(
        title=f"Start selling on {BRAND} today!",
        url=STORE_URL,
        description="Choose how your product gets delivered to buyers. A private ticket opens and walks you through creating your listing.",
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="Serials",
        value=(
            "Delivers items you pre-load, one per line.\n"
            "**Stock:** Based on the number of entered items\n"
            "**Best for:** License keys, accounts, gift cards, top-up codes"
        ),
        inline=False,
    )
    embed.add_field(
        name="Files",
        value=(
            "Delivers downloadable files attached to each variant.\n"
            "**Stock:** Set manually, can be infinite\n"
            "**Best for:** E-books, templates, digital assets"
        ),
        inline=False,
    )
    embed.set_footer(text=BRAND)
    return embed


class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Serials", style=discord.ButtonStyle.primary, custom_id="astre:new:serial")
    async def serials(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "serial")

    @discord.ui.button(label="Files", style=discord.ButtonStyle.primary, custom_id="astre:new:files")
    async def files(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "files")


# ---------- tickets ----------
class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="astre:ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = read_ticket(interaction.channel)
        if ticket is None:
            await interaction.response.send_message("This isn't a ticket channel.", ephemeral=True)
            return

        staff = is_staff(interaction.user)
        if not staff:
            if interaction.user.id != ticket["owner_id"]:
                await interaction.response.send_message("Only the ticket owner or staff can close this.", ephemeral=True)
                return
            if ticket["submitted"]:
                await interaction.response.send_message(
                    "Your product was submitted. Staff will close this ticket once it's handled.", ephemeral=True)
                return

        await interaction.response.send_message("Closing this ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")


async def open_ticket(interaction: discord.Interaction, kind: str):
    guild, user = interaction.guild, interaction.user
    await interaction.response.defer(ephemeral=True)

    category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
    if not isinstance(category, discord.CategoryChannel):
        category = None

    async with client.ticket_lock:  # stops two simultaneous clicks from getting the same number
        tickets = [t for ch in guild.text_channels if (t := read_ticket(ch))]
        if sum(1 for t in tickets if t["owner_id"] == user.id) >= MAX_OPEN_TICKETS_PER_USER:
            await interaction.followup.send(
                f"You already have {MAX_OPEN_TICKETS_PER_USER} open tickets. Finish or close one first.", ephemeral=True)
            return

        number = max((t["number"] for t in tickets), default=0) + 1
        perms = dict(view_channel=True, send_messages=True, attach_files=True, embed_links=True, read_message_history=True)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(**perms),
            guild.me: discord.PermissionOverwrite(**perms),
        }
        if STAFF_ROLE_ID and (staff_role := guild.get_role(STAFF_ROLE_ID)):
            overwrites[staff_role] = discord.PermissionOverwrite(**perms)

        try:
            channel = await guild.create_text_channel(
                name=f"{kind}-ticket-{number}",
                category=category,
                overwrites=overwrites,
                topic=f"owner: {user.id} | submitted: no | {KIND_LABEL[kind]} ticket for {user}",
                reason=f"{KIND_LABEL[kind]} ticket opened by {user}",
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"I couldn't create your ticket ({e.text}). Please tell staff.", ephemeral=True)
            return

    command = client.mentions.get("createproduct", "/createproduct")
    await channel.send(
        f"{user.mention} please use the command {command} to create your product",
        view=CloseTicketView(),
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await interaction.followup.send(f"Your ticket is ready: {channel.mention}", ephemeral=True)


# ---------- /createproduct ----------
async def parse_serials(msg: discord.Message) -> list[str]:
    """Serials are split on ';' (new lines work too). A .txt upload is read as well."""
    chunks = [msg.content]
    for att in msg.attachments:
        is_text = att.filename.lower().endswith(".txt") or (att.content_type or "").startswith("text/")
        if is_text and att.size <= 2_000_000:
            chunks.append((await att.read()).decode("utf-8", errors="replace"))
    return [s.strip() for chunk in chunks for s in re.split(r"[;\r\n]+", chunk) if s.strip()]


async def collect_delivery(interaction: discord.Interaction, kind: str):
    """Waits for the seller's files / serials. Returns (message, items) or None if cancelled / timed out."""
    channel = interaction.channel

    def check(m: discord.Message) -> bool:
        return m.author.id == interaction.user.id and m.channel.id == channel.id

    while True:
        try:
            msg = await client.wait_for("message", check=check, timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            await channel.send("Timed out. Run the command again whenever you're ready.")
            return None

        if msg.content.strip().lower() == "cancel":
            await channel.send("Cancelled. Run the command again whenever you're ready.")
            return None

        if kind == "files":
            if msg.attachments:
                return msg, list(msg.attachments)
            await channel.send("I didn't see any files in that message. Attach your file(s) and send again, or type `cancel`.")
        else:
            serials = await parse_serials(msg)
            if serials:
                return msg, serials
            await channel.send("I couldn't find any serials in that message. Separate them with `;`, upload a `.txt` file, or type `cancel`.")


@client.tree.command(name="createproduct", description="Create your product listing for [ASTRE] MARKET")
@app_commands.describe(
    name="Product name displayed on the website",
    picture="Product picture displayed on the website",
    description="Product description displayed on the website (use \\n for a new line)",
    picture_2="Extra product picture (optional)",
    picture_3="Extra product picture (optional)",
    picture_4="Extra product picture (optional)",
    picture_5="Extra product picture (optional)",
)
@app_commands.guild_only()
async def createproduct(
    interaction: discord.Interaction,
    name: app_commands.Range[str, 1, 100],
    picture: discord.Attachment,
    description: app_commands.Range[str, 1, 4000],
    picture_2: Optional[discord.Attachment] = None,
    picture_3: Optional[discord.Attachment] = None,
    picture_4: Optional[discord.Attachment] = None,
    picture_5: Optional[discord.Attachment] = None,
):
    channel = interaction.channel
    ticket = read_ticket(channel)

    async def refuse(text: str):
        await interaction.response.send_message(text, ephemeral=True)

    if ticket is None:
        return await refuse("This command only works inside a ticket channel.")
    if interaction.user.id != ticket["owner_id"]:
        return await refuse("Only the person who opened this ticket can use this command.")
    if ticket["submitted"]:
        return await refuse("This ticket already has a submitted product. Open a new ticket for another one.")
    if interaction.channel_id in client.awaiting:
        return await refuse("I'm already waiting for your files / serials in this ticket.")

    pictures = [p for p in (picture, picture_2, picture_3, picture_4, picture_5) if p is not None]
    not_images = [p.filename for p in pictures if not (p.content_type or "").startswith("image/")]
    if not_images:
        return await refuse(f"These aren't images: {', '.join(not_images)}")
    limit = interaction.guild.filesize_limit
    if sum(p.size for p in pictures) > limit:
        return await refuse(f"Your pictures are too big together (max {limit // 1_000_000} MB total).")

    kind = ticket["kind"]
    if kind == "files":
        prompt = ("Now send your **file(s)**.\nAttach one or multiple files (up to 10) in **one message**. "
                  "These are what buyers receive after purchase.\nType `cancel` to abort.")
    else:
        prompt = ("Now send **all your serials** in **one message**, separated by a semicolon (`;`).\n"
                  "Example: `KEY-1;KEY-2;KEY-3`\nToo many for one message? Upload them as a `.txt` file instead.\n"
                  "Type `cancel` to abort.")
    await interaction.response.send_message(embed=discord.Embed(
        title="Product details received", description=prompt, color=EMBED_COLOR))

    client.awaiting.add(interaction.channel_id)
    try:
        result = await collect_delivery(interaction, kind)
    finally:
        client.awaiting.discard(interaction.channel_id)
    if result is None:
        return
    delivery_msg, items = result

    try:
        files = []
        for i, p in enumerate(pictures, 1):
            ext = os.path.splitext(p.filename)[1] or ".png"
            files.append(discord.File(io.BytesIO(await p.read()), filename=f"picture_{i}{ext}"))
    except discord.HTTPException:
        await channel.send("I couldn't download your pictures. Please run the command again.")
        return

    embed = discord.Embed(title=name, description=description.replace("\\n", "\n"), color=EMBED_COLOR)
    embed.add_field(name="Delivery type", value=KIND_LABEL[kind])
    embed.add_field(name="Seller", value=interaction.user.mention)
    embed.add_field(name="Pictures", value=str(len(pictures)))
    noun = "file(s)" if kind == "files" else "serial(s)"
    embed.add_field(name=KIND_LABEL[kind], value=f"{len(items)} {noun} in [this message]({delivery_msg.jump_url})", inline=False)
    embed.set_footer(text=f"{BRAND} • {channel.name}")

    staff_ping = f"<@&{STAFF_ROLE_ID}> new product submission from {interaction.user.mention}" if STAFF_ROLE_ID else None
    await channel.send(
        content=staff_ping,
        embed=embed,
        files=files,
        allowed_mentions=discord.AllowedMentions(roles=True),
    )
    await channel.send("Your product has been submitted for review. Staff will take it from here.")

    try:
        await channel.edit(topic=(channel.topic or "").replace("submitted: no", "submitted: yes", 1))
    except discord.HTTPException:
        pass


# ---------- /dashboard (admin) ----------
@client.tree.command(name="dashboard", description="Post the seller dashboard in this channel")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def dashboard(interaction: discord.Interaction):
    try:
        await interaction.channel.send(embed=build_dashboard_embed(), view=DashboardView())
    except discord.Forbidden:
        await interaction.response.send_message("I can't send messages in this channel.", ephemeral=True)
        return
    await interaction.response.send_message("Dashboard posted.", ephemeral=True)


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Command error: {error!r}")
    text = "Something went wrong. Please try again or tell staff."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Fill in DISCORD_TOKEN in the .env file first.")
    client.run(TOKEN)

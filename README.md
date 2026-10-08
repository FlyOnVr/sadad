# [ASTRE] MARKET seller bot

Sellers click **Serials** or **Files** on the dashboard, get a private ticket
(`serial-ticket-N` / `files-ticket-N`), and fill in their product with `/createproduct`.

## Discord Developer Portal
1. **Bot** tab > enable **Message Content Intent** (the bot reads the serials / files the seller sends).
2. Invite the bot with the `bot` and `applications.commands` scopes and these permissions:
   Manage Channels, Manage Roles, View Channels, Send Messages, Embed Links, Attach Files, Read Message History
   (or just Administrator).

## Run it (PyCharm)
1. File > Open this folder, create a venv, install `requirements.txt`.
2. Fill in `.env`: `DISCORD_TOKEN`, plus optional `TICKET_CATEGORY_ID` and `STAFF_ROLE_ID`.
3. Run `main.py`. Commands sync on startup.
4. In the channel where you want the dashboard, run `/dashboard` (admins only).

## How it works
- **Dashboard**: embed "Start selling on [ASTRE] MARKET today!" with the Serials / Files buttons.
- **Ticket**: private to the seller and your staff role. The bot posts "please use the command /createproduct to create your product".
- **/createproduct**: product name, picture (+ up to 4 extra pictures), description. Then the bot asks for:
  - **Files ticket**: the file(s) to deliver (one message, up to 10 attachments)
  - **Serials ticket**: the serials separated by `;` (or a `.txt` upload for big lists)
- The bot then posts a submission summary (name, description, pictures, link to the files / serials) and pings your staff role.

## Notes
- Discord forces slash command names to be lowercase, so it's `/createproduct`.
- Descriptions typed into a slash command are one line; `\n` becomes a new line.
- Seller can close their ticket until they submit; after that only staff can.
- Ticket numbers are one shared counter (stored in `data.json`), max 3 open tickets per person (`MAX_OPEN_TICKETS_PER_USER`).

## Hosting on Render
- Use a **Background Worker** (the bot has no web port). Workers have no free tier, so pick **Starter**.
- Attach a **persistent disk** mounted at `/data` and set `DATA_FILE=/data/data.json`. Without it, tickets and the
  ticket counter reset on every deploy and `/createproduct` stops recognising existing tickets.
- Build command: `pip install -r requirements.txt`. Start command: `python main.py`.
- Add `DISCORD_TOKEN` (and optionally `TICKET_CATEGORY_ID`, `STAFF_ROLE_ID`) under Environment. Never commit `.env`.
- `render.yaml` in this project sets all of that up as a Blueprint.

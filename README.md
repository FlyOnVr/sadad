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
- Nothing is saved on disk: ticket type/number come from the channel name and the owner / submitted status from the channel topic. Don't rename ticket channels or edit their topic. The next ticket number is the highest existing one + 1, so a number can be reused once the newest tickets are closed.
- Max 3 open tickets per person (`MAX_OPEN_TICKETS_PER_USER`).

## Hosting on Render (free Web Service)
1. Push this project to a **private** GitHub repo (`.env` is git-ignored).
2. Render > **New > Web Service** > connect the repo. Runtime **Python**, instance type **Free**.
   Build command `pip install -r requirements.txt`, start command `python main.py`.
   (Or use **New > Blueprint**, which reads `render.yaml`.)
3. Environment: add `DISCORD_TOKEN` (and optionally `TICKET_CATEGORY_ID`, `STAFF_ROLE_ID`).
4. Deploy and wait for `Logged in as ...` in the logs. Copy your service URL (https://something.onrender.com).
5. Free web services sleep after ~15 minutes without web traffic, which would take the bot offline.
   Create a free **UptimeRobot** account > **Add New Monitor** > HTTP(s) > your Render URL > every 5 minutes.
6. Run `/dashboard` in your server.

Free instances can still restart at any time. Tickets survive that (they live in Discord), but a seller who is
in the middle of `/createproduct` has to run it again.

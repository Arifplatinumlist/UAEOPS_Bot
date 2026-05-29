# Slack CLI Guide — Install, Login & Manage Any Slack Bot

> Purpose: Step-by-step guide to install the Slack CLI on any Mac and manage your Slack bot from the terminal.
> Audience: Anyone setting up their own Slack bot — no prior experience needed.
> Last updated: May 29, 2026

---

## Understanding the Key Terms — Read This First

Before diving into installation, it helps to understand what each piece of the puzzle actually is. This section explains every term you'll encounter in plain language.

---

### What is a Slack Bot?

A Slack bot is a software program that lives inside your Slack workspace and can send messages, respond to questions, set reminders, post alerts, and more. It behaves like a user but is fully automated.

To build one, you register it at https://api.slack.com/apps — Slack gives you a **bot token** (a secret key) that your code uses to talk to Slack on the bot's behalf.

---

### What is a Bot Token?

A bot token is a long string starting with `xoxb-`. It is the password your bot uses to authenticate with Slack. Anyone who has this token can send messages, delete messages, and read channels as your bot.

- Keep it secret — never paste it in a chat or email
- If leaked, go to api.slack.com/apps → Reinstall App to generate a new one
- There are different token types — only `xoxb-` is the bot token. `xapp-` is for Socket Mode connections only and won't work for API calls.

---

### What is the Slack CLI?

The Slack CLI (`slack`) is a command-line tool that lets you interact with Slack directly from your Mac terminal. With it you can:

- Authenticate as yourself or as your bot
- List messages in any channel
- Delete messages your bot posted
- Call any Slack API method without writing code

It is installed via Homebrew and is completely separate from the Slack desktop app.

---

### What is Railway — and Why Is It Referenced Here?

**Railway** (railway.com) is a cloud hosting platform. When your Slack bot's code is deployed to Railway, it runs on Railway's servers 24 hours a day, 7 days a week — even when your laptop is off.

This guide references Railway because it is one of the most common ways to keep a Slack bot running continuously. The bot token (`xoxb-...`) is stored in Railway's environment variables, which is why instructions like "get your token from Railway" appear throughout.

**If your bot is NOT on Railway**, the token is wherever you deployed it — see the hosting options section below.

---

### What is GitHub — and Does It Host the Bot?

**GitHub** is where the bot's code is stored (like a code library or version control). It does NOT run the bot. Think of GitHub as the filing cabinet where the instructions live, and Railway (or another server) as the worker who actually follows those instructions.

When you push new code to GitHub, Railway detects the change and automatically redeploys the bot with the updated code. That's the only connection between the two.

---

## Hosting Options — Where Should Your Bot Run?

Your bot needs to run on a server somewhere so it stays online. Here are your main options:

---

### Option 1 — Railway (Recommended for most people)

Railway hosts your bot in the cloud. You push your code to GitHub, connect Railway to that repo, and Railway keeps it running automatically.

| | |
|---|---|
| ✅ Always online | Runs 24/7 even when your laptop is off |
| ✅ Auto-redeploys | Push new code → Railway rebuilds and restarts automatically |
| ✅ No setup overhead | No need to manage servers, ports, or infrastructure |
| ✅ Easy env vars | Store your bot token and secrets in Railway's Variables tab |
| ❌ Costs money | Free tier is limited; ~$5/month for a small always-on bot |
| ❌ Not instant | Each redeploy takes ~45 seconds of downtime |

**How to get your bot token from Railway:**
Railway → your project → service → Variables tab → copy `SLACK_BOT_TOKEN`

---

### Option 2 — Run From Your Laptop / Home Computer

You can run the bot directly from your terminal with `python app.py` (or whatever your bot's start command is). As long as that terminal window stays open, the bot is online.

| | |
|---|---|
| ✅ Free | No hosting costs at all |
| ✅ Instant changes | Edit code and restart — no deploy wait |
| ✅ Full control | You see logs in real time, easy to debug |
| ❌ Not 24/7 | Bot goes offline the moment you close the laptop or lose internet |
| ❌ Your IP changes | Home internet IPs change periodically, which can cause connection issues |
| ❌ Sleep/restart kills it | Mac sleep mode stops the process |
| ❌ Not production-ready | Fine for testing, not reliable for a team depending on it |

**How to run locally:**
```bash
cd your-bot-folder
pip install -r requirements.txt
python app.py
```

Your bot token lives in a local `.env` file in this case:
```
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_APP_TOKEN=xapp-your-token-here
```

---

### Option 3 — A Dedicated Home Server (Raspberry Pi, old Mac, etc.)

If you have a spare computer you can leave plugged in and always on, you can run the bot on it permanently for free. This gives you 24/7 uptime without paying for Railway.

| | |
|---|---|
| ✅ Free after hardware cost | No monthly fees |
| ✅ Always on (if configured correctly) | Can run 24/7 |
| ❌ Power cuts / internet drops kill it | No automatic recovery unless you set it up |
| ❌ Requires technical setup | Need to configure auto-start on boot, port forwarding, etc. |
| ❌ Maintenance burden | OS updates, hardware failures are your responsibility |

---

### Option 4 — Other Cloud Platforms

Railway is not the only option. Other platforms that work the same way:

| Platform | Free tier | Notes |
|----------|-----------|-------|
| Render | Yes (spins down after inactivity) | Good Railway alternative |
| Heroku | No free tier anymore | Used to be the standard |
| Fly.io | Yes (limited) | Good for lightweight bots |
| AWS / GCP / Azure | Free tier available | More complex to set up |

In all cases, the bot token is stored in the platform's environment variables section, not hard-coded in the code.

---

> **Summary:** If you want the bot online 24/7 without thinking about it → use Railway. If you're just testing or developing → run it locally from your laptop. If you want free 24/7 → use a spare computer or Render's free tier.

---

## What is Homebrew — and Why Do You Need It?

**Homebrew** is a package manager for macOS. Think of it like an App Store, but for developer tools that don't come pre-installed on your Mac.

When you want to install something like the Slack CLI, Node.js, Python, or Git on a Mac, Homebrew is the standard way to do it. Instead of googling, downloading a .dmg file, and going through an installer wizard — you just run one command in the terminal and Homebrew handles everything.

**Why it matters for this guide:**
- The Slack CLI (the tool we use to manage the bot from terminal) is installed via Homebrew
- Without Homebrew, there is no simple way to install the Slack CLI on Mac
- Once Homebrew is installed, installing any other tool is just `brew install <tool-name>`

**Homebrew only needs to be installed once per Mac.** If you're on a new Mac and it's not installed yet, you'll know because running `brew --version` returns `zsh: command not found: brew`.

---

## Full Process Flowchart

```
START — New Mac or fresh terminal
         │
         ▼
┌─────────────────────────┐
│ Is Homebrew installed?  │
│ Run: brew --version     │
└─────────────────────────┘
         │
    ┌────┴────┐
   YES        NO
    │          │
    │          ▼
    │   Install Homebrew (5 min)
    │   Then add it to PATH
    │          │
    └────┬─────┘
         │
         ▼
┌─────────────────────────┐
│ Is Slack CLI installed? │
│ Run: slack version      │
└─────────────────────────┘
         │
    ┌────┴────┐
   YES        NO
    │          │
    │          ▼
    │   brew install slack-cli
    │          │
    └────┬─────┘
         │
         ▼
┌─────────────────────────┐
│ Run: slack login        │
│ Terminal shows a        │
│ /slackauthticket code   │
└─────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ Open Slack → any channel or DM          │
│ Paste the /slackauthticket command      │
│ Click Allow in the modal that appears   │
│ Slack shows a short challenge code      │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────┐
│ Type the challenge code │
│ back in your terminal   │
│ Press Enter             │
└─────────────────────────┘
         │
         ▼
   ✅ AUTHENTICATED
   You can now run Slack API commands
```

---

## Step-by-Step Instructions With Exact Commands

---

### STEP 1 — Check if Homebrew is Already Installed

```bash
brew --version
```

- If you see something like `Homebrew 4.x.x` → skip to Step 3
- If you see `zsh: command not found: brew` → continue to Step 2

---

### STEP 2 — Install Homebrew

Paste this single line exactly as-is and press Enter:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**What happens:**
1. It asks for your Mac password — type it and press Enter (nothing shows as you type, that is normal)
2. It shows a list of directories it will create — press **Enter/Return** to continue
3. It downloads and installs (~2-3 minutes)
4. At the end it says `==> Installation successful!`

**After installation, add Homebrew to your PATH** (copy all 3 lines together):

```bash
echo >> /Users/$(whoami)/.zprofile
echo 'eval "$(/opt/homebrew/bin/brew shellenv zsh)"' >> /Users/$(whoami)/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv zsh)"
```

Verify it worked:

```bash
brew --version
```

You should see a version number. Homebrew is now installed permanently on this Mac.

---

### STEP 3 — Install the Slack CLI

```bash
brew install slack-cli
```

This takes about 1-2 minutes. When it's done you'll see `🍺 slack-cli was successfully installed!`

Verify:

```bash
slack version
```

---

### STEP 4 — Log In to Slack

```bash
slack login
```

**What you'll see in the terminal:**

```
📋 Run the following slash command in any Slack channel or DM
   This will open a modal with user permissions for you to approve
   Once approved, a challenge code will be generated in Slack

/slackauthticket XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

┃ Enter challenge code
┃ ❱
```

The terminal is now waiting. **Do not close it.**

---

### STEP 5 — Authenticate in Slack

1. Open the **Slack app** (desktop or browser)
2. Go to **any channel or DM** (it doesn't matter which one)
3. In the message box, paste the exact `/slackauthticket XXXXXXX` command shown in your terminal
4. Press Enter
5. A pop-up modal appears — click **Allow**
6. Slack shows a short **challenge code** (looks like `abc-123` or similar)

---

### STEP 6 — Enter the Challenge Code

Go back to your terminal. Type the challenge code Slack showed you and press **Enter**.

You will see:

```
🔑 You've successfully authenticated!
   Authorization data was saved to ~/.slack/credentials.json
```

**You are now logged in.** Credentials are saved — you won't need to log in again on this Mac unless the token expires.

---

## Managing Bot Messages (Deleting)

Once logged in, you can list and delete bot messages from any channel.

### List recent messages in a channel

```bash
slack api conversations.history channel=CHANNEL_ID limit=10 --token YOUR_BOT_TOKEN
```

Replace `CHANNEL_ID` with the Slack channel ID (e.g. `C0B5ML7HVDF`) and `YOUR_BOT_TOKEN` with the `xoxb-...` token from Railway.

### Delete a specific message

```bash
slack api chat.delete channel=CHANNEL_ID ts=MESSAGE_TIMESTAMP --token YOUR_BOT_TOKEN
```

Replace `MESSAGE_TIMESTAMP` with the `ts` value from the message (e.g. `1779736810.715319`).

### Delete all bot messages after a specific message (bulk delete)

Save this as a file and run it:

```bash
cat > /tmp/delete_msgs.py << 'EOF'
import urllib.request, json

TOKEN = "YOUR_BOT_TOKEN"        # xoxb-... from Railway
CHANNEL = "YOUR_CHANNEL_ID"     # e.g. C0B5ML7HVDF
AFTER_TS = "ANCHOR_TIMESTAMP"   # ts of the message to delete after

def get(method, params):
    qs = "&".join(f"{k}={v}" for k,v in params.items())
    req = urllib.request.Request(f"https://slack.com/api/{method}?{qs}",
        headers={"Authorization": f"Bearer {TOKEN}"})
    return json.loads(urllib.request.urlopen(req).read())

def post(method, data):
    req = urllib.request.Request(f"https://slack.com/api/{method}",
        data=json.dumps(data).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())

cursor, deleted, failed = None, 0, 0
while True:
    params = {"channel": CHANNEL, "oldest": AFTER_TS, "limit": "100"}
    if cursor:
        params["cursor"] = cursor
    result = get("conversations.history", params)
    for m in result.get("messages", []):
        r = post("chat.delete", {"channel": CHANNEL, "ts": m["ts"]})
        if r.get("ok"):
            deleted += 1
            print(f"✅ {m['ts']} deleted")
        else:
            print(f"❌ {m['ts']} failed: {r.get('error')} — {m.get('text','')[:40]}")
            failed += 1
    cursor = result.get("response_metadata", {}).get("next_cursor")
    if not cursor:
        break

print(f"\nDone — deleted: {deleted}, failed: {failed}")
EOF
python3 /tmp/delete_msgs.py
```

> Note: The bot token can only delete messages posted by the bot itself, not messages sent by human users.

---

## Where to Find the Bot Token

The bot token (`xoxb-...`) lives in Railway:

1. Go to https://railway.com
2. Open the **UAEOPS_Bot** project
3. Click the service → **Variables** tab
4. Copy the value of `SLACK_BOT_TOKEN`

---

## Security Rules — Read Before Using

| Rule | Why |
|------|-----|
| Never paste tokens into a chat (Slack, Claude, email) | Anyone with the token can post and delete messages as the bot |
| If a token was shared by mistake, rotate it immediately | See rotation steps below |
| Credentials are saved in `~/.slack/credentials.json` — don't share that file | It contains your personal Slack auth token |
| The `xapp-...` token is NOT the bot token | It's the Socket Mode token — won't work for API calls |
| The `xoxb-...` token is the bot token | Use this for `chat.delete`, `conversations.history`, etc. |

### How to rotate the bot token (if accidentally shared)

1. Go to https://api.slack.com/apps
2. Select the **UAEOPS Bot** app
3. **OAuth & Permissions** → click **Reinstall App**
4. Copy the new `xoxb-...` Bot User OAuth Token
5. Go to Railway → UAEOPS_Bot service → **Variables** tab
6. Update `SLACK_BOT_TOKEN` with the new token
7. Click **Deploy** (bottom bar — "Apply changes")

---

## Common Problems and Fixes

| Problem | Cause | Fix |
|---------|-------|-----|
| `zsh: command not found: brew` | Homebrew not installed | Run the install command in Step 2 |
| `zsh: command not found: slack` | Slack CLI not installed | Run `brew install slack-cli` |
| `dquote>` stuck in terminal | Unclosed quote in pasted command | Press **Ctrl+C** to cancel, then paste as a single line |
| `not_authed` error | No token provided | Add `--token xoxb-...` to the command |
| `missing_scope` error | Wrong token type (CLI token, not bot token) | Use `--token xoxb-...` (from Railway), not the CLI credentials token |
| `message_not_found` on delete | Wrong timestamp, or message already deleted | Re-run `conversations.history` to get fresh timestamps |
| `token_revoked` | Token was rotated | Get the new token from Railway Variables |
| Slack modal doesn't appear after `/slackauthticket` | Typed in wrong place | Make sure you're in a message box in Slack, not in a browser URL bar |

---

## Quick Reference — Most Used Commands

```bash
# Check Homebrew
brew --version

# Install Slack CLI
brew install slack-cli

# Log in to Slack
slack login

# List recent messages in a channel
slack api conversations.history channel=CHANNEL_ID limit=20 --token xoxb-...

# Delete a specific message
slack api chat.delete channel=CHANNEL_ID ts=TIMESTAMP --token xoxb-...

# Check your logged-in credentials
cat ~/.slack/credentials.json
```

---

*This document is part of the UAEOPS Bot knowledge base. Keep it up to date when procedures change.*

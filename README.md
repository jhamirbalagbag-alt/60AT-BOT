# 60AT Bot

## Setup

1. Go to https://discord.com/developers/applications
2. Create new app → Bot → copy token
3. Enable ALL Privileged Intents (Presence, Server Members, Message Content)
4. Invite bot with permissions: Administrator

## Deploy on Railway (FREE, 24/7)

1. Go to https://railway.app and sign up (free)
2. New Project → Deploy from GitHub repo
3. Upload these files to a GitHub repo first
4. In Railway → Variables → add:
   BOT_TOKEN = your_token_here
5. Deploy → done, runs 24/7

## Commands

### Security (/ prefix)
- /antinuke enable/disable
- /antiraid enable/disable
- /antispam enable/disable
- /antilink enable/disable
- /setlogchannel

### Welcome/Leave
- /setwelcome channel:#channel
- /configwelcome message:"Welcome {user} to {server}!" banner:https://...
- /setleave channel:#channel
- /configleave message:"Goodbye {user}!" banner:https://...

### Moderation
- /ban /kick /mute /unmute /warn /warnings /purge /slowmode /lock /unlock /unban

### Triggers
- /settrigger trigger:hello message:Hello there!
- /removetrigger trigger:hello
- /listtriggers

### Levels
- /profile
- /leaderboard

### Tickets
- /setupticket category: support_role: log_channel:
- /ticket reason:help me

### Economy
- /balance /daily /give /richlist

### Utility
- /embed /poll /remind /rolemembers /giveaway /say /roleadd /roleremove /nick

### Games (AT prefix, type in chat)
- ATBLACKJACK [bet]
- ATMINES [bet] [bombs]
- ATCOINFLIP [bet] heads/tails
- ATRPS [bet] rock/paper/scissors
- ATROLL [sides]
- ATSLOTS [bet]
- ATCRASH [bet]
- ATHELP

## Streaming Status
Bot shows: Streaming "JOIN 60AT" on startup automatically.

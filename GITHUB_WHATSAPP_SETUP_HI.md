# GitHub + WhatsApp Auto-Setup Guide (Hinglish)

Is folder mein tumhare **9 original `india-trader-skills`** ke saath 3 nayi files jodi gayi hain:
1. `chart_gen.py` — Jo har breakout stock ka **Candlestick + Entry/SL/Target/Qty PNG Chart** banati hai.
2. `whatsapp_notify.py` — Jo बनी हुई Chart Image aur poora Trade Ticket tumhare **WhatsApp** (ya Telegram) par bhejti hai.
3. `auto_runner.py` & `.github/workflows/intraday_bot.yml` — Jo bina laptop khole **Monday se Friday automatic time par** poora pipeline run karte hain.

## Step 1: GitHub par Upload Kaise Karein
1. GitHub.com par jakar ek **New Repository** banao (Naam rakho: `nse-intraday-bot`, aur ise **Public** rakho taaki GitHub Actions ke free minutes unlimited milein).
2. Is zip file ke andar ki saari files aur folders (`.github`, `india-scanner`, `trader`, `auto_runner.py`, `chart_gen.py`, `whatsapp_notify.py` etc.) apne GitHub repo mein upload karke **Commit** kar do.

## Step 2: WhatsApp API Secrets Kahan Daalein
Apne GitHub Repo mein upar **`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`** par jao:

### Option A: Green-API (Sabse Aasan - Normal WhatsApp QR Scan)
1. [green-api.com](https://green-api.com/) par free Developer account banao aur apna WhatsApp QR scan karo.
2. GitHub Secrets mein ye 3 naam aur unki value daalo:
   - `WHATSAPP_PHONE` : `919876543210` (Apna 10-digit number `91` ke saath, bina `+` ke)
   - `GREEN_API_INSTANCE_ID` : Tumhara Instance ID
   - `GREEN_API_TOKEN` : Tumhara API Token

### Option B: Meta Official WhatsApp Cloud API
- `WHATSAPP_PHONE` : `919876543210`
- `META_WA_PHONE_ID` : Phone Number ID
- `META_WA_TOKEN` : Permanent Access Token

### Option C: Telegram Bot (100% Free & 1-Minute Setup Backup)
- `TELEGRAM_BOT_TOKEN` : `@BotFather` se mila token
- `TELEGRAM_CHAT_ID` : Tumhara Chat ID

## Step 3: Exact 5-Minute Timer (Optional Zero-Delay Trick)
- `.github/workflows/intraday_bot.yml` mein pehle se automatic `schedule: cron` laga hua hai jo Monday–Friday subah **9:00 AM IST** se **3:20 PM IST** tak har 5 minute par apne aap run hota hai.
- Agar kabhi GitHub ka free cron 5-10 minute late chale, toh tum [cron-job.org](https://cron-job.org/) par free account bana kar GitHub API URL (`https://api.github.com/repos/<USER>/<REPO>/actions/workflows/intraday_bot.yml/dispatches`) ko har 5 minute (9:35 AM se 2:45 PM IST) ping karwa sakte ho—isse 1 second ka bhi delay nahi aayega!

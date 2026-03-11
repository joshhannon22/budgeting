# Pushover Notifications Setup

This project uses [Pushover](https://pushover.net) to send real-time budget report summaries to your devices.

## Setup Steps

### 1. Create a Pushover Account
- Go to [pushover.net](https://pushover.net)
- Sign up for a free account
- Download the Pushover app on your iOS/Android device and log in

### 2. Register Your Application
- In your Pushover dashboard, go to "Create an Application/API Token"
- Fill in the details:
  - **Name:** Budget Reports (or your preferred name)
  - **Type:** Application
  - **Description:** Automated budget spending notifications
- Click "Create Application"
- Copy the **API Token** provided

### 3. Get Your User Key
- In your Pushover dashboard, find your **User Key** (shown at the top)
- This is different from your app token

### 4. Set Environment Variables
Add these to your shell profile (`~/.zshrc` or `~/.bash_profile`):

```bash
export PUSHOVER_APP_TOKEN="your_api_token_here"
export PUSHOVER_USER_KEY="your_user_key_here"
```

Then reload your shell:
```bash
source ~/.zshrc
# or
source ~/.bash_profile
```

### 5. Test the Setup
Run either script and it will automatically send a notification:

```bash
python monthly_report.py
python weekly_report.py
```

You should see:
```
✓ Notification sent via Pushover
```

## What Gets Sent

Each report generates a **TLDR (TL;DR)** summary that appears at the top of the full report and is sent as a push notification. Examples:

**Monthly:**
> 📱 TLDR
> On pace to overspend — Restaurants ($745) are your biggest drain. Cut 2 restaurant meals this week to save ~$100.

**Weekly:**
> 📱 TLDR
> Over budget at $962. Utilities ($366) hit hardest. Cut one restaurant meal to save ~$80. 🔴

## If Notifications Don't Work

If you don't set the environment variables, the scripts will still run normally—they just won't send notifications. You'll see:

```
⚠ Pushover notification not configured (set PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY)
```

## Troubleshooting

- **Missing requests module:** Run `pip install requests`
- **Status 400 errors:** Check that your token and user key are correct
- **Timeouts:** Check your internet connection (Pushover API requires network)
- **Messages not arriving:** Confirm the Pushover app is installed and you're logged in

## Optional: Pushover Priorities and Sounds

The current setup sends notifications at normal priority. You can customize this in `notifications.py`:

```python
payload["priority"] = 1  # 2=emergency, 1=high, 0=normal, -1=low, -2=quiet
payload["sound"] = "money"  # see Pushover docs for available sounds
```

## Learn More

- [Pushover Documentation](https://pushover.net/api)
- [Pushover Apps](https://pushover.net/apps)

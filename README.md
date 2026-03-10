
# Talon ETA Automated Dispatch Tracker

An automated schedule tracker and notification bot for student pilots using the Talon ETA flight management system.

Flight school schedules are incredibly dynamic. Checking the Talon portal fifteen times a day to see if you received a new flight block, a weather cancellation, or a hidden note from dispatch is frustrating and inefficient. I built this Python script to run silently in the background, check the portal automatically, and push formatted alerts directly to your phone the second something changes.

This project uses Playwright to mimic a real desktop browser. It logs into your portal, scrapes your schedule, compares it to the last known state, and sends alerts via Telegram. It also features webhook support to push your schedule to a TRMNL e-ink display so your desk always reflects your current flight line status.

## Core Features

* **Real-Time Change Detection:** Alerts you only when a new flight is scheduled, a flight is canceled, or a detail changes (like a new instructor, a different tail number, or an updated status).
* **Deep Remark Scanning:** Automatically hunts down and extracts hidden dispatcher remarks and tooltips while filtering out generic system noise like attendance buttons.
* **Telegram Integration:** Sends clean, formatted schedule blocks directly to your phone.
* **TRMNL Support:** Keeps your e-ink desk display perfectly synced with your schedule.
* **Serverless and Free:** Designed to run entirely on GitHub Actions. You do not have to pay for web hosting or keep your computer running.

---

## The Ultimate Setup Guide

You do not need to know how to code to use this. Follow these steps exactly, and you will have your own personal dispatch bot running in about ten minutes.

You will need three things before you start:

1. A free **GitHub** account.
2. The **Telegram** app installed on your phone.
3. Your standard **Talon ETA** login credentials.

### Step 1: Create Your Private Telegram Bot

To get alerts on your phone, you need to create a dedicated Telegram bot. This bot will privately message you whenever your schedule changes.

1. Open the Telegram app and search for the user `@BotFather`. This is the official bot creation tool.
2. Tap **Start** or send the message `/start`.
3. Send the message `/newbot`.
4. BotFather will ask you to choose a name for your bot (for example: "My Dispatch Bot").
5. BotFather will then ask you to choose a username. It must end in "bot" (for example: "AeroDispatchTracker_bot").
6. Once created, BotFather will give you a long string of text called an **HTTP API Token**. Copy this exact text and save it somewhere safe. Do not share this with anyone.
7. Next, go back to the main Telegram search bar and look for `@userinfobot`.
8. Send `@userinfobot` any message (like "Hello"). It will reply with your personal **Id** number. Copy this number. This tells the bot exactly who to send the messages to.

### Step 2: Copy This Repository (Forking)

You need your own private copy of this code so it runs on your account, not mine.

1. Create a GitHub account and log in.
2. Scroll to the top right corner of this exact page and click the **Fork** button.
3. Leave all the default settings as they are and click **Create fork**.
4. You will be redirected to a new page. You are now looking at your own private copy of the code.

### Step 3: Add Your Login Credentials

You need to give the script your login credentials safely. GitHub has a feature called "Secrets" that encrypts your passwords so no one else can see them.

1. In your forked repository, click on the **Settings** tab near the top.
2. On the left sidebar, scroll down to the "Security" section. Click on **Secrets and variables**, then click on **Actions**.
3. Click the green **New repository secret** button.
4. You will need to create four separate secrets. For each one, type the Name exactly as written below in all capital letters, paste the corresponding value, and hit Add secret.
* Name: `TALON_USER`
* Value: Your Talon login username.


* Name: `TALON_PASS`
* Value: Your Talon password.


* Name: `TELEGRAM_BOT_TOKEN`
* Value: The long token you got from BotFather in Step 1.


* Name: `TELEGRAM_CHAT_ID`
* Value: The ID number you got from userinfobot in Step 1.





*(Optional)* If you have a TRMNL e-ink display, create a fifth secret named `TRMNL_WEBHOOK_URL` and paste your plugin's webhook link there.

### Step 4: Turn On the Automation

By default, GitHub disables automated background tasks on newly copied repositories to prevent spam. You need to flip the switch to turn your bot on.

1. Click the **Actions** tab at the top of your repository.
2. You will see a warning message. Click the green button that says **I understand my workflows, go ahead and enable them**.
3. On the left sidebar, click on **Talon Scraper Schedule**.
4. A banner will appear in the middle of the screen. Click **Enable workflow**.

**Congratulations! Your bot is now live.** It will automatically wake up and check your Talon portal every two hours. If it finds a change, your phone will instantly buzz with the details.

---

## How to Trigger the Bot Manually

Sometimes you want to force the bot to check your schedule immediately. For example, if you just finished a ground lesson and know dispatch is updating your board for tomorrow.

1. Go to the **Actions** tab in your repository.
2. Click on **Talon Scraper Schedule** on the left sidebar.
3. On the right side of the screen, click the **Run workflow** dropdown menu.
4. Hit the green **Run workflow** button.
5. Give it about one minute to launch the browser, log in, and check for updates. If there is new information, it will text you immediately.

---

## Troubleshooting and Maintenance

* **Password Changes:** Talon requires you to update your password periodically. When you change your password on the Talon website, you must also come back to your GitHub repository, go to Settings > Secrets and variables > Actions, click the pencil icon next to `TALON_PASS`, and update it. The bot will fail to log in until you do this.
* **GitHub Activity Pause:** GitHub Actions is completely free, but GitHub will automatically pause your scheduled tasks if you do not log into GitHub or touch the repository for 60 days. To prevent this, simply log into GitHub once a month, go to the Actions tab, and manually trigger a run.

## Disclaimer

This is an unofficial, community-built tool. It is not affiliated with, endorsed by, or supported by Talon Systems or any specific flight academy. Web scrapers can break if the host website changes its layout. You are ultimately responsible for maintaining your own flight schedule, checking the official portal, and showing up to your briefs on time. Use this tool entirely at your own risk.

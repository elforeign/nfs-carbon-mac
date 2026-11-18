# Getting started

Setup turns **your own copy** of Need for Speed: Carbon into a native Mac app. It checks your game files,
translates and compiles the game on your Mac, converts your assets and installs the app. Nothing is uploaded, and
nothing it makes is meant to be shared.

## What you need

| | |
|---|---|
| **Mac** | Apple Silicon (M1 or later) with **macOS 14.5 or later** (provisional). |
| **The game** | Your own **Need for Speed: Carbon** for PC. Use the installed folder, its `NFSC.exe`, a `.zip` or `.7z` of the folder, or your original PC discs. Setup checks that `NFSC.exe` is the supported release. |
| **Xcode Command Line Tools** | Apple's free developer tools. Setup offers to install them; in Terminal, `xcode-select --install`. |
| **Disk space** | Free space for Setup's work folder and the installed app. Setup shows the estimate and free space at the destination. If a required volume is short on space, Setup asks you to free some. |

This project does not provide, link to, or explain how to obtain any game file. Use your own copy.

## Set up

1. Download the Setup disk image from the
   [latest release](https://github.com/elforeign/nfs-carbon-mac/releases/latest) and open it.
2. Open **NFS Carbon Native Setup**. The app is not notarized by Apple, so the first time macOS blocks it: click
   **Done**, then go to **System Settings > Privacy & Security** and click **Open Anyway** next to its name. You only
   do this once.
3. **Choose your Carbon PC source.** For discs, keep the disc images or copied disc folders together. Choose the
   official update for your disc edition and a compatible `NFSC.exe`. Choose where the app goes.
4. If asked, install Apple's Command Line Tools and wait for them.
5. Click **Build**. You see each step and its progress. The first build compiles the whole game on your Mac, so it
   takes a while. **Cancel** stops it and leaves anything already installed as it was.
6. When it finishes, click **Open**.

If something fails, Setup says which step failed and what to do. **Show Log** opens the full log.

## Playing

- **F10** (Fn+F10 on a Mac keyboard) opens the settings menu; so does the touchpad click on a DualSense or DualShock 4.
  The same key closes it. Up/Down and Left/Right change things; Esc closes it.
- Rows marked with a restart symbol take effect after **Restart game**.
- **Settings** such as the frame limit, anti-aliasing and the performance overlay are in the F10 menu.
- **Controllers** default to PlayStation buttons on PlayStation pads and Xbox buttons on other pads. **F10 > Controls > Button layout** also offers PC.

## Where things are

- Your saves and settings: `~/Library/Application Support/NFSMW-port/Carbon/`
- The game's logs: `~/Library/Logs/NFSMW-port/`
- Setup's saved choices: `~/Library/Application Support/NFSMW-Setup/Carbon/source-choices.json`. Keep this file for Update now,
  along with every original source it lists, including the disc update, compatible `NFSC.exe` and optional Xbox 360 files if used.
- Setup's cache: `~/Library/Caches/NFSMW-Setup/` (can be deleted after building; later builds may need to prepare files again).
- Setup's logs: `~/Library/Logs/NFSMW-Setup/`

## Updating

Use **F10 > Display & performance > Check for updates**, then **Update now** when offered. Follow the status,
quit and reopen when ready. Keep Setup's saved source choices and every original source they point to. If they moved or were
deleted, run the latest Setup and select them again. Careers and settings are kept.

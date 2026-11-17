# Need for Speed: Carbon (2006) — Native for Apple Silicon Macs

The real PC game, running natively on your Mac. Setup translates the game's own code for Apple Silicon (static
recompilation) and builds it on your Mac with a Metal renderer, native sound and native controller support.
No emulator, no Wine, no Windows.

> **You need your own copy of the game.** This repository contains **no game code, executables, artwork, sound,
> movies, tracks or textures.** Setup builds the game on **your** Mac from **your** game files. Nothing it builds is
> meant to be shared, and nothing is uploaded.

Watch the demo: [Carbon on a Mac (YouTube)](https://www.youtube.com/watch?v=Hp7fy4FyHwc).

## What you need

- An Apple Silicon Mac (M1 or later) with macOS 14.5 or later.
- Free disk space for the build (Setup checks before it starts and tells you if there is not enough).
- Your own Need for Speed: Carbon PC game: the installed game folder (the one with `NFSC.exe` and `TRACKS`).
  Carbon installs on its own; no other game is needed.

## Install

1. Download the **Setup app** from the [latest release](https://github.com/elforeign/nfs-carbon-mac/releases/latest)
   and open it. The first time, macOS asks you to allow it once (System Settings > Privacy & Security > Open Anyway).
2. Choose your Carbon game folder and click **Build**. Setup offers to install Apple's free Command Line Tools if you
   don't have them.
3. Play **NFS Carbon Native** from Applications.

Step by step: **[Getting started](GETTING_STARTED.md)**. Problems: **[Troubleshooting](TROUBLESHOOTING.md)**.

## Better than the original PC game

Press **F10** (Fn+F10 on a Mac keyboard, or click the touchpad on a DualSense or DualShock 4) for the settings menu.
**F10 > Help > Guide** explains the settings.

**Picture and looks**
- 16:9 widescreen with the HUD and menus laid out for it, resolutions up to 4K and your display's own size,
  anti-aliasing Off, 2x or 4x.
- Street lamps light the road and walls around them at night, and their light shows in the car paint.
- Lacquered car paint and real-looking chrome, wheels and glass.
- Optional sharper car reflections and day-night lighting.
- Look presets: Port, PC retail or your own picks.

**Performance**
- Native Apple Silicon code; shaders are prepared in the background so races don't hitch. A frame limit
  (Off, 120, 60 or 40) and an optional performance overlay.

**Controllers**
- DualSense, DualShock 4 and other controllers macOS supports, with the PC game's own button defaults and
  PlayStation button prompts.
- Rumble that follows slips, collisions, gear shifts and nitrous; DualSense adaptive triggers.
- An on-screen keyboard for typing with a controller.

**Sound**
- Surround on by default: 5.1 when your output has it, true stereo otherwise.
- A peak limiter that stops loud moments from clipping.

**Quality of life**
- Gameplay options: fixed heat level, no rubber banding, skip the intro movies or the prologue, more reward cards
  after a boss win, Unlock All, and the game's own cheats as switches.
- Record clips with sound, save the last 30 seconds, or stream to YouTube.
- No "Cannot connect to EA Nation!" prompt at start; Carbon keeps its saves in its own folder.
- Updates from inside the game, and problem reports (F10 > Help > Save report) ready for a GitHub issue.

What changed in each version: [changelog](CHANGELOG.md).

## Help and news

- **[Discord](https://discord.gg/d6HfMwdM9v)**: questions, help and news.
- **[GitHub issues](https://github.com/elforeign/nfs-carbon-mac/issues)**: bug reports.

## Also from this project: Most Wanted

**[NFS Most Wanted Native](https://github.com/elforeign/nfs-most-wanted-mac)** is the same kind of port for Need for
Speed: Most Wanted (2005), in its own repository.

## Credits and licenses

Unofficial; not affiliated with or endorsed by Electronic Arts, Criterion Games or Black Box. *Need for Speed* and
*Carbon* are trademarks of Electronic Arts Inc. Credits, bundled tools and licences: [NOTICE](NOTICE); the project's
own code is MIT ([LICENSE](LICENSE)) and the game is not relicensed.

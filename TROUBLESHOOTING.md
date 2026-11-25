# Troubleshooting

## Setup

**"Apple could not verify" when opening the Setup app** — it is not notarized by Apple. Click **Done**, then
**System Settings > Privacy & Security > Open Anyway**. You only need to do this once. The game app it builds is made
on your Mac.

**Setup stopped with an error** — it names the step, says what to do, and **Show Log** opens the full log. Logs are in
`~/Library/Logs/NFSMW-Setup/`. A failed build installs nothing and leaves any earlier install as it was.

**"Setup requires native Apple Silicon macOS"** — run the Apple Silicon version of Setup, not under Rosetta. If you
run `setup.sh` in Terminal, turn off **Open using Rosetta** for Terminal (Finder > Get Info) or use
`arch -arm64 ./setup.sh ...`. Intel Macs are not supported.

**"Intel-only (x86_64) developer tools found"** — Setup builds only with Apple's own tools in `/usr/bin`; the message
names the Intel-only tool it found. Install Apple's Command Line Tools (`xcode-select --install`), then build again.

**Developer tools missing, too old, or unable to compile** — Setup builds the game with Apple's Command Line Tools
(clang and the macOS SDK; full Xcode is not needed). Install or update them in **System Settings > General > Software
Update**, or run `xcode-select --install`, then build again. The macOS SDK must be version 14 or newer.

**"The Carbon game folder was not found" / "has no NFSC.exe or no TRACKS folder"** — choose the installed PC folder with
`NFSC.exe` and `TRACKS`, its `NFSC.exe`, or a `.zip` or `.7z` of the folder. You can also use your original PC discs. Keep the
disc images or copied disc folders together and select the official update for your disc edition and a compatible `NFSC.exe`.

**"NFSC.exe is not the supported PC release of Need for Speed Carbon"** — the port is a translation of one release of
the PC game, the compatible version 1.4 `NFSC.exe`. Other releases contain different code and would not work. The
message shows the version your file states. The executable on the Carbon disc is copy-protected and can't be used.
Setup changed nothing.

**"This disc isn't a supported Carbon PC disc edition"** or **"Setup can't read this .mdf"** — Setup reads one Carbon
PC disc edition, as an `.iso`, an ISO-compatible `.mdf` or the disc's files. Raw-sector `.mdf`/`.bin` images can't be
read. Choose your installed Carbon folder (updated to 1.4) instead. If you report it, include the disc id the message shows.

**"macOS did not allow Setup to read ..."** — macOS protects Desktop, Documents, Downloads and external drives. Open
**System Settings > Privacy & Security > Files and Folders** and allow Setup (or Terminal, if you run `setup.sh`); for an
external drive, allow **Removable Volumes**. Or move the game folder somewhere else, then try again.

**"Not enough space on ...: N GB more needed"** or **"There is not enough free disk space ..."** — free that much space
on the volume the message names (the Review page shows how much each volume needs), then press **Retry**.

**"Another Setup is using this work or cache folder"** — wait for the other Setup to finish, or quit it.

**"Dependency checksum failed" or "Setup source is missing ..."** — the downloaded Setup is damaged or incomplete.
Download it again from the releases page.

## Playing

**The game won't open, or quits at once** — look at the newest log in `~/Library/Logs/NFSMW-port/`. It begins with the
app version and your Mac. Please include it when you report a problem.

**The F10 menu doesn't open** — on a Mac keyboard press **Fn+F10**. On a DualSense or DualShock 4, click the touchpad.

**Check for updates says nothing new** — it asks GitHub only when you press it. "No answer: press to retry" means it
could not reach GitHub.

**Update now failed or asks for sources** — choose **F10 > Display & performance > Open log**. Keep
`~/Library/Application Support/NFSMW-Setup/Carbon/source-choices.json` and every original source it lists, including
the disc update, compatible `NFSC.exe` and optional Xbox 360 files if used. If sources are missing or moved, run the
latest Setup and select them again, then retry.

## Reporting a bug

Open an issue on [GitHub](https://github.com/elforeign/nfs-carbon-mac/issues), or ask in #help on the
[Discord](https://discord.gg/d6HfMwdM9v). Include your Mac model and macOS version, what you did, what you expected,
and the game's log (and Setup's log if Setup failed). For a problem in Most Wanted alone, use the
[Most Wanted repository](https://github.com/elforeign/nfs-most-wanted-mac/issues).
Please do **not** attach game files or saves that contain game data.

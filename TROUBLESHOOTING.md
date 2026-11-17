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

**"The Carbon game folder was not found" / "has no NFSC.exe or no TRACKS folder"** — choose the installed Need for
Speed Carbon (PC) folder that holds `NFSC.exe` together with `TRACKS`.

**"NFSC.exe is not the supported PC release of Need for Speed Carbon"** — the port is a translation of one release of
the PC game. Other releases contain different code and would not work. Setup changed nothing.

**"There is not enough free disk space"** — free some space on the volumes you chose for the app and for Setup's
work folder, then build again.

**"Another Setup is using this work or cache folder"** — wait for the other Setup to finish, or quit it.

**"Dependency checksum failed" or "Setup source is missing ..."** — the downloaded Setup is damaged or incomplete.
Download it again from the releases page.

## Playing

**The game won't open, or quits at once** — look at the newest log in `~/Library/Logs/NFSMW-port/`. It begins with the
app version and your Mac. Please include it when you report a problem.

**The F10 menu doesn't open** — on a Mac keyboard press **Fn+F10**. On a DualSense or DualShock 4, click the touchpad.

**Check for updates says nothing new** — it asks GitHub only when you press it. "No answer: press to retry" means it
could not reach GitHub.

**Update now failed or asks for sources** — choose **Open log** in Display & performance > Online. Keep your original
game folder and `~/Library/Application Support/NFSMW-Setup/source-choices.json`. If missing or moved, run the latest
Setup and select them again, then retry.

## Reporting a bug

Open an issue on [GitHub](https://github.com/elforeign/nfs-carbon-mac/issues), or ask in #help on the
[Discord](https://discord.gg/d6HfMwdM9v). Include your Mac model and macOS version, what you did, what you expected,
and the game's log (and Setup's log if Setup failed). For a problem in Most Wanted alone, use the
[Most Wanted repository](https://github.com/elforeign/nfs-most-wanted-mac/issues).
Please do **not** attach game files or saves that contain game data.

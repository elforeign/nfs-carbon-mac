# Changelog

## 1.2.0

- **Sharper rear-view mirror:** with the game's Rearview Mirror option on, the mirror shows the same buildings and scenery detail as the main view. The option stays off until you turn it on.
- **Skippable credits:** Back closes the credits from the menu and at the end of the career.
- **Fixed:** traffic headlights no longer paint bright patches on the road at midday with the day-night clock on; F12 screenshots no longer freeze the picture for a moment.
- **Going back to an older version:** run that version's Setup again.

## 1.1.0

- **Send to GitHub:** F10 > Help > Report a problem can now preview your report and post it to Carbon's GitHub issues, or open the issue form. Your home folder paths are hidden first, and nothing is sent without your choice.
- **Update now works inside Carbon:** the in-game update hands over to the new version, checks that it is the announced one and newer than yours, and ignores redirects from the version feed.
- **Setup takes the same inputs as Most Wanted's:** a .7z of your PC game, and a mounted or copied original disc folder with the same helper controls as an .iso. The PC picker no longer offers an Xbox 360 .iso as the base game, and Setup checks unusual files, archives and free space before it starts.
- **Rumble Off is fully off:** the triggers and the controller light are left alone too. Rumble goes to the controller you are playing with and moves to another one if you unplug it.
- **No stuck keys:** Shift, Ctrl and Alt are released when you switch away from the game, and menu keys are released when you change controller.
- **120 Hz screens:** the game speed follows the screen when you move it between a 60 Hz and a 120 Hz display.
- **Safer career autosave:** a failed save can be tried again and no longer blocks the next one.
- **Fixed:** F12 screenshots no longer contain unrelated pixels; Dolby output is no longer silent at the lowest audio latency; movie sound stays in step after a stall; F10 Surround matches the game's Audio menu; the daylight no longer jumps at 06:00 and 18:00; career races follow their own clock; a 15 second pause in the background no longer files a hang report; boss reward picks are no longer cut short; the minimap atlas turns on only when its maps are valid; hang reports keep the menu state that explains them; the correct build number shows in reports.

## 1.0.1

- **Update now fixed:** Update now could stop with "The prepared update folder or its retained tools failed verification" when your game files were copied from a USB stick, network share or another computer.

## 1.0.0

First release of NFS Carbon Native for Apple Silicon Macs.

- **Carbon on your Mac:** Setup builds a native app from your own Need for Speed: Carbon PC game. Metal renderer,
  CoreAudio sound, widescreen. It installs alone: only your Carbon folder is needed.
- **Controllers:** PlayStation buttons by default on PlayStation pads and Xbox buttons on other pads. **F10 > Controls > Button layout** also offers PC. DualSense, DualShock 4 and other
  controllers macOS supports; rumble.
- **Picture and looks:** 4K and 16:9, anti-aliasing, a frame limit, contact shadows (Off by default; an F10 Picture row), lacquered paint, chrome and glass.
- **Sound:** surround on by default, with a limiter against clipping.
- **Settings and updates:** the F10 settings menu, and Check for updates / Update now inside the game.
- **Coming later:** Rockport and Palmont in one world. Most Wanted has its own repository: [nfs-most-wanted-mac](https://github.com/elforeign/nfs-most-wanted-mac).

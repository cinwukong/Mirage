# Mirage — your voice assistant

Mirage listens for its name in the background. Say **"mirage"** and then a command.
Speech recognition is fully offline, so your audio never leaves your computer.

## The app
Double-click **start_mirage.bat** to open the app (`mirage_app.py`).
- **Home**: an animated orb that reacts to your voice, plus a chat of everything you and Mirage have said. You can also type commands.
- **Settings**: microphone choice with a live level meter, mute, voice, speed, volume, wake words, beep, AI key, start with Windows, and quit.
- **Shortcuts**: add your own websites and apps ("mirage open <name>"), plus a list of things you can say.

Closing the window keeps Mirage running in the **tray** (the icons in the bottom-right of the taskbar).
Click the tray icon to open it again, or right-click it to mute or quit. You can also say "mirage show yourself".

## Updating
Go to **Settings → App → Check for updates**. If there's a new version, click **Install** and Mirage
downloads it from GitHub and restarts itself. Your settings (`config.json`) and the speech model are
never touched. Mirage also checks quietly each time it starts and tells you in the chat when an update is out.

## Files
- `install.bat`: installs everything and opens the app
- `start_mirage.bat`: opens the app, or brings it forward if it's already running
- `stop_mirage.bat`: force-stops Mirage
- `add_to_startup.bat`: starts Mirage with Windows. The same setting is in Settings > App.
- `mirage.log`: everything Mirage heard and did. Look here when something doesn't work.

## Memory (Obsidian)
In **Settings → Memory**, pick your Obsidian vault. Mirage writes to a `Mirage` folder inside it:
`Memory.md` (things you ask it to remember), `To-do.md`, and optional daily logs. When answering,
Mirage also searches the rest of your vault. Everything is plain notes you can edit or delete.

## Accurate hearing (Whisper)
In **Settings → Microphone**, click **Install Whisper**, then choose **Accurate**. Mirage still listens
for "mirage" with the fast recognizer, but your commands are transcribed by Whisper (offline).

## Things you can say
"mirage open youtube", "mirage play lofi music", "mirage search …", "mirage set a timer for 10 minutes",
"mirage what time is it", "mirage volume up / mute / pause / next song", "mirage take a screenshot",
"mirage type …", "mirage lock my computer", "mirage close window", "mirage mute microphone",
"mirage show yourself", "mirage shut down" (stops Mirage, not your PC),
"mirage remember that …", "mirage what do you know about …", "mirage add … to my to-do list",
"mirage remind me at 5 pm to …", "mirage what's the weather", "mirage who is …",
"mirage what's on my screen" (needs the AI brain), "mirage playtest" / "stop playtest" (Roblox Studio).

With an Anthropic API key (Settings > AI brain), Mirage can also answer questions and understand free-form requests.

# Mirage

A voice assistant for Windows, in the spirit of JARVIS. Say **"mirage"**, then what you want.

- **Shortcuts first.** Opening apps and websites, timers, reminders, your to-do list, notes, weather,
  media keys and Roblox Studio are handled by Mirage itself: instant, offline and free.
- **Claude Code for everything else.** Questions and bigger tasks go to Claude Code, using your Claude
  account. It can use Mirage's skills, search the web, read files and (if you allow it) run commands.
- **Memory in Obsidian.** What you ask Mirage to remember becomes linked notes in your vault, so it
  shows up as a web in Obsidian's graph.
- **A hologram in the corner.** The purple headband appears while Mirage listens, thinks and speaks,
  with optional subtitles.

## Install
1. Install Python 3.9 or newer from python.org (tick "Add python.exe to PATH").
2. Download this repository and double-click `install.bat`.
3. In Mirage, open **Settings → Brain** and click **Install Claude Code**, then **Log in**.

After that, `start_mirage.bat` opens Mirage, and **Settings → App → Start with Windows** starts it
hidden in the tray when you log in. Updates install from **Settings → App → Check for updates**.

## Pages
- **Home**: the hologram, your conversation, and a box to type to Mirage.
- **Memory**: things Mirage remembers, your to-do list and reminders. Add, tick off or delete.
- **Shortcuts**: your own voice commands ("mirage good morning" → open Spotify), plus websites,
  apps and Roblox games Mirage can open.
- **Settings**: brain, listening (microphone, wake words, Whisper), voice (Windows or VoiceStudio),
  hologram, memory (Obsidian vault), skills (weather city, music) and app options.

## Files
- `mirage_app.py`: starts Mirage (and offers to install missing parts after an update)
- `ui_web.py` + `web/`: the window and interface
- `mirage.py`: listening, speaking and the built-in shortcuts
- `brains.py`: Claude Code and API-key brains, and the skills they can use
- `skills.py`: memory, to-dos, reminders, weather, facts, Roblox Studio
- `hearing.py`: Whisper; `hologram.py`: the corner hologram
- `config.json`, `memory/`, `reminders.json`, `model/` are kept on your PC and never uploaded.

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
- **Settings**: brain, listening (microphone, wake words, hearing), voice (Mirage, Windows or VoiceStudio),
  hologram, memory (Obsidian vault), skills (weather city, music) and app options.

## Spotify
Save playlists on the **Shortcuts** page (in Spotify: right-click a playlist → Share → Copy link to playlist).
Then "mirage play chill" or "mirage switch to gym" opens it in the Spotify app and presses play.
"mirage stop the music", "play music", "next song" and "what's playing" work too. No Spotify login needed.

## Mirage's own brain
**Settings → Brain → Mirage → Install** downloads [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT) and an
open AI model that runs on your graphics card: **Qwen3.5 9B** (smarter, about 7 GB with its vision add-on) or
**Gemma 4 E4B** (lighter, about 6 GB). Both are Apache-2.0, use Mirage's skills as tools, and can look at your screen.
- Free and private: nothing leaves your PC, and there are no usage limits.
- After a few idle minutes it hands graphics memory back (for games) and wakes up on the next question.
- Start a question with **"think hard"** for tough ones: Claude answers if Claude Code is set up, otherwise the
  local model takes longer to think it through.
- Write Mirage's **personality** in your own words under Settings → Brain.
- Stored in `%LOCALAPPDATA%\Mirage\brain`.

## Mirage's own voice and hearing
**Settings → Voice → Mirage → Install** downloads Mirage's voice and ears (about 830 MB), which run on this PC
with no other apps:
- **Voice:** [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0), 28 English voices (Bella is the
  default), with pitch and a robotic "hologram" effect. Lines Mirage says often are saved, so they play instantly.
- **Hearing:** NVIDIA [Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0) writes
  down what you say, and Silero VAD (MIT) tells when you're talking. Parakeet also listens for "mirage".
- Both run with [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Apache-2.0). Models are stored in
  `%LOCALAPPDATA%\Mirage\speech`.

## Conversations
- **Keep listening after replies** (Settings → Listening): after Mirage answers something you said, it listens for
  about 8 seconds (the hologram turns gold), so you can carry on without saying "mirage" again. Say "that's all",
  "never mind", "okay" or "thanks" to end it.
- **Interrupt by talking:** talk over Mirage and it stops, then treats what you're saying as the next command.
  "Stop" or "shut up" just stop it; "hold on" stops it and keeps listening.
- Mirage notices when it can hear its own voice (speakers instead of a headset). Then only "Mirage, …" cuts it off,
  so it doesn't interrupt itself. It switches back when you put the headset on.

## Memory
- **Things it remembers:** say "remember that …", or let it notice: when a conversation goes quiet, Mirage's own
  brain picks out lasting things about you (what you like, your projects, the people in your life) and saves
  them, tagged *noticed*. If you correct something ("actually I play drums now"), the old fact is replaced.
  Passwords, codes and card numbers are never kept, even if you ask.
- **Get to know me:** say "get to know me" (or press the button on the Memory page) and Mirage asks a few questions.
- **Past chats:** conversations are kept on this PC (not in your notes), so you can ask "what did we talk about
  yesterday?" or search them on the Memory page. Turn it off or delete it under **Settings → Memory**.
- Everything is grouped by who or what it's about on the Memory page, and stays as linked notes in Obsidian.

## Windows and using your PC
- **Window shortcuts** (no brain needed): "switch to Discord", "snap this left", "put Chrome and Discord side by
  side", "move this to my other screen", "minimize Spotify", "minimize everything", "maximize", "what's open",
  "close Spotify", "close this tab".
- **The brain can use your mouse and keyboard** for things like "open Discord and go to my messages": it reads the
  buttons, links and text boxes of the window you're using (Windows UI Automation, like a screen reader), or looks
  at a screenshot with those controls numbered, then clicks, types, presses keys and scrolls. The hologram turns
  coral while it does.
- **Safety:** press **Esc** or move the mouse to stop it at once (saying "stop" works too). It never types into
  password boxes, and it asks you before clicking things like Send, Delete or Buy, or pressing Enter in a chat.
  Turn it off with **Settings → Brain → Let Mirage use my mouse and keyboard**.

## Files
- `mirage_app.py`: starts Mirage (and offers to install missing parts after an update)
- `ui_web.py` + `web/`: the window and interface
- `mirage.py`: listening, speaking and the built-in shortcuts
- `local_brain.py`: Mirage's own brain (llama.cpp)
- `brains.py`: Claude Code and API-key brains, and the skills they can use
- `skills.py`: memory, to-dos, reminders, weather, facts, Roblox Studio; `spotify.py`: Spotify control
- `hologram.py`: the corner hologram; `speech.py`: Mirage's own voice and hearing
- `config.json`, `memory/`, `reminders.json`, `model/` and `voices/` are kept on your PC and never uploaded.
  The voice model is stored in `%LOCALAPPDATA%\Mirage\voice_model`, outside the Mirage folder.

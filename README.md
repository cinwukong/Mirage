# Mirage

A voice assistant for Windows that runs on your own PC. Say **"Mirage"**, then what you want.

- **Shortcuts that need no AI:** open apps and websites, switch and snap windows, timers, reminders, your to-do
  list, notes, weather, media keys and Spotify. Instant, offline and free.
- **Its own brain:** an open AI model on your graphics card answers questions, holds a conversation, can look at
  your screen and use your mouse and keyboard for you. Free and private. Claude works too, if you'd rather.
- **Its own voice and ears:** a natural voice (Kokoro) and accurate hearing (NVIDIA Parakeet), both on your PC.
- **It remembers:** what you tell it, and things it notices about you, as notes you can read (and open in
  Obsidian). Past conversations are searchable.
- **Talk naturally:** carry on without repeating "Mirage", and talk over it to interrupt.
- **A hologram in the corner** while it listens, thinks and speaks, with optional subtitles.

## Install
1. Download **`Mirage-Setup-<version>.exe`** from [Releases](https://github.com/cinwukong/Mirage/releases/latest)
   and run it. Windows 10 or 11, 64-bit.
2. Windows may say it protected your PC, because the installer isn't signed: click **More info**, then
   **Run anyway**.
3. Mirage walks you through the rest: your name, your microphone, its voice and hearing (about 830 MB), and its
   brain (about 6 GB; an NVIDIA graphics card is recommended).

Mirage updates itself from **Settings → App → Check for updates**, from published releases only, and it keeps the
previous version to fall back on if the new one doesn't start. It installs to
`%LOCALAPPDATA%\Programs\Mirage` and needs no administrator rights.

## Where your things are
- **Settings, chat history, the voice and the brain:** `%LOCALAPPDATA%\Mirage`. They stay when you update.
  When you uninstall, Mirage asks whether to delete them.
- **Notes:** `Documents\Mirage`, or an Obsidian vault you pick under **Settings → Memory**.
- Nothing is sent anywhere unless you choose Claude as the brain, or ask for the weather or a web search.

## What you can say
| | |
|---|---|
| Apps and sites | "open YouTube", "open Discord", "search for cheap headphones" |
| Windows | "switch to Chrome", "snap this left", "put Chrome and Discord side by side", "minimize everything" |
| Timers and reminders | "set a timer for 10 minutes", "remind me at 5 pm to call mom" |
| To-dos and memory | "add buy milk to my to-do list", "remember that my favourite colour is purple", "get to know me" |
| Music | "play lofi beats", "pause", "next song", "play chill" (a Spotify playlist you saved) |
| Your PC | "open Discord and go to my messages" (the brain uses your mouse and keyboard; Esc stops it) |
| Questions | anything else goes to the brain |
| Quiet | "do not disturb for two hours", "you can talk again" |

Make your own voice commands on the **Shortcuts** page, and turn off built-in ones you don't want.

## Speaking up on its own
Rarely, and only when it's worth it: a date it remembers is coming up, a task in your notes is due, or once a day
your to-do list. It stays quiet during quiet hours (23:00 to 08:00 by default), when you're away, and while a game
fills the screen. Your own reminders always come through. See **Settings → Speaking up**.

## Using your mouse and keyboard
The brain reads the buttons and text boxes of the window you're using (Windows UI Automation, like a screen
reader) or looks at the screen, then clicks, types and presses keys. Press **Esc** or move the mouse to stop it.
It never types into password boxes, it starts programs only through apps you have (never the Run box or a command
line), and it asks before sending, deleting or buying anything, or typing into a terminal. Turn it off under
**Settings → Brain**.

## Building it yourself
The installer is built by GitHub Actions (`.github/workflows/build.yml` runs `installer/build.ps1` on Windows):
a private copy of Python 3.13 with every package, Mirage's code in `app\`, a small `Mirage.exe` launcher
(`installer/launcher.c`) so Windows shows Mirage rather than Python, and an Inno Setup installer
(`installer/mirage.iss`). To run from source instead: install Python 3.11+, `pip install -r requirements.txt`,
then `pythonw mirage_app.py`.

### Releases and updates
A release is just: bump `version.txt` and push to `main`. The build publishes the release with the installer and the
update files installed copies use (`mirage-app-<version>.zip` and `mirage-update.json`, made by `release_tool.py`).
Installed copies only update from published releases, never from `main` directly, and check the download against
`mirage-update.json` before installing it.

## Credits
Mirage stands on these, each under its own license:
- Voice: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0)
- Hearing: NVIDIA [Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0),
  [Silero VAD](https://github.com/snakers4/silero-vad) (MIT), [Vosk](https://alphacephei.com/vosk/) (Apache-2.0)
- Running them: [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Apache-2.0),
  [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT)
- Brains: [Qwen 3.5](https://huggingface.co/Qwen) (Apache-2.0), [Gemma 4](https://ai.google.dev/gemma/terms)
  (Gemma Terms of Use), or [Claude](https://claude.ai)
- The app: [Python](https://www.python.org) (PSF), [pywebview](https://pywebview.flowrl.com) (BSD),
  [Inno Setup](https://jrsoftware.org/isinfo.php)

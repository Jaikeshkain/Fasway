# Fasway

Use your Android phone as a **touchpad** and **voice keyboard** (English, Hindi and mixed Hinglish) for your Windows laptop or Mac.

## Android app
A native Android app lives in [`app/`](app/README.md). It pairs by scanning the QR, finds the laptop on any Wi-Fi by itself, pins the laptop's certificate (no "Not secure" warning), and has real landscape full screen and reliable clipboard copy. The web app below keeps working too.

**Several laptops:** the app remembers every laptop you pair. Tap the laptop's name at the top of the app to switch to another one, **Add a laptop** (scan its QR), rename one, or forget one. One laptop is controlled at a time, and switching takes about a second. **Send clipboard** and **Copy to laptop** go to the laptop you have selected. Switching stops file transfers that are still running (the app asks first).

## Assistant
Tap **✨** in the Android app and say or type what you want, in English, हिंदी or Hinglish.
- **Built-in commands** ("volume 30", "agla gaana", "YouTube kholo", "laptop lock karo") run instantly on the laptop, with no internet, no key and no cost.
- **Everyday sentences without a key** ("can you turn the sound down a bit", "volume 30 aur YouTube kholo", "search cats on YouTube", "battery kitni hai") work from the words that matter. This covers volume, brightness, music, power, opening apps and sites, search and simple typing. If it isn't sure, it does nothing and says so.
- **Everything else** goes to the AI model you choose, once you add an Anthropic (Claude) or OpenAI (GPT) API key with **AI API key** in the Fasway window on the laptop. Keys are kept in the system's credential store (Windows Credential Manager / macOS Keychain) and never go to the phone. You pay that company directly for what you use.
- **Model:** choose **Opus 5.5** (smartest), **Haiku 5.5** (fastest and cheapest), **GPT-6 Luna** (fast and cheap) or **GPT-6 Sol** (stronger) on the assistant screen. Each needs its own company's key. With Opus, a request its safety checks decline is automatically retried on Anthropic's fallback model.
- **Spending limits:** ₹30 per task and ₹150 per day by default; change them in the ⋮ menu. The rupee figures use a fixed rate and our own estimate from token counts, so check your Anthropic or OpenAI console for the exact bill.
- **Installed apps first:** "open ChatGPT" opens the ChatGPT app if it's installed, and the website only if it isn't.
- **YouTube:** "lo-fi music chala do" plays the top result; "search … / dikhao" only searches.
- **Buttons inside apps (Windows):** the assistant can read a window's buttons, menus and text boxes and press or fill them, e.g. "log out of Voice Logger". It never types into password boxes, and buttons like Log out, Delete, Pay or Send ask you first.
- **Web pages:** it reads pages in your **Windows default browser** (Edge, Chrome or Brave), in the profile you're using. The first time, the browser has to be reopened once with page reading turned on; the assistant asks first, and your tabs come back.
- **Voice conversation:** the conversation screen keeps listening until you close it, and replies are read aloud.

### Routines
One phrase runs several steps at once, with no AI and no cost (they work without an API key).
- **Starter routines:**
  - **🌙 Good night** ("good night", "so raha hoon"): mute, brightness 10%, sleep.
  - **📚 Study mode** ("study mode", "padhai mode"): lo-fi music on YouTube, volume 30%.
  - **☀️ Good morning** ("good morning"): unmute, volume 40%, brightness 80%, then the time and battery.
- **Run one:** say its name or one of its phrases to the assistant, or tap it under **Apps → Routines**.
- **Make your own:** **Apps → Routines → New**. Pick steps: volume, mute, brightness, play on YouTube, open an app or website, music, lock/sleep/shut down, keys, a quick action, wait. Or ask the assistant (needs a key): *"make a routine called gym time: volume 80 and play workout songs"*.
- **Safety:** each step goes through the same checks as everything else. Sleep, shut down and other risky steps still ask on the phone. If you say no, or a step fails, the other steps still run. Routines can't type text or press buttons inside apps.
- Stored on the laptop in `data/routines.json`.

**What it can't do, whatever it's asked:** run terminal commands, open terminals or script files, delete files, or read your clipboard.
**What it asks you first:** shutting down, restarting, sleeping or signing out; closing a window; unusual shortcuts; quick actions that run a command; pressing risky buttons (log out, delete, pay, send); reopening the browser; typing into a terminal or a window that looks like a sign-in or payment page. No answer in 2 minutes counts as no, and **STOP** ends a task at once.

These limits are enforced by Fasway's code, not by the AI. They can't catch everything: the AI can still type into ordinary windows and open links on its own, so watch what it does on sensitive tasks. Requests sent to the AI include your words, the active window's title and what its tools read (such as the list of open windows). A log of every action is in `data/fasway.log`.

## Security
- **A phone needs your OK on the laptop** before it can connect the first time (see [Pairing](#pairing-and-trusted-phones)).
- **Confirm it's you (Android app):** restart, shut down, sign out, sleep, quick actions that run a command, and allowing an assistant step first ask for your fingerprint, face or screen lock. After one check, more of these within a minute don't ask again. Turn it off in ⚙ Settings (turning it off asks too). It needs a screen lock on the phone.
- **New commands are allowed on the laptop:** a quick action that runs a command (the *Run a command* type, or a macro with `cmd` steps) is set up on a phone, so the first time it runs, or after it's changed, the laptop shows **"Run this command?"** with the exact command. After you allow it, it runs without asking until it's changed. Someone with your phone can't add and run a new command without you at the laptop.
- **Old phones are forgotten:** a phone that hasn't connected for **90 days** is removed from Trusted phones and has to be approved again, so a sold or lost phone stops working by itself.
- Fasway can run as administrator (see [Notes](#notes)); a trusted phone can then control everything on the laptop. Only approve phones you own.

## Tests
- Laptop: `python -m unittest tests.test_core tests.test_routines tests.test_agent`. These use a fake laptop and scripted AI replies, so they spend nothing.
- Android app: `flutter test` in `app/`.
- GitHub runs both on every push. The laptop apps are only built when the laptop tests pass, and the Android APKs are built too.

## Start

**Windows:** double-click **`run.bat`**. The first run installs dependencies into `.venv`. Fasway then runs **in the system tray** (the blue **F** icon next to the clock), with no console window.
- **Tray icon:** green dot = a phone is connected. Click it to show the pairing QR; right-click for options and **Quit**.
- **Closing the QR window** hides it; Fasway keeps running.
- **Running `run.bat` again** while Fasway is running just opens its window.
- **Start with Windows** (tick it in the window or the tray menu): Fasway starts silently at sign-in. Together with **Always run as administrator**, it starts with admin rights **without a UAC prompt each time** (it uses a Task Scheduler task; you approve one prompt when you turn it on).
- **Log file:** `data/fasway.log`.

### Pairing and trusted phones
- **First connection:** the first time a phone connects, the laptop asks **"A phone wants to connect"** with the phone's name and address. You choose **Allow** or **Deny**, and the phone shows *"Approve this phone on your laptop"* while it waits.
- **After that:** each approved phone has its own secret key; the laptop stores only a hash of it in `data/devices.json`. The phone then connects without asking, even after **New pairing code**.
- **On their own, the QR code and link are not enough to control the laptop:** a phone also needs your approval.
- **Trusted phones** in the Fasway window lists each phone, whether it's connected, and when it was last seen. **Remove** disconnects a phone immediately; it has to be approved again to come back.
- **New pairing code** only stops old QR codes from *asking* to pair; trusted phones keep working.
- **After 90 days without connecting**, a phone is forgotten and has to be approved again.

### The phone link that keeps working
Each laptop gets its own permanent address, for example **`https://fasway-7uble.local:8443`**, which the QR code uses by default.
- It's announced on the network (mDNS/Bonjour), so it doesn't depend on the laptop's IP address or computer name.
- The same bookmark or home-screen shortcut works on any Wi-Fi, even after the IP changes.
- When the laptop joins a different network, the tray shows a notification and the address keeps working.
- If a phone can't open `.local` addresses, pick an IP address in the **Address** list instead.

**macOS:** see [macOS setup](#macos-setup) below.

A window opens with a **QR code**. Scan it with your phone camera; the phone and laptop must be on the same Wi-Fi.

### First time on the phone
1. Chrome shows **"Your connection is not private"**. That's expected, because the laptop uses its own certificate. Tap **Advanced → Proceed to …**.
2. Allow the **microphone** when you first tap the mic.
3. Optional: Chrome menu ⋮ → **Add to Home screen** for one-tap access.

### First time on Windows
When Windows Firewall asks, allow Python on **Private networks**.

## Touchpad
| Gesture | Action |
|---|---|
| 1 finger move | Move cursor |
| Tap | Left click (tap twice for double click) |
| 2-finger tap | Right click |
| 3-finger tap | Middle click |
| 2-finger drag | Scroll (vertical + horizontal) |
| Double-tap, then drag | Drag / select |
| Hold **Left** button + move on pad | Drag |

You can adjust speed, acceleration, scroll speed and natural scrolling with ⚙ on the phone.

## Live screen preview (WebRTC)
Tap **🖥** in the top bar to show the laptop screen, with its cursor, above the touchpad (also shown on the Keyboard tab).

**Touch the preview to control the laptop.** The mode button cycles 🖱 → 👆 → 👁. A blue ring highlights the cursor, which is tiny at phone size.

**🖱 Trackpad mode (default):** the preview works as an invisible touchpad, so your finger never covers what you're looking at.

| On the preview | Does |
|---|---|
| Slide one finger (anywhere) | Moves the cursor from where it is, by the same distance your finger moves on the preview |
| Tap | Click wherever the cursor is |
| Double-tap | Double click |
| Double-tap, then slide | Drag or select (the ring fills in while held) |
| Long-press / 2-finger tap | Right click |
| 2-finger slide | Scroll |
| Pinch | Zoom the preview around the cursor (up to 6×); the view then follows the cursor |

**👆 Direct mode:** tap exactly where you want to click, long-press to right-click, drag to drag. Pinch zooms, 2-finger drag pans (when zoomed) or scrolls, and a 2-finger tap resets the zoom.

**👁 View only:** touches only zoom and pan the preview.

The preview's toolbar:
- **🔇 / 🔊** plays the laptop's sound on the phone, in the same stream as the video. It's Windows only; a Mac would need an extra audio driver.
- **🖱 / 👆 / 👁** switches the touch mode.
- **⛶** goes full screen in landscape. In full screen, **⌨** opens the phone keyboard so you can type. The back gesture or ⛶ leaves full screen.
  - If Chrome won't rotate the page (for example because of the certificate warning, or because auto-rotate is off), the preview is turned sideways for you: just hold the phone sideways.
  - **⟳** switches between sideways and upright by hand.
- **⤢** switches between a small and a large preview.
- ⚙ → **Screen preview quality**:

  | Setting | Resolution / frame rate |
  |---|---|
  | Low | 480p / 20 fps |
  | Medium (default) | 720p / 30 fps |
  | High | 1080p / 30 fps |

  The change applies instantly.
- The stream runs only while the Touchpad tab is open and the screen is on, to save battery.
- It shows the monitor the cursor is on.
- Windows uses fast GPU capture (Desktop Duplication).
- On **Mac**, allow **Screen Recording** for Fasway (or Terminal) in System Settings → Privacy & Security. Without it, the preview shows only the wallpaper.

## Keyboard
Open the **⌨️ Keyboard** tab and type with your phone keyboard. Every letter appears on the laptop **live**, wherever the cursor is.
- **Works with any phone keyboard:** Gboard autocorrect and suggestions, swipe typing, Hindi keyboards, emoji, and the keyboard's own mic. When autocorrect changes a word on the phone, the laptop gets the same fix.
- **Special keys:** Esc, Tab, arrows, ⌫, Del, Home, End, PgUp, PgDn, Enter, F1–F12, Ins, PrtSc. Hold the arrows, ⌫ and Del to repeat them.
- **Modifier keys:** **Ctrl / Alt / Shift / Win**. On a Mac these show as **⌘ Cmd** and **⌥ Opt**.
  - Tap once to apply to the **next key only**; tap twice to **lock** it on (underlined); tap again to turn it off.
  - Examples: Ctrl, then type `c` → Ctrl+C. Shift, then ← → select text. Win, then type `d` → show desktop.
- **Shortcut buttons:** Copy, Paste, Cut, Undo, Redo, Select all, Save, Find. They use Ctrl on Windows and ⌘ on Mac.
- **Screen preview:** shown above the keyboard too (🖥), so you can watch what you type. While the phone keyboard is open, the bottom tabs hide to make room.

## Wake the laptop (Wake-on-LAN)
When the app can't reach the laptop for a few seconds, it shows **"… isn't reachable"** with a **Wake laptop** button. **Wake laptop** is also in the laptop list's ⋮ menu. The phone sends a "wake-up packet" on the Wi-Fi to the laptop's network card; the laptop tells the phone that card's address each time it connects.

It only works if the laptop is set up to wake this way:
1. **Device Manager** → **Network adapters** → your Wi-Fi (or Ethernet) adapter → **Properties**.
2. **Power Management** tab: tick **Allow this device to wake the computer**, and **Only allow a magic packet to wake the computer**.
3. **Advanced** tab: set **Wake on Magic Packet** to **Enabled**. On some Wi-Fi adapters it's called **Wake on WLAN**.

- **Wi-Fi** can usually wake the laptop only from **sleep**, not from shut down or hibernate. **Ethernet** often also works from hibernate.
- The phone and laptop must be on the same network.
- Some laptops also need Wake-on-LAN switched on in the BIOS/UEFI.
- If it doesn't wake, the laptop's Wi-Fi card doesn't support it while asleep.

## Presentation remote
**Apps → Presentation remote** turns the phone into a clicker for PowerPoint, Google Slides, Keynote or a PDF:
- **Next / Back:** big buttons (Next is the large one). They press → and ←.
- **Volume buttons:** up = next slide, down = back, while this screen is open.
- **Start** (F5), **From here** (Shift+F5), **Black** (B, again to show), **End** (Esc).
- **Laser** (PowerPoint, Windows): turns on PowerPoint's laser pointer (Ctrl+L); slide your finger on the pad to move it.
- **Timer** at the top: starts with **Start**. Tap it to pause or go on, and hold it to reset.
- The phone screen stays on while Fasway is open.

## Apps tab 🧩
- **Quick actions:** your own one-tap buttons, saved on the laptop (`actions.json`). It comes with some starter buttons: File Explorer, Task Manager, Screenshot, Show desktop, Settings, Notepad, YouTube, Google.
  - Tap **Edit** to change or delete a button, move it with ◀ ▶, or add one with ＋.

  | Type | Example |
  |---|---|
  | Open | `https://youtube.com` · `notepad` · `calc` · `C:\Users\me\Downloads` |
  | Type text | your email, address or signature |
  | Shortcut keys | `ctrl+shift+esc` · `win+d` · `ctrl+c, ctrl+v` |
  | Macro (one step per line) | `key win+r` / `wait 400` / `type notepad` / `key enter` / `open …` / `cmd …` |
  | Run a command | `shutdown /h` (runs without a window) |

  A new or changed command is allowed once on the laptop before it runs (see [Security](#security)).

- **Open link on laptop:** paste a link, or tap *Open the link copied on this phone*, and it opens in the laptop's browser. Links in the clipboard list also get a 🌐 button. Only http(s) links are allowed.
- **Open windows:** every open laptop window with its icon. Tap a row to switch to it; ▁ minimizes, ▢ maximizes or restores, ✕ closes (after you confirm, and the app can still ask to save). On a Mac this lists apps instead of windows.

## Controls tab 🎛️
- **Laptop status:** battery (charging or time left), CPU and RAM use, and how long the laptop has been on.
- **Alerts:** you get a pop-up and a vibration when the charger is plugged in or unplugged, when the battery drops to 20% or 10%, and when it's fully charged.
- **Now Playing:** artwork, title and artist of whatever plays on the laptop (Spotify, YouTube or Netflix in Chrome or Edge, VLC, the Media Player app…).
  - The **seek bar** shows elapsed and total time, and you can drag it to jump.
  - ⏮ ⏯ ⏭ control that app directly.
  - When several apps are playing, chips let you pick one.
  - With nothing detected, the buttons act as normal media keys.
  - On a Mac it supports Spotify and Apple Music.
- **Volume:** a slider plus mute.
- **Brightness:** a slider. On a Mac, or a monitor that doesn't report its brightness, you get 🔅/🔆 buttons instead.
- **Clipboard:**
  - **Laptop → phone:** copy anything on the laptop and it appears in the list. With *Auto-copy to phone* on, it's copied to the phone clipboard automatically. Tap **Copy** or **Paste** on any item.
  - **📤 Send phone clipboard:** puts the phone's clipboard on the laptop clipboard.
  - **📋 Paste on laptop:** does the same and presses Ctrl+V (⌘V on Mac).
  - The first time, Chrome asks to allow clipboard access.
  - In the Android app, *Auto-copy* also works the other way: text you copy in another phone app is sent to the laptop when you switch back to Fasway.
  - **Send clipboard** (Android app): after copying in any app, pull down the notification shade and tap **Send clipboard** in the Fasway notification, or add the **Send clipboard** Quick Settings tile. Fasway doesn't open; the copied text goes to the laptop clipboard. (The notification can be switched off in Settings.)
  - **Copy to laptop** (Android app): select text in any app and pick **Copy to laptop** in the selection menu (sometimes under ⋮), or share text to Fasway. It goes straight to the laptop clipboard without opening Fasway. (Android doesn't let apps read the clipboard in the background, so a plain Copy can't be sent automatically.)
- **Files** (Android app, its own tab): every transfer shows live progress, speed and time left, with cancel and retry, plus a list of recent transfers.
  - **Phone → laptop:** **Send to laptop** picks any files; they're saved in `Downloads\Fasway` on the laptop (a notification says when one arrives). **Show on laptop** opens that folder.
  - **Laptop → phone:** right-click files or folders in Explorer → **Send to phone (Fasway)** (Windows 11: under *Show more options*), drag them onto the Fasway window, or click **Choose files…**. If no phone is connected yet, they are sent as soon as one connects. They download to the phone's `Downloads/Fasway`, and you can open them from the list. The web app downloads them in the browser.
- **Power:** Lock, Display off, Sleep, Sign out, Restart, Shut down. The last four ask for confirmation first.
- On **Mac**, Restart, Shut down and Sign out may ask once for permission to control "System Events".

## Voice typing
Click into any text field on the laptop, open the **Voice** tab, tap the mic and speak. The text is typed wherever the cursor is.

| Language option | Output |
|---|---|
| Mixed – Hinglish (Roman) | `mujhe kal meeting schedule karni hai` |
| Mixed – हिंदी लिपि | `मुझे कल मीटिंग शेड्यूल करनी है` |
| English | English |
| हिंदी | Hindi (Devanagari) |

- **Review before sending**: speech goes into the text box first so you can edit it, then tap **Send**.
- The text box also works with your phone keyboard, including Gboard's mic.
- Speech recognition uses Chrome's (Google) engine, so the phone needs internet.

## macOS setup
1. Install **Python 3.10 or newer from [python.org](https://www.python.org/downloads/macos/)**. It includes Tk, which the QR window needs. The `python3` that ships with macOS is too old. With Homebrew Python, also run `brew install python-tk`.
2. Copy the Fasway folder to the Mac **without** `.venv` and `data` (those are Windows-specific and get recreated).
3. In Terminal, run once:
   ```bash
   cd path/to/Fasway
   bash run.command
   ```
   Later you can double-click `run.command` in Finder, after running `chmod +x run.command` once.
4. **Accessibility permission (required):** macOS asks for it the first time. Otherwise go to System Settings → Privacy & Security → **Accessibility** and turn on **Terminal**, or whichever app you started Fasway from. Then **quit and restart Fasway**. Without this the cursor and typing do nothing; the QR window shows a red warning when the permission is missing.
5. Click **Allow** when macOS asks whether Python may accept incoming network connections.

Differences on Mac:
- **Undo** sends Cmd+Z, and **⌫ word** sends Option+Delete.
- Scrolling is smooth (pixel-based).
- The ⚙ **Natural scrolling** switch on the phone decides scroll direction; the Mac's own setting doesn't apply.
- If the cursor feels too fast or slow, change **Pointer speed** in ⚙.

## Sharing ready-made apps (no Python needed)
| For | File | Built by |
|---|---|---|
| Mac, Apple Silicon (M1–M4) | `Fasway-mac-arm64.dmg` | GitHub Actions (`macos-15`) |
| Mac, Intel | `Fasway-mac-x86_64.dmg` | GitHub Actions (`macos-15-intel`) |
| Windows | `Fasway-windows.zip` → `Fasway.exe` | GitHub Actions, or locally: `packaging\build_windows.bat` |
| Android | `Fasway-v1.x.x-arm64.apk` (old phones: `-arm32`) | Locally: `app\tool\build_apk.ps1`; GitHub Actions also builds them |

APKs from GitHub are signed with a different key than ones built on your PC, so Android can't install one over the other: uninstall first, or stick to one source.

Mac apps can only be built on a Mac, so GitHub builds them for free:
1. Push this folder to a GitHub repository.
2. Open the repo → **Actions** → **Build apps**. Each push builds everything (about 5 minutes).
3. Download the files from the finished run's **Artifacts**. To get a permanent download page, push a tag such as `git tag v1.0 && git push --tags`; the files are attached to a **Release**.

**What the Mac user does:**
1. Open the `.dmg` and drag **Fasway** into **Applications**.
2. The first time, macOS blocks it because the app isn't signed by Apple. Open **System Settings → Privacy & Security**, scroll down, click **Open Anyway**, and confirm. This is only needed once.
3. Allow **Accessibility** for **Fasway** when asked, then reopen Fasway.
4. Scan the QR code with the phone.

To remove the "Open Anyway" step, the app has to be signed and notarized with an Apple Developer account ($99/year).

Settings for the packaged app are stored in `~/Library/Application Support/Fasway` on Mac and `%APPDATA%\Fasway` on Windows.

## Notes
- If the QR doesn't open, choose a different **Laptop IP** in the window (your laptop has several network adapters).
- **New pairing code** makes old QR codes stop working for new phones; phones you already approved keep working.
- **Admin apps:** Windows blocks every program from controlling apps that run **as Administrator** (Task Manager, admin terminals, installers, Registry Editor) unless that program also runs as Administrator. While such an app is in front, Fasway's touchpad and keyboard do nothing, and the phone shows a warning explaining why.
  - Click **Restart as administrator** in the Fasway window (one UAC prompt). The phone reconnects by itself.
  - Tick **Always start as administrator** to do this automatically every time.
  - Even as Administrator, the lock screen, Ctrl+Alt+Del and UAC prompts can't be controlled remotely; Windows protects those screens.

## Layout
```
fasway/   Python service: server.py, main.py (QR window),
          input_win.py (Windows SendInput), input_mac.py (macOS Quartz), platform_input.py (picks one)
fasway/agent/  The assistant: runtime.py, intents.py (built-in commands), tools.py, policy.py (approvals),
          appui.py (buttons in apps), browser_access.py (page reading), llm.py (Claude / GPT),
          routines.py (one phrase, several steps)
fasway/wol.py  The network card address the phone needs to wake the laptop
app/      Android app (Flutter)
web/      Phone web app (index.html, app.js, app.css)
tests/    Laptop tests (test_core.py, test_routines.py, test_agent.py)
packaging/  App builds: build_mac.sh (.app + .dmg), build_windows.bat (.exe), make_icon.py
.github/workflows/build.yml  Builds Mac + Windows apps on GitHub
data/     Generated: pairing token, HTTPS certificate (keep private)
```

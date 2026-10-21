# Fasway

Use your Android phone as a **touchpad** and **voice keyboard** (English, Hindi and mixed Hinglish) for your Windows laptop or Mac.

## Start

**Windows:** double-click **`run.bat`**. The first run installs dependencies into `.venv`. Fasway then runs **in the system tray** (the blue **F** icon next to the clock), with no console window.
- **Tray icon:** green dot = a phone is connected. Click it to show the pairing QR; right-click for options and **Quit**.
- **Closing the QR window** hides it; Fasway keeps running.
- **Running `run.bat` again** while Fasway is running just opens its window.
- **Start with Windows** (tick it in the window or the tray menu): Fasway starts silently at sign-in. Together with **Always run as administrator**, it starts with admin rights **without a UAC prompt each time** (it uses a Task Scheduler task; you approve one prompt when you turn it on).
- **Log file:** `data/fasway.log`.

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
- **⛶** goes full screen in landscape. In full screen, **⌨** opens the phone keyboard so you can type.
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

- **Open link on laptop:** paste a link, or tap *Open the link copied on this phone*, and it opens in the laptop's browser. Links in the clipboard list also get a 🌐 button. Only http(s) links are allowed.
- **Open windows:** every open laptop window with its icon. Tap a row to switch to it; ▁ minimizes, ▢ maximizes or restores, ✕ closes (after you confirm, and the app can still ask to save). On a Mac this lists apps instead of windows.

## Controls tab 🎛️
- **Laptop status:** battery (charging or time left), CPU and RAM use, and how long the laptop has been on.
- **Alerts:** you get a pop-up and a vibration when the charger is plugged in or unplugged, when the battery drops to 20% or 10%, and when it's fully charged.
- **Media:** ⏮ ⏯ ⏭ control whatever is playing (YouTube, Spotify, VLC…).
- **Volume:** a slider plus mute.
- **Brightness:** a slider. On a Mac, or a monitor that doesn't report its brightness, you get 🔅/🔆 buttons instead.
- **Clipboard:**
  - **Laptop → phone:** copy anything on the laptop and it appears in the list. With *Auto-copy to phone* on, it's copied to the phone clipboard automatically. Tap **Copy** or **Paste** on any item.
  - **📤 Send phone clipboard:** puts the phone's clipboard on the laptop clipboard.
  - **📋 Paste on laptop:** does the same and presses Ctrl+V (⌘V on Mac).
  - The first time, Chrome asks to allow clipboard access.
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
| Mac, Apple Silicon (M1–M4) | `Fasway-mac-arm64.dmg` | GitHub Actions (`macos-14`) |
| Mac, Intel | `Fasway-mac-x86_64.dmg` | GitHub Actions (`macos-15-intel`) |
| Windows | `Fasway-windows.zip` → `Fasway.exe` | GitHub Actions, or locally: `packaging\build_windows.bat` |

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
- **New pairing code** disconnects every phone; scan the QR again to reconnect.
- **Admin apps:** Windows blocks every program from controlling apps that run **as Administrator** (Task Manager, admin terminals, installers, Registry Editor) unless that program also runs as Administrator. While such an app is in front, Fasway's touchpad and keyboard do nothing, and the phone shows a warning explaining why.
  - Click **Restart as administrator** in the Fasway window (one UAC prompt). The phone reconnects by itself.
  - Tick **Always start as administrator** to do this automatically every time.
  - Even as Administrator, the lock screen, Ctrl+Alt+Del and UAC prompts can't be controlled remotely; Windows protects those screens.

## Layout
```
fasway/   Python service: server.py, main.py (QR window),
          input_win.py (Windows SendInput), input_mac.py (macOS Quartz), platform_input.py (picks one)
web/      Phone web app (index.html, app.js, app.css)
packaging/  App builds: build_mac.sh (.app + .dmg), build_windows.bat (.exe), make_icon.py
.github/workflows/build.yml  Builds Mac + Windows apps on GitHub
data/     Generated: pairing token, HTTPS certificate (keep private)
```

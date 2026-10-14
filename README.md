# Fasway

Use your Android phone as a **touchpad** and **voice keyboard** (English, Hindi and mixed Hinglish) for your Windows laptop or Mac.

## Start

**Windows:** double-click **`run.bat`** (the first run installs dependencies into `.venv`).

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
Tap **🖥** in the top bar to show the laptop screen, with its cursor, above the touchpad.
- **Tap the preview** to move the cursor to that spot, then tap the pad to click.
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
- Windows blocks typing into apps that run **as Administrator** unless Fasway also runs as Administrator.

## Layout
```
fasway/   Python service: server.py, main.py (QR window),
          input_win.py (Windows SendInput), input_mac.py (macOS Quartz), platform_input.py (picks one)
web/      Phone web app (index.html, app.js, app.css)
packaging/  App builds: build_mac.sh (.app + .dmg), build_windows.bat (.exe), make_icon.py
.github/workflows/build.yml  Builds Mac + Windows apps on GitHub
data/     Generated: pairing token, HTTPS certificate (keep private)
```

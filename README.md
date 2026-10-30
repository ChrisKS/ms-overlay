# MapleReader (ms-overlay)

A small always-on-top overlay that reads your **Level, EXP and EXP %** from the MapleStory
status bar and shows how fast you're gaining EXP: EXP per hour over several time windows, time
to the next level, kills, and an optional graph.

It only **reads pixels from the screen**. It never touches game memory, never sends input to
the game, and never talks to the network.

---

## Contents

- [Quick start](#quick-start)
- [The overlay](#the-overlay)
- [How reading works](#how-reading-works)
- [How EXP is tracked](#how-exp-is-tracked)
- [Settings](#settings)
- [Files it creates](#files-it-creates)
- [Command line](#command-line)
- [Building from source](#building-from-source)
- [Troubleshooting](#troubleshooting)

---

## Quick start

Each [release](https://github.com/ChrisKS/ms-overlay/releases) has two zips:
`MapleReader-windows-<version>.zip` and `MapleReader-macos-<version>.zip`.

### Windows

1. Unzip `MapleReader-windows-<version>.zip` anywhere.
2. Run `maple_reader.exe`. No install is needed: Tesseract OCR is bundled in the `tesseract`
   folder next to the exe.

### macOS (Apple Silicon)

1. Unzip `MapleReader-macos-<version>.zip` and move `MapleReader.app` to Applications.
   Tesseract OCR is bundled inside the app.
2. The app isn't signed with an Apple Developer ID, so macOS blocks the first launch. Open it
   once, then go to **System Settings → Privacy & Security** and click **Open Anyway**. You can
   instead run this once in Terminal:

   ```bash
   xattr -dr com.apple.quarantine /Applications/MapleReader.app
   ```

3. Allow **Screen Recording** for MapleReader in **System Settings → Privacy & Security**, then
   quit and reopen it. Without this permission macOS only lets it see the desktop background,
   so the status bar is never found. Each new version needs this permission again.

The macOS build only runs on Apple Silicon Macs (M1 and later), not on Intel Macs.

### Then

1. Start MapleStory. The game must be visible on screen with its HP/MP/EXP status bar showing.
   The overlay finds the bar by itself on any monitor, at any position, and in windowed mode.
2. Drag the overlay wherever you like. Right-click it for the menu. On a Mac, Control-click
   works too.

---

## The overlay

```
 ● Character            (hint)            51.23%   Lv 142
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   ← level progress
   EXP/H · 5M   │  EXP/H · 15M  │  EXP/H · 30M  │  EXP/H · 60M
   12.345.678   │  11.902.114   │  11.450.000   │  10.998.210
                              ▾                               ← show/hide graph
```

### Header

| Element | Meaning |
|---|---|
| **Status dot** | Grey: waiting for the first reading. Green: reading OK. Red: something is wrong (see the hint). Amber: paused. |
| **Name** | The character name read from the status bar. You can hide it in the settings. |
| **Hint** | A short red message appears after 5 failed reads in a row: `status bar not found`, `unreadable digit`, `can't read status bar` or `capture error`. |
| **% and Lv** | The current EXP % and level. |
| **Divider line** | Doubles as a level-progress bar, filled in the accent colour up to the current %. |

### Rate columns

You can show up to four columns. Each one has a **window** in minutes and a **kind**. The
header reads `KIND · 15M`, or `KIND · SESSION` when the window is 0.

| Kind | Header | Shows |
|---|---|---|
| EXP per hour | `EXP/H` | EXP gained in the window, scaled to one hour |
| EXP gained | `EXP` | Total EXP gained in the window, e.g. `+1.234.567` |
| Level % per hour | `%/H` | Level percentage gained per hour |
| Level % gained | `% GAINED` | Level percentage gained in the window |
| Time to level | `LEVEL IN` | Time to reach 100% at that window's %/hour. Shows `99h+` if it's 100 hours or more, and `—` if there's no progress. |
| Kills | `KILLS` | Number of separate EXP gains seen in the window |
| Avg per kill | `AVG/KILL` | EXP gained in the window ÷ kills |

- A column shows `—` until there's enough data: at least one EXP gain, plus 8 seconds.
- A number is **dimmed** while it's based on less time than its window covers. You can turn
  dimming off.
- A `~` before an EXP value means a level-up had to be estimated. See
  [Level-ups](#level-ups).
- Long numbers shrink automatically so the columns never overlap.

### Graph

Click the small chevron (`▾` / `▴`) at the bottom to open or close the graph panel.

- **Summary line:** session length · total EXP gained · total % gained · estimated time to
  level. The estimate uses the last 15 minutes' rate, or the whole session if it's shorter.
- The **EXP / %** buttons switch the graph between cumulative EXP and cumulative level %.
- The X axis is time since the session started. The Y axis is the cumulative gain.
- The line can be stepped, straight or smooth. You can set its thickness, opacity and fill in
  the settings.
- The graph needs at least two data points. Until then it shows
  "Gain some EXP to start the graph".

### Mouse controls

| Action | Result |
|---|---|
| Left-drag | Move the overlay (unless *Lock position* is on). The position is saved. |
| Click `▾` / `▴` | Show or hide the graph. |
| Click `EXP` / `%` | Switch what the graph plots. |
| Right-click (or Control-click on a Mac) | Menu: **Pause / Resume**, **Reset session**, **Settings…**, **Quit**. |

**Pause** stops all screen reading until you resume. **Reset session** clears every
accumulated number and starts fresh.

---

## How reading works

The game's status bar is found and read on every frame, by default 10 times a second.

1. **Finding the bar.** The reader scans every monitor for the bright green `[` `]` brackets
   around HP, MP and EXP. It looks for 7–9 px tall vertical runs of that green, with at least
   6 on the same row. If there are several matches, it uses the lowest one on screen. After 3
   failed reads in a row it searches again, so moving or resizing the game window is fine.
2. **EXP and %.** The EXP number and the bracketed percentage use a 1-bit white 5×7 pixel font.
   They're read by **exact glyph matching**, not OCR, so they are fast and exact. The digit `5`
   hasn't been captured from a real screen yet and uses best-guess shapes. If an unrecognised
   digit-shaped glyph appears while every other digit is known, it is learned as the one
   missing digit for that run.
3. **Level.** The orange level box is read with Tesseract. It's re-read when the level is
   unknown, every 3 seconds, and right away when the % drops by more than 30 (a likely
   level-up).
4. **Character name.** The name line is read with Tesseract on a separate, slower thread. It
   reads about every second until 5 readings are collected, then every 15 seconds. Each reading
   is a majority vote over several image scalings, and a name is accepted once it wins the vote
   across recent readings.

A reading is only used when the level, the EXP and the % were all read without any unknown
characters.

---

## How EXP is tracked

- **Confirmation.** A new (level, EXP, %) reading must be seen **twice in a row** before it's
  accepted. This filters out one-frame misreads.
- **Session start.** The first accepted reading is the baseline. The rate clock starts at the
  **first EXP gain**, so idle time before you start grinding doesn't lower your rates.
- **Rate windows.** A window covers the last *N* minutes, but never goes back before the first
  EXP gain. A window of `0` covers the whole session.
- **Kills.** Each accepted increase in EXP counts as one kill. Several kills that land between
  two reads count as one.
- **EXP vs. %.** EXP gains come from the EXP number. % gains use level + % together, so they
  carry across level-ups.

### Level-ups

The EXP needed for each level is **learned on the fly**: at every reading of 1% or more,
`EXP × 100 / %` estimates the total for that level. When you level up:

- If the level went up by exactly one, the old % was above 50 and the new % is below 50, and
  the old level's total was learned, the gain is **estimated** as *(learned total − old EXP) +
  new EXP*. EXP-based values are then marked with `~`.
- If the % dropped by more than 30 but the level hasn't been re-read yet, the reading becomes
  the new baseline and no EXP is counted for that step.
- Any other unexpected jump (a misread, losing a level, etc.) also just resets the baseline.

### New character

When *Start a new session when the character changes* is on, a newly read name that is clearly
different from the current one resets the session. "Clearly different" means less than 60%
similar, so small OCR wobbles on the same name don't count. This only happens after a name has
already been read once since the overlay started.

---

## Settings

Open **Settings…** from the right-click menu. Changes apply instantly and are saved
automatically.

### General

| Setting | Default | Notes |
|---|---|---|
| Always on top | On | |
| Lock position | Off | Turns off dragging. |
| Show character name | On | |
| Start a new session when the character changes | On | See [New character](#new-character). |
| Screen reads per second | 10 | 2–20. Higher means faster updates and slightly more CPU. |

### Rates

There are four column slots. For each one you set:

- **On or off.** At least one column is always kept on.
- **Minutes**, from 0 to 720. 0 means the whole session.
- **What it shows**: one of the kinds in [Rate columns](#rate-columns).

The defaults are four EXP/H columns at 5, 15, 30 and 60 minutes. Dimming numbers until their
window has filled up is on by default.

### Appearance

| Setting | Options |
|---|---|
| Text colour | White, Soft, Yellow, Cyan, Mint, Pink |
| Text size | Small, Normal, Large, Extra large |
| Text shadow | On or off (default on) |
| Accent colour | Sky, Mint, Amber, Rose, Violet, Orange, Silver. Used for the progress bar, the graph and the buttons. |
| Opacity | **Background** 0–100%, **Text** 20–100% |
| Number format | `1.234.567` (Danish, the default), `1,234,567` (English), `1 234 567` (spaces), `1.2M` (compact) |

With the Danish format, percentages use a decimal comma (`12,50%`). In every format, numbers
of 10 million or more are shortened to `M`.

Opacity works per layer: the background, graph fill, graph line and text are separate
transparent windows stacked together, so each one can fade on its own.

### Graph

| Setting | Options |
|---|---|
| Show graph | On or off |
| Plots | EXP gained or % gained |
| Line style | **Stepped** shows exactly when EXP arrived, **Straight** joins the points, **Smooth** averages them |
| Line thickness | 1–4 px |
| Line opacity | 0–100% |
| Fill under the line | On or off, plus fill opacity 0–100% (default 25%) |

### Data

- **Save every EXP change to `maple_log.csv`.** On by default.
- **Open data folder** opens the folder that holds the settings and log.
- **Reset session now** and **Reset window position**. The default position is centred at the
  top of the main screen.
- **Restore default settings** resets everything except the character name and the window
  position.

---

## Files it creates

On Windows these are written **next to `maple_reader.exe`**. The macOS app writes them to
**`~/Library/Application Support/MapleReader`**, because the app's own folder has to stay
unchanged. When run from source, they're written next to `maple_reader.py`.

| File | Contents |
|---|---|
| `maple_settings.json` | All settings, plus the window position and the last character name. Settings from older versions are migrated on load, and invalid values are replaced with defaults. |
| `maple_log.csv` | One row per accepted change: `time` (ISO local time), `level`, `exp`, `percent`. Rows are only added, never removed, across runs. |
| `debug/` | Only with `--debug`: the raw and processed level-OCR crops. |

Nothing carries over between runs except settings and the log. Each launch starts a new
session.

---

## Command line

```bash
maple_reader.exe [--image FILE] [--debug] [--demo]
```

| Option | Effect |
|---|---|
| *(none)* | Start the overlay. |
| `--image FILE` | Read one screenshot, print the result (level, EXP, %, name, raw text) and exit. Prints `status bar not found` if there's no bar. Useful for testing the reader. |
| `--debug` | Save the level OCR crops to `./debug`. |
| `--demo` | Run the overlay with fake, slowly rising EXP, to preview the UI without the game. |

From source, use `python maple_reader.py …` instead. For the macOS app, run
`/Applications/MapleReader.app/Contents/MacOS/MapleReader …` from Terminal.

---

## Building from source

### Run directly

Needs Python 3.10+ and a Tesseract install.

```bash
pip install -r requirements.txt
```

```bash
python maple_reader.py
```

Tesseract is looked for in a `tesseract` folder next to the script, then in
`C:\Program Files\Tesseract-OCR\` (Windows) or Homebrew's `/opt/homebrew/bin` and
`/usr/local/bin` (macOS), then on `PATH`. On a Mac, `brew install tesseract` is enough.

### Build the release zip (Windows)

```bash
build.bat
```

`build.bat` runs `build.ps1`, which:

1. Installs the Python dependencies (`mss`, `Pillow`, `numpy`, `pytesseract`, `pyinstaller`).
2. Downloads the UB-Mannheim Tesseract 5.4 installer and **unpacks** it with 7-Zip instead of
   installing it. If 7-Zip isn't installed, it's unpacked from its MSI too. No admin rights are
   needed.
3. Builds a single-file, windowless `maple_reader.exe` with PyInstaller.
4. Trims Tesseract down to `tesseract.exe` and the `eng`/`osd` language data.
5. Zips the exe and the `tesseract` folder into `MapleReader.zip`.

### Build the release zip (macOS)

Needs Python 3.10+ and [Homebrew](https://brew.sh).

```bash
./build_mac.sh
```

`build_mac.sh`:

1. Installs the Python dependencies, and Tesseract and `dylibbundler` with Homebrew.
2. Copies Tesseract out of Homebrew and uses `dylibbundler` to bundle the libraries it needs
   into a `libs` folder next to it, so it runs on Macs without Homebrew. The build fails if
   anything still points at Homebrew.
3. Keeps only the `eng`/`osd` language data, and ad-hoc signs the rewritten binaries. Apple
   Silicon won't run unsigned code.
4. Builds `MapleReader.app` with PyInstaller and puts Tesseract in its `Contents/Resources`.
5. Ad-hoc signs the app, checks the signature, and zips it into `MapleReader-mac.zip`.

The app is built for the Mac's own architecture. It's ad-hoc signed only, not notarized, so
Gatekeeper asks before the first launch (see [Quick start](#macos-apple-silicon)).

### Releases (CI)

`.github/workflows/release.yml` builds on `windows-latest` and on `macos-latest` (Apple
Silicon) at the same time:

- **Pushing a `v*` tag**, e.g. `git tag v1.0.0 && git push --tags`, builds
  `MapleReader-windows-v1.0.0.zip` and `MapleReader-macos-v1.0.0.zip`. Once both builds
  succeed, it publishes them together as one GitHub release with auto-generated notes. If
  either build fails, nothing is published.
- **Running the workflow manually** from the Actions tab builds `MapleReader-windows-dev.zip`
  and `MapleReader-macos-dev.zip` and only uploads them as workflow artifacts.

---

## Troubleshooting

| Symptom | What to check |
|---|---|
| Red dot, `status bar not found` | The HP/MP/EXP bar must be visible and not covered. Very unusual UI scaling or colour filters can change the green bracket colour so it isn't recognised. |
| `unreadable digit` | A glyph in the EXP/% text didn't match. This is most likely a `5` whose shape differs from the built-in guess. It usually fixes itself once every other digit has been seen. |
| `can't read status bar` | The bar was found, but the level, EXP or % couldn't be read. Try `--debug` and check `debug/level_proc.png`. |
| `capture error` | Screen capture failed, for example because the screen is locked or a secure desktop is showing. |
| Mac: `status bar not found` while the game is visible | Allow MapleReader under *Screen Recording* in System Settings → Privacy & Security, then quit and reopen it. Each new version needs this again. |
| Values show `~` | A level-up was estimated. See [Level-ups](#level-ups). |
| Rates reset by themselves | The character name changed. You can turn off *Start a new session when the character changes*. |
| Overlay hidden behind the game | Turn on *Always on top*, and run the game in windowed or borderless mode. Exclusive fullscreen can cover overlays. |

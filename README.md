# ms-overlay

A small always-on-top overlay that reads your **Level, EXP and EXP %** from the MapleStory
status bar and shows how fast you're gaining EXP: EXP per hour over several time windows, time
to the next level, kills, and an optional graph. It can also post level-ups and session
summaries to Discord, and show your progress on your Discord profile.

It only **reads pixels from the screen**. It never touches game memory and never sends input to
the game. It only uses the network to check for new versions (which you can turn off) and for
the Discord features you turn on.

---

## Contents

- [Quick start](#quick-start)
- [The overlay](#the-overlay)
- [How reading works](#how-reading-works)
- [How EXP is tracked](#how-exp-is-tracked)
- [Discord](#discord)
- [Updates](#updates)
- [Settings](#settings)
- [Files it creates](#files-it-creates)
- [Command line](#command-line)
- [Building from source](#building-from-source)
- [Troubleshooting](#troubleshooting)

---

## Quick start

Each [release](https://github.com/ChrisKS/ms-overlay/releases) has two zips:
`ms-overlay-windows-<version>.zip` and `ms-overlay-macos-<version>.zip`.

### Windows

1. Unzip `ms-overlay-windows-<version>.zip` anywhere.
2. Run `ms-overlay.exe`. No install is needed: Tesseract OCR is bundled in the `tesseract`
   folder next to the exe.

### macOS (Apple Silicon)

1. Unzip `ms-overlay-macos-<version>.zip` and move `ms-overlay.app` to Applications.
   Tesseract OCR is bundled inside the app.
2. The app isn't signed with an Apple Developer ID, so macOS blocks the first launch. Open it
   once, then go to **System Settings → Privacy & Security** and click **Open Anyway**. You can
   instead run this once in Terminal:

   ```bash
   xattr -dr com.apple.quarantine /Applications/ms-overlay.app
   ```

3. Allow **Screen Recording** for ms-overlay in **System Settings → Privacy & Security**, then
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
| **Update notice** | `Update v1.1.0 available` in the accent colour when a newer version is out (unless a red hint is showing). Click it to open the release's download page. See [Updates](#updates). |
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

- A column shows `—` until there's enough data: two EXP gains. The first gain only starts
  the clock (see [How EXP is tracked](#how-exp-is-tracked)), so the numbers appear with the
  second.
- A number is **dimmed** while it's based on less time than its window covers. You can turn
  dimming off.
- A `~` before an EXP value means a level-up had to be estimated. See
  [Level-ups](#level-ups).
- Long numbers shrink automatically so the columns never overlap.

### Graph

Click the small chevron (`▾` / `▴`) at the bottom to open or close the graph panel.

- **Summary line:** session length · total EXP gained · total % gained · estimated time to
  level. The estimate uses the last 15 minutes' rate, or the whole session if it's shorter.
- The **EXP**, **%** and **EXP/H** buttons switch what the graph plots:
  - **EXP:** cumulative EXP gained.
  - **%:** cumulative level % gained.
  - **EXP/H:** your EXP per hour through the session, measured over the last 5 minutes by
    default. It shows when you were fast and when you slowed down, for example when a buff ran
    out or the map got crowded. A dashed line shows your session average up to each moment, so
    the line is above it whenever you were beating your average. The line starts one minute
    after your first EXP gain, because a rate from a few kills swings wildly.
- The X axis is time since the session started.
- The EXP and % lines can be stepped, straight or smooth. The EXP/H line is straight, or
  smooth if you choose that style. You can set thickness, opacity and fill in the settings.
- The EXP and % graphs need at least two data points, and EXP/H needs a minute of EXP. Until
  then the graph shows a short message instead.

### Mouse controls

| Action | Result |
|---|---|
| Left-drag | Move the overlay (unless *Lock position* is on). The position is saved. |
| Click `▾` / `▴` | Show or hide the graph. |
| Click `EXP` / `%` / `EXP/H` | Switch what the graph plots. |
| Click `Update … available` | Open the new release's download page. |
| Right-click (or Control-click on a Mac) | Menu: **Pause / Resume**, **Reset session**, **Settings…**, **Download update…** (when there is one), **Quit**. |

**Pause** works like a stopwatch: the session stops until you resume. **Reset session** clears
every accumulated number and starts fresh. See [Pausing](#pausing) for exactly what Pause does.

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
4. **Character name and job.** The name line, and the job line above it, are read with
   Tesseract on a separate, slower thread. It reads about every second until 5 readings are
   collected, then every 15 seconds. Each reading is a majority vote over several image
   scalings, and a name or job is accepted once it wins the vote across recent readings. The
   job must also closely match a real MapleStory job name, so a misread is dropped rather than
   shown. The job line's position is derived from the name line's and hasn't been checked
   against a real screen yet; `--debug` saves `debug/job_raw.png` to check it.

A reading is only used when the level, the EXP and the % were all read without any unknown
characters.

---

## How EXP is tracked

- **Confirmation.** A new (level, EXP, %) reading must be seen **twice in a row** before it's
  accepted. This filters out one-frame misreads.
- **Session start.** The first accepted reading is the baseline. The rate clock starts at the
  **first EXP gain**, so idle time before you start grinding doesn't lower your rates. That gain
  itself isn't counted, because how long it took is unknown. Rates appear with the second gain,
  dimmed at first because they're based on very little time.
- **Rate windows.** A window covers the last *N* minutes, but never goes back before the first
  EXP gain. A window of `0` covers the whole session.
- **Kills.** Each accepted increase in EXP counts as one kill. Several kills that land between
  two reads count as one.
- **EXP vs. %.** EXP gains come from the EXP number. % gains use level + % together, so they
  carry across level-ups.

### Pausing

Pause stops the session like a stopwatch:

- **Time stands still.** Paused time is cut out of everything: the rates and their windows, the
  session time, the graph's time axis and the Discord timer. A 5-minute window that spans a
  pause covers 5 minutes of unpaused time. After you resume, the numbers continue as if the
  pause never happened.
- **Gains made while paused don't count.** If you keep playing while paused, the first reading
  after you resume becomes the new starting point. EXP gained during the pause, including a
  level-up, isn't added to the session. A level-up is still posted to Discord, because you did
  reach that level.
- **Screen reading stops** while paused, so no CPU goes to OCR. The status dot turns amber, and
  Discord shows *Paused* without a timer.

To start over instead, use **Reset session**.

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

## Discord

Both Discord features are optional and set up in **Settings → Discord**. Nothing is sent
anywhere until you set them up.

### Channel posts (webhook)

ms-overlay can post to a Discord channel through a webhook. A webhook lets an app post to one
channel. It needs no bot and no Discord login.

1. In Discord, open the channel's settings: **Edit Channel → Integrations → Webhooks → New
   Webhook**, then **Copy Webhook URL**. You need the *Manage Webhooks* permission, which you
   have on your own server.
2. Paste the URL into **Settings → Discord**, and click **Send test message**.

It posts:

- **Level-ups:** "Mapler (Hero) reached level 143! 🎉". The job is left out until it has been
  read. Each level is posted once per run, even if the level is briefly misread. A level-up only
  counts if the new level starts below 50%. Optionally with a screenshot of the game; see below.
- **Session summaries** (off by default): time, EXP gained, average EXP/h, level (e.g.
  `142 → 143 (0,31%)`), level % gained and kills. A summary is posted when a session ends: when
  you reset it, when the character changes, or when you quit. Sessions with less than 5
  minutes since the first EXP gain aren't posted.

Each can be turned on or off separately. `--demo` never posts, except the test message. If a post
fails (no internet, or the webhook was deleted), the reason is shown next to the test button.

The webhook URL is hidden in the settings window because anyone who has it can post to that
channel. It's stored in plain text in `maple_settings.json`, so don't share that file.

#### Screenshots with level-ups

Turn on **Attach a screenshot of the game to level-up posts** to add a picture of the game,
taken a second after the level-up so the level-up effect shows. It's off by default.

**Only the MapleStory window is captured, never anything else on the screen.** The game
window itself is captured, not the area of the screen where it is, so nothing covering the
game (the overlay, notifications, other windows) and nothing around it can be in the picture:

- **Windows:** the window of the `MapleStory.exe` process, without its title bar. The game
  runs as administrator and is guarded by anti-cheat, so its process may refuse to say its
  name; the window is then recognised by its window class, `MapleStoryClass`, which any
  program can read. It's captured with **Windows Graphics Capture**, the method Discord streams
  with: Windows hands over the frames of that one window, even if something covers it, and it
  works while the game runs as administrator without ms-overlay needing to. If that fails,
  Windows is asked to draw the window on its own, which only works for an administrator's
  window if ms-overlay runs as administrator too. On Windows 10 a yellow border may flash
  around the game while the picture is taken; Windows 11 lets ms-overlay turn it off.
- **macOS:** the window of the app named MapleStory, captured on its own. A browser tab or
  other window merely *titled* MapleStory never matches.

If the game window can't be found or captured on its own, the post goes without a picture
and the status next to the test button says which step failed: no MapleStory window found,
the window is minimised, Windows wouldn't let ms-overlay capture it, or it came back black
(exclusive fullscreen). It never falls back to capturing the screen. Other platforms never
attach a picture.

To find out what's going on, run `ms-overlay.exe --capture-test` with the game open. It tries
one screenshot right away, shows the result, and saves `capture_test.txt` (what it found:
every window mentioning Maple, with its class and process) and, if it worked,
`capture_test.png` in the data folder.

The picture shows whatever the game shows, chat included. With the option on, **Send test
message** attaches a screenshot too, so you can check what would be shared.

### Profile status (Rich Presence)

Rich Presence shows what you're doing on your Discord profile and in the member list:

```
Playing ms-overlay
Lv 143 · 0,31%
EXP/H 7,64M · LEVEL IN 5:12:00
00:42:17 elapsed
```

Turn on **Show on my Discord profile** in **Settings → Discord**; nothing else is needed. The
status line below it says whether it's connected. It talks to the Discord desktop app running
on the same computer, so Discord must be open.

Discord shows the name of a Discord *application* after "Playing". ms-overlay has its own
application built in, like games do, so profiles show its name (currently *ms-overlay*; the
name is set in Discord's developer portal, not in ms-overlay). To show a different name, create your own application at
[discord.com/developers/applications](https://discord.com/developers/applications) (**New
Application**, named what you want shown), copy its **Application ID** from the *General
Information* page, and paste it into **Own Application ID**. Leave that field empty to use
ms-overlay's.

Details:

- The first line shows your level and %. The second line shows up to two items you choose,
  with the same options as the [rate columns](#rate-columns): what each shows (EXP per hour,
  time to level, kills, …) and how many minutes it covers. By default it's EXP/h and time to
  level, both over the last 15 minutes. Turn both items off to show only the first line.
  Items without enough data yet are left out; with none to show, it says *Starting a
  session*.
- The time counts up from the start of the session, leaving out paused time. While paused it
  shows *Paused* without a timer.
- If the status bar hasn't been read for a minute (the game is closed, for example), the status
  is cleared until it's read again.
- Discord accepts at most one update every 15 seconds, so the numbers lag a little.
- If Discord isn't running, ms-overlay keeps trying every 15 seconds in the background.

---

## Updates

ms-overlay tells you when a newer version has been released. It asks GitHub for the latest
release of this repository 10 seconds after starting and then every 6 hours. When there's a
newer one, the overlay shows `Update v1.1.0 available` in its header, and the right-click menu
gets **Download update…**. Either one opens the release's download page in your browser; it
only ever opens a page of this repository's releases.

Nothing is downloaded or installed: to update, download the new zip and replace the old app.
Settings and the log stay where they are.

- Only published releases count, never drafts or pre-releases.
- The version is stamped into the app when a release is built, from the release's tag.
  Builds from source or from a manual workflow run are development builds, which never check.
- Turn it off with **Tell me when a new version is out** in **Settings → General**. The line
  below it shows the result of the last check.
- If GitHub can't be reached, nothing happens; the settings line says why.

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
| Tell me when a new version is out | On | See [Updates](#updates). |

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
| Text colour | White, Silver, Sky, Cyan, Mint, Yellow, Amber, Orange, Rose, Pink, Violet, or any colour with the rainbow dot (opens the colour picker). A custom colour shows in that dot. |
| Text size | Small, Normal, Large, Extra large |
| Text shadow | On or off (default on) |
| Accent colour | The same colours as the text, or any colour with the rainbow dot. Used for the progress bar, the graph and the buttons. |
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
| Plots | EXP gained, % gained or EXP per hour |
| EXP per hour: rate over the last | 1–60 minutes (default 5). Shorter shows every change of pace; longer is calmer. |
| EXP per hour: session average | Show or hide the dashed session-average line (default on) |
| Line style | **Stepped** shows exactly when EXP arrived, **Straight** joins the points, **Smooth** averages them |
| Line thickness | 1–4 px |
| Line opacity | 0–100% |
| Fill under the line | On or off, plus fill opacity 0–100% (default 25%) |

### Data

- **Save every EXP change to `maple_log.csv`.** On by default.
- **Open data folder** opens the folder that holds the settings and log.
- **Reset session now** and **Reset window position**. The default position is centred at the
  top of the main screen.
- **Restore default settings** resets everything except the character name, the window
  position, and the Discord webhook URL and own Application ID.

### Discord

| Setting | Default | Notes |
|---|---|---|
| Webhook URL | Empty | See [Channel posts](#channel-posts-webhook). |
| Post when you level up | On | Only once a webhook URL is set. |
| Attach a screenshot of the game to level-up posts | Off | See [Screenshots with level-ups](#screenshots-with-level-ups). |
| Post a summary when a session ends | Off | Only once a webhook URL is set, and only for sessions of 5+ minutes. |
| Show on my Discord profile | Off | See [Profile status](#profile-status-rich-presence). |
| Item 1, Item 2 | On, 15 minutes, EXP per hour / Time to next level | What the second line of your Discord status shows, like the rate columns. |
| Own Application ID | Empty | Optional: your own Discord application, to show another name after "Playing". Empty uses ms-overlay's. |

---

## Files it creates

On Windows these are written **next to `ms-overlay.exe`**. The macOS app writes them to
**`~/Library/Application Support/ms-overlay`**, because the app's own folder has to stay
unchanged. When run from source, they're written next to `ms_overlay.py`.

| File | Contents |
|---|---|
| `maple_settings.json` | All settings, plus the window position and the last character name. Settings from older versions are migrated on load, and invalid values are replaced with defaults. If you use Discord, this file also holds the webhook URL, so don't share it. |
| `maple_log.csv` | One row per accepted change: `time` (ISO local time), `level`, `exp`, `percent`. Rows are only added, never removed, across runs. |
| `debug/` | Only with `--debug`: the raw and processed level-OCR crops. |

Nothing carries over between runs except settings and the log. Each launch starts a new
session.

---

## Command line

```bash
ms-overlay.exe [--image FILE] [--debug] [--demo]
```

| Option | Effect |
|---|---|
| *(none)* | Start the overlay. |
| `--image FILE` | Read one screenshot, print the result (level, EXP, %, name, raw text) and exit. Prints `status bar not found` if there's no bar. Useful for testing the reader. |
| `--debug` | Save the level OCR crops to `./debug`. |
| `--demo` | Run the overlay with fake, slowly rising EXP, to preview the UI without the game. |
| `--capture-test` | Try one screenshot of the game window and show what happened; saves a report (and the picture) in the data folder. See [Screenshots with level-ups](#screenshots-with-level-ups). |

From source, use `python ms_overlay.py …` or `python -m msoverlay …` instead. For the macOS app, run
`/Applications/ms-overlay.app/Contents/MacOS/ms-overlay …` from Terminal.

---

## Building from source

### Run directly

Needs Python 3.10+ and a Tesseract install.

```bash
pip install -r requirements.txt
```

```bash
python ms_overlay.py
```

Tesseract is looked for in a `tesseract` folder next to the script, then in
`C:\Program Files\Tesseract-OCR\` (Windows) or Homebrew's `/opt/homebrew/bin` and
`/usr/local/bin` (macOS), then on `PATH`. On a Mac, `brew install tesseract` is enough.

### Project layout

The code is the `msoverlay` package. `ms_overlay.py` only starts it, so the build scripts
and `python ms_overlay.py` keep working.

| Module | What it does |
|---|---|
| `__main__.py` | Command line (`--image`, `--debug`, `--demo`) |
| `paths.py` | The app's folder and the data folder |
| `settings.py` | Defaults, the choices offered, validation, loading and saving |
| `fmt.py` | Number, % and duration formatting, following the number-format setting |
| `ocr.py` | Finding and reading the status bar in pixels: glyph matching for EXP and %, Tesseract for level and name |
| `capture.py` | Screen-capture threads that feed the overlay through a queue |
| `tracker.py` | EXP bookkeeping: gains, level-ups, rates over windows |
| `session.py` | The core without UI: readings in, session out, with a clock that stops while paused |
| `datalog.py` | The CSV log |
| `discord.py` | Webhook posts, Rich Presence, and the messages they send |
| `gamewindow.py` | Screenshots of the game window only (Windows and macOS) |
| `updates.py`, `version.py` | Checking GitHub for a newer release; the app's version |
| `ui/overlay.py` | The overlay window |
| `ui/graph.py`, `ui/columns.py` | What the graph and the rate columns show, and drawing the graph |
| `ui/settings_window.py` | The settings window |
| `ui/theme.py` | Colours, fonts and drawing helpers |

Only `ui/` and `capture.py` touch Tk or the screen; everything else can be used and tested on
its own.

### Tests

```bash
pip install pytest
```

```bash
python -m pytest
```

The tests cover formatting, settings, the tracker and session (including pausing), the reader
(against status bars drawn pixel by pixel with the game's glyphs), the graph and columns, and
Discord (against a local fake webhook and a fake Discord app). A few tests build the real
overlay window; they need Tk and a display, and are skipped without them. On Linux without a
screen, use `xvfb-run -a python -m pytest`.

### Build the release zip (Windows)

```bash
build.bat
```

`build.bat` runs `build.ps1`, which:

1. Installs the Python dependencies (`mss`, `Pillow`, `numpy`, `pytesseract`, `pyinstaller`).
2. Downloads the UB-Mannheim Tesseract 5.4 installer and **unpacks** it with 7-Zip instead of
   installing it. If 7-Zip isn't installed, it's unpacked from its MSI too. No admin rights are
   needed.
3. Builds a single-file, windowless `ms-overlay.exe` with PyInstaller.
4. Trims Tesseract down to `tesseract.exe` and the `eng`/`osd` language data.
5. Zips the exe and the `tesseract` folder into `ms-overlay.zip`.

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
4. Builds `ms-overlay.app` with PyInstaller and puts Tesseract in its `Contents/Resources`.
5. Ad-hoc signs the app, checks the signature, and zips it into `ms-overlay-mac.zip`.

The app is built for the Mac's own architecture. It's ad-hoc signed only, not notarized, so
Gatekeeper asks before the first launch (see [Quick start](#macos-apple-silicon)).

### CI

`.github/workflows/tests.yml` runs the tests on every push and pull request.

`.github/workflows/release.yml` runs the same tests, then builds on `windows-latest` and on
`macos-latest` (Apple Silicon) at the same time. Before building, it writes the tag into
`msoverlay/version.py`, so the app knows its version for [update checks](#updates):

- **Pushing a `v*` tag**, e.g. `git tag v1.0.0 && git push --tags`, builds
  `ms-overlay-windows-v1.0.0.zip` and `ms-overlay-macos-v1.0.0.zip`. Once both builds
  succeed, it publishes them together as one GitHub release with auto-generated notes. If the
  tests or either build fail, nothing is published.
- **Running the workflow manually** from the Actions tab builds `ms-overlay-windows-dev.zip`
  and `ms-overlay-macos-dev.zip` and only uploads them as workflow artifacts.

---

## Troubleshooting

| Symptom | What to check |
|---|---|
| Red dot, `status bar not found` | The HP/MP/EXP bar must be visible and not covered. Very unusual UI scaling or colour filters can change the green bracket colour so it isn't recognised. |
| `unreadable digit` | A glyph in the EXP/% text didn't match. This is most likely a `5` whose shape differs from the built-in guess. It usually fixes itself once every other digit has been seen. |
| `can't read status bar` | The bar was found, but the level, EXP or % couldn't be read. Try `--debug` and check `debug/level_proc.png`. |
| `capture error` | Screen capture failed, for example because the screen is locked or a secure desktop is showing. |
| Mac: `status bar not found` while the game is visible | Allow ms-overlay under *Screen Recording* in System Settings → Privacy & Security, then quit and reopen it. Each new version needs this again. |
| Values show `~` | A level-up was estimated. See [Level-ups](#level-ups). |
| Rates reset by themselves | The character name changed. You can turn off *Start a new session when the character changes*. |
| Discord: `Couldn't post: the webhook was deleted.` | Someone deleted the webhook in Discord. Create a new one and paste its URL. |
| Discord: `(no screenshot: …)` | The reason names the step that failed. Run `ms-overlay.exe --capture-test` with the game open for details. If Windows wouldn't let ms-overlay capture the game, the part in brackets says why Graphics Capture failed; running ms-overlay as administrator, like the game, is a last resort. |
| Discord: `Not connected: Discord isn't running.` | Rich Presence needs the Discord desktop app open on the same computer. The browser version won't work. |
| Discord: `Not connected: …` with another reason | If you set an own Application ID, check it's the number from your application's *General Information* page, or clear it to use ms-overlay's. |
| Overlay hidden behind the game | Turn on *Always on top*, and run the game in windowed or borderless mode. Exclusive fullscreen can cover overlays. |

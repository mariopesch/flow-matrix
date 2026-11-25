# LED Animator

A web interface for a Raspberry Pi with the Adafruit RGB Matrix HAT + RTC and chained 32×32 panels. Use it to draw animations, play effects, show the clock or the weather, and run a playlist. It works from any phone or computer on your network.

## Install

On a fresh Raspberry Pi OS (Lite is fine), copy this folder to the Pi and run the installer:

```bash
# on your computer
scp -r led-animator <user>@<pi-name>.local:~/

# on the Pi
cd ~/led-animator
chmod +x install.sh run.sh
./install.sh
```

The installer asks a few questions: how many panels you have, whether you soldered the jumper on the HAT, whether to use the clock chip, and whether to start automatically at boot. It then sets everything up and reboots if needed.

Open **http://\<pi-name\>.local:8080** in a browser.

## Use

| Area | What it does |
|---|---|
| Editor | Draw frames, add/duplicate/reorder them, preview, save. Tick **Live on matrix** to draw directly on the panels |
| Effects | Plasma, Fire, Matrix rain, Fireworks, Snowfall and more. **→ Editor** copies an effect into editable frames |
| Views | Clock, Weather, Clock + weather. Set the city for the weather here (free data from Open-Meteo, no account needed) |
| openSenseMap | Paste an openSenseMap box ID (or its link from opensensemap.org), tick the sensors to show, pick **One at a time** or **List**, then **Show on matrix**. Values update every minute; values older than an hour are dimmed. The **openSenseMap** view can also go in the playlist |
| Games | **Paddle Duel**: two players, one at each end of the matrix. Players open **http://\<pi-name\>.local:8080/play** on their phones and slide a finger to steer; the matrix also shows this address. With one player, the computer takes the other side. Each hit speeds the ball up, and green orbs give the last player who hit the ball a bigger paddle for 10 seconds. First to 7 wins |
| Playlist | Rotates through animations, effects and views |
| Image / GIF, Text | Import pictures or animated GIFs, or create scrolling text |

After a reboot, the matrix shows whatever was showing before.

## Start, stop, update

```bash
./run.sh                                  # start by hand (Ctrl+C to stop)
sudo systemctl restart led-animator       # restart (with autostart)
sudo systemctl stop led-animator          # stop
journalctl -u led-animator -f             # view the log
```

To update, copy the new files over the old ones and restart. Your animations and settings in `data/` are kept.

## Settings

Settings are in `config.env`. Change them by running `./install.sh` again or by editing the file, then restart.

| Setting | Meaning |
|---|---|
| `CHAIN` | Number of panels |
| `MAPPING` | `adafruit-hat`, or `adafruit-hat-pwm` if GPIO4 and GPIO18 are soldered together |
| `SLOWDOWN` | 1–4. Raise it if you see glitches or random pixels |
| `EXTRA_ARGS` | e.g. `--pwm-bits 8` against flicker. See `./run.sh --help` |

## Troubleshooting

- **The page says "SIMULATOR"**: the matrix driver isn't installed. Run `./install.sh` again.
- **Flicker**: use `MAPPING=adafruit-hat-pwm` (needs the solder jumper) or add `--pwm-bits 8` to `EXTRA_ARGS`.
- **Wrong colors, garbled or duplicated content**: open **Views → Test pattern**. Each panel should show a white border, a white dot in the top-left corner and a big number: 1 red, 2 green, 3 blue (left to right). Fix what's off by adding options to `EXTRA_ARGS` in `config.env`, then restart:
  - Wrong colors: `--rgb-sequence RBG` (or `BGR`, `GRB`, `GBR`, `BRG`). The R/G/B bars at the top show which color appears where.
  - Garbled characters, repeated rows or blocks: `--multiplexing 1` (try 1 to 18), then `--row-addr-type 1` to `4`, then `--scan-mode 1`.
  - Everything upside down: `--pixel-mapper "Rotate:180"`.
  - Panels stay dark or flicker oddly: `--panel-type FM6126A`.
- **Weather shows an error**: the Pi needs internet access. Check the spelling of the city.
- **Phones can't join a game** ("Reconnecting…"): phone controllers use a second port, 8081 by default (the web port + 1, or `--game-port` in `EXTRA_ARGS`). The phone must be on the same network as the Pi, and guest Wi‑Fi networks often block devices from reaching each other.

## Project layout

```
app.py              web server + API
run.sh              starts the app with config.env
install.sh          installer
ledanim/            display engine: driver, scenes, effects, weather, openSenseMap,
                    games, WebSocket server for phone controllers, pixel font
static/             web interface
data/               your animations, playlist and saved state
```

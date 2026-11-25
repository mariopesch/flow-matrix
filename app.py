#!/usr/bin/env python3
"""
LED Animator - web editor & display controller for an RGB LED matrix.

Hardware: Raspberry Pi + Adafruit RGB Matrix HAT (+RTC) + chained 32x32 panels.
Start with ./run.sh (needs root for GPIO), then open http://<pi>:8080.
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import signal
import sys

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageSequence

from ledanim.driver import MatrixDriver
from ledanim.scenes import (AnimationScene, ClockScene, EffectScene, LiveScene,
                            PlaylistScene, OpenSenseMapScene, TestPatternScene, WeatherScene)
from ledanim.opensensemap import OpenSenseMapService
from ledanim.weather import WeatherService

try:
    from ledanim.effects import EFFECTS
    EFFECTS_ERROR = None
except ImportError as exc:  # numpy missing
    EFFECTS, EFFECTS_ERROR = {}, "effects need numpy: sudo apt install python3-numpy (%s)" % exc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ANIM_DIR = os.path.join(DATA_DIR, "animations")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
PLAYLIST_FILE = os.path.join(DATA_DIR, "playlist.json")
MAX_FRAMES = 1000
VIEWS = {"clock": "Clock", "weather": "Weather", "dashboard": "Clock + weather",
         "opensensemap": "openSenseMap", "test": "Test pattern"}

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
driver = None   # type: MatrixDriver
weather = None  # type: WeatherService
opensensemap = None  # type: OpenSenseMapService
settings = {"clock_color": "#ff8c00", "effect_speed": 1.0}


# ------------------------------------------------------------- helpers
def safe_name(name):
    name = re.sub(r"[^A-Za-z0-9_\- ]", "", str(name or "")).strip().replace(" ", "_")
    if not name:
        abort(400, "invalid name")
    return name[:64]


def anim_path(name):
    return os.path.join(ANIM_DIR, safe_name(name) + ".json")


def read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    with open(path + ".tmp", "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(path + ".tmp", path)


def parse_color(value, default=(255, 140, 0)):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(value or ""))
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else default


def decode_frame(b64):
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        abort(400, "frame data is not valid base64")
    need = driver.width * driver.height * 3
    if len(raw) != need:
        abort(400, "frame must be %d bytes (got %d)" % (need, len(raw)))
    return Image.frombytes("RGB", (driver.width, driver.height), raw)


def encode_image(img):
    return base64.b64encode(img.convert("RGB").tobytes()).decode("ascii")


def validate_animation(data):
    """Return (normalized dict, list of (image, seconds))."""
    if not isinstance(data, dict) or not isinstance(data.get("frames"), list) or not data["frames"]:
        abort(400, "animation needs at least one frame")
    if len(data["frames"]) > MAX_FRAMES:
        abort(400, "too many frames (max %d)" % MAX_FRAMES)
    frames, norm = [], []
    for f in data["frames"]:
        if not isinstance(f, dict):
            abort(400, "bad frame")
        dur = int(max(10, min(60000, int(f.get("duration", 100)))))
        frames.append((decode_frame(f.get("data", "")), dur / 1000.0))
        norm.append({"data": f["data"], "duration": dur})
    return {"width": driver.width, "height": driver.height,
            "loop": bool(data.get("loop", True)), "frames": norm}, frames


def load_animation(name):
    path = anim_path(name)
    if not os.path.exists(path):
        abort(404, "animation '%s' not found" % name)
    return read_json(path, {})


# -------------------------------------------------------------- scenes
def build_scene(spec, nested=False):
    """Create (scene, normalized spec) from e.g. {"type": "effect", "name": "fire"}."""
    kind, name = spec.get("type"), spec.get("name")
    W, H = driver.width, driver.height
    if kind == "animation":
        data = load_animation(name)
        _, frames = validate_animation(data)
        loop = True if nested else data.get("loop", True)
        return AnimationScene(frames, loop), {"type": "animation", "name": safe_name(name)}
    if kind == "effect":
        if name not in EFFECTS:
            abort(400, EFFECTS_ERROR or "unknown effect '%s'" % name)
        speed = max(0.1, min(5.0, float(spec.get("speed", settings["effect_speed"]))))
        return EffectScene(EFFECTS[name], W, H, speed), {"type": "effect", "name": name, "speed": speed}
    if kind == "view":
        color = parse_color(spec.get("color") or settings["clock_color"])
        if name == "clock":
            return ClockScene(W, H, color), {"type": "view", "name": name}
        if name == "test":
            return TestPatternScene(W, H), {"type": "view", "name": name}
        if name == "opensensemap":
            return OpenSenseMapScene(opensensemap, W, H, color), {"type": "view", "name": name}
        if name in ("weather", "dashboard"):
            return WeatherScene(weather, W, H, style=name, color=color), {"type": "view", "name": name}
        abort(400, "unknown view '%s'" % name)
    if kind == "playlist" and not nested:
        items = []
        for item in read_json(PLAYLIST_FILE, []):
            try:
                items.append((build_scene(item, nested=True)[0], item.get("seconds", 20)))
            except Exception as exc:
                print("playlist: skipping", item, exc)
        if not items:
            abort(400, "playlist is empty")
        return PlaylistScene(items), {"type": "playlist"}
    abort(400, "unknown type '%s'" % kind)


def show(spec):
    if spec.get("type") == "off":
        driver.stop()
    else:
        scene, norm = build_scene(spec)
        driver.show(scene, norm)
    save_state()


def save_state():
    spec = driver.spec
    if spec.get("type") in ("live", "unsaved"):
        spec = {"type": "off"}
    state = {"spec": spec, "brightness": driver.brightness,
             "weather": {"city": weather.city, "units": weather.units},
             "opensensemap": opensensemap.config(), **settings}
    try:
        write_json(STATE_FILE, state)
    except OSError as exc:
        print("could not save state:", exc)


def migrate_old_layout():
    """v1/v2 kept animations/, state.json and playlist.json next to app.py."""
    old_anims = os.path.join(BASE_DIR, "animations")
    if os.path.isdir(old_anims):
        for fn in os.listdir(old_anims):
            if fn.endswith(".json") and not os.path.exists(os.path.join(ANIM_DIR, fn)):
                shutil.move(os.path.join(old_anims, fn), os.path.join(ANIM_DIR, fn))
        try:
            os.rmdir(old_anims)  # only succeeds if it is empty now
        except OSError:
            pass
    for fn in ("state.json", "playlist.json"):
        old = os.path.join(BASE_DIR, fn)
        if os.path.exists(old) and not os.path.exists(os.path.join(DATA_DIR, fn)):
            shutil.move(old, os.path.join(DATA_DIR, fn))


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
def json_error(err):
    return jsonify(error=getattr(err, "description", str(err))), err.code


# ---------------------------------------------------------- endpoints
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def api_status():
    return jsonify({**driver.status(), **settings})


@app.get("/api/catalog")
def api_catalog():
    return jsonify(effects=[{"id": k, "title": v.title} for k, v in EFFECTS.items()],
                   effects_error=EFFECTS_ERROR,
                   views=[{"id": k, "title": v} for k, v in VIEWS.items()])


@app.post("/api/show")
def api_show():
    body = request.get_json(silent=True) or {}
    if body.get("type") == "view" and body.get("color"):
        settings["clock_color"] = "#%02x%02x%02x" % parse_color(body["color"])
    if body.get("type") == "effect" and "speed" in body:
        settings["effect_speed"] = max(0.1, min(5.0, float(body["speed"])))
    show(body)
    return jsonify(driver.status())


@app.post("/api/play")
def api_play():
    """Play a saved animation by name, or an unsaved one sent from the editor."""
    body = request.get_json(silent=True) or {}
    if body.get("name"):
        show({"type": "animation", "name": body["name"]})
    elif body.get("animation"):
        norm, frames = validate_animation(body["animation"])
        driver.show(AnimationScene(frames, norm["loop"]), {"type": "unsaved"})
        save_state()
    else:
        abort(400, "give 'name' or 'animation'")
    return jsonify(driver.status())


@app.post("/api/live")
def api_live():
    body = request.get_json(silent=True) or {}
    driver.show(LiveScene(decode_frame(body.get("data", ""))), {"type": "live"})
    return jsonify(ok=True)


@app.post("/api/brightness")
def api_brightness():
    try:
        driver.set_brightness(int((request.get_json(silent=True) or {}).get("value")))
    except (TypeError, ValueError):
        abort(400, "value must be 1-100")
    save_state()
    return jsonify(driver.status())


@app.get("/api/screen.png")
def api_screen():
    buf = io.BytesIO()
    driver.current_image.save(buf, "PNG")
    buf.seek(0)
    resp = send_file(buf, mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/animations")
def api_list():
    items = []
    for fn in sorted(os.listdir(ANIM_DIR)):
        if fn.endswith(".json"):
            path = os.path.join(ANIM_DIR, fn)
            n = len(read_json(path, {}).get("frames", []))
            items.append({"name": fn[:-5], "frames": n, "modified": os.path.getmtime(path)})
    return jsonify(items)


@app.get("/api/animations/<name>")
def api_get(name):
    return jsonify(load_animation(name))


@app.put("/api/animations/<name>")
def api_save(name):
    norm, _ = validate_animation(request.get_json(silent=True))
    write_json(anim_path(name), norm)
    return jsonify(ok=True, name=safe_name(name))


@app.delete("/api/animations/<name>")
def api_delete(name):
    path = anim_path(name)
    if not os.path.exists(path):
        abort(404, "animation not found")
    os.remove(path)
    if driver.spec == {"type": "animation", "name": safe_name(name)}:
        show({"type": "off"})
    return jsonify(ok=True)


@app.post("/api/import")
def api_import():
    """Convert an uploaded image / animated GIF into editor frames."""
    up = request.files.get("file")
    if up is None:
        abort(400, "no file uploaded")
    fit = request.form.get("fit", "contain")
    try:
        src = Image.open(up.stream)
    except Exception:
        abort(400, "not an image file")
    W, H = driver.width, driver.height
    frames = []
    for frame in ImageSequence.Iterator(src):
        if len(frames) >= MAX_FRAMES:
            break
        rgba = frame.convert("RGBA")
        img = Image.alpha_composite(Image.new("RGBA", rgba.size, (0, 0, 0, 255)), rgba).convert("RGB")
        sw, sh = img.size
        if fit == "stretch":
            tw, th = W, H
        else:
            s = max(W / sw, H / sh) if fit == "cover" else min(W / sw, H / sh)
            tw, th = max(1, round(sw * s)), max(1, round(sh * s))
        img = img.resize((tw, th), Image.NEAREST if tw >= sw else Image.LANCZOS)
        out = Image.new("RGB", (W, H))
        out.paste(img, ((W - tw) // 2, (H - th) // 2))
        dur = int(frame.info.get("duration", 100) or 100)
        frames.append({"data": encode_image(out), "duration": max(20, dur)})
    return jsonify(frames=frames, loop=True)


@app.post("/api/capture")
def api_capture():
    """Render a few seconds of an effect into editor frames."""
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if name not in EFFECTS:
        abort(400, EFFECTS_ERROR or "unknown effect")
    fps = max(1, min(30, int(body.get("fps", 15))))
    seconds = max(0.5, min(20.0, float(body.get("seconds", 3))))
    speed = float(body.get("speed", 1.0))
    eff = EFFECTS[name](driver.width, driver.height)
    for _ in range(int(1.5 * fps)):  # warm up (fire, snow... need a moment)
        eff.step(speed / fps)
    frames = [{"data": encode_image(Image.fromarray(eff.step(speed / fps), "RGB")),
               "duration": int(1000 / fps)} for _ in range(int(seconds * fps))]
    return jsonify(frames=frames, loop=True)


@app.get("/api/weather")
def api_weather():
    return jsonify(weather.info())


@app.post("/api/weather")
def api_weather_set():
    body = request.get_json(silent=True) or {}
    weather.configure(city=str(body.get("city", "")).strip()[:80] or None, units=body.get("units"))
    save_state()
    return jsonify(weather.info())


@app.get("/api/opensensemap")
def api_opensensemap():
    return jsonify(opensensemap.info())


@app.post("/api/opensensemap")
def api_opensensemap_set():
    """{"box": "<id or link>"} loads a box; {"sensors": [...], "mode": "big|list"} picks what to show."""
    body = request.get_json(silent=True) or {}
    if body.get("box"):
        try:
            opensensemap.set_box(str(body["box"])[:300])
        except ValueError as exc:
            abort(400, str(exc))
    sensors = body.get("sensors")
    if sensors is not None and not isinstance(sensors, list):
        abort(400, "sensors must be a list")
    opensensemap.configure(sensors=sensors, mode=body.get("mode"))
    save_state()
    return jsonify(opensensemap.info())


@app.get("/api/playlist")
def api_playlist():
    return jsonify(read_json(PLAYLIST_FILE, []))


@app.put("/api/playlist")
def api_playlist_save():
    items = request.get_json(silent=True)
    if not isinstance(items, list):
        abort(400, "playlist must be a list")
    clean = []
    for it in items[:100]:
        if not isinstance(it, dict) or it.get("type") not in ("animation", "effect", "view"):
            abort(400, "bad playlist item")
        c = {"type": it["type"], "name": str(it.get("name", "")),
             "seconds": max(1, min(3600, int(it.get("seconds", 20))))}
        if it["type"] == "effect" and "speed" in it:
            c["speed"] = max(0.1, min(5.0, float(it["speed"])))
        clean.append(c)
    write_json(PLAYLIST_FILE, clean)
    return jsonify(clean)


# --------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="Web animation editor for RGB LED matrices")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--rows", type=int, default=32, help="rows per panel")
    p.add_argument("--cols", type=int, default=32, help="columns per panel")
    p.add_argument("--chain", type=int, default=3, help="number of chained panels")
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--mapping", default="adafruit-hat",
                   help="adafruit-hat, or adafruit-hat-pwm with the GPIO4-GPIO18 solder mod")
    p.add_argument("--slowdown", type=int, default=2, help="GPIO slowdown (Pi 3: 1-2, Pi 4: 3-4)")
    p.add_argument("--brightness", type=int, default=60)
    p.add_argument("--pwm-bits", type=int, default=11, help="lower = less flicker, fewer colors")
    p.add_argument("--no-hardware-pulse", action="store_true")
    g = p.add_argument_group("panel quirks (see the Troubleshooting section of the README)")
    g.add_argument("--rgb-sequence", default="RGB", help="color order of the panel, e.g. RBG, BGR, GRB")
    g.add_argument("--multiplexing", type=int, default=0, help="0=direct, 1=stripe, 2=checker, ... up to 18")
    g.add_argument("--row-addr-type", type=int, default=0, help="0=default, 1=AB, 2=direct, 3=ABC, 4=ABC shift+DE")
    g.add_argument("--scan-mode", type=int, default=0, help="0=progressive, 1=interlaced")
    g.add_argument("--panel-type", default="", help="FM6126A or FM6127 for panels that need init")
    g.add_argument("--pixel-mapper", default="", help='e.g. "Rotate:180" or "Mirror:H"')
    p.add_argument("--simulate", action="store_true", help="run without matrix hardware")
    args = p.parse_args()

    os.makedirs(ANIM_DIR, exist_ok=True)
    migrate_old_layout()
    state = read_json(STATE_FILE, {})
    settings.update({k: state[k] for k in settings if k in state})

    global driver, weather, opensensemap
    driver = MatrixDriver(rows=args.rows, cols=args.cols, chain=args.chain,
                          parallel=args.parallel, hardware_mapping=args.mapping,
                          gpio_slowdown=args.slowdown, brightness=state.get("brightness", args.brightness),
                          pwm_bits=args.pwm_bits, no_hardware_pulse=args.no_hardware_pulse,
                          force_simulator=args.simulate,
                          panel_options={"led_rgb_sequence": args.rgb_sequence,
                                         "multiplexing": args.multiplexing,
                                         "row_address_type": args.row_addr_type,
                                         "scan_mode": args.scan_mode,
                                         "panel_type": args.panel_type,
                                         "pixel_mapper_config": args.pixel_mapper})
    wcfg = state.get("weather", {})
    weather = WeatherService(city=wcfg.get("city", "Berlin"), units=wcfg.get("units", "metric"))
    scfg = state.get("opensensemap", {})
    opensensemap = OpenSenseMapService(box_id=scfg.get("box"), sensors=scfg.get("sensors"), mode=scfg.get("mode", "big"))

    spec = state.get("spec") or {}
    if spec.get("type") not in (None, "off"):
        try:
            show(spec)
        except Exception as exc:
            print("could not restore previous view:", exc)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print("LED Animator %dx%d (%s)" % (driver.width, driver.height,
                                     "hardware" if driver.hardware else "SIMULATOR - rgbmatrix not found"))
    if EFFECTS_ERROR:
        print("WARNING:", EFFECTS_ERROR)
    print("Web UI: http://<this-pi>:%d" % args.port)
    try:
        try:
            from waitress import serve
            serve(app, host=args.host, port=args.port, threads=6)
        except ImportError:
            app.run(host=args.host, port=args.port, threaded=True)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        driver.shutdown()


if __name__ == "__main__":
    main()

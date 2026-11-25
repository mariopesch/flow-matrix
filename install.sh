#!/usr/bin/env bash
# =====================================================================
#  LED Animator installer for Raspberry Pi OS (Bookworm / Trixie / Bullseye)
#
#  Installs all dependencies, builds the rpi-rgb-led-matrix driver into a
#  Python virtual environment, configures the Pi for the matrix (sound off,
#  optional CPU isolation and RTC) and optionally enables autostart.
#
#  Usage:   ./install.sh          (interactive)
#           ./install.sh --yes    (accept all defaults)
#  Safe to run again: finished steps are skipped.
# =====================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RGB_DIR="${RGB_DIR:-$HOME/rpi-rgb-led-matrix}"
RGB_REPO="https://github.com/hzeller/rpi-rgb-led-matrix.git"
SERVICE="led-animator"
VENV="$DIR/venv"
VPY="$VENV/bin/python"
REBOOT_NEEDED=0
ASSUME_YES=0
[[ "${1:-}" == "-y" || "${1:-}" == "--yes" ]] && ASSUME_YES=1

# ------------------------------------------------------------- helpers
c_b=$'\e[1m'; c_g=$'\e[32m'; c_y=$'\e[33m'; c_r=$'\e[31m'; c_0=$'\e[0m'
step() { echo; echo "${c_b}==> $*${c_0}"; }
ok()   { echo "${c_g}✔${c_0} $*"; }
warn() { echo "${c_y}!${c_0} $*"; }
die()  { echo "${c_r}✘ $*${c_0}" >&2; exit 1; }

ask() {  # ask "question" default  -> prints answer
    local ans
    if [[ $ASSUME_YES == 1 ]]; then echo "$2"; return; fi
    read -r -p "$1 [$2]: " ans </dev/tty || true
    echo "${ans:-$2}"
}
ask_yn() {  # ask_yn "question" y|n  -> exit status 0 = yes
    local def=$2 hint ans
    [[ $def == y ]] && hint="Y/n" || hint="y/N"
    if [[ $ASSUME_YES == 1 ]]; then ans=$def; else
        read -r -p "$1 [$hint]: " ans </dev/tty || true
        ans=${ans:-$def}
    fi
    [[ ${ans,,} == y* ]]
}

boot_file() {  # boot_file config.txt|cmdline.txt
    if [[ -f /boot/firmware/$1 ]]; then echo "/boot/firmware/$1"; else echo "/boot/$1"; fi
}

# -------------------------------------------------------------- checks
[[ $EUID -eq 0 ]] && die "Run this as your normal user (./install.sh). It uses sudo where needed."
command -v apt-get >/dev/null || die "This installer needs Raspberry Pi OS / Debian (apt-get)."

MODEL="$(tr -d '\0' 2>/dev/null </proc/device-tree/model || echo unknown)"
case "$MODEL" in
    *"Pi 5"*) warn "$MODEL: the rpi-rgb-led-matrix driver does not support the Pi 5."
              ask_yn "Continue anyway?" n || exit 1; DEF_SLOWDOWN=4 ;;
    *"Pi 4"*|*"Compute Module 4"*) DEF_SLOWDOWN=4 ;;
    *"Pi 3"*|*"Zero 2"*) DEF_SLOWDOWN=2 ;;
    *"Pi Zero"*|*"Pi Model"*|*"Pi 2"*) DEF_SLOWDOWN=1 ;;
    *) DEF_SLOWDOWN=2 ;;
esac

# Previous answers become the new defaults when re-running
PORT=8080; CHAIN=3; MAPPING=adafruit-hat; SLOWDOWN=$DEF_SLOWDOWN; EXTRA_ARGS=""
# shellcheck disable=SC1091
[[ -f "$DIR/config.env" ]] && . "$DIR/config.env"

echo "${c_b}LED Animator installer${c_0}"
echo "Device:  $MODEL"
echo "Folder:  $DIR"
echo
echo "A few questions first - after that the install runs on its own (~10-20 min on a Pi 3)."
echo

CHAIN=$(ask "How many 32x32 panels are chained?" "$CHAIN")
[[ $MAPPING == adafruit-hat-pwm ]] && def_pwm=y || def_pwm=n
if ask_yn "Did you solder the jumper between GPIO4 and GPIO18 on the HAT (less flicker)?" "$def_pwm"; then
    MAPPING=adafruit-hat-pwm
else
    MAPPING=adafruit-hat
fi
PORT=$(ask "Web interface port" "$PORT")
DO_ISOL=n; [[ $(nproc) -ge 4 ]] && ask_yn "Reserve one CPU core for the matrix (recommended, less flicker)?" y && DO_ISOL=y
DO_RTC=n;  ask_yn "Set up the HAT's real-time clock (DS1307, needs a CR1220 battery)?" y && DO_RTC=y
DO_AUTO=n; ask_yn "Start LED Animator automatically at boot?" y && DO_AUTO=y

[[ $CHAIN =~ ^[0-9]+$ ]] || die "Number of panels must be a number"
[[ $PORT =~ ^[0-9]+$ ]] || die "Port must be a number"

sudo -v || die "sudo is required"

# ----------------------------------------------------------- packages
step "Installing system packages"
sudo apt-get update
sudo apt-get install -y \
    git build-essential cmake pkg-config cython3 \
    python3-dev python3-venv python3-pip \
    python3-pil python3-flask python3-waitress python3-numpy \
    fonts-dejavu-core
ok "Packages installed"

# ------------------------------------------------------ matrix driver
step "Matrix driver (rpi-rgb-led-matrix)"
if [[ -d $RGB_DIR ]]; then
    ok "Using existing source in $RGB_DIR"
else
    git clone --depth 1 "$RGB_REPO" "$RGB_DIR"
    ok "Downloaded to $RGB_DIR"
fi

step "Python environment"
if [[ ! -x $VPY ]]; then
    python3 -m venv --system-site-packages "$VENV"
    ok "Created $VENV"
else
    ok "Using existing $VENV"
fi

if "$VPY" -c "import rgbmatrix" 2>/dev/null; then
    ok "rgbmatrix Python module already installed"
else
    echo "Building the rgbmatrix Python module - this takes a while..."
    (
        # shellcheck disable=SC1091
        source "$VENV/bin/activate"
        cd "$RGB_DIR"
        if grep -q "install-python" Makefile 2>/dev/null; then
            make install-python PYTHON="$VPY"
        elif [[ -f pyproject.toml || -f setup.py ]]; then
            pip install .
        else
            cd bindings/python && pip install .
        fi
    ) || die "Building the matrix driver failed (see the messages above)"
    "$VPY" -c "import rgbmatrix" 2>/dev/null || die "rgbmatrix module still not importable after the build"
    ok "rgbmatrix installed"
fi
"$VPY" -c "import flask, PIL, numpy" || die "Python dependencies missing in the venv"
ok "All Python modules available"

# ----------------------------------------------------- system config
step "Configuring the Raspberry Pi for the matrix"
BOOT_CFG=$(boot_file config.txt)
CMDLINE=$(boot_file cmdline.txt)

# The onboard sound uses the same hardware as the matrix driver -> disable it
BLACKLIST=/etc/modprobe.d/blacklist-rgb-matrix.conf
if [[ ! -f $BLACKLIST ]]; then
    echo "blacklist snd_bcm2835" | sudo tee "$BLACKLIST" >/dev/null
    REBOOT_NEEDED=1
fi
if [[ -f $BOOT_CFG ]] && grep -q "^dtparam=audio=on" "$BOOT_CFG"; then
    sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$BOOT_CFG"
    REBOOT_NEEDED=1
fi
ok "Onboard sound disabled"

if [[ $DO_ISOL == y && -f $CMDLINE ]]; then
    if ! grep -q "isolcpus=" "$CMDLINE"; then
        sudo sed -i '1 s/$/ isolcpus=3/' "$CMDLINE"
        REBOOT_NEEDED=1
    fi
    ok "CPU core 3 reserved for the matrix"
fi

if [[ $DO_RTC == y && -f $BOOT_CFG ]]; then
    command -v raspi-config >/dev/null && sudo raspi-config nonint do_i2c 0
    if ! grep -q "^dtoverlay=i2c-rtc" "$BOOT_CFG"; then
        printf '\n[all]\ndtoverlay=i2c-rtc,ds1307\n' | sudo tee -a "$BOOT_CFG" >/dev/null
        REBOOT_NEEDED=1
    fi
    if dpkg -s fake-hwclock >/dev/null 2>&1; then
        sudo apt-get -y remove fake-hwclock
        sudo update-rc.d -f fake-hwclock remove 2>/dev/null || true
    fi
    if [[ -f /lib/udev/hwclock-set ]]; then  # let udev set the clock from the RTC (older OS versions)
        sudo sed -i '/^if \[ -e \/run\/systemd\/system \] ; then/,/^fi/ s/^/#/' /lib/udev/hwclock-set
    fi
    ok "Real-time clock configured"
fi

# ------------------------------------------------------------ config
cat >"$DIR/config.env" <<EOF
# LED Animator settings - used by run.sh. Re-run install.sh or edit by hand.
PORT=$PORT
CHAIN=$CHAIN
MAPPING=$MAPPING
SLOWDOWN=$SLOWDOWN
# more app.py options, e.g. EXTRA_ARGS="--pwm-bits 8 --brightness 40"
EXTRA_ARGS="$EXTRA_ARGS"
EOF
chmod +x "$DIR/run.sh"
mkdir -p "$DIR/data/animations"
ok "Settings saved to config.env"

# --------------------------------------------------------- autostart
step "Autostart"
UNIT=/etc/systemd/system/$SERVICE.service
if [[ $DO_AUTO == y ]]; then
    sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=LED Animator (RGB matrix web editor)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$DIR
ExecStart=$DIR/run.sh
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE" >/dev/null 2>&1
    if [[ $REBOOT_NEEDED == 0 ]]; then
        sudo systemctl restart "$SERVICE"
        ok "Autostart enabled and LED Animator started"
    else
        ok "Autostart enabled (starts after the reboot)"
    fi
else
    if [[ -f $UNIT ]]; then
        sudo systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
        sudo rm -f "$UNIT"
        sudo systemctl daemon-reload
    fi
    ok "No autostart - start manually with: $DIR/run.sh"
fi

# ----------------------------------------------------------- summary
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "${c_g}${c_b}Installation complete!${c_0}"
echo "Web interface:  http://$(hostname).local:$PORT   or   http://${IP:-<pi-ip>}:$PORT"
[[ $DO_RTC == y ]] && echo "RTC: after the reboot, once the Pi has internet time, store it once with:  sudo hwclock -w"
if [[ $REBOOT_NEEDED == 1 ]]; then
    echo
    warn "A reboot is needed for the system changes to take effect."
    if ask_yn "Reboot now?" y; then
        sudo reboot
    else
        echo "Reboot later with:  sudo reboot"
    fi
fi

#!/usr/bin/env python3
import os, subprocess, pathlib

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, AppIndicator3, GLib

HEAD_STATE = os.path.expanduser("~/.config/ae5-headphones.state")
SPK_STATE  = os.path.expanduser("~/.config/ae5-speakers.state")
MARK_FILE  = os.path.expanduser("~/.config/ae5-current")  # guarda "headphones" o "speakers"

APP_ID = "ae5.audio.switcher"
ICON_DEFAULT    = "audio-card"
ICON_HEADPHONES = "audio-headphones"
ICON_SPEAKERS   = "audio-speakers"

def sh(cmd):
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def notify(msg):
    subprocess.run(f"notify-send 'AE-5' '{msg}'", shell=True)

def restore(state_file):
    return sh(f"alsactl --file {state_file} restore")

def mark_set(mode):
    try:
        pathlib.Path(os.path.dirname(MARK_FILE)).mkdir(parents=True, exist_ok=True)
        with open(MARK_FILE, "w") as f:
            f.write(mode.strip())
    except Exception:
        pass

def mark_get():
    try:
        with open(MARK_FILE) as f:
            v = f.read().strip().lower()
            if v in ("headphones", "speakers"):
                return v
    except Exception:
        pass
    return None

def find_ae5_card_index():
    try:
        with open("/proc/asound/cards") as f:
            for line in f:
                line=line.rstrip("\n")
                if "[" in line and "]" in line and any(x in line for x in ("Sound BlasterX AE-5","AE-5","CA0132")):
                    # índice es el primer token de la línea
                    return int(line.strip().split()[0])
    except Exception:
        pass
    return None

def find_hp_speakers_enum(card_index):
    if card_index is None: return None
    out = sh(f"amixer -c {card_index} controls").stdout
    # 1) candidatos por nombre
    for line in out.splitlines():
        if "numid=" not in line: continue
        if any(p in line.lower() for p in ("output select","headphone","speaker","route","output","hp")):
            numid = line.split("numid=")[1].split(",")[0]
            cg = sh(f"amixer -c {card_index} cget numid={numid}").stdout
            if "type=ENUMERATED" in cg and "Headphones" in cg and "Speakers" in cg:
                return numid
    # 2) escaneo completo
    for line in out.splitlines():
        if "numid=" not in line: continue
        numid = line.split("numid=")[1].split(",")[0]
        cg = sh(f"amixer -c {card_index} cget numid={numid}").stdout
        if "type=ENUMERATED" in cg and "Headphones" in cg and "Speakers" in cg:
            return numid
    return None

def current_from_enum(card_index, numid):
    if card_index is None or numid is None: return None
    cg = sh(f"amixer -c {card_index} cget numid={numid}").stdout.lower()
    for ln in cg.splitlines():
        if ": values=" in ln:
            val = ln.split(": values=")[1].strip().strip("[]").lower()
            if "head" in val:  return "headphones"
            if "speak" in val: return "speakers"
    return None

class Indicator:
    def __init__(self):
        self.card  = find_ae5_card_index()
        self.numid = find_hp_speakers_enum(self.card)

        self.ind = AppIndicator3.Indicator.new(APP_ID, ICON_DEFAULT, AppIndicator3.IndicatorCategory.SYSTEM_SERVICES)
        self.ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        # Menú
        self.menu = Gtk.Menu()
        self.item_head = Gtk.MenuItem(label="Switch → 🎧 Headphones")
        self.item_head.connect("activate", self.to_headphones)
        self.menu.append(self.item_head)

        self.item_spk = Gtk.MenuItem(label="Switch → 🔊 Speakers")
        self.item_spk.connect("activate", self.to_speakers)
        self.menu.append(self.item_spk)

        self.item_toggle = Gtk.MenuItem(label="Toggle 🎧/🔊")
        self.item_toggle.connect("activate", self.toggle)
        self.menu.append(self.item_toggle)

        self.menu.append(Gtk.SeparatorMenuItem())
        self.item_quit = Gtk.MenuItem(label="Salir")
        self.item_quit.connect("activate", self.quit)
        self.menu.append(self.item_quit)

        self.menu.show_all()
        self.ind.set_menu(self.menu)

        # Clic medio en el icono -> activa "Toggle"
        self.ind.set_secondary_activate_target(self.item_toggle)

        # Refresco periódico de icono/label
        GLib.timeout_add_seconds(2, self.refresh)

    def detect_state(self):
        """
        Intenta detectar estado real por ENUM ALSA; si no es posible, usa MARK_FILE.
        Devuelve 'headphones', 'speakers' o None.
        """
        s = current_from_enum(self.card, self.numid)
        if s: return s
        return mark_get()

    def refresh(self):
        state = self.detect_state()
        if state == "headphones":
            self.ind.set_icon_full(ICON_HEADPHONES, "")
            self.ind.set_label("AE-5 🎧", "")
        elif state == "speakers":
            self.ind.set_icon_full(ICON_SPEAKERS, "")
            self.ind.set_label("AE-5 🔊", "")
        else:
            self.ind.set_icon_full(ICON_DEFAULT, "")
            self.ind.set_label("AE-5", "")
        return True

    def ensure_states(self):
        miss=[]
        if not os.path.exists(HEAD_STATE): miss.append("~/.config/ae5-headphones.state")
        if not os.path.exists(SPK_STATE):  miss.append("~/.config/ae5-speakers.state")
        if miss:
            notify("Faltan estados ALSA:\n" + "\n".join(miss))
            return False
        return True

    def to_headphones(self, _=None):
        if not self.ensure_states(): return
        r = restore(HEAD_STATE)
        if r.returncode == 0:
            mark_set("headphones")
            notify("🎧 Headphones")
        else:
            notify(f"Error: {r.stderr}")
        self.refresh()

    def to_speakers(self, _=None):
        if not self.ensure_states(): return
        r = restore(SPK_STATE)
        if r.returncode == 0:
            mark_set("speakers")
            notify("🔊 Speakers")
        else:
            notify(f"Error: {r.stderr}")
        self.refresh()

    def toggle(self, _=None):
        # 1) Si podemos leer el estado real por ENUM, úsalo
        state = current_from_enum(self.card, self.numid)
        if state == "headphones":
            return self.to_speakers()
        if state == "speakers":
            return self.to_headphones()
        # 2) Fallback al marker si no hay ENUM
        state = mark_get()
        if state == "headphones":
            return self.to_speakers()
        # por defecto, pasa a headphones
        return self.to_headphones()

    def quit(self, _=None):
        Gtk.main_quit()

def main():
    Indicator()
    Gtk.main()

if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""
TLB Intel Maker - Google Slides -> Arma 3 .paa intel images.

Downloads a Google Presentation, renders every slide to PNG, names them
in1.png, in2.png, ... and converts them to .paa with the Arma 3 Tools.

Usage:
    python tlbintelmaker.py                       # open the GUI
    python tlbintelmaker.py <slides-url> <folder> # one-shot from the command line
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field, asdict
from pathlib import Path

__version__ = "1.0.0"

# Frozen by PyInstaller: read-only resources live in the temporary extraction
# directory, but settings must sit next to the .exe where they persist.
FROZEN = getattr(sys, "frozen", False)
APP_DIR = (Path(sys.executable).resolve().parent if FROZEN
           else Path(__file__).resolve().parent)
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))

SETTINGS_FILE = APP_DIR / "settings.json"
ASSET_DIR = RESOURCE_DIR / "assets"
ICON_FILE = ASSET_DIR / "icon.ico"
LOGO_FILE = ASSET_DIR / "logo_64.png"

# ImageToPAA refuses anything that is not a power of two, so resizing is not optional.
MIN_POT, MAX_POT = 4, 8192

CONVERTERS = {
    # label -> (subfolder, executable)
    "ImageToPAA": ("ImageToPAA", "ImageToPAA.exe"),
    "TexView2": ("TexView2", "Pal2PacE.exe"),
}

COMMON_TOOL_PATHS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Arma 3 Tools",
    r"C:\Program Files\Steam\steamapps\common\Arma 3 Tools",
    r"E:\SteamLibrary\steamapps\common\Arma 3 Tools",
    r"D:\SteamLibrary\steamapps\common\Arma 3 Tools",
    r"F:\SteamLibrary\steamapps\common\Arma 3 Tools",
]

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #

@dataclass
class Settings:
    arma_tools: str = ""
    converter: str = "ImageToPAA"
    last_output: str = ""
    prefix: str = "in"
    start_index: int = 1
    long_edge: int = 2048
    resize_mode: str = "stretch"      # stretch | pad | none
    pad_color: str = "#000000"
    keep_png: bool = False
    clean_target: bool = False
    recent_urls: list = field(default_factory=list)

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except Exception:
                pass
        if not s.arma_tools or not Path(s.arma_tools).is_dir():
            found = find_arma_tools()
            if found:
                s.arma_tools = found
        return s

    def save(self) -> None:
        try:
            SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except Exception:
            pass


def find_arma_tools() -> str:
    """Best-effort auto-detection of the Arma 3 Tools install."""
    for p in COMMON_TOOL_PATHS:
        if Path(p, "ImageToPAA", "ImageToPAA.exe").exists():
            return p
    # Walk every Steam library folder listed in libraryfolders.vdf.
    for steam in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        vdf = Path(steam, "steamapps", "libraryfolders.vdf")
        if not vdf.exists():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lib in re.findall(r'"path"\s*"([^"]+)"', text):
            cand = Path(lib.replace("\\\\", "\\"), "steamapps", "common", "Arma 3 Tools")
            if (cand / "ImageToPAA" / "ImageToPAA.exe").exists():
                return str(cand)
    return ""


def converter_exe(arma_tools: str, converter: str) -> Path:
    sub, exe = CONVERTERS.get(converter, CONVERTERS["ImageToPAA"])
    return Path(arma_tools) / sub / exe


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def extract_presentation_id(url: str) -> str:
    """Accepts a full Google Slides URL or a bare presentation ID."""
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        raise ValueError("No presentation link given.")
    m = re.search(r"/presentation/d/(?:e/)?([A-Za-z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", url):
        return url
    raise ValueError("Could not find a presentation ID in: " + url)


def normalize_folder(raw: str) -> Path:
    """Cleans up a pasted path.

    Arma's "Other Profiles" folders are literally named with percent escapes on
    disk (CPT%20W%2e%20Fosse), so the raw text always wins. Only when the literal
    path does not exist do we try the URL-decoded form, for paths copied out of a
    browser address bar.
    """
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("No output folder given.")
    if raw.lower().startswith("file:///"):
        raw = urllib.parse.unquote(raw[8:]).replace("/", os.sep)
    literal = Path(raw).expanduser()
    if literal.exists():
        return literal
    if re.search(r"%[0-9A-Fa-f]{2}", raw):
        decoded = Path(urllib.parse.unquote(raw)).expanduser()
        if decoded.exists():
            return decoded
    return literal


def nearest_pot(n: int) -> int:
    n = max(1, int(n))
    lo = 1 << (n.bit_length() - 1)
    hi = lo << 1
    best = lo if (n - lo) <= (hi - n) else hi
    return max(MIN_POT, min(MAX_POT, best))


def target_size(w: float, h: float, long_edge: int) -> tuple:
    """Power-of-two size that best matches the slide's aspect ratio."""
    long_edge = nearest_pot(long_edge)
    if w >= h:
        return long_edge, nearest_pot(round(long_edge * h / w))
    return nearest_pot(round(long_edge * w / h)), long_edge


def hex_to_rgb(value: str) -> tuple:
    v = (value or "#000000").lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (0, 0, 0)


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #

def require(module: str):
    """Imports a third-party module, or explains how to install it.

    Note for packaging: because this import is dynamic, PyInstaller cannot see
    it. build.bat passes the corresponding --hidden-import / --collect-all
    flags; keep them in step with requirements.txt.
    """
    try:
        return __import__(module)
    except ImportError:
        if FROZEN:
            raise RuntimeError(
                "This build is missing the '%s' component and is broken.\n"
                "Please download TLB Intel Maker again from the Releases page." % module)
        raise RuntimeError(
            "The Python package '%s' is missing.\n"
            "Run install-requirements.bat in the TLB Intel Maker folder." % module)


def download_pdf(pres_id: str, log=print) -> bytes:
    requests = require("requests")

    url = "https://docs.google.com/presentation/d/" + pres_id + "/export/pdf"
    log("Downloading " + url)
    r = requests.get(url, timeout=120, allow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0 TLB Intel Maker"})
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or "pdf" not in ctype.lower():
        if r.status_code in (401, 403) or "text/html" in ctype.lower():
            raise RuntimeError(
                "Google refused the download. Set the presentation's sharing to\n"
                '  "Anyone with the link" (Viewer is enough), then try again.\n'
                "(HTTP %s, content-type %s)" % (r.status_code, ctype or "unknown"))
        raise RuntimeError("Unexpected response: HTTP %s, %s" % (r.status_code, ctype))
    log("Got %.0f KB of PDF" % (len(r.content) / 1024))
    return r.content


def render_slides(pdf_bytes: bytes, out_dir: Path, prefix: str, start_index: int,
                  long_edge: int, resize_mode: str, pad_color: str, log=print) -> list:
    """Renders every page of the PDF straight to prefix<N>.png in out_dir."""
    pymupdf = require("pymupdf")
    require("PIL")
    from PIL import Image

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count == 0:
        raise RuntimeError("The presentation exported an empty PDF.")

    page = doc[0]
    pw, ph = page.rect.width, page.rect.height
    if resize_mode == "none":
        tw = th = None
        log("%d slides, rendering at %dpx long edge (no power-of-two resize - "
            "conversion fails unless the slide size already is a power of two)"
            % (doc.page_count, long_edge))
    else:
        tw, th = target_size(pw, ph, long_edge)
        log("%d slides, slide ratio %.0fx%.0f -> %dx%d px (%s)"
            % (doc.page_count, pw, ph, tw, th, resize_mode))

    written = []
    for i, pg in enumerate(doc):
        dst = out_dir / ("%s%d.png" % (prefix, start_index + i))
        if resize_mode == "stretch" and tw:
            mat = pymupdf.Matrix(tw / pg.rect.width, th / pg.rect.height)
            pg.get_pixmap(matrix=mat, alpha=False).save(dst)
        elif resize_mode == "pad" and tw:
            scale = min(tw / pg.rect.width, th / pg.rect.height)
            pix = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            src = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            canvas = Image.new("RGB", (tw, th), hex_to_rgb(pad_color))
            canvas.paste(src, ((tw - src.width) // 2, (th - src.height) // 2))
            canvas.save(dst)
        else:
            scale = long_edge / max(pg.rect.width, pg.rect.height)
            pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(dst)
        written.append(dst)
        log("  slide %d/%d -> %s" % (i + 1, doc.page_count, dst.name))
    doc.close()
    return written


def png_to_paa(png: Path, exe: Path) -> Path:
    paa = png.with_suffix(".paa")
    if paa.exists():
        try:
            paa.unlink()
        except OSError as e:
            raise RuntimeError("Cannot overwrite %s: %s" % (paa.name, e))
    res = subprocess.run([str(exe), str(png), str(paa)], capture_output=True,
                         text=True, creationflags=CREATE_NO_WINDOW)
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    if res.returncode != 0 or not paa.exists():
        detail = out.splitlines()[-1] if out else "exit code %s" % res.returncode
        raise RuntimeError("%s failed on %s: %s" % (exe.name, png.name, detail))
    return paa


def clean_existing(out_dir: Path, prefix: str, log=print) -> int:
    """Removes previously generated prefix<number>.png / .paa files."""
    pat = re.compile(r"^%s\d+\.(png|paa)$" % re.escape(prefix), re.IGNORECASE)
    removed = 0
    for f in out_dir.iterdir():
        if f.is_file() and pat.match(f.name):
            try:
                f.unlink()
                removed += 1
            except OSError as e:
                log("  could not delete %s: %s" % (f.name, e))
    if removed:
        log("Cleaned %d existing %s*.png/.paa file(s)" % (removed, prefix))
    return removed


def run_job(url: str, out_folder: str, s: Settings, log=print) -> list:
    pres_id = extract_presentation_id(url)
    out_dir = normalize_folder(out_folder)
    exe = converter_exe(s.arma_tools, s.converter)

    if not s.arma_tools:
        raise RuntimeError("Arma 3 Tools folder is not set.")
    if not exe.exists():
        raise RuntimeError("Converter not found:\n  %s\nCheck the Arma 3 Tools path." % exe)

    out_dir.mkdir(parents=True, exist_ok=True)
    log("Presentation ID : " + pres_id)
    log("Output folder   : %s" % out_dir)
    log("Converter       : %s" % exe)
    log("-" * 60)

    if s.clean_target:
        clean_existing(out_dir, s.prefix, log)

    pdf = download_pdf(pres_id, log)
    pngs = render_slides(pdf, out_dir, s.prefix, int(s.start_index), int(s.long_edge),
                         s.resize_mode, s.pad_color, log)

    log("-" * 60)
    log("Converting %d image(s) to .paa" % len(pngs))
    paas = []
    for p in pngs:
        paa = png_to_paa(p, exe)
        paas.append(paa)
        log("  %s -> %s" % (p.name, paa.name))

    if not s.keep_png:
        for p in pngs:
            try:
                p.unlink()
            except OSError:
                pass
        log("Removed %d intermediate .png file(s)" % len(pngs))

    log("-" * 60)
    log("Done. %d .paa file(s) in %s" % (len(paas), out_dir))
    if paas:
        log("First: %s   Last: %s" % (paas[0].name, paas[-1].name))
    return paas


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main_cli(argv: list) -> int:
    s = Settings.load()
    ap = argparse.ArgumentParser(
        prog="intel",
        description="Download a Google Presentation and convert every slide to Arma 3 .paa.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("examples:\n"
                "  intel --gui\n"
                '  intel "https://docs.google.com/presentation/d/ID/edit" '
                '"C:\\...\\images\\BR\\intel"\n'
                "  intel ID out\\folder --prefix in --start 1 --size 2048 --keep-png\n"))
    ap.add_argument("url", nargs="?", help="Google Slides link or presentation ID")
    ap.add_argument("output", nargs="?", help="folder to put the .paa files in")
    ap.add_argument("--gui", action="store_true", help="open the graphical interface")
    ap.add_argument("--prefix", default=s.prefix, help="file name prefix (default: %s)" % s.prefix)
    ap.add_argument("--start", type=int, default=s.start_index,
                    help="first number (default: %s)" % s.start_index)
    ap.add_argument("--size", type=int, default=s.long_edge,
                    help="power-of-two long edge in px (default: %s)" % s.long_edge)
    ap.add_argument("--mode", choices=["stretch", "pad", "none"], default=s.resize_mode,
                    help="how to reach power-of-two size (default: %s)" % s.resize_mode)
    ap.add_argument("--pad-color", default=s.pad_color, help="pad colour, e.g. #000000")
    ap.add_argument("--converter", choices=list(CONVERTERS), default=s.converter,
                    help="which Arma tool to use (default: %s)" % s.converter)
    ap.add_argument("--arma-tools", default=s.arma_tools, help="path to the Arma 3 Tools folder")
    ap.add_argument("--keep-png", action="store_true", default=s.keep_png,
                    help="keep the intermediate .png files")
    ap.add_argument("--clean", action="store_true", default=False,
                    help="delete existing <prefix><n>.png/.paa in the target first")
    ap.add_argument("--save-settings", action="store_true",
                    help="store these options as the new defaults")
    ap.add_argument("--version", action="version", version="TLB Intel Maker " + __version__)
    a = ap.parse_args(argv)

    if a.gui or not a.url:
        return main_gui()

    s.prefix, s.start_index, s.long_edge = a.prefix, a.start, a.size
    s.resize_mode, s.pad_color, s.converter = a.mode, a.pad_color, a.converter
    s.arma_tools, s.keep_png, s.clean_target = a.arma_tools, a.keep_png, a.clean
    if not a.output:
        a.output = s.last_output
    if not a.output:
        ap.error("no output folder given and no saved default")

    try:
        run_job(a.url, a.output, s)
    except Exception as e:
        sys.stderr.write("\nERROR: %s\n" % e)
        return 1

    s.last_output = str(normalize_folder(a.output))
    if a.save_settings:
        s.save()
        print("Settings saved to %s" % SETTINGS_FILE)
    return 0


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

def main_gui() -> int:
    import threading
    import queue
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    s = Settings.load()
    root = tk.Tk()
    root.title("TLB Intel Maker - Google Slides to Arma 3 .paa")
    root.geometry("860x700")
    root.minsize(760, 620)

    # Window and taskbar icon. Both are cosmetic, so never let them break startup.
    if ICON_FILE.exists():
        try:
            root.iconbitmap(default=str(ICON_FILE))
        except Exception:
            pass

    msgs = queue.Queue()
    running = tk.BooleanVar(value=False)

    pad = {"padx": 8, "pady": 4}
    main = ttk.Frame(root, padding=10)
    main.pack(fill="both", expand=True)
    main.columnconfigure(1, weight=1)
    row = 0

    # --- header -----------------------------------------------------------
    header = ttk.Frame(main)
    header.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
    row += 1

    if LOGO_FILE.exists():
        try:
            # Kept on root so Tk does not garbage collect the image.
            root.logo_img = tk.PhotoImage(file=str(LOGO_FILE))
            ttk.Label(header, image=root.logo_img).grid(row=0, column=0, rowspan=2,
                                                        padx=(0, 12))
        except Exception:
            pass

    ttk.Label(header, text="TLB Intel Maker", font=("Segoe UI", 16, "bold")).grid(
        row=0, column=1, sticky="sw")
    ttk.Label(header, text="Google Slides to Arma 3 .paa briefing images",
              foreground="#666").grid(row=1, column=1, sticky="nw")
    header.columnconfigure(2, weight=1)
    ttk.Label(header, text="v" + __version__, foreground="#999").grid(
        row=1, column=2, sticky="se")

    ttk.Separator(main, orient="horizontal").grid(row=row, column=0, columnspan=3,
                                                  sticky="ew", pady=(0, 10))
    row += 1

    # --- source -----------------------------------------------------------
    ttk.Label(main, text="Presentation link", font=("", 9, "bold")).grid(
        row=row, column=0, sticky="w", **pad)
    url_var = tk.StringVar(value=s.recent_urls[0] if s.recent_urls else "")
    url_box = ttk.Combobox(main, textvariable=url_var, values=s.recent_urls)
    url_box.grid(row=row, column=1, columnspan=2, sticky="ew", **pad)
    row += 1

    ttk.Label(main, text="Output folder", font=("", 9, "bold")).grid(
        row=row, column=0, sticky="w", **pad)
    out_var = tk.StringVar(value=s.last_output)
    ttk.Entry(main, textvariable=out_var).grid(row=row, column=1, sticky="ew", **pad)

    def browse_out():
        start = ""
        try:
            if out_var.get():
                start = str(normalize_folder(out_var.get()))
        except Exception:
            start = ""
        d = filedialog.askdirectory(title="Where do the .paa files go?",
                                    initialdir=start or os.path.expanduser("~"))
        if d:
            out_var.set(os.path.normpath(d))

    ttk.Button(main, text="Browse...", command=browse_out).grid(row=row, column=2, **pad)
    row += 1

    ttk.Label(main, text="(a %20-encoded path pasted from a browser is fine)",
              foreground="#666").grid(row=row, column=1, sticky="w", padx=8)
    row += 1

    # --- naming / image ---------------------------------------------------
    opts = ttk.LabelFrame(main, text="Naming and image size", padding=8)
    opts.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 4))
    row += 1

    prefix_var = tk.StringVar(value=s.prefix)
    start_var = tk.IntVar(value=s.start_index)
    size_var = tk.StringVar(value=str(s.long_edge))
    mode_var = tk.StringVar(value=s.resize_mode)

    ttk.Label(opts, text="Prefix").grid(row=0, column=0, sticky="w", padx=4)
    ttk.Entry(opts, textvariable=prefix_var, width=8).grid(row=0, column=1, padx=4)
    ttk.Label(opts, text="Start at").grid(row=0, column=2, sticky="w", padx=4)
    ttk.Spinbox(opts, from_=0, to=999, textvariable=start_var, width=6).grid(
        row=0, column=3, padx=4)
    ttk.Label(opts, text="Long edge").grid(row=0, column=4, sticky="w", padx=4)
    ttk.Combobox(opts, textvariable=size_var, width=7, state="readonly",
                 values=["512", "1024", "2048", "4096"]).grid(row=0, column=5, padx=4)
    ttk.Label(opts, text="Fit").grid(row=0, column=6, sticky="w", padx=4)
    ttk.Combobox(opts, textvariable=mode_var, width=9, state="readonly",
                 values=["stretch", "pad", "none"]).grid(row=0, column=7, padx=4)

    name_hint = ttk.Label(opts, text="", foreground="#666")
    name_hint.grid(row=1, column=0, columnspan=8, sticky="w", padx=4, pady=(6, 0))

    def refresh_hint(*_):
        p = prefix_var.get() or "in"
        try:
            n = int(start_var.get())
        except Exception:
            n = 1
        name_hint.config(text="Files will be %s%d.paa, %s%d.paa, %s%d.paa ...   "
                              "Arma needs power-of-two textures, so slides are "
                              "resized (%s)." % (p, n, p, n + 1, p, n + 2, mode_var.get()))

    for v in (prefix_var, start_var, mode_var):
        v.trace_add("write", refresh_hint)
    refresh_hint()

    keep_var = tk.BooleanVar(value=s.keep_png)
    clean_var = tk.BooleanVar(value=s.clean_target)
    ttk.Checkbutton(opts, text="Keep the .png files as well", variable=keep_var).grid(
        row=2, column=0, columnspan=4, sticky="w", padx=4, pady=(6, 0))
    ttk.Checkbutton(opts, text="Delete existing prefix+number files first",
                    variable=clean_var).grid(row=2, column=4, columnspan=4, sticky="w",
                                             padx=4, pady=(6, 0))

    # --- tools ------------------------------------------------------------
    tools = ttk.LabelFrame(main, text="Arma 3 Tools", padding=8)
    tools.grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
    tools.columnconfigure(1, weight=1)
    row += 1

    tools_var = tk.StringVar(value=s.arma_tools)
    conv_var = tk.StringVar(value=s.converter)
    ttk.Label(tools, text="Folder").grid(row=0, column=0, sticky="w", padx=4)
    ttk.Entry(tools, textvariable=tools_var).grid(row=0, column=1, sticky="ew", padx=4)

    def browse_tools():
        d = filedialog.askdirectory(title="Select the 'Arma 3 Tools' folder",
                                    initialdir=tools_var.get() or "C:\\")
        if d:
            tools_var.set(os.path.normpath(d))

    ttk.Button(tools, text="Browse...", command=browse_tools).grid(row=0, column=2, padx=4)
    ttk.Label(tools, text="Converter").grid(row=1, column=0, sticky="w", padx=4, pady=(6, 0))
    ttk.Combobox(tools, textvariable=conv_var, width=14, state="readonly",
                 values=list(CONVERTERS)).grid(row=1, column=1, sticky="w", padx=4, pady=(6, 0))
    tools_status = ttk.Label(tools, text="", foreground="#666")
    tools_status.grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 0))

    def refresh_tools(*_):
        if not tools_var.get():
            tools_status.config(text="Not set - click Browse and pick 'Arma 3 Tools'.",
                                foreground="#a00")
            return
        exe = converter_exe(tools_var.get(), conv_var.get())
        if exe.exists():
            tools_status.config(text="OK: %s" % exe, foreground="#070")
        else:
            tools_status.config(text="Missing: %s" % exe, foreground="#a00")

    tools_var.trace_add("write", refresh_tools)
    conv_var.trace_add("write", refresh_tools)
    refresh_tools()

    # --- log --------------------------------------------------------------
    logf = ttk.Frame(main)
    logf.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(8, 4))
    main.rowconfigure(row, weight=1)
    logf.columnconfigure(0, weight=1)
    logf.rowconfigure(0, weight=1)
    row += 1

    log_box = tk.Text(logf, height=14, wrap="none", state="disabled",
                      bg="#101418", fg="#d7dde3", insertbackground="#d7dde3",
                      font=("Consolas", 9))
    log_box.grid(row=0, column=0, sticky="nsew")
    sb = ttk.Scrollbar(logf, command=log_box.yview)
    sb.grid(row=0, column=1, sticky="ns")
    log_box.config(yscrollcommand=sb.set)
    log_box.tag_config("err", foreground="#ff8080")
    log_box.tag_config("ok", foreground="#8fe08f")

    def append(text, tag=""):
        log_box.config(state="normal")
        log_box.insert("end", text + "\n", tag)
        log_box.see("end")
        log_box.config(state="disabled")

    # --- actions ----------------------------------------------------------
    bar = ttk.Frame(main)
    bar.grid(row=row, column=0, columnspan=3, sticky="ew")
    bar.columnconfigure(0, weight=1)

    status = ttk.Label(bar, text="Ready")
    status.grid(row=0, column=0, sticky="w", padx=4)

    def collect():
        s.prefix = prefix_var.get().strip() or "in"
        s.start_index = int(start_var.get())
        s.long_edge = int(size_var.get())
        s.resize_mode = mode_var.get()
        s.converter = conv_var.get()
        s.arma_tools = tools_var.get().strip()
        s.keep_png = bool(keep_var.get())
        s.clean_target = bool(clean_var.get())
        return s

    def open_folder():
        try:
            d = normalize_folder(out_var.get())
        except Exception:
            return
        if d.is_dir():
            os.startfile(str(d))
        else:
            messagebox.showinfo("TLB Intel Maker", "That folder does not exist yet.")

    def worker(url, out, cfg):
        try:
            paas = run_job(url, out, cfg, log=lambda m: msgs.put(("log", m)))
            msgs.put(("done", "%d .paa file(s) written." % len(paas)))
        except Exception as e:
            msgs.put(("error", str(e)))

    def start():
        if running.get():
            return
        cfg = collect()
        url, out = url_var.get().strip(), out_var.get().strip()
        try:
            extract_presentation_id(url)
            normalize_folder(out)
        except Exception as e:
            messagebox.showerror("TLB Intel Maker", str(e))
            return
        if not converter_exe(cfg.arma_tools, cfg.converter).exists():
            messagebox.showerror("TLB Intel Maker",
                                 "The Arma 3 Tools converter was not found.\n"
                                 "Set the correct 'Arma 3 Tools' folder below.")
            return
        if cfg.clean_target:
            d = normalize_folder(out)
            if d.is_dir() and not messagebox.askyesno(
                    "TLB Intel Maker",
                    "Delete existing %s<number>.png / .paa files in\n%s\n\n"
                    "before writing the new ones?" % (cfg.prefix, d)):
                return

        cfg.last_output = str(normalize_folder(out))
        cfg.recent_urls = ([url] + [u for u in cfg.recent_urls if u != url])[:10]
        cfg.save()
        url_box.config(values=cfg.recent_urls)

        log_box.config(state="normal")
        log_box.delete("1.0", "end")
        log_box.config(state="disabled")
        running.set(True)
        go_btn.config(state="disabled")
        status.config(text="Working...")
        bar_prog.start(12)
        threading.Thread(target=worker, args=(url, out, cfg), daemon=True).start()

    bar_prog = ttk.Progressbar(bar, mode="indeterminate", length=140)
    bar_prog.grid(row=0, column=1, padx=6)
    ttk.Button(bar, text="Open folder", command=open_folder).grid(row=0, column=2, padx=4)
    go_btn = ttk.Button(bar, text="Download and convert", command=start)
    go_btn.grid(row=0, column=3, padx=4)

    def finish(text, tag, status_text):
        append(text, tag)
        status.config(text=status_text)
        running.set(False)
        go_btn.config(state="normal")
        bar_prog.stop()

    def pump():
        try:
            while True:
                kind, text = msgs.get_nowait()
                if kind == "log":
                    append(text)
                elif kind == "done":
                    finish(text, "ok", text)
                else:
                    finish("ERROR: " + text, "err", "Failed")
        except queue.Empty:
            pass
        root.after(80, pump)

    append("Paste the Google Slides share link, pick the mission's intel folder,")
    append("then press 'Download and convert'.")
    if not s.arma_tools:
        append("Arma 3 Tools was not auto-detected - set it below.", "err")
    pump()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main_cli(sys.argv[1:]))

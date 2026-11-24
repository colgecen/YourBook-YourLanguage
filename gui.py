#!/usr/bin/env python3
"""Kitap PDF Cevirmen - masaustu grafik arayuzu (Tkinter).

CLI'yi (main.py) arka planda calistirir; kaynak secimi, kayit klasoru,
cikti dosya adi, sayfa araligi, ilerleme cubugu ve canli gunluk sunar.
Ek pip bagimliligi gerektirmez.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "main.py"
ICON_DIR = ROOT / "assets" / "icons"
ICON_PNG = ICON_DIR / "book.png"
ICON_ICO = ICON_DIR / "book.ico"

COLORS = {
    "bg": "#f1f5f9",
    "card": "#ffffff",
    "border": "#e2e8f0",
    "text": "#0f172a",
    "muted": "#64748b",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "header": "#0f172a",
    "header_soft": "#cbd5e1",
    "log_bg": "#0f172a",
    "log_fg": "#e2e8f0",
    "ok": "#16a34a",
    "warn": "#d97706",
    "err": "#dc2626",
}

PROGRESS_RE = re.compile(r"Sayfalar:\s+(\d+)%\|[^|]*\|\s*(\d+)/(\d+)")
FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'


def human_size(num: int) -> str:
    """Bayt degerini okunakli hale getirir."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def pdf_page_count(path: Path) -> int | None:
    """PDF sayfa sayisini dondurur; okunamayan/parolali PDF'lerde None."""
    try:
        import pymupdf

        with pymupdf.open(str(path)) as doc:
            if doc.needs_pass or doc.page_count <= 0:
                return None
            return doc.page_count
    except Exception:
        return None


def valid_file_name(name: str) -> bool:
    """Cikti dosya adinin gecerli olup olmadigini kontrol eder."""
    if not name or name in {".", ".."}:
        return False
    if name != name.strip() or name.endswith("."):
        return False
    return not any(char in name for char in FORBIDDEN_NAME_CHARS)


def display_path(path: Path) -> str:
    """Proje klasoru altindaysa kisa yol gosterir."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _native_pick(kind: str, initial: Path) -> tuple[str | None, bool]:
    """KDE/zenity yerel secim penceresi.

    Returns:
        (secili yol veya None, islem ele alindi mi)
    """
    if shutil.which("kdialog"):
        if kind == "file":
            cmd = [
                "kdialog",
                "--title",
                "Kaynak PDF seç",
                "--getopenfilename",
                str(initial),
                "PDF dosyaları (*.pdf)",
            ]
        else:
            cmd = [
                "kdialog",
                "--title",
                "Kayıt klasörü seç",
                "--getexistingdirectory",
                str(initial),
            ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired):
            return None, False
        if result.returncode == 0:
            return result.stdout.strip() or None, True
        if result.returncode == 1:
            return None, True
        return None, False
    if shutil.which("zenity"):
        if kind == "file":
            cmd = [
                "zenity",
                "--file-selection",
                "--title=Kaynak PDF seç",
                "--file-filter=PDF dosyaları | *.pdf",
            ]
        else:
            cmd = ["zenity", "--file-selection", "--directory", "--title=Kayıt klasörü seç"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired):
            return None, False
        if result.returncode == 0:
            return result.stdout.strip() or None, True
        if result.returncode == 1:
            return None, True
        return None, False
    return None, False


def pick_pdf_file(initial: Path, parent: tk.Misc) -> str | None:
    """PDF secimi icin yerel (KDE) pencereyi, yoksa Tk penceresini acar."""
    path, handled = _native_pick("file", initial)
    if handled:
        return path
    selected = filedialog.askopenfilename(
        parent=parent,
        title="Kaynak PDF seç",
        initialdir=str(initial),
        filetypes=[("PDF dosyaları", "*.pdf")],
    )
    return selected or None


def pick_directory(initial: Path, parent: tk.Misc) -> str | None:
    """Klasor secimi icin yerel pencereyi, yoksa Tk penceresini acar."""
    path, handled = _native_pick("folder", initial)
    if handled:
        return path
    selected = filedialog.askdirectory(
        parent=parent,
        title="Kayıt klasörü seç",
        initialdir=str(initial),
    )
    return selected or None


def subprocess_env() -> dict[str, str]:
    """Yerel tesseract varsa PATH/TESSDATA_PREFIX'i ayarlar."""
    env = os.environ.copy()
    local_tess = ROOT / ".tools" / "tesseract"
    if (local_tess / "tesseract").exists():
        env["PATH"] = f"{local_tess}{os.pathsep}{env.get('PATH', '')}"
        env["TESSDATA_PREFIX"] = str(local_tess / "tessdata")
    env["PYTHONUNBUFFERED"] = "1"
    return env


class App:
    """Ana pencere ve is akisi."""

    def __init__(
        self,
        root: tk.Tk,
        input_path: str | None = None,
        output_path: str | None = None,
        print_window_id: bool = False,
    ) -> None:
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.events: queue.Queue = queue.Queue()
        self.last_output: Path | None = None
        self._name_custom = False
        self._lock_widgets: list[tk.Widget] = []
        self._browse_buttons: list[ttk.Button] = []
        self._stopping = False
        self._info_job: str | None = None
        self._clear_job: str | None = None
        self._icon_img: tk.PhotoImage | None = None
        self._logo_img: object | None = None

        self.input_var = tk.StringVar()
        self.folder_var = tk.StringVar(value=str(ROOT / "output"))
        self.name_var = tk.StringVar()
        self.start_var = tk.StringVar(value="1")
        self.end_var = tk.StringVar()
        self.dpi_var = tk.StringVar(value="200")
        self.status_var = tk.StringVar(value="Hazır")
        self.percent_var = tk.StringVar(value="%0")

        self._setup_window()
        self._setup_styles()
        self._build_ui()
        self._bind_events()

        if input_path:
            self._set_input(input_path)
        if output_path:
            output = self._abs_path(output_path)
            self._name_custom = True
            self.folder_var.set(str(output.parent))
            self.name_var.set(output.stem)
        self._update_input_info()
        self._update_output_preview()

        if print_window_id:
            self.root.after(600, self._print_window_id)
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _setup_window(self) -> None:
        self.root.title("Kitap PDF Çevirmen")
        self.root.iconname("Kitap PDF Çevirmen")
        self.root.geometry("940x830")
        self.root.minsize(860, 740)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="DejaVu Sans", size=10)
        self._load_app_icon()

    def _load_app_icon(self) -> None:
        if ICON_PNG.exists():
            try:
                self._icon_img = tk.PhotoImage(file=str(ICON_PNG))
                self.root.iconphoto(True, self._icon_img)
            except tk.TclError:
                self._icon_img = None
        if sys.platform.startswith("win") and ICON_ICO.exists():
            try:
                self.root.iconbitmap(default=str(ICON_ICO))
            except tk.TclError:
                pass
        if ICON_PNG.exists():
            try:
                from PIL import Image, ImageTk

                logo = Image.open(ICON_PNG).convert("RGBA")
                logo = logo.resize((50, 50), Image.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(logo)
            except Exception:  # noqa: BLE001 - logo opsiyonel
                self._logo_img = None

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="white",
            borderwidth=0,
            focusthickness=0,
            padding=(16, 9),
            font=("DejaVu Sans", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[
                ("active", COLORS["accent_hover"]),
                ("disabled", "#93c5fd"),
            ],
            foreground=[("disabled", "#f8fafc")],
        )
        style.configure(
            "Secondary.TButton",
            background="#e2e8f0",
            foreground=COLORS["text"],
            borderwidth=0,
            focusthickness=0,
            padding=(13, 9),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#cbd5e1"), ("disabled", "#f1f5f9")],
            foreground=[("disabled", "#94a3b8")],
        )
        style.configure(
            "Field.TEntry",
            fieldbackground="white",
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            padding=7,
        )
        style.configure(
            "TCombobox",
            fieldbackground="white",
            background="white",
            bordercolor=COLORS["border"],
            padding=5,
        )
        style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor="#e2e8f0",
            background=COLORS["accent"],
            bordercolor=COLORS["bg"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
        )

    def _card_label(self, parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9, "bold"),
        )

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["header"], height=100)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_left = tk.Frame(header, bg=COLORS["header"])
        header_left.pack(side="left", padx=30, pady=16)
        if self._logo_img is not None:
            tk.Label(header_left, image=self._logo_img, bg=COLORS["header"]).pack(
                side="left", padx=(0, 14)
            )
        header_text = tk.Frame(header_left, bg=COLORS["header"])
        header_text.pack(side="left")
        tk.Label(
            header_text,
            text="Kitap PDF Çevirmen",
            bg=COLORS["header"],
            fg="white",
            font=("DejaVu Sans", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header_text,
            text="Taranmış İngilizce PDF → Türkçe  ·  Garamond dizgi  ·  Yerel OCR",
            bg=COLORS["header"],
            fg=COLORS["header_soft"],
            font=("DejaVu Sans", 10),
        ).pack(anchor="w", pady=(2, 0))
        self.badge = tk.Label(
            header,
            text="●  Hazır",
            bg="#1e293b",
            fg="#93c5fd",
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=5,
        )
        self.badge.place(relx=1.0, x=-30, y=30, anchor="ne")

        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=26, pady=(16, 4))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        # --- Dosya karti -------------------------------------------------
        card = tk.Frame(
            body,
            bg=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        card.grid(row=0, column=0, sticky="ew")
        inner = tk.Frame(card, bg=COLORS["card"])
        inner.pack(fill="x", padx=18, pady=14)
        inner.columnconfigure(1, weight=1)

        self._card_label(inner, "1 · Kaynak PDF").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        self.input_entry = ttk.Entry(
            inner, textvariable=self.input_var, style="Field.TEntry"
        )
        self.input_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.input_browse = ttk.Button(
            inner,
            text="Dosya Seç…",
            style="Secondary.TButton",
            command=self._browse_input,
        )
        self.input_browse.grid(row=1, column=2, padx=(8, 0), pady=(4, 0))
        self.input_info = tk.Label(
            inner,
            text="Çevrilecek PDF dosyasını seçin.",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 9),
        )
        self.input_info.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 12))
        self._browse_buttons.append(self.input_browse)

        self._card_label(inner, "2 · Nereye kaydedilsin?").grid(
            row=3, column=0, columnspan=3, sticky="w"
        )
        self.folder_entry = ttk.Entry(
            inner, textvariable=self.folder_var, style="Field.TEntry"
        )
        self.folder_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.folder_browse = ttk.Button(
            inner,
            text="Klasör Seç…",
            style="Secondary.TButton",
            command=self._browse_folder,
        )
        self.folder_browse.grid(row=4, column=2, padx=(8, 0), pady=(4, 0))
        self._browse_buttons.append(self.folder_browse)

        self._card_label(inner, "3 · Çıktı dosya adı").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )
        name_row = tk.Frame(inner, bg=COLORS["card"])
        name_row.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        name_row.columnconfigure(0, weight=1)
        self.name_entry = ttk.Entry(
            name_row, textvariable=self.name_var, style="Field.TEntry"
        )
        self.name_entry.grid(row=0, column=0, sticky="ew")
        tk.Label(
            name_row,
            text=".pdf",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 10, "bold"),
        ).grid(row=0, column=1, padx=(8, 0))
        self.output_preview = tk.Label(
            inner,
            text="",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 8),
            anchor="w",
            justify="left",
        )
        self.output_preview.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(6, 12))

        options = tk.Frame(inner, bg=COLORS["card"])
        options.grid(row=8, column=0, columnspan=3, sticky="w")
        tk.Label(
            options,
            text="Başlangıç sayfası",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            options,
            text="Bitiş sayfası",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9),
        ).grid(row=0, column=1, padx=(18, 0), sticky="w")
        tk.Label(
            options,
            text="DPI",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9),
        ).grid(row=0, column=2, padx=(18, 0), sticky="w")

        self.start_entry = ttk.Entry(
            options, textvariable=self.start_var, width=9, style="Field.TEntry"
        )
        self.start_entry.grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.end_entry = ttk.Entry(
            options, textvariable=self.end_var, width=9, style="Field.TEntry"
        )
        self.end_entry.grid(row=1, column=1, padx=(18, 0), sticky="w", pady=(3, 0))
        self.dpi_box = ttk.Combobox(
            options,
            textvariable=self.dpi_var,
            values=("150", "200", "300"),
            width=7,
            state="readonly",
        )
        self.dpi_box.grid(row=1, column=2, padx=(18, 0), sticky="w", pady=(3, 0))
        tk.Label(
            options,
            text="(boş = sonuna kadar)",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 8),
        ).grid(row=1, column=3, padx=(8, 0), sticky="w", pady=(5, 0))
        tk.Label(
            options,
            text="200 önerilir",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 8),
        ).grid(row=1, column=4, padx=(8, 0), sticky="w", pady=(5, 0))

        self._lock_widgets.extend(
            [
                self.input_entry,
                self.folder_entry,
                self.name_entry,
                self.start_entry,
                self.end_entry,
                self.dpi_box,
            ]
        )

        # --- Butonlar ----------------------------------------------------
        buttons = tk.Frame(body, bg=COLORS["bg"])
        buttons.grid(row=1, column=0, sticky="ew", pady=(12, 8))
        self.start_btn = ttk.Button(
            buttons,
            text="▶  Çeviriyi Başlat",
            style="Accent.TButton",
            command=self._start,
        )
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            buttons,
            text="■  Durdur",
            style="Secondary.TButton",
            command=self._stop,
        )
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.stop_btn.state(["disabled"])
        self.open_btn = ttk.Button(
            buttons,
            text="Çıktıyı Aç",
            style="Secondary.TButton",
            command=self._open_output,
        )
        self.open_btn.pack(side="left", padx=(8, 0))
        self.open_btn.state(["disabled"])

        # --- Durum / ilerleme -------------------------------------------
        progress_card = tk.Frame(
            body,
            bg=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        progress_card.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        pinner = tk.Frame(progress_card, bg=COLORS["card"])
        pinner.pack(fill="x", padx=18, pady=9)
        pinner.columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            pinner,
            textvariable=self.status_var,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 10, "bold"),
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        tk.Label(
            pinner,
            textvariable=self.percent_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 9),
        ).grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(
            pinner,
            style="Blue.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))

        # --- Gunluk ------------------------------------------------------
        log_header = tk.Frame(body, bg=COLORS["bg"])
        log_header.grid(row=3, column=0, sticky="nsew")
        log_header.columnconfigure(0, weight=1)
        log_header.rowconfigure(1, weight=1)
        tk.Label(
            log_header,
            text="Günlük",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        clear_btn = tk.Button(
            log_header,
            text="Temizle",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            activebackground=COLORS["bg"],
            activeforeground=COLORS["text"],
            bd=0,
            cursor="hand2",
            font=("DejaVu Sans", 8),
            command=self._clear_log,
        )
        clear_btn.grid(row=0, column=1, sticky="e", pady=(0, 4))
        log_wrap = tk.Frame(log_header, bg=COLORS["border"], padx=1, pady=1)
        log_wrap.grid(row=1, column=0, columnspan=2, sticky="nsew")
        log_wrap.columnconfigure(0, weight=1)
        log_wrap.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_wrap,
            bg=COLORS["log_bg"],
            fg=COLORS["log_fg"],
            insertbackground="white",
            relief="flat",
            bd=0,
            wrap="word",
            height=7,
            padx=12,
            pady=9,
            font=("DejaVu Sans Mono", 9),
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        footer = tk.Label(
            self.root,
            text="Tesseract OCR  ·  Google Translate  ·  Garamond Auto-Fit  ·  %100 ücretsiz",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 8),
        )
        footer.pack(side="bottom", pady=(0, 7))
        self.root.update_idletasks()

    def _bind_events(self) -> None:
        self.input_var.trace_add("write", lambda *_: self._schedule_input_info())
        self.folder_var.trace_add("write", lambda *_: self._on_destination_changed())
        self.name_var.trace_add("write", lambda *_: self._on_destination_changed())
        self.name_entry.bind("<KeyRelease>", self._on_name_typed)

    # -------------------------------------------------------------- helpers
    def _print_window_id(self) -> None:
        print("WINDOW_ID", self.root.winfo_id(), flush=True)

    @staticmethod
    def _abs_path(value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (ROOT / path).resolve()

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp}  {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self._cancel_clear_timer()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _clear_log_after_done(self) -> None:
        self._clear_job = None
        self._clear_log()
        self.status_var.set("Tamamlandı")

    def _cancel_clear_timer(self) -> None:
        if self._clear_job is not None:
            try:
                self.root.after_cancel(self._clear_job)
            except tk.TclError:
                pass
            self._clear_job = None

    def _badge(self, text: str, color: str) -> None:
        self.badge.configure(text=text, fg=color)

    def _schedule_input_info(self) -> None:
        if self._info_job is not None:
            self.root.after_cancel(self._info_job)
        self._info_job = self.root.after(300, self._update_input_info)

    def _set_input_info(self, text: str, color: str) -> None:
        self.input_info.configure(text=text, fg=color)

    def _update_input_info(self) -> None:
        self._info_job = None
        raw = self.input_var.get().strip()
        if not raw:
            self._set_input_info("Çevrilecek PDF dosyasını seçin.", COLORS["muted"])
            return
        path = self._abs_path(raw)
        if not path.exists():
            self._set_input_info("Dosya bulunamadı. Yazı okunamadı.", COLORS["err"])
            return
        if path.suffix.lower() != ".pdf":
            self._set_input_info(
                "Desteklenmeyen dosya. Yalnızca PDF destekleniyor.", COLORS["err"]
            )
            return
        pages = pdf_page_count(path)
        if not pages:
            self._set_input_info(
                "Yazı okunamadı. PDF bozuk veya parola korumalı.", COLORS["err"]
            )
            return
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = "?"
        self._set_input_info(
            f"{pages} sayfa  ·  {size}  ·  yazı okunabilir", COLORS["muted"]
        )

    def _on_name_typed(self, _event: tk.Event) -> None:
        self._name_custom = True

    def _on_destination_changed(self) -> None:
        self._update_output_preview()
        self._sync_open_button()

    @staticmethod
    def _clean_name(raw: str) -> str:
        name = raw.strip()
        if name.lower().endswith(".pdf"):
            name = name[:-4].rstrip()
        return name

    def _output_path(self) -> Path | None:
        folder = self.folder_var.get().strip()
        name = self._clean_name(self.name_var.get())
        if not folder or not valid_file_name(name):
            return None
        return self._abs_path(folder) / f"{name}.pdf"

    def _update_output_preview(self) -> None:
        folder_raw = self.folder_var.get().strip()
        name = self._clean_name(self.name_var.get())
        if not folder_raw:
            self.output_preview.configure(
                text="Kayıt klasörü seçin.", fg=COLORS["err"]
            )
            return
        if not name:
            self.output_preview.configure(text="Dosya adı girin.", fg=COLORS["err"])
            return
        if not valid_file_name(name):
            self.output_preview.configure(
                text='Geçersiz dosya adı. \\ / : * ? " < > | kullanılamaz.',
                fg=COLORS["err"],
            )
            return
        folder = self._abs_path(folder_raw)
        path = folder / f"{name}.pdf"
        text = f"Çıktı: {display_path(path)}"
        color = COLORS["muted"]
        if not folder.exists():
            text += "   (klasör oluşturulacak)"
            color = COLORS["warn"]
        elif path.exists():
            text += "   (mevcut dosyanın üzerine yazılacak)"
            color = COLORS["warn"]
        self.output_preview.configure(text=text, fg=color)

    def _sync_open_button(self) -> None:
        out = self._output_path()
        if out is not None and out.is_file():
            self.open_btn.state(["!disabled"])
        else:
            self.open_btn.state(["disabled"])

    def _set_input(self, value: str) -> None:
        path = self._abs_path(value)
        self.input_var.set(str(path))
        if not self._name_custom or not self.name_var.get().strip():
            stem = path.stem or "kitap"
            self.name_var.set(f"{stem}_tr")
        if not self.folder_var.get().strip():
            self.folder_var.set(str(ROOT / "output"))
        self._update_input_info()
        self._update_output_preview()

    def _browse_input(self) -> None:
        current = self.input_var.get().strip()
        if current:
            candidate = self._abs_path(current).parent
        else:
            candidate = ROOT / "input"
        if not candidate.is_dir():
            candidate = Path.home()
        path = pick_pdf_file(candidate, self.root)
        if path:
            self._set_input(path)

    def _browse_folder(self) -> None:
        current = self.folder_var.get().strip()
        candidate = self._abs_path(current) if current else ROOT / "output"
        if not candidate.is_dir():
            candidate = ROOT
        path = pick_directory(candidate, self.root)
        if path:
            self.folder_var.set(str(Path(path).resolve()))

    # ---------------------------------------------------------------- start
    def _show_input_error(self, message: str) -> None:
        self._set_input_info(message, COLORS["err"])
        messagebox.showerror("Geçersiz dosya", message)

    def _validate(self) -> tuple[Path, Path, int, int | None, int] | None:
        raw_in = self.input_var.get().strip()
        if not raw_in:
            messagebox.showwarning("Eksik bilgi", "Önce bir kaynak PDF seçin.")
            return None
        inp = self._abs_path(raw_in)
        if not inp.exists():
            self._show_input_error("Dosya bulunamadı. Yazı okunamadı.")
            return None
        if inp.suffix.lower() != ".pdf":
            self._show_input_error(
                "Desteklenmeyen dosya. Yalnızca PDF destekleniyor."
            )
            return None
        pages = pdf_page_count(inp)
        if not pages:
            self._show_input_error(
                "Yazı okunamadı. PDF bozuk veya parola korumalı."
            )
            return None

        folder_raw = self.folder_var.get().strip()
        if not folder_raw:
            messagebox.showwarning("Eksik bilgi", "Kayıt klasörünü seçin.")
            return None
        name = self._clean_name(self.name_var.get())
        if not valid_file_name(name):
            messagebox.showerror(
                "Geçersiz dosya adı",
                'Dosya adı boş olamaz ve \\ / : * ? " < > | karakterlerini içeremez.',
            )
            return None
        folder = self._abs_path(folder_raw)
        out = folder / f"{name}.pdf"
        if out.resolve() == inp.resolve():
            messagebox.showerror(
                "Geçersiz konum", "Çıktı, kaynak PDF ile aynı dosya olamaz."
            )
            return None
        if not folder.exists():
            if not messagebox.askyesno(
                "Klasör yok",
                f"Bu klasör henüz yok:\n{folder}\n\nOluşturulsun mu?",
            ):
                return None
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("Klasör oluşturulamadı", str(exc))
                return None

        try:
            start = int(self.start_var.get().strip())
            if start < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Geçersiz aralık", "Başlangıç sayfası 1 veya daha büyük olmalı."
            )
            return None
        end_raw = self.end_var.get().strip()
        if end_raw:
            try:
                end = int(end_raw)
                if end < start:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Geçersiz aralık",
                    "Bitiş sayfası sayı olmalı ve başlangıçtan küçük olamaz.",
                )
                return None
        else:
            end = None
        try:
            dpi = int(self.dpi_var.get())
        except ValueError:
            dpi = 200
        if end is not None and end > pages:
            if not messagebox.askyesno(
                "Aralık düzeltilsin mi?",
                f"PDF {pages} sayfa. Bitiş {end} yerine {pages} kullanılsın mı?",
            ):
                return None
            end = pages
            self.end_var.set(str(pages))
        if out.exists():
            if not messagebox.askyesno(
                "Üzerine yazılsın mı?",
                f"Bu dosya zaten var:\n{out}\n\nÜzerine yazılsın mı?",
            ):
                return None
        return inp, out, start, end, dpi

    def _start(self) -> None:
        if self.proc is not None:
            return
        validated = self._validate()
        if not validated:
            return
        inp, out, start, end, dpi = validated
        cmd = [
            sys.executable,
            str(MAIN),
            "--input",
            str(inp),
            "--output",
            str(out),
            "--start-page",
            str(start),
            "--dpi",
            str(dpi),
            "--no-deps",
        ]
        if end is not None:
            cmd.extend(["--end-page", str(end)])

        self._cancel_clear_timer()
        self.last_output = out
        self.progress.configure(value=0)
        self.percent_var.set("%0")
        self.status_var.set("Başlatılıyor…")
        self._badge("●  Çalışıyor", "#93c5fd")
        self._log(f"Kaynak: {inp}")
        self._log(f"Çıktı:  {out}")
        self._log(f"Aralık: {start}–{end or 'son'}  ·  DPI: {dpi}")
        self._set_running(True)
        self.events = queue.Queue()
        threading.Thread(
            target=self._worker,
            args=(cmd, subprocess_env(), out),
            daemon=True,
        ).start()

    def _set_running(self, running: bool) -> None:
        if running:
            self.start_btn.state(["disabled"])
            self.stop_btn.state(["!disabled"])
            for widget in self._lock_widgets:
                widget.state(["disabled"])
            for button in self._browse_buttons:
                button.state(["disabled"])
        else:
            self.start_btn.state(["!disabled"])
            self.stop_btn.state(["disabled"])
            for widget in self._lock_widgets:
                widget.state(["!disabled"])
            for button in self._browse_buttons:
                button.state(["!disabled"])

    def _stop(self) -> None:
        if self.proc is None:
            return
        self._stopping = True
        self.status_var.set("Durduruluyor…")
        self._badge("●  Durduruluyor", "#fcd34d")
        self._log("Kullanıcı işlemi durdurdu; checkpoint korunuyor.")
        try:
            self.proc.terminate()
        except OSError as exc:
            self._log(f"Durdurma hatası: {exc}")

    # --------------------------------------------------------------- worker
    def _worker(self, cmd: list[str], env: dict[str, str], out: Path) -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
            self.proc = proc
            assert proc.stdout is not None
            buffer = ""
            fd = proc.stdout.fileno()
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", "replace")
                while "\n" in buffer or "\r" in buffer:
                    indexes = [i for i in (buffer.find("\n"), buffer.find("\r")) if i >= 0]
                    cut = min(indexes)
                    line, buffer = buffer[:cut], buffer[cut + 1 :]
                    if line.strip():
                        self.events.put(("line", line))
            if buffer.strip():
                self.events.put(("line", buffer))
            code = proc.wait()
            self.events.put(("done", (code, out)))
        except Exception as exc:  # noqa: BLE001 - arayuzu ayakta tut
            self.events.put(("error", str(exc)))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "line":
                    self._handle_line(payload)
                elif kind == "done":
                    self._finish(*payload)
                elif kind == "error":
                    self._fail(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        match = PROGRESS_RE.search(line)
        if match:
            percent, current, total = (int(value) for value in match.groups())
            self.progress.configure(value=percent)
            self.percent_var.set(f"%{percent}")
            self.status_var.set(f"{current} / {total} sayfa işlendi")
            return
        if PROGRESS_RE.search(line) or line.startswith("Sayfalar:"):
            return
        if any(
            token in line
            for token in (
                "UYARI",
                "atlandı",
                "atlandi",
                "Traceback",
                "Error",
                "HATA",
                "basarisiz",
                "başarısız",
            )
        ):
            self._log(line)
        elif line.startswith("Cikti olusturuldu") or line.startswith("Çıktı"):
            self._log(line)

    def _finish(self, code: int, out: Path) -> None:
        self.proc = None
        self._set_running(False)
        self._sync_open_button()
        if self._stopping:
            self._stopping = False
            self.status_var.set("Durduruldu")
            self._badge("●  Durduruldu", "#fcd34d")
            self._log("İşlem durduruldu. Aynı ayarlarla kaldığı yerden devam edebilirsiniz.")
            return
        if code == 0:
            self.progress.configure(value=100)
            self.percent_var.set("%100")
            self.status_var.set("Tamamlandı · günlük 10 sn sonra temizlenecek")
            self._badge("●  Tamamlandı", "#86efac")
            self._log(f"Bitti: {out}")
            self.root.bell()
            self._clear_job = self.root.after(10000, self._clear_log_after_done)
        else:
            self.status_var.set("Hata ile durdu")
            self._badge("●  Hata", "#fca5a5")
            self._log(f"İşlem {code} koduyla sonlandı. Ayrıntı için yukarıdaki günlüğe bakın.")
            messagebox.showerror(
                "Çeviri tamamlanamadı",
                "İşlem hata ile durdu. Ayrıntılar günlük panelinde.",
            )

    def _fail(self, message: str) -> None:
        self.proc = None
        self._stopping = False
        self._set_running(False)
        self.status_var.set("Başlatılamadı")
        self._badge("●  Hata", "#fca5a5")
        self._log(f"Hata: {message}")
        messagebox.showerror("Başlatılamadı", message)

    # ---------------------------------------------------------------- misc
    def _open_output(self) -> None:
        out = self.last_output
        if out is None:
            out = self._output_path()
        if out is None or not out.is_file():
            messagebox.showinfo("Çıktı yok", "Henüz oluşturulmuş bir çıktı PDF yok.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(out))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(out)])
            else:
                subprocess.Popen(["xdg-open", str(out)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Açılamadı", str(exc))

    def _on_close(self) -> None:
        if self.proc is not None:
            if not messagebox.askyesno(
                "İşlem sürüyor",
                "Çeviri hâlâ devam ediyor. Durdurup çıkmak istiyor musunuz?\n"
                "Checkpoint sayesinde daha sonra kaldığı yerden devam edebilirsiniz.",
            ):
                return
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Kitap PDF Çevirmen arayüzü")
    parser.add_argument("--input", help="Önceden doldurulacak kaynak PDF")
    parser.add_argument("--output", help="Önceden doldurulacak çıktı PDF")
    parser.add_argument(
        "--print-window-id",
        action="store_true",
        help="Pencere kimliğini yazdır (otomasyon/test için)",
    )
    args = parser.parse_args()

    root = tk.Tk(className="KitapPdfCevirmen")
    App(root, args.input, args.output, args.print_window_id)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

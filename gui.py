#!/usr/bin/env python3
"""Kitap PDF Cevirmen - masaustu grafik arayuzu (Tkinter).

CLI'yi (main.py) arka planda calistirir; kaynak secimi, kayit klasoru,
cikti dosya adi, sayfa araligi, ilerleme cubugu ve canli gunluk sunar.
Ek pip bagimliligi gerektirmez.
"""

from __future__ import annotations

import argparse
import json
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
ICON_PNG = ROOT / "assets" / "icon.png"
LAST_OUTPUT_FILE = ROOT / ".cache" / "last_output.json"

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

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
CONFIG_FILE = XDG_CONFIG / "yourbook-yourlanguage" / "config.json"

TEXTS: dict[str, dict[str, str]] = {
    "tr": {
        "app_title": "YourBook YourLanguage",
        "subtitle": "Taranmış İngilizce PDF → Türkçe  ·  Garamond dizgi  ·  Yerel OCR",
        "badge_ready": "●  Hazır",
        "badge_working": "●  Çalışıyor",
        "badge_stopping": "●  Durduruluyor",
        "badge_stopped": "●  Durduruldu",
        "badge_completed": "●  Tamamlandı",
        "badge_error": "●  Hata",
        "section_source": "1 · Kaynak PDF",
        "section_folder": "2 · Nereye kaydedilsin?",
        "section_name": "3 · Çıktı dosya adı",
        "browse_file": "Dosya Seç…",
        "browse_folder": "Klasör Seç…",
        "source_hint": "Çevrilecek PDF dosyasını seçin.",
        "source_missing": "Dosya bulunamadı. Yazı okunamadı.",
        "unsupported": "Desteklenmeyen dosya. Yalnızca PDF destekleniyor.",
        "unreadable": "Yazı okunamadı. PDF bozuk veya parola korumalı.",
        "pages_info": "{pages} sayfa  ·  {size}  ·  yazı okunabilir",
        "start_page": "Başlangıç sayfası",
        "end_page": "Bitiş sayfası",
        "dpi": "DPI",
        "end_hint": "(boş = sonuna kadar)",
        "dpi_hint": "200 önerilir",
        "start_button": "▶  Çeviriyi Başlat",
        "stop_button": "■  Durdur",
        "open_last": "Son Çıktıyı Aç",
        "log_title": "Günlük",
        "clear": "Temizle",
        "footer": "Tesseract OCR  ·  Google Translate  ·  Garamond Auto-Fit  ·  %100 ücretsiz",
        "output_preview": "Çıktı: {path}",
        "folder_will_create": "(klasör oluşturulacak)",
        "overwrite_note": "(mevcut dosyanın üzerine yazılacak)",
        "choose_folder": "Kayıt klasörü seçin.",
        "name_required": "Dosya adı girin.",
        "invalid_name_hint": 'Geçersiz dosya adı. \\ / : * ? " < > | kullanılamaz.',
        "invalid_file_title": "Geçersiz dosya",
        "missing_info": "Eksik bilgi",
        "select_source_first": "Önce bir kaynak PDF seçin.",
        "select_folder_first": "Kayıt klasörünü seçin.",
        "invalid_name_title": "Geçersiz dosya adı",
        "invalid_name_msg": 'Dosya adı boş olamaz ve \\ / : * ? " < > | karakterlerini içeremez.',
        "invalid_location_title": "Geçersiz konum",
        "same_file": "Çıktı, kaynak PDF ile aynı dosya olamaz.",
        "folder_missing_title": "Klasör yok",
        "folder_missing_msg": "Bu klasör henüz yok:\n{folder}\n\nOluşturulsun mu?",
        "folder_create_error": "Klasör oluşturulamadı",
        "invalid_range_title": "Geçersiz aralık",
        "start_invalid": "Başlangıç sayfası 1 veya daha büyük olmalı.",
        "end_invalid": "Bitiş sayfası sayı olmalı ve başlangıçtan küçük olamaz.",
        "fix_range_title": "Aralık düzeltilsin mi?",
        "fix_range_msg": "PDF {pages} sayfa. Bitiş {end} yerine {pages} kullanılsın mı?",
        "overwrite_title": "Üzerine yazılsın mı?",
        "overwrite_msg": "Bu dosya zaten var:\n{out}\n\nÜzerine yazılsın mı?",
        "status_ready": "Hazır",
        "status_starting": "Başlatılıyor…",
        "status_stopping": "Durduruluyor…",
        "status_stopped": "Durduruldu",
        "status_completed": "Tamamlandı",
        "status_completed_clearing": "Tamamlandı · günlük 10 sn sonra temizlenecek",
        "status_error": "Hata ile durdu",
        "status_failed": "Başlatılamadı",
        "status_page_progress": "{current} / {total} sayfa işlendi",
        "log_source": "Kaynak: {path}",
        "log_output": "Çıktı:  {path}",
        "log_range": "Aralık: {start}–{end}  ·  DPI: {dpi}",
        "log_range_end": "son",
        "log_user_stopped": "Kullanıcı işlemi durdurdu; checkpoint korunuyor.",
        "log_stop_error": "Durdurma hatası: {error}",
        "log_stopped": "İşlem durduruldu. Aynı ayarlarla kaldığı yerden devam edebilirsiniz.",
        "log_finished": "Bitti: {path}",
        "log_output_created": "Çıktı oluşturuldu: {path}",
        "log_error_code": "İşlem {code} koduyla sonlandı. Ayrıntı için yukarıdaki günlüğe bakın.",
        "log_failed": "Hata: {message}",
        "error_title": "Çeviri tamamlanamadı",
        "error_msg": "İşlem hata ile durdu. Ayrıntılar günlük panelinde.",
        "no_output_title": "Çıktı yok",
        "no_output_msg": "Henüz oluşturulmuş bir çıktı PDF yok.",
        "open_error_title": "Açılamadı",
        "close_running_title": "İşlem sürüyor",
        "close_running_msg": "Çeviri hâlâ devam ediyor. Durdurup çıkmak istiyor musunuz?\nCheckpoint sayesinde daha sonra kaldığı yerden devam edebilirsiniz.",
        "picker_source_title": "Kaynak PDF seç",
        "picker_folder_title": "Kayıt klasörü seç",
        "picker_pdf_filter": "PDF dosyaları",
        "language_tr": "Türkçe",
        "language_en": "English",
        "lang_button": "TR ▾",
    },
    "en": {
        "app_title": "YourBook YourLanguage",
        "subtitle": "Scanned English PDF → Turkish  ·  Garamond typesetting  ·  Local OCR",
        "badge_ready": "●  Ready",
        "badge_working": "●  Working",
        "badge_stopping": "●  Stopping",
        "badge_stopped": "●  Stopped",
        "badge_completed": "●  Completed",
        "badge_error": "●  Error",
        "section_source": "1 · Source PDF",
        "section_folder": "2 · Where to save?",
        "section_name": "3 · Output file name",
        "browse_file": "Choose File…",
        "browse_folder": "Choose Folder…",
        "source_hint": "Select the PDF to translate.",
        "source_missing": "File not found. Could not read the text.",
        "unsupported": "Unsupported file. Only PDF is supported.",
        "unreadable": "Could not read the text. The PDF is corrupt or password-protected.",
        "pages_info": "{pages} pages  ·  {size}  ·  text readable",
        "start_page": "Start page",
        "end_page": "End page",
        "dpi": "DPI",
        "end_hint": "(blank = to the end)",
        "dpi_hint": "200 recommended",
        "start_button": "▶  Start Translation",
        "stop_button": "■  Stop",
        "open_last": "Open Last Output",
        "log_title": "Log",
        "clear": "Clear",
        "footer": "Tesseract OCR  ·  Google Translate  ·  Garamond Auto-Fit  ·  100% free",
        "output_preview": "Output: {path}",
        "folder_will_create": "(folder will be created)",
        "overwrite_note": "(existing file will be overwritten)",
        "choose_folder": "Choose an output folder.",
        "name_required": "Enter a file name.",
        "invalid_name_hint": 'Invalid file name. \\ / : * ? " < > | are not allowed.',
        "invalid_file_title": "Invalid file",
        "missing_info": "Missing information",
        "select_source_first": "Select a source PDF first.",
        "select_folder_first": "Choose an output folder.",
        "invalid_name_title": "Invalid file name",
        "invalid_name_msg": 'The file name cannot be empty or contain \\ / : * ? " < > |.',
        "invalid_location_title": "Invalid location",
        "same_file": "The output cannot be the same file as the source PDF.",
        "folder_missing_title": "Folder does not exist",
        "folder_missing_msg": "This folder does not exist yet:\n{folder}\n\nCreate it?",
        "folder_create_error": "Could not create folder",
        "invalid_range_title": "Invalid range",
        "start_invalid": "The start page must be 1 or greater.",
        "end_invalid": "The end page must be a number and cannot be less than the start page.",
        "fix_range_title": "Adjust the range?",
        "fix_range_msg": "The PDF has {pages} pages. Use {pages} instead of {end} as the end page?",
        "overwrite_title": "Overwrite?",
        "overwrite_msg": "This file already exists:\n{out}\n\nOverwrite it?",
        "status_ready": "Ready",
        "status_starting": "Starting…",
        "status_stopping": "Stopping…",
        "status_stopped": "Stopped",
        "status_completed": "Completed",
        "status_completed_clearing": "Completed · log clears in 10 seconds",
        "status_error": "Stopped with an error",
        "status_failed": "Could not start",
        "status_page_progress": "{current} / {total} pages processed",
        "log_source": "Source: {path}",
        "log_output": "Output:  {path}",
        "log_range": "Range: {start}–{end}  ·  DPI: {dpi}",
        "log_range_end": "end",
        "log_user_stopped": "The user stopped the process; the checkpoint is kept.",
        "log_stop_error": "Stop error: {error}",
        "log_stopped": "Process stopped. You can resume with the same settings.",
        "log_finished": "Finished: {path}",
        "log_output_created": "Output created: {path}",
        "log_error_code": "Process exited with code {code}. See the log above for details.",
        "log_failed": "Error: {message}",
        "error_title": "Translation failed",
        "error_msg": "The process stopped with an error. Details are in the log panel.",
        "no_output_title": "No output",
        "no_output_msg": "No output PDF has been created yet.",
        "open_error_title": "Could not open",
        "close_running_title": "Process running",
        "close_running_msg": "Translation is still running. Stop and exit?\nYou can resume later thanks to the checkpoint.",
        "picker_source_title": "Select source PDF",
        "picker_folder_title": "Select output folder",
        "picker_pdf_filter": "PDF files",
        "language_tr": "Türkçe",
        "language_en": "English",
        "lang_button": "EN ▾",
    },
}


def load_language() -> str:
    """Kayitli dili, yoksa sistem dilini dondurur."""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        language = data.get("language")
        if language in {"tr", "en"}:
            return language
    except (OSError, json.JSONDecodeError):
        pass
    return "tr" if os.environ.get("LANG", "").lower().startswith("tr") else "en"


def save_language(language: str) -> None:
    """Secilen arayuz dilini saklar."""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        data["language"] = language
        CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


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


def is_complete_output(path: Path) -> bool:
    """Checkpoint varsa islemin gercekten bittigini dogrular."""
    checkpoint = Path(f"{path}.checkpoint.json")
    if not checkpoint.exists():
        return True
    try:
        data = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("finished"))


def display_path(path: Path) -> str:
    """Proje klasoru altindaysa kisa yol gosterir."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _native_pick(kind: str, initial: Path, lang: str) -> tuple[str | None, bool]:
    """KDE/zenity yerel secim penceresi.

    Returns:
        (secili yol veya None, islem ele alindi mi)
    """
    texts = TEXTS.get(lang, TEXTS["en"])
    if shutil.which("kdialog"):
        if kind == "file":
            cmd = [
                "kdialog",
                "--title",
                texts["picker_source_title"],
                "--getopenfilename",
                str(initial),
                f"{texts['picker_pdf_filter']} (*.pdf *.PDF)",
            ]
        else:
            cmd = [
                "kdialog",
                "--title",
                texts["picker_folder_title"],
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
                f"--title={texts['picker_source_title']}",
                f"--file-filter={texts['picker_pdf_filter']} | *.pdf *.PDF",
            ]
        else:
            cmd = [
                "zenity",
                "--file-selection",
                "--directory",
                f"--title={texts['picker_folder_title']}",
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
    return None, False


def pick_pdf_file(initial: Path, parent: tk.Misc, lang: str) -> str | None:
    """PDF secimi icin yerel (KDE) pencereyi, yoksa Tk penceresini acar."""
    texts = TEXTS.get(lang, TEXTS["en"])
    path, handled = _native_pick("file", initial, lang)
    if handled:
        return path
    selected = filedialog.askopenfilename(
        parent=parent,
        title=texts["picker_source_title"],
        initialdir=str(initial),
        filetypes=[(texts["picker_pdf_filter"], "*.pdf *.PDF")],
    )
    return selected or None


def pick_directory(initial: Path, parent: tk.Misc, lang: str) -> str | None:
    """Klasor secimi icin yerel pencereyi, yoksa Tk penceresini acar."""
    texts = TEXTS.get(lang, TEXTS["en"])
    path, handled = _native_pick("folder", initial, lang)
    if handled:
        return path
    selected = filedialog.askdirectory(
        parent=parent,
        title=texts["picker_folder_title"],
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
        language: str | None = None,
    ) -> None:
        self.root = root
        self.lang = language if language in {"tr", "en"} else load_language()
        self._status_state: tuple[str, dict] = ("status_ready", {})
        self._badge_state: tuple[str, str] = ("badge_ready", "#93c5fd")
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
        self.folder_var = tk.StringVar(value="output")
        self.name_var = tk.StringVar()
        self.start_var = tk.StringVar(value="1")
        self.end_var = tk.StringVar()
        self.dpi_var = tk.StringVar(value="200")
        self.status_var = tk.StringVar(value=self.t("status_ready"))
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
            self.folder_var.set(display_path(output.parent))
            self.name_var.set(output.stem)
        self._load_last_output()
        self._update_input_info()
        self._update_output_preview()
        self._sync_open_button()

        if print_window_id:
            self.root.after(600, self._print_window_id)
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _setup_window(self) -> None:
        self.root.title(self.t("app_title"))
        self.root.iconname(self.t("app_title"))
        self.root.geometry("940x830")
        self.root.minsize(860, 740)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="DejaVu Sans", size=10)
        self._load_app_icon()

    def _choose_language(self, language: str) -> None:
        if language == self.lang:
            return
        self.lang = language
        save_language(language)
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        """Arayuz dilini degistirir; alan degerlerini ve gunlugu korur."""
        log_content = self.log_text.get("1.0", "end-1c") if hasattr(self, "log_text") else ""
        progress = float(self.progress["value"]) if hasattr(self, "progress") else 0.0
        for child in self.root.winfo_children():
            child.destroy()
        self._lock_widgets.clear()
        self._browse_buttons.clear()
        self.root.title(self.t("app_title"))
        self.root.iconname(self.t("app_title"))
        self._build_ui()
        self.name_entry.bind("<KeyRelease>", self._on_name_typed)
        if log_content:
            self.log_text.configure(state="normal")
            self.log_text.insert("1.0", log_content)
            self.log_text.configure(state="disabled")
            self.log_text.see("end")
        self.progress.configure(value=progress)
        self._update_input_info()
        self._update_output_preview()
        self._sync_open_button()
        status_key, status_args = self._status_state
        self._set_status(status_key, **status_args)
        self._badge(*self._badge_state)
        self._set_running(self.proc is not None)

    def _load_app_icon(self) -> None:
        if ICON_PNG.exists():
            try:
                self._icon_img = tk.PhotoImage(file=str(ICON_PNG))
                self.root.iconphoto(True, self._icon_img)
            except tk.TclError:
                self._icon_img = None
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
            text=self.t("app_title"),
            bg=COLORS["header"],
            fg="white",
            font=("DejaVu Sans", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header_text,
            text=self.t("subtitle"),
            bg=COLORS["header"],
            fg=COLORS["header_soft"],
            font=("DejaVu Sans", 10),
        ).pack(anchor="w", pady=(2, 0))
        self.badge = tk.Label(
            header,
            text=self.t("badge_ready"),
            bg="#1e293b",
            fg="#93c5fd",
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=5,
        )
        self.badge.place(relx=1.0, x=-30, y=58, anchor="ne")
        self.lang_btn = tk.Menubutton(
            header,
            text=self.t("lang_button"),
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="white",
            bd=0,
            relief="flat",
            padx=12,
            pady=5,
            font=("DejaVu Sans", 9, "bold"),
            cursor="hand2",
            indicatoron=False,
        )
        lang_menu = tk.Menu(
            self.lang_btn,
            tearoff=False,
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground=COLORS["accent"],
            activeforeground="white",
            bd=0,
            font=("DejaVu Sans", 9),
        )
        lang_menu.add_command(
            label=self.t("language_tr"), command=lambda: self._choose_language("tr")
        )
        lang_menu.add_command(
            label=self.t("language_en"), command=lambda: self._choose_language("en")
        )
        self.lang_btn.configure(menu=lang_menu)
        self.lang_btn.place(relx=1.0, x=-30, y=18, anchor="ne")

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

        self._card_label(inner, self.t("section_source")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        self.input_entry = ttk.Entry(
            inner, textvariable=self.input_var, style="Field.TEntry"
        )
        self.input_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.input_browse = ttk.Button(
            inner,
            text=self.t("browse_file"),
            style="Secondary.TButton",
            command=self._browse_input,
        )
        self.input_browse.grid(row=1, column=2, padx=(8, 0), pady=(4, 0))
        self.input_info = tk.Label(
            inner,
            text=self.t("source_hint"),
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 9),
        )
        self.input_info.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 12))
        self._browse_buttons.append(self.input_browse)

        self._card_label(inner, self.t("section_folder")).grid(
            row=3, column=0, columnspan=3, sticky="w"
        )
        self.folder_entry = ttk.Entry(
            inner, textvariable=self.folder_var, style="Field.TEntry"
        )
        self.folder_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.folder_browse = ttk.Button(
            inner,
            text=self.t("browse_folder"),
            style="Secondary.TButton",
            command=self._browse_folder,
        )
        self.folder_browse.grid(row=4, column=2, padx=(8, 0), pady=(4, 0))
        self._browse_buttons.append(self.folder_browse)

        self._card_label(inner, self.t("section_name")).grid(
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
            text=self.t("start_page"),
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            options,
            text=self.t("end_page"),
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9),
        ).grid(row=0, column=1, padx=(18, 0), sticky="w")
        tk.Label(
            options,
            text=self.t("dpi"),
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
            text=self.t("end_hint"),
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 8),
        ).grid(row=1, column=3, padx=(8, 0), sticky="w", pady=(5, 0))
        tk.Label(
            options,
            text=self.t("dpi_hint"),
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
            text=self.t("start_button"),
            style="Accent.TButton",
            command=self._start,
        )
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            buttons,
            text=self.t("stop_button"),
            style="Secondary.TButton",
            command=self._stop,
        )
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.stop_btn.state(["disabled"])
        self.open_btn = ttk.Button(
            buttons,
            text=self.t("open_last"),
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
            text=self.t("log_title"),
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        clear_btn = tk.Button(
            log_header,
            text=self.t("clear"),
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
            text=self.t("footer"),
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
        self._set_status("status_completed")

    def _cancel_clear_timer(self) -> None:
        if self._clear_job is not None:
            try:
                self.root.after_cancel(self._clear_job)
            except tk.TclError:
                pass
            self._clear_job = None

    def t(self, key: str, **kwargs: object) -> str:
        """Aktif arayuz dilinde metin dondurur."""
        text = TEXTS.get(self.lang, TEXTS["en"]).get(key, key)
        return text.format(**kwargs) if kwargs else text

    def _set_status(self, key: str, **kwargs: object) -> None:
        self._status_state = (key, kwargs)
        self.status_var.set(self.t(key, **kwargs))

    def _badge(self, key: str, color: str) -> None:
        self._badge_state = (key, color)
        self.badge.configure(text=self.t(key), fg=color)

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
            self._set_input_info(self.t("source_hint"), COLORS["muted"])
            return
        path = self._abs_path(raw)
        if not path.exists():
            self._set_input_info(self.t("source_missing"), COLORS["err"])
            return
        if path.suffix.lower() != ".pdf":
            self._set_input_info(self.t("unsupported"), COLORS["err"])
            return
        pages = pdf_page_count(path)
        if not pages:
            self._set_input_info(self.t("unreadable"), COLORS["err"])
            return
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = "?"
        self._set_input_info(
            self.t("pages_info", pages=pages, size=size), COLORS["muted"]
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
            self.output_preview.configure(text=self.t("choose_folder"), fg=COLORS["err"])
            return
        if not name:
            self.output_preview.configure(text=self.t("name_required"), fg=COLORS["err"])
            return
        if not valid_file_name(name):
            self.output_preview.configure(
                text=self.t("invalid_name_hint"), fg=COLORS["err"]
            )
            return
        folder = self._abs_path(folder_raw)
        path = folder / f"{name}.pdf"
        text = self.t("output_preview", path=display_path(path))
        color = COLORS["muted"]
        if not folder.exists():
            text += f"   {self.t('folder_will_create')}"
            color = COLORS["warn"]
        elif path.exists():
            text += f"   {self.t('overwrite_note')}"
            color = COLORS["warn"]
        self.output_preview.configure(text=text, fg=color)

    def _load_last_output(self) -> None:
        """Önceki oturumda üretilen son çıktı yolunu yükler."""
        try:
            data = json.loads(LAST_OUTPUT_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        raw = data.get("path")
        if not raw:
            return
        path = Path(raw)
        if path.is_file():
            self.last_output = path

    def _remember_last_output(self, out: Path) -> None:
        """Son başarılı çıktıyı oturumlar arasında hatırlar."""
        self.last_output = out
        try:
            LAST_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            LAST_OUTPUT_FILE.write_text(
                json.dumps({"path": str(out)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _latest_output(self) -> Path | None:
        """Uygulamanın ürettiği en son çıktı PDF'ini bulur."""
        candidates: list[Path] = []
        if self.last_output is not None and self.last_output.is_file():
            candidates.append(self.last_output)
        folders: list[Path] = []
        raw_folder = self.folder_var.get().strip()
        if raw_folder:
            folders.append(self._abs_path(raw_folder))
        default_folder = ROOT / "output"
        if default_folder not in folders:
            folders.append(default_folder)
        input_path: Path | None = None
        if self.input_var.get().strip():
            input_path = self._abs_path(self.input_var.get().strip())
        for folder in folders:
            if not folder.is_dir():
                continue
            for path in folder.glob("*.pdf"):
                if not path.is_file() or path == input_path:
                    continue
                if not is_complete_output(path):
                    continue
                is_app_output = (
                    path.name.lower().endswith("_tr.pdf")
                    or Path(f"{path}.checkpoint.json").exists()
                    or path == self.last_output
                )
                if is_app_output and path not in candidates:
                    candidates.append(path)
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.stat().st_mtime)

    def _sync_open_button(self) -> None:
        if self._latest_output() is not None:
            self.open_btn.state(["!disabled"])
        else:
            self.open_btn.state(["disabled"])

    def _set_input(self, value: str) -> None:
        path = self._abs_path(value)
        self.input_var.set(display_path(path))
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
        path = pick_pdf_file(candidate, self.root, self.lang)
        if path:
            self._set_input(path)

    def _browse_folder(self) -> None:
        current = self.folder_var.get().strip()
        candidate = self._abs_path(current) if current else ROOT / "output"
        if not candidate.is_dir():
            candidate = ROOT
        path = pick_directory(candidate, self.root, self.lang)
        if path:
            self.folder_var.set(str(Path(path).resolve()))

    # ---------------------------------------------------------------- start
    def _show_input_error(self, message: str) -> None:
        self._set_input_info(message, COLORS["err"])
        messagebox.showerror(self.t("invalid_file_title"), message)

    def _validate(self) -> tuple[Path, Path, int, int | None, int] | None:
        raw_in = self.input_var.get().strip()
        if not raw_in:
            messagebox.showwarning(
                self.t("missing_info"), self.t("select_source_first")
            )
            return None
        inp = self._abs_path(raw_in)
        if not inp.exists():
            self._show_input_error(self.t("source_missing"))
            return None
        if inp.suffix.lower() != ".pdf":
            self._show_input_error(self.t("unsupported"))
            return None
        pages = pdf_page_count(inp)
        if not pages:
            self._show_input_error(self.t("unreadable"))
            return None

        folder_raw = self.folder_var.get().strip()
        if not folder_raw:
            messagebox.showwarning(
                self.t("missing_info"), self.t("select_folder_first")
            )
            return None
        name = self._clean_name(self.name_var.get())
        if not valid_file_name(name):
            messagebox.showerror(
                self.t("invalid_name_title"), self.t("invalid_name_msg")
            )
            return None
        folder = self._abs_path(folder_raw)
        out = folder / f"{name}.pdf"
        if out.resolve() == inp.resolve():
            messagebox.showerror(
                self.t("invalid_location_title"), self.t("same_file")
            )
            return None
        if not folder.exists():
            if not messagebox.askyesno(
                self.t("folder_missing_title"),
                self.t("folder_missing_msg", folder=folder),
            ):
                return None
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(self.t("folder_create_error"), str(exc))
                return None

        try:
            start = int(self.start_var.get().strip())
            if start < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                self.t("invalid_range_title"), self.t("start_invalid")
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
                    self.t("invalid_range_title"), self.t("end_invalid")
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
                self.t("fix_range_title"),
                self.t("fix_range_msg", pages=pages, end=end),
            ):
                return None
            end = pages
            self.end_var.set(str(pages))
        if out.exists():
            if not messagebox.askyesno(
                self.t("overwrite_title"),
                self.t("overwrite_msg", out=out),
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
        self.progress.configure(value=0)
        self.percent_var.set("%0")
        self._set_status("status_starting")
        self._badge("badge_working", "#93c5fd")
        self._log(self.t("log_source", path=inp))
        self._log(self.t("log_output", path=out))
        self._log(
            self.t(
                "log_range",
                start=start,
                end=end or self.t("log_range_end"),
                dpi=dpi,
            )
        )
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
        self._set_status("status_stopping")
        self._badge("badge_stopping", "#fcd34d")
        self._log(self.t("log_user_stopped"))
        try:
            self.proc.terminate()
        except OSError as exc:
            self._log(self.t("log_stop_error", error=exc))

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
            self._set_status(
                "status_page_progress", current=current, total=total
            )
            return
        if PROGRESS_RE.search(line) or line.startswith("Sayfalar:"):
            return
        if line.startswith("Cikti olusturuldu") or line.startswith("Çıktı oluşturuldu"):
            _, _, path = line.partition(":")
            self._log(self.t("log_output_created", path=path.strip()))
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

    def _finish(self, code: int, out: Path) -> None:
        self.proc = None
        self._set_running(False)
        self._sync_open_button()
        if self._stopping:
            self._stopping = False
            self._set_status("status_stopped")
            self._badge("badge_stopped", "#fcd34d")
            self._log(self.t("log_stopped"))
            return
        if code == 0:
            if out.is_file():
                self._remember_last_output(out)
            self.progress.configure(value=100)
            self.percent_var.set("%100")
            self._set_status("status_completed_clearing")
            self._badge("badge_completed", "#86efac")
            self._log(self.t("log_finished", path=out))
            self._sync_open_button()
            self.root.bell()
            self._clear_job = self.root.after(10000, self._clear_log_after_done)
        else:
            self._set_status("status_error")
            self._badge("badge_error", "#fca5a5")
            self._log(self.t("log_error_code", code=code))
            messagebox.showerror(
                self.t("error_title"),
                self.t("error_msg"),
            )

    def _fail(self, message: str) -> None:
        self.proc = None
        self._stopping = False
        self._set_running(False)
        self._set_status("status_failed")
        self._badge("badge_error", "#fca5a5")
        self._log(self.t("log_failed", message=message))
        messagebox.showerror(self.t("status_failed"), message)

    # ---------------------------------------------------------------- misc
    def _open_output(self) -> None:
        out = self._latest_output()
        if out is None:
            messagebox.showinfo(
                self.t("no_output_title"), self.t("no_output_msg")
            )
            return
        self._remember_last_output(out)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(out))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(out)])
            else:
                subprocess.Popen(["xdg-open", str(out)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(self.t("open_error_title"), str(exc))

    def _on_close(self) -> None:
        if self.proc is not None:
            if not messagebox.askyesno(
                self.t("close_running_title"),
                self.t("close_running_msg"),
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
    parser.add_argument(
        "--lang",
        choices=("tr", "en"),
        help="Arayüz dili / interface language",
    )
    args = parser.parse_args()

    root = tk.Tk(className="KitapPdfCevirmen")
    App(
        root,
        args.input,
        args.output,
        args.print_window_id,
        language=args.lang,
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

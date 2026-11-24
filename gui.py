#!/usr/bin/env python3
"""Kitap PDF Cevirmen - masaustu grafik arayuzu (Tkinter).

CLI'yi (main.py) arka planda calistirir; dosya secimi, sayfa araligi,
ilerleme cubugu ve canli gunluk sunar. Ek pip bagimliligi gerektirmez.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
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


def human_size(num: int) -> str:
    """Bayt degerini okunakli hale getirir."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def pdf_page_count(path: Path) -> int | None:
    """PyMuPDF varsa PDF sayfa sayisini dondurur; yoksa None."""
    try:
        import pymupdf

        with pymupdf.open(str(path)) as doc:
            return doc.page_count
    except Exception:
        return None


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
        self._auto_output = True
        self._lock_widgets: list[tk.Widget] = []
        self._browse_buttons: list[ttk.Button] = []
        self._stopping = False
        self._info_job: str | None = None

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
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
            self._auto_output = False
            self.output_var.set(str(self._abs_path(output_path)))

        if print_window_id:
            self.root.after(600, self._print_window_id)
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _setup_window(self) -> None:
        self.root.title("Kitap PDF Çevirmen")
        self.root.geometry("940x760")
        self.root.minsize(840, 680)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="DejaVu Sans", size=10)

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

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["header"], height=96)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="Kitap PDF Çevirmen",
            bg=COLORS["header"],
            fg="white",
            font=("DejaVu Sans", 20, "bold"),
        ).pack(anchor="w", padx=30, pady=(18, 0))
        tk.Label(
            header,
            text="Taranmış İngilizce PDF → Türkçe  ·  Garamond dizgi  ·  Yerel OCR",
            bg=COLORS["header"],
            fg=COLORS["header_soft"],
            font=("DejaVu Sans", 10),
        ).pack(anchor="w", padx=31, pady=(2, 0))
        self.badge = tk.Label(
            header,
            text="●  Hazır",
            bg="#1e293b",
            fg="#93c5fd",
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=5,
        )
        self.badge.place(relx=1.0, x=-30, y=26, anchor="ne")

        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=26, pady=(18, 4))
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
        inner.pack(fill="x", padx=18, pady=16)
        inner.columnconfigure(1, weight=1)

        tk.Label(
            inner,
            text="Kaynak PDF",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        self.input_entry = ttk.Entry(
            inner, textvariable=self.input_var, style="Field.TEntry"
        )
        self.input_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.input_browse = ttk.Button(
            inner,
            text="Gözat…",
            style="Secondary.TButton",
            command=self._browse_input,
        )
        self.input_browse.grid(row=1, column=2, padx=(8, 0), pady=(4, 0))
        self.input_info = tk.Label(
            inner,
            text="Çevrilecek taranmış PDF dosyasını seçin.",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 9),
        )
        self.input_info.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 12))
        self._browse_buttons.append(self.input_browse)

        tk.Label(
            inner,
            text="Çıktı PDF",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("DejaVu Sans", 9, "bold"),
        ).grid(row=3, column=0, columnspan=3, sticky="w")
        self.output_entry = ttk.Entry(
            inner, textvariable=self.output_var, style="Field.TEntry"
        )
        self.output_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        self.output_browse = ttk.Button(
            inner,
            text="Kaydet…",
            style="Secondary.TButton",
            command=self._browse_output,
        )
        self.output_browse.grid(row=4, column=2, padx=(8, 0), pady=(4, 12))
        self._browse_buttons.append(self.output_browse)

        options = tk.Frame(inner, bg=COLORS["card"])
        options.grid(row=5, column=0, columnspan=3, sticky="w")
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

        self._lock_widgets.extend([self.input_entry, self.output_entry, self.start_entry,
                                   self.end_entry, self.dpi_box])

        # --- Butonlar ----------------------------------------------------
        buttons = tk.Frame(body, bg=COLORS["bg"])
        buttons.grid(row=1, column=0, sticky="ew", pady=(14, 10))
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
        progress_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        pinner = tk.Frame(progress_card, bg=COLORS["card"])
        pinner.pack(fill="x", padx=18, pady=10)
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
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

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
            height=9,
            padx=12,
            pady=10,
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
        footer.pack(side="bottom", pady=(0, 8))
        self.root.update_idletasks()

    def _bind_events(self) -> None:
        self.input_var.trace_add("write", lambda *_: self._schedule_input_info())
        self.output_var.trace_add("write", lambda *_: self._sync_open_button())

    @staticmethod
    def _abs_path(value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (ROOT / path).resolve()

    def _schedule_input_info(self) -> None:
        if self._info_job is not None:
            self.root.after_cancel(self._info_job)
        self._info_job = self.root.after(300, self._update_input_info)

    # -------------------------------------------------------------- helpers
    def _print_window_id(self) -> None:
        print("WINDOW_ID", self.root.winfo_id(), flush=True)

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp}  {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _badge(self, text: str, color: str) -> None:
        self.badge.configure(text=text, fg=color)

    def _update_input_info(self) -> None:
        self._info_job = None
        raw = self.input_var.get().strip()
        if not raw:
            self.input_info.configure(text="Çevrilecek taranmış PDF dosyasını seçin.")
            return
        path = self._abs_path(raw)
        if not path.is_file():
            self.input_info.configure(text="Dosya bulunamadı.")
            return
        pages = pdf_page_count(path)
        page_text = f"{pages} sayfa" if pages else "sayfa sayısı okunamadı"
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = "?"
        self.input_info.configure(text=f"{page_text}  ·  {size}")

    def _sync_open_button(self) -> None:
        raw = self.output_var.get().strip()
        if raw and self._abs_path(raw).is_file():
            self.open_btn.state(["!disabled"])
        else:
            self.open_btn.state(["disabled"])

    def _auto_output_for(self, input_path: Path) -> str:
        stem = input_path.stem or "kitap"
        return str((ROOT / "output" / f"{stem}_tr.pdf").resolve())

    def _set_input(self, value: str) -> None:
        self.input_var.set(str(Path(value).expanduser().resolve()))
        if self._auto_output or not self.output_var.get().strip():
            self.output_var.set(self._auto_output_for(Path(value)))

    def _browse_input(self) -> None:
        initial = ROOT / "input"
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Kaynak PDF seç",
            initialdir=str(initial if initial.exists() else ROOT),
            filetypes=[("PDF dosyaları", "*.pdf"), ("Tüm dosyalar", "*.*")],
        )
        if path:
            self._set_input(path)

    def _browse_output(self) -> None:
        current = Path(self.output_var.get().strip() or (ROOT / "output" / "kitap_tr.pdf"))
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Çıktı PDF konumu",
            initialdir=str(current.parent),
            initialfile=current.name,
            defaultextension=".pdf",
            filetypes=[("PDF dosyası", "*.pdf")],
        )
        if path:
            self._auto_output = False
            self.output_var.set(str(Path(path).expanduser().resolve()))

    # ---------------------------------------------------------------- start
    def _validate(self) -> tuple[Path, Path, int, int | None, int] | None:
        raw_in = self.input_var.get().strip()
        raw_out = self.output_var.get().strip()
        if not raw_in:
            messagebox.showwarning("Eksik bilgi", "Önce bir kaynak PDF seçin.")
            return None
        inp = self._abs_path(raw_in)
        if not inp.is_file() or inp.suffix.lower() != ".pdf":
            messagebox.showerror("Geçersiz PDF", f"PDF bulunamadı:\n{inp}")
            return None
        if not raw_out:
            messagebox.showwarning("Eksik bilgi", "Çıktı PDF konumunu girin.")
            return None
        out = self._abs_path(raw_out)
        if out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")
            self.output_var.set(str(out))
        if out.resolve() == inp.resolve():
            messagebox.showerror("Geçersiz konum", "Çıktı, kaynak PDF ile aynı olamaz.")
            return None
        try:
            start = int(self.start_var.get().strip())
            if start < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Geçersiz aralık", "Başlangıç sayfası 1 veya daha büyük olmalı.")
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
                    "Bitiş sayfası, başlangıçtan küçük olamaz ve sayı olmalı.",
                )
                return None
        else:
            end = None
        try:
            dpi = int(self.dpi_var.get())
        except ValueError:
            dpi = 200
        pages = pdf_page_count(inp)
        if pages and end and end > pages:
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
        out.parent.mkdir(parents=True, exist_ok=True)
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
        if any(token in line for token in ("UYARI", "atlandı", "atlandi", "Traceback",
                                           "Error", "HATA", "basarisiz", "başarısız")):
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
            self.status_var.set("Tamamlandı")
            self._badge("●  Tamamlandı", "#86efac")
            self._log(f"Bitti: {out}")
            self.root.bell()
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
            raw = self.output_var.get().strip()
            out = self._abs_path(raw) if raw else None
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

    root = tk.Tk()
    App(root, args.input, args.output, args.print_window_id)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

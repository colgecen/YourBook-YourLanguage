"""PyMuPDF tabanli Garamond dizgi PDF olusturucu."""

from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_REGULAR = FONT_DIR / "Garamond-Regular.ttf"
FONT_ITALIC = FONT_DIR / "Garamond-Italic.ttf"

FONT_NAME = "Garamond"
FALLBACK_FONT = "helv"
MAX_FONT_SIZE = 12.0
MIN_FONT_SIZE = 7.0
FONT_STEP = 0.5


def calculate_optimal_fontsize(text: str, width: float, height: float) -> float:
    """Turkce metnin kutuya sigmasi icin en uygun font boyutunu bulur.

    Turkce metin ~%30 uzadigi icin hedef kutunun genislik ve yuksekligine
    sigana kadar font boyutu 12pt'den 7pt'ye kadar 0.5 adimlarla dusurulur.

    Args:
        text: Dizgi yapilacak metin.
        width: Hedef kutunun genisligi (pt).
        height: Hedef kutunun yuksekligi (pt).

    Returns:
        Secilen font boyutu (pt). Min degerin altina inilmez.
    """
    size = MAX_FONT_SIZE
    while size >= MIN_FONT_SIZE:
        # Yaklasik satir sayisi: karakter / (genislik / (0.5 * boyut))
        char_w = size * 0.5
        if char_w <= 0:
            break
        chars_per_line = max(1, int(width / char_w))
        lines = max(1, (len(text) + chars_per_line - 1) // chars_per_line)
        line_h = size * 1.25
        if lines * line_h <= height and len(text) * char_w <= width * max(1, lines) * 1.3:
            return size
        size -= FONT_STEP
    return MIN_FONT_SIZE


class PDFBuilder:
    """Garamond fontuyla iki yana yasli PDF dizgisi yapar.

    Sablon PDF uzerine yazmaz; bos yeni belge acar. Gerekirse temizlenmis
    sayfa gorseli arka plan olarak basilir, uzerine ceviri yazilir. Boylece
    eski Ingilizce metin altta kalmaz.
    """

    def __init__(
        self,
        template_path: str | Path | None = None,
        resume_path: str | Path | None = None,
    ) -> None:
        """Builder'i baslatir.

        Args:
            template_path: Sayfa olculerini almak icin sablon PDF. Uzerine
                yazilmaz, sadece boyut referansi olarak okunur.
            resume_path: Varsa kaldigi yerden devam icin acilacak kismi
                cikti PDF (checkpoint resume).
        """
        self.template_path = Path(template_path) if template_path else None
        self.template_rects: list[fitz.Rect] = []
        if self.template_path and self.template_path.exists():
            tmp = fitz.open(str(self.template_path))
            try:
                self.template_rects = [p.rect for p in tmp]
            finally:
                tmp.close()
        if resume_path and Path(resume_path).exists():
            self.doc = fitz.open(str(resume_path))
        else:
            self.doc = fitz.open()
        self._fonts_registered = False

    def _active_font(self) -> str:
        """Garamond mevcutsa onu, yoksa helv doner."""
        if FONT_REGULAR.exists():
            return FONT_NAME
        return FALLBACK_FONT

    @staticmethod
    def _register_fonts_for_page(page: fitz.Page) -> None:
        """Garamond fontunu sayfaya (dokuya) kaydeder; yoksa sessiz gecer."""
        try:
            if FONT_REGULAR.exists():
                page.insert_font(fontname=FONT_NAME, fontfile=str(FONT_REGULAR))
            if FONT_ITALIC.exists():
                page.insert_font(fontname=FONT_NAME + "Italic", fontfile=str(FONT_ITALIC))
        except Exception:
            # Font kaydi basarisizsa textbox helv ile devam eder.
            pass

    def _ensure_page(
        self, page_index: int, width: float | None = None, height: float | None = None
    ) -> fitz.Page:
        """page_index konumunda sayfa garantiler; yoksa olusturur."""
        while len(self.doc) <= page_index:
            if width and height:
                self.doc.new_page(width=float(width), height=float(height))
            elif self.template_rects:
                # Sablonun siradaki sayfa olcusunu kullan, yoksa son olcuyu.
                ref = self.template_rects[min(len(self.doc), len(self.template_rects) - 1)]
                self.doc.new_page(width=ref.width, height=ref.height)
            else:
                self.doc.new_page()
        return self.doc[page_index]

    def write_page(
        self,
        page_index: int,
        text: str,
        bbox: tuple[float, float, float, float],
        background: Image.Image | None = None,
    ) -> None:
        """Metni yeni belgede page_index sayfasina yazar.

        Args:
            page_index: Hedef sayfa indeksi (0 tabanli, ciktiya gore).
            text: Yazilacak metin.
            bbox: (x0, y0, x1, y1) hedef kutu (pt). Genelde tam sayfa.
            background: Temizlenmis sayfa gorseli (PIL). Verilirse once
                sayfaya tam boy basilir, metin uzerine yazilir.
        """
        x0, y0, x1, y1 = bbox
        width = max(1.0, x1 - x0)
        height = max(1.0, y1 - y0)
        page = self._ensure_page(page_index, width=width, height=height)
        self._register_fonts_for_page(page)
        fontname = self._active_font()

        # 1) Arka plan: temizlenmis gorsel (eski yazi silinmis hali).
        if background is not None:
            buf = io.BytesIO()
            # RGB'ye cevir (RGBA/P modunda insert_image bozulabilir).
            bg = background.convert("RGB") if background.mode != "RGB" else background
            bg.save(buf, format="PNG")
            page_rect = fitz.Rect(x0, y0, x1, y1)
            page.insert_image(page_rect, stream=buf.getvalue(), overlay=False)

        # 2) Metin kutusu: kenarlardan kucuk pay birak.
        margin = min(36.0, width * 0.05, height * 0.05)
        rect = fitz.Rect(x0 + margin, y0 + margin, x1 - margin, y1 - margin)
        fontsize = calculate_optimal_fontsize(text, rect.width, rect.height)
        rc = page.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontsize=fontsize,
            align=fitz.TEXT_ALIGN_JUSTIFY,
            color=(0, 0, 0),
        )
        # Sigmazsa bir adim daha kucultup tekrar dene
        if rc < 0:
            fontsize = max(MIN_FONT_SIZE, fontsize - FONT_STEP)
            page.insert_textbox(
                rect,
                text,
                fontname=fontname,
                fontsize=fontsize,
                align=fitz.TEXT_ALIGN_JUSTIFY,
                color=(0, 0, 0),
            )

    def save(self, output_path: str | Path) -> Path:
        """PDF'i diske kaydeder (incremental checkpoint icin tekrar cagrilabilir).

        Args:
            output_path: Cikti dosya yolu.

        Returns:
            Yazilan dosya yolu.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        # garbage=4, deflate: kismi kayitlarda sismeyi onler.
        self.doc.save(str(out), garbage=4, deflate=True)
        return out

    def close(self) -> None:
        """Belgeyi kapatir."""
        self.doc.close()

"""PyMuPDF tabanli Garamond dizgi PDF olusturucu."""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_REGULAR = FONT_DIR / "Garamond-Regular.ttf"
FONT_ITALIC = FONT_DIR / "Garamond-Italic.ttf"

FONT_NAME = "Garamond"
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
    """Garamond fontuyla iki yana yasli PDF dizgisi yapar."""

    def __init__(self, template_path: str | Path | None = None) -> None:
        """Builder'i baslatir; fontu sisteme kaydeder.

        Args:
            template_path: Uzerine yazilacak sablon PDF. None ise bos belge acilir.
        """
        self.template_path = Path(template_path) if template_path else None
        if self.template_path and self.template_path.exists():
            self.doc = fitz.open(str(self.template_path))
        else:
            self.doc = fitz.open()

    @staticmethod
    def register_fonts(page: fitz.Page) -> None:
        """Garamond fontunu sayfaya (dokuya) kaydeder.

        Args:
            page: Font kaydedilecek PyMuPDF sayfasi.
        """
        if FONT_REGULAR.exists():
            page.insert_font(fontname=FONT_NAME, fontfile=str(FONT_REGULAR))
        if FONT_ITALIC.exists():
            page.insert_font(fontname=FONT_NAME + "Italic", fontfile=str(FONT_ITALIC))

    def write_page(self, page_index: int, text: str, bbox: tuple[float, float, float, float]) -> None:
        """Metni verilen sayfadaki kutuya, iki yana yasli ve auto-fit fontla yazar.

        Args:
            page_index: Hedef sayfa indeksi (0 tabanli).
            text: Yazilacak metin.
            bbox: (x0, y0, x1, y1) hedef kutu (pt).
        """
        if page_index >= len(self.doc):
            raise IndexError(f"Sayfa {page_index} belgede yok")
        page = self.doc[page_index]
        self.register_fonts(page)
        x0, y0, x1, y1 = bbox
        width = max(1.0, x1 - x0)
        height = max(1.0, y1 - y0)
        fontsize = calculate_optimal_fontsize(text, width, height)
        rect = fitz.Rect(x0, y0, x1, y1)
        rc = page.insert_textbox(
            rect,
            text,
            fontname=FONT_NAME,
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
                fontname=FONT_NAME,
                fontsize=fontsize,
                align=fitz.TEXT_ALIGN_JUSTIFY,
                color=(0, 0, 0),
            )

    def save(self, output_path: str | Path) -> Path:
        """PDF'i diske kaydeder.

        Args:
            output_path: Cikti dosya yolu.

        Returns:
            Yazilan dosya yolu.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(out))
        return out

    def close(self) -> None:
        """Belgeyi kapatir."""
        self.doc.close()

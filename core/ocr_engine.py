"""Tesseract OCR motoru: PDF sayfalarını görselleştirip metin bloklarını çıkarır."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from PIL import Image


@dataclass(frozen=True)
class TextBlock:
    """OCR'dan çıkarılan tek bir metin bloğu.

    Attributes:
        text: Bloğun ham metni.
        bbox: Koordinat kutusu (x0, y0, x1, y1) piksel cinsinden.
        confidence: Tespit edilen dilin güvenilirlik skoru (0-100).
        language: Tespit edilen dil kodu (ör. 'eng').
    """

    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    language: str


class OCREngine:
    """pytesseract ve pdf2image tabanlı OCR motoru.

    PDF sayfalarını 300 DPI çözünürlükte görsellere çevirir,
    her sayfadaki metin bloklarını koordinat ve güven skoruyla döner.
    """

    def __init__(self, dpi: int = 300, lang: str = "eng") -> None:
        """OCR motorunu başlatır.

        Args:
            dpi: PDF'ten görsel üretme çözünürlüğü.
            lang: Tesseract dil kodu.
        """
        self.dpi = dpi
        self.lang = lang

    def pdf_to_images(self, pdf_path: str | Path, start_page: int = 1, end_page: int | None = None) -> list[Image.Image]:
        """PDF dosyasını sayfa görsellerine çevirir.

        Args:
            pdf_path: Kaynak PDF dosya yolu.
            start_page: Başlangıç sayfası (1 tabanlı, dahil).
            end_page: Bitiş sayfası (1 tabanlı, dahil). None ise sonuna kadar.

        Returns:
            PIL.Image nesnelerinin listesi.
        """
        first = max(1, start_page)
        kwargs: dict = {"dpi": self.dpi, "first_page": first}
        # last_page verilmezse pdf2image belgenin sonuna kadar gider.
        # Eskiden 10**9 gonderiliyordu, poppler'da hata veriyordu.
        if end_page is not None:
            kwargs["last_page"] = max(first, end_page)
        try:
            return convert_from_path(str(pdf_path), **kwargs)
        except Exception as exc:
            raise RuntimeError(
                "pdf2image donusumu basarisiz. Poppler kurulu olmali: "
                "Windows'ta poppler'i kurup PATH'e ekleyin, "
                "Linux'ta 'sudo apt install poppler-utils'. "
                f"Orijinal hata: {exc}"
            ) from exc

    def extract_blocks(self, image: Image.Image) -> list[TextBlock]:
        """Tek bir sayfa görselinden metin bloklarını çıkarır.

        Args:
            image: OCR uygulanacak sayfa görseli.

        Returns:
            Metin, koordinat kutusu ve güven skoru içeren TextBlock listesi.
        """
        data = pytesseract.image_to_data(
            image, lang=self.lang, output_type=pytesseract.Output.DICT
        )
        blocks: list[TextBlock] = []
        n = len(data["text"])
        for i in range(n):
            raw = str(data["text"][i]).strip()
            if not raw:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                continue
            x0 = int(data["left"][i])
            y0 = int(data["top"][i])
            x1 = x0 + int(data["width"][i])
            y1 = y0 + int(data["height"][i])
            blocks.append(
                TextBlock(
                    text=raw,
                    bbox=(x0, y0, x1, y1),
                    confidence=conf,
                    language=self.lang,
                )
            )
        return blocks

    def extract_page_text(self, image: Image.Image) -> str:
        """Sayfa görselini tek parça düz metin olarak OCR'lar.

        Args:
            image: OCR uygulanacak sayfa görseli.

        Returns:
            Sayfanın birleşik ham metni.
        """
        return pytesseract.image_to_string(image, lang=self.lang).strip()

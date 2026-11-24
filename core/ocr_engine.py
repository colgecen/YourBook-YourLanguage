"""Tesseract OCR motoru: PDF sayfalarını görselleştirip metin bloklarını çıkarır."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path, pdfinfo_from_path
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

    def _image_to_data(self, image: Image.Image) -> dict:
        """Tesseract'ı bir kez çalıştırıp ham kelime verisini döndürür."""
        return pytesseract.image_to_data(
            image, lang=self.lang, output_type=pytesseract.Output.DICT
        )

    def _word_records(
        self, data: dict
    ) -> list[tuple[int, int, int, int, int, int, int, str, float]]:
        """Ham Tesseract verisini kelime kayitlarina donusturur.

        Returns:
            (block, par, line, x0, y0, x1, y1, text, conf) demetleri.
        """
        records: list[tuple[int, int, int, int, int, int, int, str, float]] = []
        for i in range(len(data["text"])):
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
            records.append(
                (
                    int(data["block_num"][i]),
                    int(data["par_num"][i]),
                    int(data["line_num"][i]),
                    x0,
                    y0,
                    x1,
                    y1,
                    raw,
                    conf,
                )
            )
        return records

    def _blocks_from_records(
        self, records: list[tuple[int, int, int, int, int, int, int, str, float]]
    ) -> list[TextBlock]:
        """Kelime kayitlarindan TextBlock listesi uretir."""
        return [
            TextBlock(
                text=raw, bbox=(x0, y0, x1, y1), confidence=conf, language=self.lang
            )
            for _b, _p, _l, x0, y0, x1, y1, raw, conf in records
        ]

    def pdf_page_count(self, pdf_path: str | Path) -> int:
        """PDF'in toplam sayfa sayisini dondurur."""
        try:
            return int(pdfinfo_from_path(str(pdf_path))["Pages"])
        except Exception as exc:
            raise RuntimeError(
                "PDF sayfa sayisi okunamadi. Poppler kurulu olmali: "
                "Linux'ta 'sudo apt install poppler-utils' (Fedora: 'sudo dnf install poppler-utils'). "
                f"Orijinal hata: {exc}"
            ) from exc

    def iter_pdf_images(
        self,
        pdf_path: str | Path,
        start_page: int = 1,
        end_page: int | None = None,
        chunk_size: int = 8,
    ):
        """PDF sayfalarini bellek dostu sekilde parca parca uretir.

        1000 sayfalik kitaplarda tum sayfalari ayni anda RAM'e yuklememek
        icin poppler her seferinde en fazla ``chunk_size`` sayfa cevirir.

        Args:
            pdf_path: Kaynak PDF dosya yolu.
            start_page: Baslangic sayfasi (1 tabanli, dahil).
            end_page: Bitis sayfasi (1 tabanli, dahil). None ise sonuna kadar.
            chunk_size: Ayni anda cevrilecek sayfa sayisi.

        Yields:
            PIL.Image nesneleri.
        """
        first = max(1, start_page)
        total = self.pdf_page_count(pdf_path)
        last = total if end_page is None else min(max(first, end_page), total)
        current = first
        while current <= last:
            chunk_last = min(current + chunk_size - 1, last)
            try:
                images = convert_from_path(
                    str(pdf_path),
                    dpi=self.dpi,
                    first_page=current,
                    last_page=chunk_last,
                )
            except Exception as exc:
                raise RuntimeError(
                    "pdf2image donusumu basarisiz. Poppler kurulu olmali: "
                    "Windows'ta poppler'i kurup PATH'e ekleyin, "
                    "Linux'ta 'sudo apt install poppler-utils'. "
                    f"Orijinal hata: {exc}"
                ) from exc
            yield from images
            current = chunk_last + 1

    def extract_blocks(self, image: Image.Image) -> list[TextBlock]:
        """Tek bir sayfa görselinden metin bloklarını çıkarır.

        Args:
            image: OCR uygulanacak sayfa görseli.

        Returns:
            Metin, koordinat kutusu ve güven skoru içeren TextBlock listesi.
        """
        data = self._image_to_data(image)
        return self._blocks_from_records(self._word_records(data))

    def extract_text_and_blocks(
        self, image: Image.Image
    ) -> tuple[str, list[TextBlock]]:
        """Tek OCR geçişinde hem paragraf metnini hem kelime kutularını üretir.

        Tesseract'ı iki kez çalıştırmayı önler. Satırlar paragraf içinde
        birleştirilir; satır sonu tireleri kaldırılır.

        Args:
            image: OCR uygulanacak sayfa görseli.

        Returns:
            (paragraflarla ayrılmış metin, TextBlock listesi).
        """
        records = self._word_records(self._image_to_data(image))
        paragraphs: list[str] = []
        for _key, para_group in itertools.groupby(records, key=lambda r: (r[0], r[1])):
            lines: list[str] = []
            for _line_key, line_group in itertools.groupby(para_group, key=lambda r: r[2]):
                lines.append(" ".join(r[7] for r in line_group))
            merged = ""
            for line in lines:
                if not merged:
                    merged = line
                elif merged.endswith("-"):
                    merged = merged[:-1] + line
                else:
                    merged += " " + line
            if merged.strip():
                paragraphs.append(merged.strip())
        return "\n\n".join(paragraphs), self._blocks_from_records(records)

    def extract_page_text(self, image: Image.Image) -> str:
        """Sayfa görselini tek parça düz metin olarak OCR'lar.

        Args:
            image: OCR uygulanacak sayfa görseli.

        Returns:
            Sayfanın birleşik ham metni.
        """
        return pytesseract.image_to_string(image, lang=self.lang).strip()

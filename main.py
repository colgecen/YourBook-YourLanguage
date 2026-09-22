#!/usr/bin/env python3
"""Book PDF Translator & Typesetter - CLI giris noktasi ve pipeline orkestrasyonu."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

from core.cleaner import PageCleaner
from core.ocr_engine import OCREngine
from core.pdf_builder import PDFBuilder
from core.translator import ParagraphTranslator

CHECKPOINT_EVERY = 10


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI argumanlarini ayristirir.

    Args:
        argv: Arguman listesi; None ise sys.argv kullanilir.

    Returns:
        Ayristirilmis argparse.Namespace.
    """
    p = argparse.ArgumentParser(
        description="Taranmis kitap PDF'lerini Turkceye cevirip Garamond ile dizer."
    )
    p.add_argument("--input", required=True, help="Girdi PDF dosya yolu")
    p.add_argument("--output", required=True, help="Cikti PDF dosya yolu")
    p.add_argument("--start-page", type=int, default=1, help="Baslangic sayfasi (1 tabanli)")
    p.add_argument("--end-page", type=int, default=None, help="Bitis sayfasi (1 tabanli, dahil)")
    p.add_argument(
        "--checkpoint",
        default=None,
        help="Checkpoint dosya yolu (varsayilan: cikti yani .checkpoint.json)",
    )
    p.add_argument("--dpi", type=int, default=300, help="OCR DPI cozunurlugu")
    return p.parse_args(argv)


def checkpoint_path_for(output: str) -> Path:
    """Cikti dosyasi icin checkpoint yolu uretir.

    Args:
        output: Cikti PDF yolu.

    Returns:
        .checkpoint.json dosya yolu.
    """
    return Path(str(output) + ".checkpoint.json")


def load_checkpoint(path: Path) -> dict:
    """Checkpoint dosyasini yukler; yoksa bos dict dondurur.

    Args:
        path: Checkpoint dosya yolu.

    Returns:
        Checkpoint verisi.
    """
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_checkpoint(path: Path, data: dict) -> None:
    """Checkpoint dosyasini yazar.

    Args:
        path: Checkpoint dosya yolu.
        data: Yazilacak veri.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run(args: argparse.Namespace) -> Path:
    """Ana pipeline'i calistirir: OCR -> temizle -> cevir -> dizgi.

    Args:
        args: CLI argumanlari.

    Returns:
        Cikti PDF dosya yolu.
    """
    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise FileNotFoundError(f"Girdi PDF bulunamadi: {input_path}")

    ckpt_path = Path(args.checkpoint) if args.checkpoint else checkpoint_path_for(str(output_path))
    ckpt = load_checkpoint(ckpt_path)
    done_pages: set[int] = set(ckpt.get("done_pages", []))
    next_page: int = int(ckpt.get("next_page", args.start_page))

    ocr = OCREngine(dpi=args.dpi, lang="eng")
    cleaner = PageCleaner(method="inpaint")
    translator = ParagraphTranslator(source="en", target="tr")
    builder = PDFBuilder(template_path=input_path)

    start = args.start_page
    end = args.end_page
    images = ocr.pdf_to_images(input_path, start_page=start, end_page=end)
    page_numbers = list(range(start, start + len(images)))

    try:
        for idx, (page_no, image) in enumerate(
            tqdm(list(zip(page_numbers, images)), desc="Sayfalar", unit="sayfa")
        ):
            if page_no < next_page or page_no in done_pages:
                continue

            blocks = ocr.extract_blocks(image)
            bboxes = [b.bbox for b in blocks]
            cleaned_img = cleaner.clean(image, bboxes)

            raw_text = ocr.extract_page_text(image)
            paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
            tr_paragraphs = translator.translate_paragraphs(paragraphs)
            tr_text = "\n\n".join(tr_paragraphs)

            w, h = image.size
            # Piksel -> pt (1 in = 72 pt, PDF varsayilan 72 DPI koordinat)
            scale = 72.0 / float(args.dpi)
            bbox_pt = (0.0, 0.0, w * scale, h * scale)
            # cleaned_img su anlik olarak ileride temiz katman olarak kullanilabilir;
            # mevcut dizgi metni uzerine yazar.
            _ = cleaned_img
            builder.write_page(page_index=idx, text=tr_text, bbox=bbox_pt)

            done_pages.add(page_no)
            next_page = page_no + 1

            if len(done_pages) % CHECKPOINT_EVERY == 0:
                save_checkpoint(
                    ckpt_path,
                    {
                        "input": str(input_path),
                        "output": str(output_path),
                        "next_page": next_page,
                        "done_pages": sorted(done_pages),
                    },
                )

        builder.save(output_path)
        save_checkpoint(
            ckpt_path,
            {
                "input": str(input_path),
                "output": str(output_path),
                "next_page": next_page,
                "done_pages": sorted(done_pages),
                "finished": True,
            },
        )
        return output_path
    finally:
        builder.close()
        translator.close()


def main(argv: list[str] | None = None) -> int:
    """CLI ana fonksiyonu.

    Args:
        argv: Arguman listesi.

    Returns:
        Cikis kodu (0 basari).
    """
    args = parse_args(argv)
    out = run(args)
    print(f"Cikti olusturuldu: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

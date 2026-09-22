#!/usr/bin/env python3
"""Book PDF Translator & Typesetter - CLI giris noktasi ve pipeline orkestrasyonu."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

# pip paketi -> import adi eslemesi (requirements.txt ile ayni sira)
REQUIRED_IMPORTS: tuple[tuple[str, str], ...] = (
    ("pymupdf", "fitz"),
    ("pytesseract", "pytesseract"),
    ("pdf2image", "pdf2image"),
    ("deep-translator", "deep_translator"),
    ("opencv-python-headless", "cv2"),
    ("numpy", "numpy"),
    ("pillow", "PIL"),
    ("reportlab", "reportlab"),
    ("tqdm", "tqdm"),
)

SKIP_AUTO_INSTALL_FLAGS = {"--no-deps", "--skip-deps", "--no-auto-install"}


def requirements_path() -> Path:
    """requirements.txt yolunu dondurur (main.py'nin yani)."""
    return Path(__file__).resolve().parent / "requirements.txt"


def missing_imports() -> list[str]:
    """Kurulu olmayan import adlarini listeler."""
    missing: list[str] = []
    for _pkg, mod in REQUIRED_IMPORTS:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing


def ensure_dependencies() -> None:
    """Eksik pip paketlerini otomatik kurar.

    `--no-deps` / `--skip-deps` verilirse kurulum atlanir. Sistem
    programlari (tesseract, poppler) pip ile kurulamaz; onlar ayrica
    kurulmalidir.
    """
    if any(f in sys.argv for f in SKIP_AUTO_INSTALL_FLAGS):
        return
    missing = missing_imports()
    if not missing:
        return
    req = requirements_path()
    print(f"Eksik bagimliliklar bulundu ({', '.join(missing)}), kuruluyor: {req}")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(req)]
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "Otomatik kurulum basarisiz oldu. Internete bagli oldugunuzdan emin olup "
            f"manuel deneyin: {sys.executable} -m pip install -r {req} "
            f"(hata kodu: {exc.returncode})"
        ) from exc
    # Kurulumdan sonra hala eksik varsa (yanlis env vb.) net hata ver.
    still = missing_imports()
    if still:
        raise SystemExit(
            f"Kurulum tamamlandi ama hala eksik: {', '.join(still)}. "
            f"Kullandiginiz python: {sys.executable}"
        )


ensure_dependencies()

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
    p.add_argument(
        "--no-deps",
        "--skip-deps",
        "--no-auto-install",
        dest="no_deps",
        action="store_true",
        help="Otomatik pip kurulumunu atla (eksik paket varsa hata verir).",
    )
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

    if ckpt.get("finished"):
        print("Checkpoint 'finished' gorunuyor; islem zaten tamamlanmis.")
    # Farkli aralikla tekrar calisirsa eski checkpoint'i ezme.
    if done_pages and (
        ckpt.get("start_page", args.start_page) != args.start_page
        or ckpt.get("end_page", args.end_page) != args.end_page
        or ckpt.get("input") != str(input_path)
    ):
        print(
            "UYARI: checkpoint farkli input/aralik icin; "
            f"kayitli={ckpt.get('input')}:{ckpt.get('start_page')}-{ckpt.get('end_page')} "
            f"istenen={input_path}:{args.start_page}-{args.end_page}. Sifirdan baslaniyor."
        )
        done_pages = set()
        next_page = args.start_page
    # Cikti silinmisse resume anlamsiz: bastan basla.
    if done_pages and not output_path.exists():
        print("UYARI: checkpoint var ama cikti PDF yok; bastan baslaniyor.")
        done_pages = set()
        next_page = args.start_page

    ocr = OCREngine(dpi=args.dpi, lang="eng")
    cleaner = PageCleaner(method="inpaint")
    translator = ParagraphTranslator(source="en", target="tr")
    # resume_path: yari kalmis cikti varsa uzerine devam et.
    resume = str(output_path) if (done_pages and output_path.exists()) else None
    builder = PDFBuilder(template_path=input_path, resume_path=resume)

    start = args.start_page
    end = args.end_page
    images = ocr.pdf_to_images(input_path, start_page=start, end_page=end)
    page_numbers = list(range(start, start + len(images)))

    def _flush() -> None:
        builder.save(output_path)
        save_checkpoint(
            ckpt_path,
            {
                "input": str(input_path),
                "output": str(output_path),
                "start_page": start,
                "end_page": end,
                "next_page": next_page,
                "done_pages": sorted(done_pages),
            },
        )

    try:
        for page_no, image in tqdm(
            list(zip(page_numbers, images)), desc="Sayfalar", unit="sayfa"
        ):
            if page_no < next_page or page_no in done_pages:
                continue

            try:
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
                # Cikti indeksi: sablon sayfa nosu degil, ciktiya gore 0 tabanli.
                # Eskiden idx kullaniliyordu; --start-page >1 iken yanlis sayfaya yaziyordu.
                output_index = page_no - start
                builder.write_page(
                    page_index=output_index,
                    text=tr_text,
                    bbox=bbox_pt,
                    background=cleaned_img,
                )
            except Exception as exc:  # noqa: BLE001 - tek sayfa tum isi devirmesin
                print(f"Sayfa {page_no} atlandi (hata: {exc})", file=sys.stderr)
                continue

            done_pages.add(page_no)
            next_page = page_no + 1

            if len(done_pages) % CHECKPOINT_EVERY == 0:
                _flush()

        builder.save(output_path)
        save_checkpoint(
            ckpt_path,
            {
                "input": str(input_path),
                "output": str(output_path),
                "start_page": start,
                "end_page": end,
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

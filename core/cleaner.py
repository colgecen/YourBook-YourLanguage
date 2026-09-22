"""OpenCV tabanlı görsel temizleme: OCR bounding-box alanlarını arka plana siler."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def pil_to_cv(image: Image.Image) -> np.ndarray:
    """PIL görselini OpenCV BGR numpy dizisine çevirir.

    Args:
        image: Kaynak PIL görseli.

    Returns:
        OpenCV'nin beklediği BGR formatında numpy dizisi.
    """
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def cv_to_pil(image: np.ndarray) -> Image.Image:
    """OpenCV BGR numpy dizisini PIL görseline çevirir.

    Args:
        image: Kaynak BGR dizisi.

    Returns:
        RGB PIL görseli.
    """
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def estimate_background(image: np.ndarray, bbox: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Bounding box çevresinden baski kagidi arka plan rengini tahmin eder.

    Args:
        image: BGR sayfa görseli.
        bbox: (x0, y0, x1, y1) hedef kutu.

    Returns:
        (B, G, R) tuple olarak tahmini arka plan rengi.
    """
    h, w = image.shape[:2]
    x0, y0, x1, y1 = bbox
    margin = 10
    ex0 = max(0, x0 - margin)
    ey0 = max(0, y0 - margin)
    ex1 = min(w, x1 + margin)
    ey1 = min(h, y1 + margin)
    ring = image[ey0:ey1, ex0:ex1].copy()
    # Kutunun icini ringden cikar (yaklasik): basitce dis kenarlik ornegini al
    inner_h = max(1, y1 - y0)
    inner_w = max(1, x1 - x0)
    if ring.shape[0] > inner_h + 2 * margin and ring.shape[1] > inner_w + 2 * margin:
        mask = np.ones(ring.shape[:2], dtype=np.uint8) * 255
        mask[margin:margin + inner_h, margin:margin + inner_w] = 0
        pixels = ring[mask == 255]
    else:
        pixels = ring.reshape(-1, 3)
    if pixels.size == 0:
        pixels = ring.reshape(-1, 3)
    med = np.median(pixels, axis=0)
    return (int(med[0]), int(med[1]), int(med[2]))


class PageCleaner:
    """OCR'dan gelen bounding-box alanlarını sayfa arka planina uygun sekilde siler.

    Varsayilan yöntem cv2.inpaint (doku koruyucu); rectangle yedek yontemdir.
    """

    def __init__(self, method: str = "inpaint", radius: int = 5) -> None:
        """Temizleyiciyi yapilandirir.

        Args:
            method: 'inpaint' veya 'rectangle'.
            radius: Inpaint yaricapi.
        """
        if method not in {"inpaint", "rectangle"}:
            raise ValueError("method 'inpaint' veya 'rectangle' olmali")
        self.method = method
        self.radius = radius

    def clean(self, image: Image.Image, bboxes: list[tuple[int, int, int, int]]) -> Image.Image:
        """Verilen kutulari temizleyip yeni PIL gorseli dondurur.

        Args:
            image: Kaynak sayfa gorseli (PIL).
            bboxes: Silinecek (x0, y0, x1, y1) kutulari.

        Returns:
            Temizlenmis PIL gorseli.
        """
        if not bboxes:
            return image
        canvas = pil_to_cv(image)
        h, w = canvas.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        for bbox in bboxes:
            x0, y0, x1, y1 = bbox
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            mask[y0:y1, x0:x1] = 255

        if self.method == "inpaint":
            cleaned = cv2.inpaint(canvas, mask, self.radius, cv2.INPAINT_TELEA)
        else:
            cleaned = canvas.copy()
            for bbox in bboxes:
                x0, y0, x1, y1 = bbox
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(w, x1), min(h, y1)
                if x1 <= x0 or y1 <= y0:
                    continue
                color = estimate_background(canvas, (x0, y0, x1, y1))
                cv2.rectangle(cleaned, (x0, y0), (x1, y1), color, -1)
        return cv_to_pil(cleaned)

"""deep-translator tabanlı EN→TR çeviri modülü SQLite cache ile."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from deep_translator import GoogleTranslator


class TranslationCache:
    """Tekrar eden metinleri atlamak icin SQLite tabanli ceviri onbellegi."""

    def __init__(self, db_path: str | Path = ".cache/translations.db") -> None:
        """Cache veritabanini acar.

        Args:
            db_path: SQLite dosya yolu.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "src_hash TEXT PRIMARY KEY, src TEXT, dst TEXT, created_at REAL)"
        )
        self._conn.commit()

    @staticmethod
    def _key(text: str) -> str:
        """Metinden SHA-256 anahtari uretir."""
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def get(self, text: str) -> str | None:
        """Metnin cevirisi onbellege sorulur.

        Args:
            text: Kaynak metin.

        Returns:
            Onbellekte varsa ceviri, yoksa None.
        """
        row = self._conn.execute(
            "SELECT dst FROM cache WHERE src_hash = ?", (self._key(text),)
        ).fetchone()
        return row[0] if row else None

    def put(self, src: str, dst: str) -> None:
        """Ceviriyi onbellege yazar.

        Args:
            src: Kaynak metin.
            dst: Cevrilmis metin.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (src_hash, src, dst, created_at) VALUES (?, ?, ?, ?)",
            (self._key(src), src, dst, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        """Veritabagi baglantisini kapatir."""
        self._conn.close()


class ParagraphTranslator:
    """Paragraf bazli EN→TR ceviri; hiz limiti ve tekrarlar icin cache kullanir."""

    def __init__(
        self,
        source: str = "en",
        target: str = "tr",
        cache_path: str | Path = ".cache/translations.db",
        delay: float = 1.0,
        max_retries: int = 3,
        max_chunk: int = 4000,
    ) -> None:
        """Cevirmeni yapilandirir.

        Args:
            source: Kaynak dil kodu.
            target: Hedef dil kodu.
            cache_path: SQLite cache dosya yolu.
            delay: Istekler arasindaki gecikme (saniye).
            max_retries: Ag hatasinda tekrar sayisi.
            max_chunk: Google Translate limiti icin paragraf parcasi (~5000).
        """
        self.source = source
        self.target = target
        self.delay = delay
        self.max_retries = max_retries
        self.max_chunk = max_chunk
        self._translator = GoogleTranslator(source=source, target=target)
        self.cache = TranslationCache(cache_path)

    def _translate_chunk(self, text: str) -> str:
        """Tek istekte cevrilir; rate-limit/ag hatasinda retry yapar."""
        last_err: Exception | None = None
        for attempt in range(max(1, self.max_retries)):
            try:
                return self._translator.translate(text) or ""
            except Exception as exc:  # noqa: BLE001 - ag hatasi tum isi devirmesin
                last_err = exc
                time.sleep(self.delay * (attempt + 1))
        raise RuntimeError(f"Ceviri basarisiz ({self.max_retries} deneme): {last_err}") from last_err

    def translate_paragraph(self, text: str) -> str:
        """Tek bir paragrafi cevirir; onbellekte varsa aga cikmaz.

        Uzun paragraflar max_chunk ile bolunur (Google ~5000 karakter limiti).

        Args:
            text: Kaynak paragraf.

        Returns:
            Turkce ceviri.
        """
        cleaned = text.strip()
        if not cleaned:
            return ""
        hit = self.cache.get(cleaned)
        if hit is not None:
            return hit
        if len(cleaned) > self.max_chunk:
            parts = [
                cleaned[i : i + self.max_chunk]
                for i in range(0, len(cleaned), self.max_chunk)
            ]
            result = " ".join(self._translate_chunk(p) for p in parts)
        else:
            result = self._translate_chunk(cleaned)
        self.cache.put(cleaned, result)
        if self.delay > 0:
            time.sleep(self.delay)
        return result

    def translate_paragraphs(self, paragraphs: list[str]) -> list[str]:
        """Paragraf listesini sirayla cevirir.

        Args:
            paragraphs: Kaynak paragraflar.

        Returns:
            Turkce cevrilmis paragraflar.
        """
        return [self.translate_paragraph(p) for p in paragraphs]

    def close(self) -> None:
        """Cache baglantisini kapatir."""
        self.cache.close()

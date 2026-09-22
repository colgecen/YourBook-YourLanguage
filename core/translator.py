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
    ) -> None:
        """Cevirmeni yapilandirir.

        Args:
            source: Kaynak dil kodu.
            target: Hedef dil kodu.
            cache_path: SQLite cache dosya yolu.
            delay: Istekler arasindaki gecikme (saniye).
        """
        self.source = source
        self.target = target
        self.delay = delay
        self._translator = GoogleTranslator(source=source, target=target)
        self.cache = TranslationCache(cache_path)

    def translate_paragraph(self, text: str) -> str:
        """Tek bir paragrafi cevirir; onbellekte varsa aga cikmaz.

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
        result = self._translator.translate(cleaned) or ""
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

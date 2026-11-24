"""deep-translator tabanlı EN→TR çeviri modülü SQLite cache ile."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from deep_translator import GoogleTranslator, MyMemoryTranslator

# Google'in web arayuzu bazi aglarda 429 donduruyor; bu ucnokta genelde calisir.
GOOGLE_HTTP_ENDPOINT = "https://translate.googleapis.com/translate_a/single"

XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
DEFAULT_CACHE_PATH = XDG_CACHE / "yourbook-yourlanguage" / "translations.db"


class TranslationCache:
    """Tekrar eden metinleri atlamak icin SQLite tabanli ceviri onbellegi."""

    def __init__(self, db_path: str | Path = DEFAULT_CACHE_PATH) -> None:
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

    # MyMemory tek istekte ~500 karakter kabul eder.
    MYMEMORY_MAX_CHARS = 450

    def __init__(
        self,
        source: str = "en",
        target: str = "tr",
        cache_path: str | Path = ".cache/translations.db",
        delay: float = 1.0,
        max_retries: int = 3,
        max_chunk: int = 4000,
        fallback: bool = True,
    ) -> None:
        """Cevirmeni yapilandirir.

        Args:
            source: Kaynak dil kodu.
            target: Hedef dil kodu.
            cache_path: SQLite cache dosya yolu.
            delay: Istekler arasindaki gecikme (saniye).
            max_retries: Ag hatasinda tekrar sayisi.
            max_chunk: Google Translate limiti icin paragraf parcasi (~5000).
            fallback: Google basarisiz olursa MyMemory'ye gec.
        """
        self.source = source
        self.target = target
        self.delay = delay
        self.max_retries = max_retries
        self.max_chunk = max_chunk
        self._translator = GoogleTranslator(source=source, target=target)
        # MyMemory yerel dil kodu ister (en-US, tr-TR); desteklenmeyen ciftlerde kapat.
        fallback_codes = {"en": "en-US", "tr": "tr-TR"}
        self._fallback: MyMemoryTranslator | None = (
            MyMemoryTranslator(
                source=fallback_codes[source], target=fallback_codes[target]
            )
            if fallback and source in fallback_codes and target in fallback_codes
            else None
        )
        self._fallback_warned = False
        self._google_web_disabled = False
        self.cache = TranslationCache(cache_path)

    def _translate_google_http(self, text: str) -> str:
        """Google ceviri ucnoktasini dogrudan kullanir (deep-translator yedegi).

        deep-translator'in HTML arayuzu 429 dondurdugunde devreye girer.
        """
        response = requests.get(
            GOOGLE_HTTP_ENDPOINT,
            params={"client": "gtx", "sl": self.source, "tl": self.target, "dt": "t", "q": text},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if not data or not data[0]:
            return ""
        return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()

    def _translate_chunks_with_fallback(self, text: str) -> str:
        """MyMemory ile parca parca cevirir (500 karakter siniri)."""
        if self._fallback is None:
            return ""
        parts: list[str] = []
        remaining = text.strip()
        while remaining:
            if len(remaining) <= self.MYMEMORY_MAX_CHARS:
                parts.append(remaining)
                break
            cut = remaining.rfind(" ", 0, self.MYMEMORY_MAX_CHARS)
            if cut <= 0:
                cut = self.MYMEMORY_MAX_CHARS
            parts.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        return " ".join(self._fallback.translate(p) or "" for p in parts if p).strip()

    def _translate_chunk(self, text: str) -> str:
        """Tek istekte cevrilir; rate-limit/ag hatasinda retry + yedek yapar."""
        last_err: Exception | None = None
        if not self._google_web_disabled:
            for attempt in range(max(1, self.max_retries)):
                try:
                    return self._translator.translate(text) or ""
                except Exception as exc:  # noqa: BLE001 - ag hatasi tum isi devirmesin
                    last_err = exc
                    if attempt < self.max_retries - 1:
                        time.sleep(self.delay * (attempt + 1))
            # Bu agda HTML arayuzu kalici olarak engelli olabilir; tekrar denemeyi birak.
            self._google_web_disabled = True
            print(
                "UYARI: Google web arayuzu kullanilamadi, alternatif Google ucnoktasina geciliyor.",
                file=sys.stderr,
            )
        # 1) Alternatif Google ucnoktasi (kotasiz, ayni ceviri kalitesi).
        for attempt in range(2):
            try:
                result = self._translate_google_http(text)
                if result:
                    return result
            except Exception as exc:  # noqa: BLE001 - MyMemory'ye dusebiliriz
                last_err = exc
                if attempt == 0:
                    time.sleep(self.delay)
        # 2) Son care: MyMemory (gunluk kotasi dusuk).
        if self._fallback is not None:
            if not self._fallback_warned:
                print(
                    "UYARI: Alternatif Google da basarisiz, MyMemory yedegine geciliyor.",
                    file=sys.stderr,
                )
                self._fallback_warned = True
            try:
                fallback_result = self._translate_chunks_with_fallback(text)
                if fallback_result:
                    return fallback_result
            except Exception as exc:  # noqa: BLE001 - asil hatayi raporla
                last_err = exc
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

    def _chunk_text(self, text: str) -> list[str]:
        """Metni paragraf sinirlarini koruyarak max_chunk'luk parcalara boler."""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= self.max_chunk:
                current = candidate
                continue
            if current:
                chunks.append(current)
            while len(paragraph) > self.max_chunk:
                chunks.append(paragraph[: self.max_chunk])
                paragraph = paragraph[self.max_chunk :]
            current = paragraph
        if current:
            chunks.append(current)
        return chunks or [text.strip()]

    def translate_text(self, text: str) -> str:
        """Bir sayfadaki tum metni az sayida istekle cevirir.

        Paragraflar ``\\n\\n`` ile korunur; Google bir istekte birden fazla
        paragrafi sorunsuz cevirir. Bu, sayfa basina istek sayisini ve
        dolayisiyla bekleme suresini ciddi olcude azaltir.

        Args:
            text: Kaynak metin (paragraflar bos satirla ayrilmis).

        Returns:
            Turkce ceviri.
        """
        cleaned = text.strip()
        if not cleaned:
            return ""
        hit = self.cache.get(cleaned)
        if hit is not None:
            return hit
        chunks = self._chunk_text(cleaned)
        translated: list[str] = []
        for i, chunk in enumerate(chunks):
            translated.append(self._translate_chunk(chunk))
            if self.delay > 0 and i < len(chunks) - 1:
                time.sleep(self.delay)
        result = "\n\n".join(translated)
        self.cache.put(cleaned, result)
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

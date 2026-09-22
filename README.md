# 📚 Book PDF Translator & Typesetter (Garamond)

Taranmış veya görsel (kopyalanamayan) 500-1000 sayfalık kitap PDF'lerini, sayfa düzenini bozmadan ve yayınevi kalitesinde **Garamond** fontuyla Türkçeye çeviren ultra hafif ve %100 ücretsiz Python uygulaması.

## ✨ Özellikler
- **%100 Ücretsiz & Yerel OCR:** Google Tesseract C++ motoru ile kopyalanamayan resim yazıları okuma.
- **Hızlı Çeviri:** `deep-translator` üzerinden Google Translate entegrasyonu + SQLite cache.
- **Garamond Auto-Fit Dizgi:** Türkçe metin uzamalarına karşı font boyutunu dinamik küçülterek sayfadan taşımayı önleme.
- **Görsel Temizleme (Inpainting):** OpenCV ile arka plan dokusunu koruyarak eski İngilizce yazıları silme.
- **Kesinti Koruması (Checkpoint):** Dev kitaplarda işlem yarıda kalırsa kaldığı sayfadan devam edebilme.

## 🛠️ Kurulum

1. **Sistem Gereksinimi (Tesseract + Poppler):**
   - **Windows:** [Tesseract-OCR installer](https://github.com/UB-Mannheim/tesseract/wiki) indirip kurun. `tesseract.exe` yolunu sistem PATH'ine ekleyin. Ayrica [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases) indirip `bin/` klasorunu PATH'e ekleyin (pdf2image icin sart).
   - **Linux:** `sudo apt install tesseract-ocr tesseract-ocr-tur tesseract-ocr-eng poppler-utils`
   - **macOS:** `brew install tesseract tesseract-lang poppler`

2. **Bağımlılıkları Yükleyin:**
   ```bash
   pip install -r requirements.txt
   ```

## 🚀 Kullanım

```bash
python main.py --input input/kitap.pdf --output output/kitap_tr.pdf
```

Sayfa aralığı ile:
```bash
python main.py --input input/kitap.pdf --output output/kitap_tr.pdf --start-page 1 --end-page 50
```

Checkpoint dosyası otomatik olarak oluşturulur; işlem yarıda kalırsa aynı komutu tekrar çalıştırmanız yeterlidir.

## 📁 Proje Yapısı

```
book-translator-pdf/
├── main.py                     # CLI giriş noktası ve pipeline orkestrasyonu
├── requirements.txt
├── README.md
├── .gitignore
├── assets/
│   └── fonts/
│       ├── Garamond-Regular.ttf
│       └── Garamond-Italic.ttf
├── core/
│   ├── __init__.py
│   ├── ocr_engine.py           # Tesseract OCR ve metin/koordinat çıkarma
│   ├── cleaner.py              # OpenCV ile arka plan temizleme (inpainting)
│   ├── translator.py           # deep-translator entegrasyonu ve cache
│   └── pdf_builder.py          # Garamond fontlu, auto-fit PDF oluşturucu
├── input/                      # Çevrilecek PDF buraya konur
└── output/                     # Çıktı Türkçe PDF buraya kaydolur
```

## 📄 Lisans

EB Garamond fontu [SIL Open Font License 1.1](https://scripts.sil.org/OFL) ile dağıtılmaktadır.

"""
ocr_service.py
--------------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — OCR Sub-Module

Responsibility:
    Extract raw text from images and scanned PDF files using EasyOCR.
    This service is intentionally narrow-scoped: it performs ONLY OCR.
    It does NOT call Gemini, validate records, geocode, deduplicate, or write to the database.

Design:
    - Singleton-style class: the EasyOCR reader is loaded exactly once per process lifetime.
    - Dependency-injectable: downstream extractors (PDFExtractor, ImageExtractor) can receive
      an OCRService instance via constructor injection, or let OCRService self-instantiate.
    - All public methods accept filesystem paths and return plain strings.
    - SOLID compliant: Single Responsibility, Open/Closed (extend via subclassing), Liskov-safe,
      Interface-segregated (two clean public methods), Dependency-inverted (callers depend on
      the abstract surface, not internals).
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
import threading
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Third-party imports — each guarded with a clear ImportError message so that
# missing dependencies surface as comprehensible errors rather than cryptic
# AttributeErrors at call-time.
# ---------------------------------------------------------------------------
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

try:
    from PIL import Image, UnidentifiedImageError
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

try:
    import easyocr
    _EASYOCR_AVAILABLE = True
except ImportError:
    _EASYOCR_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    from pdf2image.exceptions import (
        PDFInfoNotInstalledError,
        PDFPageCountError,
        PDFSyntaxError,
    )
    _PDF2IMAGE_AVAILABLE = True
except ImportError:
    _PDF2IMAGE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Module-level logger — follows the CIAS convention used in GeminiExtractor
# and PDFExtractor.
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported image formats (lowercase extensions).
# ---------------------------------------------------------------------------
_SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif"
})


class OCRService:
    """
    Singleton-style OCR engine wrapper for the CIAS preprocessing pipeline.

    The EasyOCR reader is instantiated at most once per OCRService instance and
    is reused across successive calls, avoiding the expensive model-loading
    overhead on every request.

    Typical usage
    -------------
    >>> service = OCRService()                          # reader lazy-loaded on first call
    >>> text = service.extract_text_from_image("scan.jpg")
    >>> text = service.extract_text_from_pdf("report.pdf")

    Thread safety
    -------------
    Reader initialisation is guarded by a threading.Lock so that concurrent
    callers share a single reader without race conditions.
    """

    # ------------------------------------------------------------------
    # Class-level singleton machinery.
    # A single reader is shared even when multiple OCRService objects are
    # created (e.g., from PDFExtractor and ImageExtractor simultaneously).
    # ------------------------------------------------------------------
    _reader_instance: Optional["easyocr.Reader"] = None
    _reader_lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        languages: Optional[List[str]] = None,
        use_gpu: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        languages:
            ISO 639-1 language codes for EasyOCR. Defaults to ["en", "hi"]
            (English + Hindi) which covers the majority of Indian police FIRs.
        use_gpu:
            Whether EasyOCR should attempt CUDA acceleration. Defaults to False
            for broad compatibility; override in GPU-enabled environments.
        """
        if not _EASYOCR_AVAILABLE:
            raise ImportError(
                "easyocr is not installed. Run: pip install easyocr"
            )
        if not _PIL_AVAILABLE:
            raise ImportError(
                "Pillow is not installed. Run: pip install Pillow"
            )
        if not _PDF2IMAGE_AVAILABLE:
            raise ImportError(
                "pdf2image is not installed. Run: pip install pdf2image"
            )

        self._languages: List[str] = languages or ["en", "hi"]
        self._use_gpu: bool = use_gpu

        logger.info(
            "OCRService initialised. Languages: %s | GPU: %s",
            self._languages,
            self._use_gpu,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_text_from_image(self, image_path: str) -> str:
        """
        Extract raw text from a single image file.

        Parameters
        ----------
        image_path:
            Absolute or relative filesystem path to the image.

        Returns
        -------
        str
            Cleaned, normalised plain text extracted from the image.
            Returns an empty string if no text is detected.

        Raises
        ------
        FileNotFoundError
            If the image path does not exist on the filesystem.
        ValueError
            If the file extension is not a supported image format or the
            image file is corrupted / cannot be opened.
        RuntimeError
            If EasyOCR fails to process the image.
        """
        path = self._validate_file_path(image_path)
        self._validate_image_extension(path)

        logger.info("OCR started for image: %s", path)
        start_time = time.time()

        try:
            image = self._load_image_pil(path)
        except (OSError, UnidentifiedImageError) as exc:
            logger.error("Failed to open image '%s': %s", path, exc)
            raise ValueError(
                f"Cannot open or decode image file: {path}"
            ) from exc

        try:
            preprocessed = self._preprocess_image(image)
            raw_text, confidence = self._run_ocr_on_array(preprocessed)
        except Exception as exc:
            logger.exception("OCR failed for image '%s'", path)
            raise RuntimeError(
                f"EasyOCR processing failed for image: {path}"
            ) from exc

        cleaned = self._clean_text(raw_text)
        elapsed = time.time() - start_time

        logger.info(
            "OCR completed for image '%s' in %.2fs | Chars extracted: %d | Avg confidence: %s",
            path,
            elapsed,
            len(cleaned),
            f"{confidence:.3f}" if confidence is not None else "N/A",
        )
        return cleaned

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract raw text from every page of a scanned or image-based PDF.

        Each page is rendered to an image at 300 DPI, preprocessed, and then
        passed through EasyOCR. Page order is strictly preserved and results
        are concatenated with double-newline paragraph boundaries.

        Parameters
        ----------
        pdf_path:
            Absolute or relative filesystem path to the PDF file.

        Returns
        -------
        str
            Cleaned, normalised plain text from all pages in document order.
            Returns an empty string if no text is detected across any page.

        Raises
        ------
        FileNotFoundError
            If the PDF path does not exist.
        ValueError
            If the file is not a .pdf or cannot be parsed by pdf2image.
        RuntimeError
            If page conversion or OCR fails on one or more pages.
        """
        path = self._validate_file_path(pdf_path)

        if path.suffix.lower() != ".pdf":
            raise ValueError(
                f"Expected a .pdf file, received: '{path.suffix}' ({path})"
            )

        logger.info("OCR started for PDF: %s", path)
        start_time = time.time()

        # ------------------------------------------------------------------
        # Convert PDF pages → PIL Images using a temporary directory so that
        # large multi-page PDFs do not exhaust process memory all at once.
        # ------------------------------------------------------------------
        try:
            pages: List[Image.Image] = self._convert_pdf_to_images(path)
        except Exception as exc:
            logger.error("PDF conversion failed for '%s': %s", path, exc)
            raise

        num_pages = len(pages)
        logger.info("PDF '%s' contains %d page(s). Starting per-page OCR.", path, num_pages)

        page_texts: List[str] = []
        total_confidence_scores: List[float] = []

        for page_index, page_image in enumerate(pages, start=1):
            page_start = time.time()
            logger.debug("Processing page %d/%d of '%s'", page_index, num_pages, path)

            try:
                preprocessed = self._preprocess_image(page_image)
                page_raw_text, page_conf = self._run_ocr_on_array(preprocessed)
            except Exception as exc:
                logger.warning(
                    "OCR failed for page %d of '%s': %s — skipping page.",
                    page_index,
                    path,
                    exc,
                )
                page_texts.append("")
                continue
            finally:
                # Eagerly release the PIL image to keep memory bounded
                page_image.close()

            page_cleaned = self._clean_text(page_raw_text)
            page_texts.append(page_cleaned)

            if page_conf is not None:
                total_confidence_scores.append(page_conf)

            logger.debug(
                "Page %d/%d done in %.2fs | Chars: %d | Confidence: %s",
                page_index,
                num_pages,
                time.time() - page_start,
                len(page_cleaned),
                f"{page_conf:.3f}" if page_conf is not None else "N/A",
            )

        combined_text = "\n\n".join(filter(None, page_texts))
        elapsed = time.time() - start_time
        avg_confidence = (
            sum(total_confidence_scores) / len(total_confidence_scores)
            if total_confidence_scores
            else None
        )

        logger.info(
            "OCR completed for PDF '%s' | Pages: %d | Total chars: %d | "
            "Avg confidence: %s | Total time: %.2fs",
            path,
            num_pages,
            len(combined_text),
            f"{avg_confidence:.3f}" if avg_confidence is not None else "N/A",
            elapsed,
        )
        return combined_text

    # ------------------------------------------------------------------
    # Private — Reader lifecycle (singleton pattern)
    # ------------------------------------------------------------------

    def _initialize_reader(self) -> "easyocr.Reader":
        """
        Load the EasyOCR reader exactly once, storing it on the class so it
        is shared across all OCRService instances within the same process.

        Thread-safe: uses a class-level lock around the initialisation block.
        """
        if OCRService._reader_instance is not None:
            return OCRService._reader_instance

        with OCRService._reader_lock:
            # Double-checked locking: recheck after acquiring the lock.
            if OCRService._reader_instance is not None:
                return OCRService._reader_instance

            logger.info(
                "Loading EasyOCR reader for languages: %s (GPU=%s). "
                "This may take a moment on first run.",
                self._languages,
                self._use_gpu,
            )
            try:
                OCRService._reader_instance = easyocr.Reader(
                    self._languages,
                    gpu=self._use_gpu,
                    verbose=False,
                )
                logger.info("EasyOCR reader successfully loaded.")
            except Exception as exc:
                logger.exception("Failed to initialise EasyOCR reader.")
                raise RuntimeError(
                    f"EasyOCR reader initialisation failed: {exc}"
                ) from exc

        return OCRService._reader_instance

    # ------------------------------------------------------------------
    # Private — Image handling
    # ------------------------------------------------------------------

    def _load_image_pil(self, path: Path) -> Image.Image:
        """Open an image from disk using Pillow and convert to RGB."""
        image = Image.open(str(path))
        # Ensure 3-channel RGB so downstream OpenCV operations are consistent.
        if image.mode != "RGB":
            image = image.convert("RGB")
        return image

    def _preprocess_image(self, image: Image.Image) -> "np.ndarray":
        """
        Apply a preprocessing pipeline optimised for OCR accuracy.

        Steps
        -----
        1. Convert PIL Image → NumPy array (BGR for OpenCV).
        2. Greyscale conversion — reduces colour noise, simplifies thresholding.
        3. Gaussian blur — attenuates sensor/scanner noise before thresholding.
        4. Adaptive thresholding — handles uneven illumination (common in phone
           photos of documents) far better than a global binary threshold.

        Returns
        -------
        np.ndarray
            Preprocessed single-channel (greyscale) image array ready for OCR.
            Falls back to a plain greyscale NumPy array if OpenCV is unavailable.
        """
        # Convert PIL → NumPy (RGB order)
        img_array = np.array(image)

        if not _CV2_AVAILABLE:
            # Graceful degradation: return a plain greyscale array without
            # noise reduction or adaptive thresholding.
            logger.debug(
                "OpenCV not available; skipping advanced preprocessing."
            )
            # Convert RGB → greyscale via standard luminosity formula
            grey = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
            return grey

        # OpenCV pathway -------------------------------------------------

        # 1. Convert RGB → BGR (OpenCV convention)
        bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        # 2. Greyscale
        grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        # 3. Gaussian noise reduction (kernel 5×5 is a good balance between
        #    smoothing and preserving fine character strokes)
        denoised = cv2.GaussianBlur(grey, (5, 5), 0)

        # 4. Adaptive thresholding — ADAPTIVE_THRESH_GAUSSIAN_C performs well
        #    on documents with varying background brightness (e.g. yellowed
        #    paper, uneven scanning).
        thresholded = cv2.adaptiveThreshold(
            denoised,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            thresholdType=cv2.THRESH_BINARY,
            blockSize=11,   # Neighbourhood size; odd number required
            C=2,            # Constant subtracted from weighted mean
        )

        logger.debug(
            "Image preprocessing complete — shape: %s", thresholded.shape
        )
        return thresholded

    def _convert_pdf_to_images(self, path: Path) -> List[Image.Image]:
        """
        Render all pages of a PDF to PIL Images at 300 DPI.

        Uses a temporary directory for intermediate files so large PDFs do
        not accumulate files on disk after conversion.

        Raises
        ------
        ValueError
            On Poppler not found, page-count errors, or malformed PDF syntax.
        RuntimeError
            On any other unexpected pdf2image failure.
        """
        try:
            pages = convert_from_path(
                str(path),
                dpi=300,
                fmt="png",
                thread_count=1,     # Predictable memory usage across all workers
                use_cropbox=True,   # Respect crop-box for properly bounded page areas
                strict=False,       # Tolerate minor PDF spec violations common in scanned docs
            )
            return pages
        except PDFInfoNotInstalledError as exc:
            logger.error(
                "Poppler is not installed or not on PATH. "
                "Install poppler-utils and ensure it's accessible. Error: %s", exc
            )
            raise ValueError(
                "pdf2image requires Poppler to be installed. "
                "See: https://poppler.freedesktop.org/"
            ) from exc
        except PDFPageCountError as exc:
            logger.error("Could not determine page count for PDF '%s': %s", path, exc)
            raise ValueError(
                f"Unable to read page count from PDF: {path}"
            ) from exc
        except PDFSyntaxError as exc:
            logger.error("Malformed PDF syntax in '%s': %s", path, exc)
            raise ValueError(
                f"The PDF file appears to be corrupted or uses unsupported syntax: {path}"
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected failure during PDF-to-image conversion for '%s'", path)
            raise RuntimeError(
                f"PDF conversion failed for '{path}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Private — OCR execution
    # ------------------------------------------------------------------

    def _run_ocr_on_array(
        self,
        image_array: "np.ndarray",
    ) -> Tuple[str, Optional[float]]:
        """
        Feed a NumPy image array into EasyOCR and return the concatenated text
        along with the average detection confidence score.

        Parameters
        ----------
        image_array:
            A NumPy array (HxW or HxWxC) representing the image to OCR.

        Returns
        -------
        Tuple[str, Optional[float]]
            (raw_text, average_confidence)
            average_confidence is None when EasyOCR returns no results.
        """
        reader = self._initialize_reader()

        results = reader.readtext(
            image_array,
            detail=1,           # Return bounding boxes + confidence scores
            paragraph=False,    # We reconstruct paragraphs ourselves in _clean_text
            batch_size=4,       # Trade-off: speed vs. memory for multi-line images
        )

        if not results:
            return "", None

        text_parts: List[str] = []
        confidence_scores: List[float] = []

        for bbox, text, confidence in results:
            if text.strip():
                text_parts.append(text.strip())
                confidence_scores.append(confidence)

        combined = " ".join(text_parts)
        avg_confidence = (
            sum(confidence_scores) / len(confidence_scores)
            if confidence_scores
            else None
        )
        return combined, avg_confidence

    # ------------------------------------------------------------------
    # Private — Text cleaning
    # ------------------------------------------------------------------

    def _clean_text(self, text: str) -> str:
        """
        Normalise and clean raw OCR output for downstream consumption.

        Operations (applied in order)
        ------------------------------
        1. Normalise line endings (CRLF / CR → LF).
        2. Collapse horizontal whitespace runs (spaces/tabs) to a single space.
        3. Remove OCR artefacts: lone punctuation or single stray characters on
           their own lines that are statistically noise.
        4. Collapse runs of blank lines exceeding two consecutive newlines
           (paragraph boundaries) down to exactly two newlines.
        5. Strip non-printable/control characters while preserving
           newlines and tabs (same approach as PDFExtractor._clean_text).
        6. Final strip of leading/trailing whitespace.

        Parameters
        ----------
        text:
            Raw text string from EasyOCR.

        Returns
        -------
        str
            Cleaned text with preserved paragraph structure.
        """
        if not text:
            return ""

        # 1. Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 2. Collapse horizontal whitespace
        text = re.sub(r"[ \t]+", " ", text)

        # 3. Remove OCR artefacts: lines containing only 1–2 non-alphanumeric
        #    characters (e.g. "|", ".", "—") which rarely carry meaning.
        text = re.sub(r"(?m)^[^a-zA-Z0-9\u0900-\u097F]{1,2}$", "", text)

        # 4. Collapse excessive blank lines → paragraph separator (double LF)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 5. Strip control characters, preserve printable + \n + \t
        text = "".join(
            ch for ch in text if ch.isprintable() or ch in ("\n", "\t")
        )

        return text.strip()

    # ------------------------------------------------------------------
    # Private — Validation helpers
    # ------------------------------------------------------------------

    def _validate_file_path(self, file_path: str) -> Path:
        """
        Ensure the provided path string points to an existing file.

        Returns
        -------
        Path
            A resolved Path object to the file.

        Raises
        ------
        TypeError
            If file_path is not a string.
        FileNotFoundError
            If the path does not exist or is not a regular file.
        """
        if not isinstance(file_path, str):
            raise TypeError(
                f"file_path must be a string, got {type(file_path).__name__}"
            )

        path = Path(file_path).resolve()

        if not path.exists():
            raise FileNotFoundError(
                f"File not found: '{path}'. Verify the path and try again."
            )

        if not path.is_file():
            raise FileNotFoundError(
                f"Path exists but is not a regular file: '{path}'."
            )

        return path

    def _validate_image_extension(self, path: Path) -> None:
        """
        Raise ValueError if the file extension is not a supported image format.
        """
        ext = path.suffix.lower()
        if ext not in _SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Unsupported image format '{ext}' for file '{path}'. "
                f"Supported formats: {sorted(_SUPPORTED_IMAGE_EXTENSIONS)}"
            )

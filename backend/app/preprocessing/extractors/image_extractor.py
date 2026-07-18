"""
image_extractor.py
------------------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Extractors Sub-Module

Responsibility:
    Extract raw text from image files (JPG, JPEG, PNG, TIFF, BMP, WEBP).
    This class is intentionally narrow-scoped: it validates the image, delegates
    all OCR work to OCRService, applies a light post-processing pass, and returns
    plain text to the caller.

    It does NOT perform Gemini extraction, schema validation, geocoding,
    duplicate detection, or database insertion.

Design:
    - Follows SOLID principles:
        S — Single Responsibility: extraction only, no analysis.
        O — Open/Closed: extend via subclassing; core flow is stable.
        L — Liskov-safe: substitutable wherever a text-extractor is expected.
        I — Interface-segregated: one public method (`extract`) for callers.
        D — Dependency-inverted: OCRService is injected, not hard-wired.
    - Mirrors the structure of PDFExtractor for consistency across the pipeline.
    - Readability layer: Pillow is used to verify the file is a valid, openable
      image before handing the path off to OCRService, giving callers an
      accurate error message rather than a cryptic EasyOCR traceback.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Pillow — used only for lightweight readability validation.
# The actual pixel operations are performed inside OCRService.
# ---------------------------------------------------------------------------
try:
    from PIL import Image, UnidentifiedImageError
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# OCRService — guarded import so the module is safe to load even when OCR
# dependencies are not yet installed (e.g., during unit-test bootstrapping).
# ---------------------------------------------------------------------------
try:
    from app.preprocessing.ocr.ocr_service import OCRService
except ImportError:
    OCRService = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported image extensions — the intersection of what Pillow, OpenCV, and
# EasyOCR can reliably handle.  Kept in sync with OCRService's own constant.
# ---------------------------------------------------------------------------
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
})


class ImageExtractor:
    """
    Extracts raw text from image files by delegating OCR to ``OCRService``.

    Typical usage
    -------------
    >>> extractor = ImageExtractor()
    >>> text = extractor.extract("/path/to/scan.jpg")

    Dependency injection
    --------------------
    Pass an existing ``OCRService`` instance to share the already-loaded
    EasyOCR reader across the pipeline (avoids reloading the heavyweight model):

    >>> shared_ocr = OCRService()
    >>> extractor  = ImageExtractor(ocr_service=shared_ocr)

    Supported formats
    -----------------
    JPG / JPEG, PNG, TIFF / TIF, BMP, WEBP.
    """

    def __init__(self, ocr_service: Optional["OCRService"] = None) -> None:
        """
        Parameters
        ----------
        ocr_service:
            An optional pre-initialised ``OCRService`` instance.  When omitted,
            a new instance is created automatically if OCRService is importable.
            If neither is available, ``extract`` will raise ``RuntimeError``.
        """
        self.ocr_service = ocr_service

        # Auto-create OCRService only when a valid class reference is available.
        if self.ocr_service is None and OCRService is not None:
            self.ocr_service = OCRService()

        if self.ocr_service is None:
            logger.warning(
                "ImageExtractor initialised without a functional OCRService. "
                "OCR dependencies may be missing. Calls to extract() will fail."
            )
        else:
            logger.info("ImageExtractor initialised with OCRService.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, file_path: str) -> str:
        """
        Extract raw text from a single image file.

        Execution flow
        --------------
        1. Validate ``file_path`` (existence, extension, readability).
        2. Delegate OCR to ``OCRService.extract_text_from_image()``.
        3. Apply a post-processing pass via ``_clean_text()``.
        4. Log summary metrics and return the cleaned string.

        Parameters
        ----------
        file_path:
            Absolute or relative filesystem path to the image file.

        Returns
        -------
        str
            Cleaned, normalised plain text extracted from the image.
            An empty string is returned when no text is detected.

        Raises
        ------
        FileNotFoundError
            If the file does not exist on the filesystem.
        ValueError
            If the extension is unsupported or Pillow cannot decode the image.
        RuntimeError
            If OCRService is unavailable or EasyOCR fails internally.
        """
        start_time = time.time()
        logger.info("ImageExtractor: starting extraction for: %s", file_path)

        # Step 1 — Validate before touching OCR (fail fast, clear errors).
        path = self._validate_image(file_path)

        # Step 2 — Ensure OCRService is ready.
        if not self.ocr_service:
            raise RuntimeError(
                "OCRService is not available. Ensure easyocr, pdf2image, and "
                "Pillow are installed, and that OCRService can be imported."
            )

        # Step 3 — Delegate OCR (OCRService owns all pixel-level operations).
        try:
            logger.debug(
                "ImageExtractor: delegating OCR to OCRService for '%s'.", path
            )
            raw_text: str = self.ocr_service.extract_text_from_image(str(path))
        except (FileNotFoundError, ValueError):
            # Re-raise structured errors from OCRService as-is; they already
            # carry descriptive messages.
            raise
        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception(
                "ImageExtractor: unexpected error during OCR for '%s'.", path
            )
            raise RuntimeError(
                f"Unexpected OCR failure while processing image: {path}"
            ) from exc

        # Step 4 — Post-process (light normalisation on top of OCRService's cleaning).
        cleaned_text: str = self._clean_text(raw_text)

        elapsed = time.time() - start_time

        if not cleaned_text:
            logger.warning(
                "ImageExtractor: extraction yielded no recognisable text for '%s'.", path
            )
        else:
            logger.info(
                "ImageExtractor: extraction complete for '%s' | "
                "Chars: %d | Time: %.2fs",
                path,
                len(cleaned_text),
                elapsed,
            )

        return cleaned_text

    # ------------------------------------------------------------------
    # Private — Validation
    # ------------------------------------------------------------------

    def _validate_image(self, file_path: str) -> Path:
        """
        Validate that ``file_path`` points to a readable, supported image file.

        Checks performed
        ----------------
        1. ``file_path`` is a non-empty string.
        2. The path resolves to an existing regular file.
        3. The file extension is a supported image format.
        4. Pillow can successfully open the file (detects corruption early,
           before OCR resources are allocated).

        Parameters
        ----------
        file_path:
            Raw string path supplied by the caller.

        Returns
        -------
        Path
            Resolved ``pathlib.Path`` object to the validated image.

        Raises
        ------
        TypeError
            If ``file_path`` is not a string.
        FileNotFoundError
            If the path does not exist or is not a regular file.
        ValueError
            If the extension is not supported or the file cannot be decoded
            as an image by Pillow.
        """
        # --- Type check ------------------------------------------------
        if not isinstance(file_path, str):
            raise TypeError(
                f"file_path must be a string, got {type(file_path).__name__}."
            )

        if not file_path.strip():
            raise ValueError("file_path must not be an empty string.")

        # --- Existence check -------------------------------------------
        path = Path(file_path).resolve()

        if not path.exists():
            logger.error(
                "ImageExtractor: file not found: '%s'.", path
            )
            raise FileNotFoundError(
                f"Image file not found: '{path}'. Verify the path and try again."
            )

        if not path.is_file():
            logger.error(
                "ImageExtractor: path is not a regular file: '%s'.", path
            )
            raise FileNotFoundError(
                f"Path exists but is not a regular file: '{path}'."
            )

        # --- Extension check -------------------------------------------
        ext = path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            logger.error(
                "ImageExtractor: unsupported extension '%s' for file '%s'.",
                ext,
                path,
            )
            raise ValueError(
                f"Unsupported image format '{ext}'. "
                f"Supported formats: {sorted(_SUPPORTED_EXTENSIONS)}"
            )

        # --- Readability check (Pillow probe) --------------------------
        # We verify the image is openable here so downstream OCR gets a
        # clean input; Pillow is far cheaper to spin up than EasyOCR.
        if _PIL_AVAILABLE:
            try:
                with Image.open(str(path)) as probe:
                    probe.verify()  # Reads enough bytes to detect corruption
            except UnidentifiedImageError as exc:
                logger.error(
                    "ImageExtractor: file '%s' could not be identified as an "
                    "image by Pillow: %s",
                    path,
                    exc,
                )
                raise ValueError(
                    f"File is not a recognisable image: '{path}'."
                ) from exc
            except (OSError, SyntaxError) as exc:
                logger.error(
                    "ImageExtractor: file '%s' appears to be corrupted: %s",
                    path,
                    exc,
                )
                raise ValueError(
                    f"Image file appears to be corrupted or truncated: '{path}'."
                ) from exc
        else:
            # Pillow not available — skip the deep probe; OCRService will
            # surface any issues when it attempts to open the file.
            logger.debug(
                "ImageExtractor: Pillow not available; skipping readability probe for '%s'.",
                path,
            )

        logger.debug("ImageExtractor: validation passed for '%s'.", path)
        return path

    # ------------------------------------------------------------------
    # Private — Text cleaning
    # ------------------------------------------------------------------

    def _clean_text(self, text: str) -> str:
        """
        Apply a post-processing normalisation pass on the raw OCR output.

        This is a lightweight complement to the cleaning already performed
        inside ``OCRService._clean_text()``.  It is intentionally idempotent —
        running it on already-clean text will not alter the result.

        Operations (applied in order)
        ------------------------------
        1. Early-exit on empty / whitespace-only input.
        2. Normalise line endings (CRLF / CR → LF).
        3. Collapse horizontal whitespace runs (spaces / tabs) to a single
           space — eliminates wide gaps common in scanned table layouts.
        4. Remove 1–2-character noise lines (e.g. lone ``|``, ``.``, ``—``)
           that are statistically artefacts of OCR on ruled forms.
        5. Collapse runs of three or more consecutive blank lines down to
           exactly two (paragraph boundary convention used across CIAS).
        6. Strip non-printable control characters while preserving ``\n``
           and ``\t`` (consistent with ``PDFExtractor._clean_text``).
        7. Final strip of leading / trailing whitespace.

        Parameters
        ----------
        text:
            Raw or partially-cleaned string from OCRService.

        Returns
        -------
        str
            Cleaned text with paragraph structure preserved.
        """
        if not text or not text.strip():
            return ""

        # 1. Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 2. Collapse horizontal whitespace
        text = re.sub(r"[ \t]+", " ", text)

        # 3. Strip lone-character noise lines (covers common OCR symbols and
        #    Devanagari-range characters used for Hindi script support)
        text = re.sub(r"(?m)^[^a-zA-Z0-9\u0900-\u097F]{1,2}$", "", text)

        # 4. Collapse excessive blank lines → paragraph separator
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 5. Remove non-printable control characters; keep \n and \t
        text = "".join(
            ch for ch in text if ch.isprintable() or ch in ("\n", "\t")
        )

        return text.strip()

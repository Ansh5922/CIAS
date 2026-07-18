import os
import time
import logging
import re
from typing import Optional

# Requires `pip install PyMuPDF` (imported as fitz)
import fitz 

logger = logging.getLogger(__name__)

# Safely attempt to import OCRService. 
# Depending on CIAS module structure, this provides strong typing while avoiding import crashes.
try:
    from app.preprocessing.ocr.ocr_service import OCRService
except ImportError:
    # We will handle the fallback dynamically in __init__ if missing
    OCRService = None


class PDFExtractor:
    """
    Service specifically responsible for extracting raw text from PDF documents.
    Implements a fast-path for digitally generated PDFs (selectable text) 
    and a fallback path delegating to OCR for scanned/image-based PDFs.
    """

    def __init__(self, ocr_service=None):
        """
        Initializes the PDFExtractor.
        Utilizes Dependency Injection for OCRService to uphold SOLID (Open-Closed and Single Responisbility).
        """
        self.ocr_service = ocr_service
        
        # Automatically instantiate OCRService if none is provided but the import was successful
        if self.ocr_service is None and OCRService is not None:
             self.ocr_service = OCRService()

    def extract(self, file_path: str) -> str:
        """
        Main lifecycle method to extract text.
        Returns the unified raw text string representing the document payload.
        """
        start_time = time.time()
        logger.info(f"Starting PDF extraction for: {file_path}")

        if not os.path.exists(file_path):
            error_msg = f"The file path requested does not exist: {file_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        document = None
        try:
            document = fitz.open(file_path)
            num_pages = len(document)
            logger.info(f"Successfully opened PDF: {file_path} containing {num_pages} pages.")

            if num_pages == 0:
                logger.warning(f"The requested PDF is entirely empty (0 pages): {file_path}")
                return ""

            if self._has_extractable_text(document):
                logger.debug("PDF determined to contain digital, selectable text. Bypassing OCR.")
                raw_text = self._extract_text(document)
            else:
                logger.info("PDF determined to be image-based/scanned. Delegating to OCRService.")
                if not self.ocr_service:
                    raise RuntimeError(
                        "OCR is required for this PDF, but OCRService is not injected or available."
                    )
                # Delegate entirely to the OCR Service module
                raw_text = self.ocr_service.extract_text_from_pdf(file_path)
                
            cleaned_text = self._clean_text(raw_text)
            
            if not cleaned_text:
                logger.warning(f"Complete extraction lifecycle yielded no recognizable text for {file_path}.")

            return cleaned_text

        except fitz.FileDataError as e:
            logger.error(f"Incomplete, malformed, or corrupted PDF structure bypassed PyMuPDF: {file_path}. Error: {e}")
            raise ValueError(f"Corrupted or invalid PDF file: {file_path}") from e
            
        except Exception as e:
            logger.exception(f"An unexpected error blocked extraction whilst processing PDF: {file_path}")
            raise
            
        finally:
            if document is not None:
                document.close()
            duration = time.time() - start_time
            logger.info(f"Extraction pipeline for {file_path} terminated in {duration:.2f} seconds.")

    def _has_extractable_text(self, document: fitz.Document, sample_pages: int = 3, min_expected_string_length: int = 50) -> bool:
        """
        Evaluates a sample set from the document to deduce if it contains an underlying text layer.
        """
        pages_to_check = min(len(document), sample_pages)
        aggregated_length = 0
        
        for index in range(pages_to_check):
            page_text = document[index].get_text("text")
            aggregated_length += len(page_text.strip())
            
            if aggregated_length >= min_expected_string_length:
                return True
                
        return False

    def _extract_text(self, document: fitz.Document) -> str:
        """
        Scavenges the document page by page in standard top-to-bottom sequence 
        retrieving the literal digital text strings encoded directly in the PDF.
        """
        text_blocks = []
        for index in range(len(document)):
            page_text = document[index].get_text("text")
            if page_text:
                text_blocks.append(page_text)
        
        # Double carriage break isolates distinct pages cleanly during parsing
        return "\n\n".join(text_blocks)

    def _clean_text(self, text: str) -> str:
        """
        Applies a unified scrubbing operation.
        Designed specifically to safeguard contextual boundaries like paragraphs 
        whilst aggressively deleting spacing/unicode anomalies.
        """
        if not text:
            return ""
            
        # 1. Normalize linebreaks (e.g. carriage returns) to standardize UNIX formats
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # 2. Squash multi-space padding artifacts typical in justified PDF layouts
        text = re.sub(r'[ \t]+', ' ', text)
        
        # 3. Collapse extreme whitespace canyons directly into double-breaks (Paragraph semantic boundaries)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 4. Exterminate junk control characters (NUL, SYN, etc.) keeping visible formatting
        text = "".join(ch for ch in text if ch.isprintable() or ch in ('\n', '\t'))

        # Strip remaining edges
        return text.strip()

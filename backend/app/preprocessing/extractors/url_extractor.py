"""
url_extractor.py
----------------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Extractors Sub-Module

Responsibility:
    Extract clean, readable main article text from a public web URL.
    This class is narrow-scoped: it downloads the remote HTML page (preferring
    newspaper3k, falling back to requests + BeautifulSoup), strips layout and
    interstitial noise (ads, scripts, stylesheets, sidebars, navigation bars),
    and returns plain text.

    It does NOT perform:
        - Gemini LLM extraction (handled by GeminiExtractor)
        - Schema validation (handled by the validation layer)
        - Geocoding, deduplication, or database insertion

Design:
    - Follows SOLID principles:
        S — Single Responsibility: URL loading and article text extraction only.
        O — Open/Closed: extensible extraction engines and clean filters.
        L — Liskov-safe: drop-in replaceable wherever URL-based text extraction is needed.
        I — Interface-segregated: simple clean public API containing only `extract()`.
        D — Injects configuration (timeout and headers) and uses fallback libraries if primary is missing.
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse
from typing import Optional, Dict, Any

# ---------------------------------------------------------------------------
# Third-party imports with fallback guards
# ---------------------------------------------------------------------------
try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

try:
    import newspaper
    # Ensure newspaper is fully functional
    _NEWSPAPER_AVAILABLE = True
except ImportError:
    _NEWSPAPER_AVAILABLE = False

logger = logging.getLogger(__name__)


class URLExtractor:
    """
    Extracts high-quality main story/article text from web pages.
    
    Implements a multi-engine layout:
      - Engine A: newspaper3k (specialised article scraper/extractor)
      - Engine B: requests + BeautifulSoup (reliable, low-overhead HTML parser fallback)
      
    Typical usage:
    --------------
    >>> extractor = URLExtractor(timeout=10)
    >>> article_text = extractor.extract("https://example.com/news-story")
    """

    def __init__(self, timeout: int = 15, headers: Optional[Dict[str, str]] = None) -> None:
        """
        Parameters
        ----------
        timeout:
            Max seconds to wait for network responses. Defaults to 15 seconds.
        headers:
            HTTP headers to pass during page request. Mimics a standard web browser
            by default to reduce site scraping blocks.
        """
        self.timeout = timeout
        self.headers = headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        logger.info(
            "URLExtractor initialised | timeout: %d | newspaper3k available: %s | "
            "BeautifulSoup available: %s",
            self.timeout,
            _NEWSPAPER_AVAILABLE,
            _BS4_AVAILABLE,
        )

    def extract(self, url: str) -> str:
        """
        Validate URL, download the content, extract clean main text, and return it.

        Parameters
        ----------
        url:
            Target http/https website address.

        Returns
        -------
        str
            Cleaned, normalized plain text representing the article or page main body.

        Raises
        ------
        ValueError
            If URL format validation fails or extracted text is empty.
        TimeoutError
            If download requests time out.
        RuntimeError
            If connection fails, returned HTTP error status is encountered, or
            no extractors are available.
        """
        start_time = time.time()
        logger.info("URLExtractor: starting extraction for URL: %s", url)

        # 1. Validate URL
        self._validate_url(url)

        raw_text = ""
        newspaper_success = False

        # 2. Try primary engine: newspaper3k
        if _NEWSPAPER_AVAILABLE:
            try:
                raw_text = self._extract_with_newspaper(url)
                if raw_text.strip():
                    newspaper_success = True
                    logger.debug("URLExtractor: successfully extracted content using newspaper3k.")
            except Exception as exc:
                logger.warning(
                    "URLExtractor: newspaper3k extraction failed for '%s'. "
                    "Attempting fallback parser. Error details: %s",
                    url,
                    exc,
                )

        # 3. Fallback engine: Requests + BeautifulSoup
        if not newspaper_success:
            if not _REQUESTS_AVAILABLE or not _BS4_AVAILABLE:
                missing_deps = []
                if not _REQUESTS_AVAILABLE:
                    missing_deps.append("requests")
                if not _BS4_AVAILABLE:
                    missing_deps.append("BeautifulSoup4")
                raise RuntimeError(
                    f"Core extraction failed (newspaper3k unavailable/failed) and "
                    f"fallback dependency libraries ({', '.join(missing_deps)}) are missing."
                )

            logger.info("URLExtractor: downloading HTML via Requests for parsing: %s", url)
            html_content = self._download_page(url)
            
            raw_text = self._extract_with_beautifulsoup(html_content)

        # 4. Post-extraction text normalization
        cleaned_text = self._clean_text(raw_text)

        if not cleaned_text.strip():
            logger.error("URLExtractor: extraction yielded empty content for URL: %s", url)
            raise ValueError(f"Extracted content is empty or contains no readable text: '{url}'")

        elapsed = time.time() - start_time
        logger.info(
            "URLExtractor: extraction completed for '%s' in %.2f seconds | Chars: %d",
            url,
            elapsed,
            len(cleaned_text),
        )
        return cleaned_text

    def _validate_url(self, url: str) -> None:
        """
        Verify that the URL string is formed correctly and uses http/https.

        Raises
        ------
        ValueError
            If URL format validation fails.
        """
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string.")

        stripped_url = url.strip()
        try:
            parsed = urlparse(stripped_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(f"URL is missing scheme or host address: '{stripped_url}'")
            if parsed.scheme.lower() not in ("http", "https"):
                raise ValueError(
                    f"Unsupported URL protocol scheme '{parsed.scheme}'. Only http and https are permitted."
                )
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Invalid URL formatting '{url}': {exc}") from exc

    def _extract_with_newspaper(self, url: str) -> str:
        """
        Invoke newspaper3k to download and extract main article details.
        """
        if not _NEWSPAPER_AVAILABLE:
            raise RuntimeError("newspaper3k package is not importable.")

        # Create Article object with our customised configuration parameters
        article = newspaper.Article(
            url,
            request_timeout=self.timeout,
            headers=self.headers,
            keep_article_html=False,
        )
        article.download()
        article.parse()
        
        return article.text

    def _download_page(self, url: str) -> str:
        """
        Download the web page using requests, handling status codes and timeouts.
        """
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError("requests package is not importable.")

        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.Timeout as exc:
            logger.error("URLExtractor: request timed out for '%s'.", url)
            raise TimeoutError(f"HTTP connection/request timed out for: '{url}'") from exc
        except requests.HTTPError as exc:
            status_code = exc.response.status_code
            logger.error("URLExtractor: HTTP error %d returned for '%s'.", status_code, url)
            if status_code == 404:
                raise ValueError(f"Remote document not found (404) at: '{url}'") from exc
            elif status_code >= 500:
                raise RuntimeError(
                    f"Remote server encountered internal error ({status_code}) at: '{url}'"
                ) from exc
            else:
                raise RuntimeError(f"HTTP load failure (Status: {status_code}) for: '{url}'") from exc
        except requests.RequestException as exc:
            logger.error("URLExtractor: network connection exception for '%s': %s", url, exc)
            raise RuntimeError(f"Failed to fetch content from URL: '{url}'. Error: {exc}") from exc

    def _extract_with_beautifulsoup(self, html_content: str) -> str:
        """
        Parse raw HTML content via BeautifulSoup and parse page elements down to readable article text.
        """
        if not _BS4_AVAILABLE:
            raise RuntimeError("BeautifulSoup4 package is not importable.")

        soup = BeautifulSoup(html_content, "html.parser")

        # Decompose interactive elements, ads, nav panels, scripts, styles
        unwanted_elements = [
            "script", "style", "nav", "footer", "header", "aside", 
            "form", "iframe", "noscript", "svg", "audio", "video", 
            "button", "input", "textarea", "select", "option", "label",
            "dialog", "menu"
        ]
        for tag in soup.find_all(unwanted_elements):
            tag.decompose()

        # Isolate semantic body wrappers if possible
        main_body = None
        for wrapper in ("article", "main"):
            found = soup.find(wrapper)
            if found:
                main_body = found
                break

        if not main_body:
            main_body = soup.body if soup.body else soup

        # Extract text blocks from structural layout elements
        text_blocks = []
        body_elements = main_body.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"])

        for element in body_elements:
            element_text = element.get_text().strip()
            if element_text:
                text_blocks.append(element_text)

        # Base case fallback: pull all raw string segments if tag matches are empty
        if not text_blocks:
            return main_body.get_text()

        return "\n\n".join(text_blocks)

    def _clean_text(self, text: str) -> str:
        """
        Remove layouts and horizontal spaces, preserving distinct paragraph block lines.
        """
        if not text:
            return ""

        # Normalize carriage returns (CRLF / CR -> LF)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")

        # Clean spaces and tabs
        normalized = re.sub(r"[ \t]+", " ", normalized)

        # Collapse excess empty lines down to double spacing for paragraphing
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)

        # Filter to printable characters + structural layout chars
        clean_chars = [
            ch for ch in normalized if ch.isprintable() or ch in ("\n", "\t")
        ]
        
        return "".join(clean_chars).strip()

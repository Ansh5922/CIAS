"""
csv_extractor.py
----------------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Extractors Sub-Module

Responsibility:
    Read structured tabular data from CSV and Excel (.xlsx / .xls) files,
    normalise column names to the CIAS CrimeRecord field schema, clean raw
    cell values, and return a list of plain Python dicts ready for downstream
    consumption — either direct CrimeRecord construction or passage to the
    Gemini extraction pipeline.

    This class does NOT perform:
        - OCR (handled by OCRService / ImageExtractor / PDFExtractor)
        - Gemini LLM extraction (handled by GeminiExtractor)
        - Schema validation (handled by the validation layer)
        - Geocoding, deduplication, or database insertion

Design:
    - Follows SOLID principles:
        S — Single Responsibility: tabular ingestion and normalisation only.
        O — Open/Closed: column alias map and required-column set are class
            attributes; extend via subclassing without touching core logic.
        L — Liskov-safe: substitutable wherever a list-of-dict extractor is needed.
        I — Interface-segregated: callers use only `extract(file_path)`.
        D — No hard external dependencies beyond pandas; no service injection needed.
    - Mirrors the logging style of PDFExtractor and GeminiExtractor for pipeline
      consistency.
    - Encoding auto-detection via chardet (optional) with a safe fallback chain
      when chardet is not installed.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# pandas — core dependency; hard-fail with a clear message if missing.
# ---------------------------------------------------------------------------
try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False

# ---------------------------------------------------------------------------
# openpyxl / xlrd are used by pandas under the hood for .xlsx / .xls.
# We probe for them here so that missing-engine errors are surfaced early
# with an actionable install instruction rather than a confusing pandas traceback.
# ---------------------------------------------------------------------------
try:
    import openpyxl  # noqa: F401  — .xlsx engine
    _OPENPYXL_AVAILABLE = True
except ImportError:
    _OPENPYXL_AVAILABLE = False

try:
    import xlrd  # noqa: F401  — legacy .xls engine
    _XLRD_AVAILABLE = True
except ImportError:
    _XLRD_AVAILABLE = False

# ---------------------------------------------------------------------------
# chardet — optional; used for encoding sniffing on CSV files.
# ---------------------------------------------------------------------------
try:
    import chardet
    _CHARDET_AVAILABLE = True
except ImportError:
    _CHARDET_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported file extensions.
# ---------------------------------------------------------------------------
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".xlsx", ".xls"})

# ---------------------------------------------------------------------------
# Encoding fallback chain for CSV files.
# pandas will be tried with each encoding in order until one succeeds.
# ---------------------------------------------------------------------------
_CSV_ENCODING_FALLBACKS: tuple[str, ...] = (
    "utf-8",
    "utf-8-sig",   # UTF-8 with BOM (common in Windows-exported CSVs)
    "latin-1",     # ISO-8859-1 — covers most Western European characters
    "cp1252",      # Windows-1252 — common in Indian administrative exports
    "ascii",
)


class CSVExtractor:
    """
    Extracts structured records from CSV and Excel files for the CIAS pipeline.

    Each row is returned as a plain Python dict whose keys are normalised
    CIAS field names (e.g. ``fir_number``, ``crime_type``, ``incident_date``).
    Values have whitespace stripped and empty strings replaced with ``None``.

    Typical usage
    -------------
    >>> extractor = CSVExtractor()
    >>> records = extractor.extract("/path/to/fir_data.csv")
    >>> print(records[0])
    {'fir_number': 'FIR-001', 'crime_type': 'Theft', 'incident_date': '2024-01-15', ...}

    Subclassing / customisation
    ---------------------------
    Override ``COLUMN_ALIAS_MAP`` to add organisation-specific column aliases,
    or override ``REQUIRED_COLUMNS`` to enforce a different set of mandatory
    fields for your deployment.
    """

    # ------------------------------------------------------------------
    # Class-level configuration — override via subclassing (Open/Closed).
    # ------------------------------------------------------------------

    #: Maps raw column header variants (case-insensitive, stripped) to the
    #: canonical CIAS CrimeRecord field name.  Covers common aliases used
    #: across Indian police FIR formats, NCRB exports, and generic CSV dumps.
    COLUMN_ALIAS_MAP: Dict[str, str] = {
        # Case identifiers
        "fir no":               "fir_number",
        "fir number":           "fir_number",
        "fir no.":              "fir_number",
        "fir_no":               "fir_number",
        "first information report number": "fir_number",
        "case no":              "case_number",
        "case number":          "case_number",
        "case no.":             "case_number",
        "case_no":              "case_number",

        # Crime classification
        "crime type":           "crime_type",
        "crime_type":           "crime_type",
        "type of crime":        "crime_type",
        "offence type":         "crime_type",
        "offense type":         "crime_type",
        "nature of crime":      "crime_type",
        "crime category":       "crime_category",
        "crime_category":       "crime_category",
        "category":             "crime_category",
        "ipc section":          "ipc_sections",
        "ipc sections":         "ipc_sections",
        "ipc_section":          "ipc_sections",
        "section":              "ipc_sections",
        "bns section":          "bns_sections",
        "bns sections":         "bns_sections",
        "bns_section":          "bns_sections",
        "status":               "status",
        "case status":          "status",
        "investigation status": "status",

        # Temporal
        "date":                 "incident_date",
        "incident date":        "incident_date",
        "incident_date":        "incident_date",
        "date of incident":     "incident_date",
        "date of occurrence":   "incident_date",
        "occurrence date":      "incident_date",
        "date of crime":        "incident_date",
        "time":                 "incident_time",
        "incident time":        "incident_time",
        "incident_time":        "incident_time",
        "time of incident":     "incident_time",
        "report date":          "report_date",
        "report_date":          "report_date",
        "date reported":        "report_date",
        "date of report":       "report_date",
        "date of filing":       "report_date",

        # Location
        "address":              "address",
        "location":             "address",
        "place of occurrence":  "address",
        "place of incident":    "address",
        "locality":             "locality",
        "area":                 "area",
        "police station":       "police_station",
        "police_station":       "police_station",
        "ps":                   "police_station",
        "thana":                "police_station",
        "district":             "district",
        "dist":                 "district",
        "state":                "state",
        "country":              "country",
        "pin":                  "postal_code",
        "pincode":              "postal_code",
        "postal code":          "postal_code",
        "zip":                  "postal_code",
        "zone":                 "zone",
        "landmark":             "landmark",

        # Victim
        "victim name":          "victim_name",
        "victim_name":          "victim_name",
        "name of victim":       "victim_name",
        "victim age":           "victim_age",
        "victim_age":           "victim_age",
        "victim gender":        "victim_gender",
        "victim_gender":        "victim_gender",
        "victim address":       "victim_address",
        "victim_address":       "victim_address",
        "victim phone":         "victim_phone",
        "victim_phone":         "victim_phone",

        # Suspect / Accused
        "suspect name":         "suspect_name",
        "suspect_name":         "suspect_name",
        "accused name":         "suspect_name",
        "accused_name":         "suspect_name",
        "name of accused":      "suspect_name",
        "suspect age":          "suspect_age",
        "suspect_age":          "suspect_age",
        "suspect gender":       "suspect_gender",
        "suspect_gender":       "suspect_gender",
        "suspect address":      "suspect_address",
        "suspect_address":      "suspect_address",

        # Officer
        "officer name":         "officer_name",
        "officer_name":         "officer_name",
        "investigating officer": "officer_name",
        "io name":              "officer_name",
        "officer rank":         "officer_rank",
        "officer_rank":         "officer_rank",
        "badge number":         "officer_badge",
        "badge no":             "officer_badge",

        # Narrative
        "description":          "description",
        "details":              "description",
        "incident details":     "description",
        "crime details":        "description",
        "modus operandi":       "modus_operandi",
        "modus_operandi":       "modus_operandi",
        "mo":                   "modus_operandi",
        "motive":               "motive",
        "remarks":              "remarks",
        "notes":                "remarks",
        "comments":             "remarks",

        # Weapon
        "weapon":               "weapon_type",
        "weapon type":          "weapon_type",
        "weapon_type":          "weapon_type",
        "weapon used":          "weapon_type",
        "arms used":            "weapon_type",

        # Vehicle
        "vehicle":              "vehicle_registration",
        "vehicle number":       "vehicle_registration",
        "vehicle no":           "vehicle_registration",
        "registration number":  "vehicle_registration",
        "vehicle type":         "vehicle_type",
        "vehicle_type":         "vehicle_type",
    }

    #: Columns that SHOULD be present for a record to be considered useful.
    #: Missing required columns are logged as warnings, not hard errors, so
    #: partial datasets are still returned rather than failing entirely.
    REQUIRED_COLUMNS: frozenset[str] = frozenset({
        "fir_number",
        "crime_type",
        "incident_date",
    })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Load a CSV or Excel file and return its contents as a list of dicts.

        Execution flow
        --------------
        1. Validate path existence and file extension.
        2. Detect encoding (CSV) / check engine availability (Excel).
        3. Read the file into a ``pandas.DataFrame``.
        4. Handle empty files gracefully.
        5. Strip and normalise raw column names via ``normalize_columns()``.
        6. Validate required columns via ``validate_dataframe()``.
        7. Clean cell values via ``clean_values()``.
        8. Convert each row to a dict, replacing NaN with ``None``.
        9. Return the list of records and log summary metrics.

        Parameters
        ----------
        file_path:
            Absolute or relative path to the ``.csv``, ``.xlsx``, or ``.xls``
            file to be processed.

        Returns
        -------
        List[Dict[str, Any]]
            One dict per data row.  Keys are normalised CIAS field names.
            An empty list is returned for empty or header-only files.

        Raises
        ------
        FileNotFoundError
            If the path does not exist on the filesystem.
        ValueError
            If the extension is unsupported, the file cannot be parsed, or
            a required Excel engine (openpyxl / xlrd) is missing.
        RuntimeError
            On any other unexpected pandas / I/O failure.
        """
        if not _PANDAS_AVAILABLE:
            raise ImportError(
                "pandas is not installed. Run: pip install pandas"
            )

        start_time = time.time()
        path = self._validate_path(file_path)
        ext = path.suffix.lower()

        logger.info(
            "CSVExtractor: starting extraction for '%s' (format: %s).",
            path,
            ext,
        )

        # --- Read into DataFrame ----------------------------------------
        df = self._read_file(path, ext)

        # --- Empty file shortcut ----------------------------------------
        if df.empty:
            logger.warning(
                "CSVExtractor: file '%s' produced an empty DataFrame — "
                "no rows to process.",
                path,
            )
            return []

        rows_raw = len(df)
        logger.info(
            "CSVExtractor: loaded %d raw row(s) and %d column(s) from '%s'.",
            rows_raw,
            len(df.columns),
            path,
        )

        # --- Normalise columns ------------------------------------------
        df = self.normalize_columns(df)

        # --- Validate required columns ----------------------------------
        self.validate_dataframe(df, path)

        # --- Clean cell values ------------------------------------------
        df = self.clean_values(df)

        # --- Convert to list of dicts (NaN → None) ----------------------
        records: List[Dict[str, Any]] = [
            {
                col: (None if pd.isna(val) else val)
                for col, val in row.items()
            }
            for row in df.to_dict(orient="records")
        ]

        elapsed = time.time() - start_time
        logger.info(
            "CSVExtractor: extraction complete for '%s' | "
            "Records: %d | Columns: %d | Time: %.2fs",
            path,
            len(records),
            len(df.columns),
            elapsed,
        )
        return records

    # ------------------------------------------------------------------
    # Public helpers (overridable)
    # ------------------------------------------------------------------

    def normalize_columns(self, df: "pd.DataFrame") -> "pd.DataFrame":
        """
        Map raw column headers to canonical CIAS CrimeRecord field names.

        Normalisation steps
        -------------------
        1. Strip leading/trailing whitespace from every column header.
        2. Collapse internal whitespace runs to a single space.
        3. Look up the cleaned header (lowercased) in ``COLUMN_ALIAS_MAP``.
        4. If a match is found, rename to the canonical field name.
        5. If no match is found, convert the raw header to ``snake_case``
           so it is usable without crashing downstream code.

        Parameters
        ----------
        df:
            DataFrame with raw column headers as loaded from the file.

        Returns
        -------
        pd.DataFrame
            DataFrame with normalised column names.
        """
        import re as _re  # local import; re is stdlib — no cost concern

        rename_map: Dict[str, str] = {}

        for raw_col in df.columns:
            stripped = str(raw_col).strip()
            collapsed = _re.sub(r"\s+", " ", stripped)
            lookup_key = collapsed.lower()

            if lookup_key in self.COLUMN_ALIAS_MAP:
                canonical = self.COLUMN_ALIAS_MAP[lookup_key]
                rename_map[raw_col] = canonical
                if raw_col != canonical:
                    logger.debug(
                        "CSVExtractor: column '%s' → '%s'.", raw_col, canonical
                    )
            else:
                # Convert arbitrary header to snake_case as a safe fallback
                snake = _re.sub(r"[^a-zA-Z0-9]+", "_", collapsed).strip("_").lower()
                rename_map[raw_col] = snake
                if raw_col != snake:
                    logger.debug(
                        "CSVExtractor: unknown column '%s' → snake_case '%s' (no alias match).",
                        raw_col,
                        snake,
                    )

        return df.rename(columns=rename_map)

    def validate_dataframe(
        self,
        df: "pd.DataFrame",
        source_path: Optional[Path] = None,
    ) -> None:
        """
        Check that the DataFrame contains the expected required columns.

        Missing required columns are logged as **warnings** (not exceptions)
        so that partial datasets — common with real-world police exports —
        are still returned rather than completely rejected.

        Columns present in ``REQUIRED_COLUMNS`` but absent from ``df`` are
        listed individually so operators know exactly what is missing.

        Parameters
        ----------
        df:
            DataFrame with normalised column names.
        source_path:
            Optional path included in log messages for traceability.
        """
        label = str(source_path) if source_path else "<unknown>"
        present = set(df.columns)
        missing = self.REQUIRED_COLUMNS - present

        if missing:
            logger.warning(
                "CSVExtractor: file '%s' is missing %d required column(s): %s. "
                "Records will still be returned with those fields set to None.",
                label,
                len(missing),
                sorted(missing),
            )
        else:
            logger.debug(
                "CSVExtractor: all required columns present in '%s'.", label
            )

        # Log columns that ARE present for pipeline observability
        logger.debug(
            "CSVExtractor: available columns in '%s': %s",
            label,
            sorted(present),
        )

    def clean_values(self, df: "pd.DataFrame") -> "pd.DataFrame":
        """
        Sanitise cell values across the entire DataFrame.

        Operations
        ----------
        1. String columns: strip leading/trailing whitespace.
        2. Normalise empty strings (``''``, ``'N/A'``, ``'NA'``, ``'None'``,
           ``'null'``, ``'-'``) to ``NaN`` so they serialise as ``None``
           after the ``to_dict`` step.
        3. Collapse internal whitespace runs in string cells to a single space
           (eliminates padding artefacts from right-padded fixed-width exports).
        4. Non-string columns are left untouched.

        Parameters
        ----------
        df:
            DataFrame with normalised column names (post ``normalize_columns``).

        Returns
        -------
        pd.DataFrame
            DataFrame with cleaned cell values.
        """
        import re as _re
        import numpy as np

        # Sentinel strings that unambiguously represent missing data
        _EMPTY_SENTINELS: frozenset[str] = frozenset({
            "", "n/a", "na", "none", "null", "-", "--", "nil",
            "not available", "not applicable", "unknown",
        })

        for col in df.columns:
            if df[col].dtype == object:
                # 1. Strip
                df[col] = df[col].apply(
                    lambda v: v.strip() if isinstance(v, str) else v
                )
                # 2. Collapse internal whitespace
                df[col] = df[col].apply(
                    lambda v: _re.sub(r"\s+", " ", v) if isinstance(v, str) else v
                )
                # 3. Normalise empty / sentinel strings → NaN
                df[col] = df[col].apply(
                    lambda v: np.nan if isinstance(v, str) and v.lower() in _EMPTY_SENTINELS else v
                )

        return df

    # ------------------------------------------------------------------
    # Private — I/O
    # ------------------------------------------------------------------

    def _read_file(self, path: Path, ext: str) -> "pd.DataFrame":
        """
        Dispatch to the correct pandas reader based on file extension.

        Parameters
        ----------
        path:
            Resolved path to the file.
        ext:
            Lowercase file extension (e.g. ``'.csv'``, ``'.xlsx'``).

        Returns
        -------
        pd.DataFrame

        Raises
        ------
        ValueError
            On parse errors or missing Excel engines.
        RuntimeError
            On unexpected I/O failures.
        """
        if ext == ".csv":
            return self._read_csv(path)
        elif ext == ".xlsx":
            return self._read_xlsx(path)
        elif ext == ".xls":
            return self._read_xls(path)
        else:
            # Should not reach here after _validate_path, but guard anyway.
            raise ValueError(
                f"Unsupported file extension '{ext}'. "
                f"Supported: {sorted(_SUPPORTED_EXTENSIONS)}"
            )

    def _read_csv(self, path: Path) -> "pd.DataFrame":
        """
        Read a CSV file, attempting multiple encodings if necessary.

        Encoding detection priority
        ---------------------------
        1. chardet byte-sniffing (if chardet is installed).
        2. Sequential fallback through ``_CSV_ENCODING_FALLBACKS``.

        Raises
        ------
        ValueError
            If the file cannot be parsed with any known encoding.
        """
        encoding_candidates: list[str] = []

        # Chardet probe
        if _CHARDET_AVAILABLE:
            try:
                raw_bytes = path.read_bytes()
                detected = chardet.detect(raw_bytes)
                detected_enc = detected.get("encoding")
                if detected_enc:
                    encoding_candidates.append(detected_enc)
                    logger.debug(
                        "CSVExtractor: chardet detected encoding '%s' "
                        "(confidence %.2f) for '%s'.",
                        detected_enc,
                        detected.get("confidence", 0.0),
                        path,
                    )
            except Exception as exc:
                logger.debug(
                    "CSVExtractor: chardet probing failed for '%s': %s.", path, exc
                )

        # Append standard fallbacks (deduped, preserving order)
        seen: set[str] = set(encoding_candidates)
        for enc in _CSV_ENCODING_FALLBACKS:
            if enc.lower() not in seen:
                encoding_candidates.append(enc)
                seen.add(enc.lower())

        last_exc: Optional[Exception] = None

        for encoding in encoding_candidates:
            try:
                df = pd.read_csv(
                    str(path),
                    encoding=encoding,
                    dtype=str,          # Keep everything as string; let callers cast
                    keep_default_na=True,
                    na_values=["", "NA", "N/A", "NaN", "null", "None", "-"],
                    skip_blank_lines=True,
                )
                logger.debug(
                    "CSVExtractor: successfully read '%s' with encoding '%s'.",
                    path,
                    encoding,
                )
                return df
            except UnicodeDecodeError as exc:
                logger.debug(
                    "CSVExtractor: encoding '%s' failed for '%s': %s — trying next.",
                    encoding,
                    path,
                    exc,
                )
                last_exc = exc
                continue
            except pd.errors.EmptyDataError:
                logger.warning(
                    "CSVExtractor: CSV file '%s' is empty (no data rows).", path
                )
                return pd.DataFrame()
            except pd.errors.ParserError as exc:
                logger.error(
                    "CSVExtractor: CSV parse error in '%s': %s", path, exc
                )
                raise ValueError(
                    f"CSV file could not be parsed — it may be malformed: '{path}'. "
                    f"Detail: {exc}"
                ) from exc
            except Exception as exc:
                logger.exception(
                    "CSVExtractor: unexpected error reading CSV '%s'.", path
                )
                raise RuntimeError(
                    f"Unexpected failure while reading CSV '{path}': {exc}"
                ) from exc

        raise ValueError(
            f"Could not decode CSV file '{path}' with any of the attempted "
            f"encodings: {encoding_candidates}. "
            f"Last error: {last_exc}"
        )

    def _read_xlsx(self, path: Path) -> "pd.DataFrame":
        """
        Read a modern Excel (.xlsx) file using openpyxl as the engine.

        Raises
        ------
        ValueError
            If openpyxl is not installed or the file is corrupted.
        """
        if not _OPENPYXL_AVAILABLE:
            raise ValueError(
                "openpyxl is required to read .xlsx files but is not installed. "
                "Run: pip install openpyxl"
            )
        try:
            df = pd.read_excel(
                str(path),
                engine="openpyxl",
                dtype=str,
                keep_default_na=True,
                na_values=["", "NA", "N/A", "NaN", "null", "None", "-"],
            )
            logger.debug(
                "CSVExtractor: successfully read Excel file '%s' (%d rows).",
                path,
                len(df),
            )
            return df
        except Exception as exc:
            logger.error(
                "CSVExtractor: failed to read .xlsx file '%s': %s", path, exc
            )
            raise ValueError(
                f"Could not read Excel (.xlsx) file '{path}'. "
                f"The file may be corrupted or password-protected. Detail: {exc}"
            ) from exc

    def _read_xls(self, path: Path) -> "pd.DataFrame":
        """
        Read a legacy Excel (.xls) file using xlrd as the engine.

        Raises
        ------
        ValueError
            If xlrd is not installed or the file is corrupted.
        """
        if not _XLRD_AVAILABLE:
            raise ValueError(
                "xlrd is required to read .xls files but is not installed. "
                "Run: pip install xlrd"
            )
        try:
            df = pd.read_excel(
                str(path),
                engine="xlrd",
                dtype=str,
                keep_default_na=True,
                na_values=["", "NA", "N/A", "NaN", "null", "None", "-"],
            )
            logger.debug(
                "CSVExtractor: successfully read legacy Excel file '%s' (%d rows).",
                path,
                len(df),
            )
            return df
        except Exception as exc:
            logger.error(
                "CSVExtractor: failed to read .xls file '%s': %s", path, exc
            )
            raise ValueError(
                f"Could not read legacy Excel (.xls) file '{path}'. "
                f"The file may be corrupted or in an unsupported format. Detail: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Private — Validation
    # ------------------------------------------------------------------

    def _validate_path(self, file_path: str) -> Path:
        """
        Validate that ``file_path`` points to an existing, supported file.

        Returns
        -------
        Path
            Resolved ``pathlib.Path`` to the validated file.

        Raises
        ------
        TypeError
            If ``file_path`` is not a string.
        FileNotFoundError
            If the path does not exist or is not a regular file.
        ValueError
            If the file extension is not supported.
        """
        if not isinstance(file_path, str):
            raise TypeError(
                f"file_path must be a string, got {type(file_path).__name__}."
            )

        if not file_path.strip():
            raise ValueError("file_path must not be an empty string.")

        path = Path(file_path).resolve()

        if not path.exists():
            logger.error("CSVExtractor: file not found: '%s'.", path)
            raise FileNotFoundError(
                f"File not found: '{path}'. Verify the path and try again."
            )

        if not path.is_file():
            logger.error(
                "CSVExtractor: path is not a regular file: '%s'.", path
            )
            raise FileNotFoundError(
                f"Path exists but is not a regular file: '{path}'."
            )

        ext = path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            logger.error(
                "CSVExtractor: unsupported extension '%s' for file '%s'.",
                ext,
                path,
            )
            raise ValueError(
                f"Unsupported file extension '{ext}'. "
                f"Supported formats: {sorted(_SUPPORTED_EXTENSIONS)}"
            )

        return path

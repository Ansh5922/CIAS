import os
import time
import json
import logging
from typing import Optional

import google.generativeai as genai
from pydantic import ValidationError
from google.generativeai.types import generation_types

# CIAS specific imports
from app.preprocessing.models import CrimeRecord, ProcessingResult
from app.preprocessing.llm.prompt import SYSTEM_PROMPT

# Configure structured logger
logger = logging.getLogger(__name__)

class GeminiExtractor:
    """
    A service that wraps Google's Gemini model.
    Its sole responsibility is converting unstructured raw text into a validated 
    CrimeRecord Pydantic model by strictly applying preprocessing system prompts.
    """

    def __init__(self, model_name: Optional[str] = None):
        """
        Initializes the GeminiExtractor class securely with an API key from the environment.
        """
        self._initialize_client(model_name)

    def _initialize_client(self, preferred_model_name: Optional[str]) -> None:
        """
        Loads API configurations securely via OS environment, supporting fallback to CIAS config.
        """
        api_key = os.environ.get("GEMINI_API_KEY")
        
        # Fallback to app.core.config if available in the CIAS ecosystem
        if not api_key:
            try:
                from app.core.config import settings
                api_key = getattr(settings, "GEMINI_API_KEY", None)
            except ImportError:
                pass
                
        if not api_key:
            logger.error("Failed to initialize GeminiExtractor: GEMINI_API_KEY is missing.")
            raise ValueError("GEMINI_API_KEY environment variable/setting is missing.")

        genai.configure(api_key=api_key)

        # Allow settings or environment overrides, default to standard flash layer.
        self.model_name = preferred_model_name or os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
        
        try:
            self.model = genai.GenerativeModel(self.model_name)
            logger.info(f"Gemini client successfully initialized using model: {self.model_name}")
        except Exception as e:
            logger.exception("Error instantiating GenAI Model object")
            raise

    def extract(self, raw_text: str) -> ProcessingResult:
        """
        Core operational method. Orchestrates the full lifecycle of text -> Prompt -> LLM -> JSON -> CrimeRecord.
        Returns a rich ProcessingResult containing success status, metadata, and the record.
        """
        logger.info("Initializing LLM extraction process...")
        start_time = time.time()
        result = ProcessingResult()

        try:
            if not raw_text or not raw_text.strip():
                raise ValueError("Input raw_text provided for extraction is empty.")
            
            # Step 1: Combine instructions with data
            prompt = self._build_prompt(raw_text)

            # Step 2: Send data to the model
            logger.debug(f"Calling Gemini model '{self.model_name}'...")
            response_text = self._call_gemini(prompt)

            # Step 3: Clean and parse the raw string into a Python dict
            parsed_data = self._parse_response(response_text)

            # Step 4: Strict validation using Pydantic models
            record = self._validate_record(parsed_data)

            # Wrap success
            result.success = True
            result.message = "Successfully extracted and validated crime record."
            result.record = record
            logger.info("Extraction completed successfully.")

        except ValueError as e:
            result.success = False
            result.message = "Standard Error Encountered"
            result.errors.append(str(e))
            logger.error(f"Extraction failed (ValueError): {e}")
            
        except json.JSONDecodeError as e:
            result.success = False
            result.message = "JSON Parsing Failure"
            result.errors.append(f"Model output could not be parsed to JSON. Error: {e}")
            logger.error(f"JSON Parsing Error. Model output was invalid JSON: {e}")
            
        except ValidationError as e:
            result.success = False
            result.message = "Schema Validation Error"
            result.errors.append("The extracted data structure violated the CrimeRecord Pydantic constraints.")
            result.errors.append(f"Validation Details: {e.errors()}")
            logger.error(f"Pydantic Validation mismatched model extraction format: {e}")
            
        except generation_types.StopCandidateException as e:
            result.success = False
            result.message = "LLM Generation Interrupted"
            result.errors.append(f"The LLM stopped generating midway: {e}")
            logger.warning(f"StopCandidateException: {e}")
            
        except Exception as e:
            result.success = False
            result.message = "Unexpected API or runtime error"
            result.errors.append(str(e))
            logger.exception("An unexpected error occurred during Gemini processing lifecycle.")
            
        finally:
            result.processing_time_seconds = round(time.time() - start_time, 2)
            
        return result

    def _build_prompt(self, raw_text: str) -> str:
        """
        Combines the system-level persona config, schema, format rules
        with the active unstructured payload.
        """
        return f"{SYSTEM_PROMPT}\n\n### RAW TEXT TO PROCESS ###\n{raw_text}\n"

    def _call_gemini(self, prompt: str) -> str:
        """
        Handles network calls to the LLM model instance.
        """
        try:
             # Strongly suggest rigid JSON responses
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.0 # Deterministic behaviour over creative interpretation for fact extraction
            )
            
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config
            )
            
            if not response.text:
                raise ValueError("Model successfully connected but returned an empty response text payload.")
                
            return response.text
            
        except Exception as e:
            logger.error(f"Google Generative AI service call failed: {e}")
            raise

    def _parse_response(self, response_text: str) -> dict:
        """
        Cleans any errant formatting the LLM might have embedded alongside JSON payloads.
        Returns a Python Dictionary representing the model.
        """
        text = response_text.strip()
        
        # Defensive cleanup against markdown syntax if response_mime_type restriction failed
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
             text = text[3:]
             
        if text.endswith("```"):
            text = text[:-3]
            
        text = text.strip()
        return json.loads(text)

    def _validate_record(self, parsed_data: dict) -> CrimeRecord:
        """
        Accepts raw dict, attempts to pipe it into Pydantic validators.
        Raises ValidationError if mismatches exist (caught by `extract`).
        """
        return CrimeRecord(**parsed_data)

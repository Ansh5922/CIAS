import uuid
from datetime import date, time, datetime
from enum import Enum
from typing import List, Dict, Optional, Any

from pydantic import BaseModel, Field, ConfigDict


# ==========================================
# ENUMS
# ==========================================

class PersonRole(str, Enum):
    VICTIM = "Victim"
    SUSPECT = "Suspect"
    WITNESS = "Witness"
    OFFICER = "Officer"
    UNKNOWN = "Unknown"


class SourceType(str, Enum):
    PDF = "PDF"
    IMAGE = "IMAGE"
    CSV = "CSV"
    EXCEL = "EXCEL"
    URL = "URL"
    TEXT = "TEXT"


class Gender(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class CrimeStatus(str, Enum):
    OPEN = "Open"
    CLOSED = "Closed"
    UNDER_INVESTIGATION = "Under Investigation"
    RESOLVED = "Resolved"
    UNKNOWN = "Unknown"


class MediaType(str, Enum):
    IMAGE = "Image"
    VIDEO = "Video"
    DOCUMENT = "Document"
    AUDIO = "Audio"
    OTHER = "Other"


class VehicleType(str, Enum):
    TWO_WHEELER = "Two Wheeler"
    FOUR_WHEELER = "Four Wheeler"
    COMMERCIAL = "Commercial"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class WeaponType(str, Enum):
    FIREARM = "Firearm"
    BLADED = "Bladed"
    BLUNT_OBJECT = "Blunt Object"
    EXPLOSIVE = "Explosive"
    OTHER = "Other"
    UNKNOWN = "Unknown"


# ==========================================
# BASE MODEL
# ==========================================

class BaseSchema(BaseModel):
    """
    Base Pydantic model for all schemas to inherit from.
    Includes configuration common to all models.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ==========================================
# ENTITY MODELS
# ==========================================

class Person(BaseSchema):
    """
    Represents an individual involved in a case (Victim, Suspect, etc.).
    """
    person_id: Optional[uuid.UUID] = Field(default=None, description="Unique identifier for the person")
    name: Optional[str] = Field(default=None, description="Full name of the person")
    age: Optional[int] = Field(default=None, ge=0, le=150, description="Age of the person in years")
    gender: Optional[Gender] = Field(default=None, description="Gender of the person")
    role: PersonRole = Field(default=PersonRole.UNKNOWN, description="Role of the person in the case")
    address: Optional[str] = Field(default=None, description="Residential or known address")
    phone: Optional[str] = Field(default=None, description="Contact phone number")
    identification_number: Optional[str] = Field(default=None, description="National ID, Passport, or other identifying number")
    injuries: Optional[str] = Field(default=None, description="Description of any injuries sustained, if applicable")
    remarks: Optional[str] = Field(default=None, description="Any additional remarks or notes about the person")


class Vehicle(BaseSchema):
    """
    Represents a vehicle involved or related to a case.
    """
    registration_number: Optional[str] = Field(default=None, description="License plate or registration number")
    vehicle_type: Optional[VehicleType] = Field(default=None, description="Category/type of the vehicle")
    brand: Optional[str] = Field(default=None, description="Brand or manufacturer of the vehicle")
    model: Optional[str] = Field(default=None, description="Specific model of the vehicle")
    color: Optional[str] = Field(default=None, description="Primary color of the vehicle")
    owner: Optional[str] = Field(default=None, description="Registered owner of the vehicle")
    remarks: Optional[str] = Field(default=None, description="Additional notes regarding the vehicle")


class Weapon(BaseSchema):
    """
    Represents a weapon found or suspected to be used in a case.
    """
    weapon_type: Optional[WeaponType] = Field(default=None, description="Category of the weapon")
    weapon_name: Optional[str] = Field(default=None, description="Specific name or model of the weapon")
    recovered: bool = Field(default=False, description="Indicates if the weapon was recovered by authorities")
    description: Optional[str] = Field(default=None, description="Detailed description of the weapon")


class CrimeLocation(BaseSchema):
    """
    Details the geographical and administrative location of the incident.
    """
    address: Optional[str] = Field(default=None, description="Primary street address of the incident")
    locality: Optional[str] = Field(default=None, description="Neighborhood or locality")
    area: Optional[str] = Field(default=None, description="Broader area or sector")
    police_station: Optional[str] = Field(default=None, description="Jurisdictional police station")
    district: Optional[str] = Field(default=None, description="Administrative district")
    state: Optional[str] = Field(default=None, description="State or province")
    country: Optional[str] = Field(default=None, description="Country")
    postal_code: Optional[str] = Field(default=None, description="ZIP or postal code")
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0, description="Geographical latitude")
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0, description="Geographical longitude")
    zone: Optional[str] = Field(default=None, description="Police zone or circle")
    landmark: Optional[str] = Field(default=None, description="Nearby recognizable landmark")


class CrimeEvidence(BaseSchema):
    """
    Details of physical or digital evidence collected for a case.
    """
    evidence_type: Optional[str] = Field(default=None, description="Type/category of the evidence")
    description: Optional[str] = Field(default=None, description="Detailed description of the evidence")
    collected: bool = Field(default=False, description="Flag indicating if the evidence was successfully collected")
    collected_by: Optional[str] = Field(default=None, description="Name or ID of the officer who collected it")
    collection_date: Optional[datetime] = Field(default=None, description="Date and time when the evidence was collected")


class CrimeMedia(BaseSchema):
    """
    Digital media files (photos, videos, docs) associated with the case.
    """
    media_type: Optional[MediaType] = Field(default=None, description="Type of the media file")
    file_name: Optional[str] = Field(default=None, description="Original name of the file")
    file_path: Optional[str] = Field(default=None, description="Storage path or URI to access the file")
    mime_type: Optional[str] = Field(default=None, description="MIME content type (e.g., image/jpeg)")
    uploaded_by: Optional[str] = Field(default=None, description="User who uploaded the media")
    uploaded_at: Optional[datetime] = Field(default=None, description="Timestamp of the upload")


# ==========================================
# STANDARDIZED MAIN SCHEMA
# ==========================================

class CrimeRecord(BaseSchema):
    """
    The main standardized JSON schema. This is the output expected from the LLM extraction pipeline 
    and acts as the final preprocessed representation of a crime report or FIR.
    """
    # General Information
    case_number: Optional[str] = Field(default=None, description="Unique case number or identifier")
    fir_number: Optional[str] = Field(default=None, description="First Information Report number")
    crime_type: Optional[str] = Field(default=None, description="Primary type of crime")
    crime_category: Optional[str] = Field(default=None, description="Broad category of the crime (e.g., Violent, Property)")
    ipc_sections: List[str] = Field(default_factory=list, description="List of relevant IPC sections applied")
    bns_sections: List[str] = Field(default_factory=list, description="List of relevant BNS (Bharatiya Nyaya Sanhita) sections applied")
    status: Optional[CrimeStatus] = Field(default=None, description="Current investigation status")

    # Time Information
    incident_date: Optional[date] = Field(default=None, description="Date when the incident occurred")
    incident_time: Optional[time] = Field(default=None, description="Time when the incident occurred")
    report_date: Optional[datetime] = Field(default=None, description="Date and time when the crime was reported")

    # Location
    location: Optional[CrimeLocation] = Field(default=None, description="Geographical and administrative location details")

    # People - separated by role for convenience
    victims: List[Person] = Field(default_factory=list, description="Individuals identified as victims")
    suspects: List[Person] = Field(default_factory=list, description="Individuals identified as suspects or accused")
    witnesses: List[Person] = Field(default_factory=list, description="Individuals identified as witnesses")
    officers: List[Person] = Field(default_factory=list, description="Police or investigating officers involved")

    # Crime Details
    description: Optional[str] = Field(default=None, description="Detailed narrative or description of the crime")
    modus_operandi: Optional[str] = Field(default=None, description="Method of operation or how the crime was executed")
    motive: Optional[str] = Field(default=None, description="Suspected motive behind the crime")
    weapons: List[Weapon] = Field(default_factory=list, description="Weapons involved in the incident")
    vehicles: List[Vehicle] = Field(default_factory=list, description="Vehicles involved in the incident")
    evidence: List[CrimeEvidence] = Field(default_factory=list, description="Evidence collected or noted in the report")

    # Media
    media: List[CrimeMedia] = Field(default_factory=list, description="Associated media files (photos, videos)")

    # Pipeline Metadata
    source_type: Optional[SourceType] = Field(default=None, description="Type of the original source document")
    source_name: Optional[str] = Field(default=None, description="Name of the source file or document")
    source_url: Optional[str] = Field(default=None, description="URL of the source, if applicable")
    language: Optional[str] = Field(default=None, description="Primary language of the source text")
    extracted_text: Optional[str] = Field(default=None, description="Raw text extracted before structured parsing")
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Overall confidence score of the LLM extraction (0-1)")
    extraction_model: Optional[str] = Field(default=None, description="Name/version of the model used for extraction")
    preprocessing_timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the record was generated by the pipeline")

    # Processing Flags
    is_duplicate: bool = Field(default=False, description="Flag indicating if this record is a suspected duplicate")
    is_valid: bool = Field(default=True, description="Flag indicating if the record passed all validation rules")
    validation_errors: List[str] = Field(default_factory=list, description="List of any validation error messages")
    duplicate_reason: Optional[str] = Field(default=None, description="Explanation if marked as duplicate")

    # AI Metadata
    keywords: List[str] = Field(default_factory=list, description="Key terms extracted from the report")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Additional arbitrary entities recognized")
    summary: Optional[str] = Field(default=None, description="A brief AI-generated summary of the incident")


# ==========================================
# PIPELINE RESULT SCHEMA
# ==========================================

class ProcessingResult(BaseSchema):
    """
    Standardized wrapper for the output of a single document processing pipeline run.
    Contains both the extracted data and metadata about the execution process itself.
    """
    success: bool = Field(default=False, description="Indicates if the pipeline run was successful without critical failures")
    message: Optional[str] = Field(default=None, description="High-level status message or reason for failure")
    processing_time_seconds: Optional[float] = Field(default=None, ge=0.0, description="Time taken to process the document in seconds")
    record: Optional[CrimeRecord] = Field(default=None, description="The successfully extracted standard JSON output")
    errors: List[str] = Field(default_factory=list, description="List of critical errors encountered during processing")
    warnings: List[str] = Field(default_factory=list, description="List of non-critical warnings encountered")

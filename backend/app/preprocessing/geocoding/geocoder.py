"""
geocoder.py
-----------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Geocoding Module

Responsibility:
    Enrich a CrimeLocation schema object with latitude, longitude, and geographic hierarchy details.
    Uses geopy's Nominatim (OpenStreetMap) as the primary geocoding engine.
    Supports in-memory caching, auto-retry logic with backoff, and robust error handling.
    Designed to easily interface with future spatial engines (e.g. PostGIS point-in-polygon lookups).

Design:
    - Follows SOLID principles:
        S — Single Responsibility: geographic location resolution and enrichment.
        O — Open/Closed: extensible geocode provider interface and hook points for PostGIS lookups.
        L — Liskov-safe: standard input/output models.
        I — Interface-segregated: focus only on geocode and reverse_geocode.
        D — Configurable dependency (user_agent, timeout, cache capacity).
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Any, Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

from app.preprocessing.models import CrimeLocation

logger = logging.getLogger(__name__)


class Geocoder:
    """
    Enriches CrimeLocation items with spatial coordinates and address metadata.
    
    Features built-in in-memory caching to minimize Nominatim API calls and complies
    with OpenStreetMap usage guidelines (politeness rules).
    """

    def __init__(
        self,
        user_agent: str = "cias-crime-analytics-geocoder",
        timeout: int = 10,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        cache_capacity: int = 1000
    ) -> None:
        """
        Parameters
        ----------
        user_agent:
            Identifies the application toNominatim service.
        timeout:
            Max seconds to wait for Geopy response.
        max_retries:
            Number of attempts on query timeouts.
        backoff_factor:
            Multiplier applied to cooldown periods between retries.
        cache_capacity:
            Max number of lookups held in the local cache.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        
        # Initialise provider
        self.geolocator = Nominatim(user_agent=user_agent, timeout=timeout)
        
        # Simple local in-memory cache definition: Query String -> Geopy Location details
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.cache_capacity = cache_capacity

        logger.info(
            "Geocoder initialised | Timeout: %d | Retries: %d | User-Agent: '%s'",
            self.timeout,
            self.max_retries,
            user_agent,
        )

    def geocode(self, location: CrimeLocation) -> CrimeLocation:
        """
        Enriches the CrimeLocation object with coordinates and location attributes.
        
        If coordinates already exist (latitude and longitude), lookup is skipped.
        
        Parameters
        ----------
        location:
            The input location Pydantic schema instance.
            
        Returns
        -------
        CrimeLocation
            The enriched or unaltered CrimeLocation object.
        """
        if location.latitude is not None and location.longitude is not None:
            logger.info("Geocoder: Coordinates already present. Geolocating skipped.")
            return location

        query = self._build_query(location)
        if not query:
            logger.warning("Geocoder: Insufficient components in CrimeLocation to construct query.")
            return location

        # Check local cache
        cache_hit = self._cache.get(query)
        if cache_hit:
            logger.debug("Geocoder: In-memory cache hit for query: '%s'", query)
            self._apply_enrichment(location, cache_hit)
            self.enrich_location(location)  # Hook for PostGIS/polygon lookup expansions
            return location

        # Try to resolve remote address
        logger.info("Geocoder: resolving remote query: '%s'", query)
        resolved_details = self._execute_geocode_with_retry(query)

        if resolved_details:
            # Maintain cache size limit
            if len(self._cache) >= self.cache_capacity:
                self._cache.pop(next(iter(self._cache)))  # Simple FIFO eviction
            self._cache[query] = resolved_details

            self._apply_enrichment(location, resolved_details)
            self.enrich_location(location)  # Hook for PostGIS/polygon lookup expansions
        else:
            logger.warning("Geocoder: Failed to resolve coordinates for query: '%s'", query)

        return location

    def reverse_geocode(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """
        Determine spatial address attributes for given coordinate values.
        
        Parameters
        ----------
        lat:
            Latitude value [-90.0, 90.0]
        lon:
            Longitude value [-180.0, 180.0]
            
        Returns
        -------
        Optional[Dict[str, Any]]
            Dictionary mapping address blocks returned by Nominatim, or None if failed.
        """
        logger.info("Geocoder: reverse Geocoding coordinates: (%f, %f)", lat, lon)
        
        for attempt in range(1, self.max_retries + 1):
            try:
                res = self.geolocator.reverse((lat, lon), addressdetails=True)
                if res and res.raw:
                    return res.raw
                return None
            except (GeocoderTimedOut, GeocoderServiceError) as exc:
                if attempt == self.max_retries:
                    logger.error("Geocoder: Max retries exceeded during reverse geocode: %s", exc)
                    raise
                cooldown = self.backoff_factor ** attempt
                logger.warning(
                    "Geocoder: Reverse geocoding failed (attempt %d/%d). Cooldown: %.1fs. Error: %s",
                    attempt,
                    self.max_retries,
                    cooldown,
                    exc,
                )
                time.sleep(cooldown)
        return None

    def enrich_location(self, location: CrimeLocation) -> None:
        """
        Extensibility hook for future PostGIS geometry polygon checks.
        
        Allows Point-in-Polygon validation (e.g. mapping coordinates to specific
        police stations boundaries, administrative zones, or municipal wards).
        """
        logger.debug(
            "Geocoder: Running hook enrich_location for coordinates: (%s, %s)",
            location.latitude,
            location.longitude,
        )
        if location.latitude is not None and location.longitude is not None:
            # Placeholder: In the future, write PostGIS lookup logic here:
            # Query databases to verify if coordinates reside inside specific geometries.
            pass

    def _build_query(self, location: CrimeLocation) -> str:
        """
        Assemble a structured text address string from active CrimeLocation attributes.
        """
        parts = []
        if location.address:
            parts.append(location.address)
        if location.locality:
            parts.append(location.locality)
        if location.area:
            parts.append(location.area)
        if location.district:
            parts.append(location.district)
        if location.state:
            parts.append(location.state)
        if location.country:
            parts.append(location.country)
            
        return ", ".join(parts).strip()

    def _execute_geocode_with_retry(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Wrapper aroundNominatim geocode calling, managing timeouts and recovery steps.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                res = self.geolocator.geocode(query, addressdetails=True)
                if res and res.raw:
                    return res.raw
                return None
            except (GeocoderTimedOut, GeocoderServiceError) as exc:
                if attempt == self.max_retries:
                    logger.error("Geocoder: Remote search exceeded limit. Error: %s", exc)
                    raise
                cooldown = self.backoff_factor ** attempt
                logger.warning(
                    "Geocoder: Geocoding failed (attempt %d/%d). Cooldown: %.1fs. Error: %s",
                    attempt,
                    self.max_retries,
                    cooldown,
                    exc,
                )
                time.sleep(cooldown)
        return None

    def _apply_enrichment(self, location: CrimeLocation, resolved: Dict[str, Any]) -> None:
        """
        Inject address components from geolocator response back into the CrimeLocation model.
        """
        # Set Coordinates
        location.latitude = float(resolved.get("lat", location.latitude))
        location.longitude = float(resolved.get("lon", location.longitude))

        idx_address = resolved.get("address", {})

        # Fill missing attributes safely
        if not location.postal_code:
            location.postal_code = idx_address.get("postcode")
        if not location.district:
            # Nominatim values are occasionally nested under different labels
            location.district = idx_address.get("district") or idx_address.get("county")
        if not location.state:
            location.state = idx_address.get("state")
        if not location.country:
            location.country = idx_address.get("country")

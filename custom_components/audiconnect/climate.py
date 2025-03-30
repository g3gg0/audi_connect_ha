# climate.py
"""Support for Audi Climate Control."""

import logging
from typing import Any, List, Optional # Use List and Optional for type hinting

import voluptuous as vol

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_USERNAME,
    UnitOfTemperature, # Use UnitOfTemperature
)
from homeassistant.core import HomeAssistant, ServiceCall, callback # Import ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ( # Assuming these are defined in your const.py
    CLIMATE_UPDATE, # Need a dispatcher signal for climate updates
    CONF_VIN,
    CONF_CLIMATE_GLASS,
    CONF_CLIMATE_SEAT_FL,
    CONF_CLIMATE_SEAT_FR,
    CONF_CLIMATE_SEAT_RL,
    CONF_CLIMATE_SEAT_RR,
    CONF_CLIMATE_TEMP_C,
    CONF_CLIMATE_TEMP_F,
    DOMAIN,
)


# --- Service Definitions needed here for registration ---
SERVICE_START_CLIMATE_CONTROL = "start_climate_control"
SERVICE_STOP_CLIMATE_CONTROL = "stop_climate_control"
# Schemas will be defined within async_setup_entry
 

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Audi climate platform from a config entry."""
    _LOGGER.debug("Setting up Audi climate for config entry: %s", config_entry.entry_id)

    account = config_entry.data.get(CONF_USERNAME)
    # Ensure the central data store exists and the account data is loaded
    if DOMAIN not in hass.data or account not in hass.data[DOMAIN]:
        _LOGGER.error("Audi Connect data not found for account %s. Ensure integration setup is complete.", account)
        return # Or raise ConfigEntryNotReady

    audiData = hass.data[DOMAIN][account]
    entities_to_add = []

    # Check for configured vehicles
    if not hasattr(audiData, 'config_vehicles') or not audiData.config_vehicles:
        _LOGGER.warning("No configured vehicles found for account %s during climate setup.", account)
        return

    for config_vehicle in audiData.config_vehicles:
        # Check for climate instruments (assuming the list is named 'climates')
        # *** ADJUST 'climates' if your data structure uses a different name ***
        if not hasattr(config_vehicle, 'climates') or not config_vehicle.climates:
            _LOGGER.debug("No climate controls found for vehicle %s", getattr(config_vehicle, 'vehicle_name', 'Unknown'))
            continue # Skip to the next vehicle

        for instrument in config_vehicle.climates:
            # Add basic validation
            if not hasattr(instrument, 'vehicle_name') or not hasattr(instrument, 'full_name'):
                 _LOGGER.warning("Skipping invalid climate instrument data during setup: %s", instrument)
                 continue

            _LOGGER.debug("Creating AudiClimate for: %s", instrument.full_name)
            entities_to_add.append(AudiClimate(config_entry, instrument, audiData)) # Pass audiData for service calls

    # Add all discovered entities at once
    if entities_to_add:
        _LOGGER.info("Adding %d Audi climate control(s)", len(entities_to_add))
        async_add_entities(entities_to_add, True) # update_before_add=True
    else:
        _LOGGER.info("No Audi climate controls found to add for account %s.", account)

    # --- Service Handlers defined within setup_entry's scope ---
    async def async_handle_start_climate(service: ServiceCall) -> None:
        """Handle the service call to start climate control."""
        vin = service.data[CONF_VIN]
        temp_f = service.data.get(CONF_CLIMATE_TEMP_F)
        temp_c = service.data.get(CONF_CLIMATE_TEMP_C)
        glass_heating = service.data.get(CONF_CLIMATE_GLASS)
        seat_fl = service.data.get(CONF_CLIMATE_SEAT_FL)
        seat_fr = service.data.get(CONF_CLIMATE_SEAT_FR)
        seat_rl = service.data.get(CONF_CLIMATE_SEAT_RL)
        seat_rr = service.data.get(CONF_CLIMATE_SEAT_RR)

        _LOGGER.debug("Service %s called for VIN: %s", SERVICE_START_CLIMATE_CONTROL, vin)

        # Call the NEW method on the audiData (AudiAccount) object
        if hasattr(audiData, 'async_start_climate'):
            try:
                await audiData.async_start_climate(
                    vin=vin,
                    temp_c=temp_c,
                    temp_f=temp_f,
                    glass_heating=glass_heating,
                    seat_fl=seat_fl,
                    seat_fr=seat_fr,
                    seat_rl=seat_rl,
                    seat_rr=seat_rr,
                )
                _LOGGER.info("Climate start requested via service for VIN %s", vin)
            except Exception as e:
                _LOGGER.error("Error calling async_start_climate for VIN %s from service: %s", vin, e)
        else:
            _LOGGER.error("Audi data object does not have 'async_start_climate' method for service call.")

    async def async_handle_stop_climate(service: ServiceCall) -> None:
        """Handle the service call to stop climate control."""
        vin = service.data[CONF_VIN]
        _LOGGER.debug("Service %s called for VIN: %s", SERVICE_STOP_CLIMATE_CONTROL, vin)

        # Call the NEW method on the audiData (AudiAccount) object
        if hasattr(audiData, 'async_stop_climate'):
            try:
                await audiData.async_stop_climate(vin=vin)
                _LOGGER.info("Climate stop requested via service for VIN %s", vin)
            except Exception as e:
                _LOGGER.error("Error calling async_stop_climate for VIN %s from service: %s", vin, e)
        else:
             _LOGGER.error("Audi data object does not have 'async_stop_climate' method for service call.")

    # --- Register the services here ---
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_CLIMATE_CONTROL,
        async_handle_start_climate,
        schema=SERVICE_START_CLIMATE_CONTROL_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_CLIMATE_CONTROL,
        async_handle_stop_climate,
        schema=SERVICE_STOP_CLIMATE_CONTROL_SCHEMA,
    )
    # --- End Service Registration ---
 


class AudiClimate(ClimateEntity):
    """Representation of an Audi Climate system."""

    # Use _attr_ convention for HA defined properties
    _attr_hvac_modes: List[HVACMode] = [HVACMode.HEAT_COOL, HVACMode.OFF] # Basic modes for pre-climatization
    _attr_supported_features: ClimateEntityFeature = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.TURN_ON |
        ClimateEntityFeature.TURN_OFF
        # Add PRESET_MODE if you implement seat/window heating as presets
        # Add FAN_MODE if fan control is available
    )
    _attr_temperature_unit: str = UnitOfTemperature.CELSIUS # Report in Celsius, HA handles display conversion
    _attr_target_temperature_step: float = 0.5 # Or 1.0 depending on car API
    _attr_min_temp: float = 16.0 # Set realistic min/max if available from API
    _attr_max_temp: float = 30.0
    _attr_should_poll: bool = False # Data is pushed via dispatcher
    _attr_has_entity_name = True # Use "Climate" as the entity name suffix

    def __init__(self, config_entry: ConfigEntry, instrument: Any, audi_data: Any) -> None:
        """Initialize the Audi climate device."""
        self._instrument = instrument
        self._audi_data = audi_data # Store reference to call API methods if needed directly
        self._config_entry_id = config_entry.entry_id # Store for potential future use

        # Store identifiers needed for properties and updates
        self._vehicle_name = self._instrument.vehicle_name
        self._attr_unique_id = self._instrument.full_name # Instrument's full_name as unique ID

        # Device Information
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._vehicle_name)},
            "name": self._vehicle_name,
            "manufacturer": "Audi",
            "model": getattr(instrument, 'vehicle_model', None),
            "via_device": (DOMAIN, config_entry.entry_id), # Link to the integration's main device entry
        }

        # Initial state update
        self._update_state_from_instrument()

    def _update_state_from_instrument(self) -> None:
        """Update the entity's state based on the instrument data."""
        _LOGGER.debug("Updating state for %s from instrument: %s", self.entity_id, self._instrument) # Log the instrument

        # --- HVAC Mode (On/Off) ---
        # Get state from instrument's 'state' property
        instrument_state_raw = getattr(self._instrument, 'state', None)
        _LOGGER.debug("Raw instrument state: %s", instrument_state_raw)

        # Determine HVAC mode based on the raw state string
        if isinstance(instrument_state_raw, str):
            state_lower = instrument_state_raw.lower()
            if state_lower == 'off':
                self._attr_hvac_mode = HVACMode.OFF
            elif state_lower in ['on', 'heating', 'cooling', 'active']: # Add expected 'on' states
                self._attr_hvac_mode = HVACMode.HEAT_COOL # Or specific HEAT/COOL if distinguishable
            else:
                 _LOGGER.warning("Unknown climatisationState '%s' for %s", instrument_state_raw, self.entity_id)
                 self._attr_hvac_mode = None # Or HVACMode.OFF as default?
        else:
             _LOGGER.warning("Invalid or missing climatisationState type (%s) for %s", type(instrument_state_raw), self.entity_id)
             self._attr_hvac_mode = None # Or HVACMode.OFF

        # --- Target Temperature ---
        # Get temp from instrument's 'target_temperature' property
        target_temp_raw = getattr(self._instrument, 'target_temperature', None)
        _LOGGER.debug("Raw instrument target_temperature: %s", target_temp_raw)
        try:
            # Instrument property should already return float in Celsius
            self._attr_target_temperature = float(target_temp_raw) if target_temp_raw is not None else None
        except (ValueError, TypeError):
            self._attr_target_temperature = None
            _LOGGER.warning("Invalid target temperature format for %s: %s", self.entity_id, target_temp_raw)

        # --- Current Temperature (Optional) ---
        # Get current temp from instrument's 'current_temperature' property (mapped to outdoor temp)
        current_temp_raw = getattr(self._instrument, 'current_temperature', None)
        _LOGGER.debug("Raw instrument current_temperature (outdoor): %s", current_temp_raw)
        try:
            self._attr_current_temperature = float(current_temp_raw) if current_temp_raw is not None else None
        except (ValueError, TypeError):
             self._attr_current_temperature = None
             _LOGGER.debug("Invalid/missing current temperature for %s: %s", self.entity_id, current_temp_raw)

        # --- Update other attributes from instrument.attributes ---
        # This fetches the extra attributes prepared by the Instrument class
        self._attr_extra_state_attributes = getattr(self._instrument, 'attributes', {})

        _LOGGER.debug("Final state for %s: Mode=%s, Target=%.1f C, Current=%.1f C, Attrs=%s",
                      self.entity_id, self._attr_hvac_mode,
                      self._attr_target_temperature if self._attr_target_temperature is not None else -99.9,
                      self._attr_current_temperature if self._attr_current_temperature is not None else -99.9,
                      self._attr_extra_state_attributes)


    # --- ClimateEntity Properties ---

    @property
    def name(self) -> str | None:
        """Return the name of the climate device."""
        # Using _attr_has_entity_name = True means HA will combine device name + "Climate"
        # If you want full manual control: return f"{self._vehicle_name} Climate"
        # Returning None uses the default naming scheme based on has_entity_name
        return None # Let HA handle naming based on _attr_has_entity_name


    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return device specific state attributes."""
        attrs = {}
        # Safely get base attributes
        base_attrs = getattr(self._instrument, 'attributes', {})
        if isinstance(base_attrs, dict):
            attrs.update(base_attrs)

        # Add VIN for easy reference, helpful for service calls
        attrs["vin"] = getattr(self._instrument, 'vehicle_vin', None)
        # Add other relevant attributes from the instrument
        # attrs["outside_temperature"] = getattr(self._instrument, 'outside_temp', None)

        # Filter out None values if desired
        return {k: v for k, v in attrs.items() if v is not None}


    # --- ClimateEntity Methods ---

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        _LOGGER.debug("Setting target temperature for %s to %.1f %s",
                      self.entity_id, temperature, self.temperature_unit)

        vin = getattr(self._instrument, 'vehicle_vin', None)
        if not vin:
            _LOGGER.error("Cannot set temperature, VIN not found for %s", self.entity_id)
            return

        # *** Assumption: audiData has an async_set_climate_temp method ***
        # This method might need VIN and temperature (likely in Celsius)
        if hasattr(self._audi_data, 'async_set_climate_temp'):
            try:
                # Convert temperature to Celsius if the API requires it
                # The climate entity framework handles unit conversions for display,
                # but the API call needs the correct unit. Assume API wants Celsius.
                temp_c = temperature
                if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
                     # This conversion might already be handled by HA depending on how
                     # the value is passed, but explicit conversion can be safer.
                     # Alternatively, the ClimateEntity might provide converted values.
                     # Let's assume the API call needs Celsius.
                     # If your API takes Fahrenheit, adjust accordingly.
                     # temp_c = self.hass.config.units.temperature(temperature, UnitOfTemperature.FAHRENHEIT) # Requires HA util
                     pass # For now, assume API expects Celsius and HA gives it correctly


                await self._audi_data.async_set_climate_temp(vin=vin, temperature=temp_c)
                # Optimistic update: Update the state locally immediately
                self._attr_target_temperature = temperature
                self.async_write_ha_state()
                _LOGGER.info("Set target temperature for VIN %s to %.1f C (requested %.1f %s)",
                             vin, temp_c, temperature, self.temperature_unit)
            except Exception as e:
                _LOGGER.error("Error setting temperature for VIN %s: %s", vin, e)
        else:
            _LOGGER.error("Audi data object does not have 'async_set_climate_temp' method.")


    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode (calls start/stop services)."""
        _LOGGER.debug("Setting HVAC mode for %s to %s", self.entity_id, hvac_mode)
        vin = getattr(self._instrument, 'vehicle_vin', None)
        if not vin:
            _LOGGER.error("Cannot set HVAC mode, VIN not found for %s", self.entity_id)
            return

        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        elif hvac_mode == HVACMode.HEAT_COOL:
             # Start climate with current/default settings
             # Ideally, retrieve current target temp to pass along
             target_temp_c = self._attr_target_temperature # Assumes this is Celsius
             await self.async_turn_on(temperature_c=target_temp_c) # Pass temp to turn_on helper
        else:
            _LOGGER.warning("Unsupported HVAC mode requested: %s", hvac_mode)


    async def async_turn_on(self, temperature_c: Optional[float] = None) -> None:
        """Turn on climate control using the service call logic."""
        _LOGGER.info("Turning on climate for %s", self.entity_id)
        vin = getattr(self._instrument, 'vehicle_vin', None)
        if not vin:
            _LOGGER.error("Cannot turn on climate, VIN not found for %s", self.entity_id)
            return

        # Use the service handler logic for consistency
        # *** Assumption: audiData object has an start_climate_control method ***
        if hasattr(self._audi_data, 'start_climate_control'):
             try:
                 # Get current target temp if not provided, use reasonable default if needed
                 temp_to_set = temperature_c if temperature_c is not None else self._attr_target_temperature
                 if temp_to_set is None:
                     temp_to_set = 21.0 # Default to 21C if no target is set
                     _LOGGER.debug("No target temp found for turn_on, using default %.1f C", temp_to_set)

                 await self._audi_data.start_climate_control(vin=vin, temp_c=temp_to_set)
                 # Optimistic update
                 self._attr_hvac_mode = HVACMode.HEAT_COOL
                 self.async_write_ha_state()
                 _LOGGER.info("Climate turn on requested for VIN %s", vin)
             except Exception as e:
                 _LOGGER.error("Error turning on climate for VIN %s: %s", vin, e)
        else:
             _LOGGER.error("Audi data object does not have 'start_climate_control' method.")


    async def async_turn_off(self) -> None:
        """Turn off climate control using the service call logic."""
        _LOGGER.info("Turning off climate for %s", self.entity_id)
        vin = getattr(self._instrument, 'vehicle_vin', None)
        if not vin:
            _LOGGER.error("Cannot turn off climate, VIN not found for %s", self.entity_id)
            return

        # Use the service handler logic for consistency
        # *** Assumption: audiData object has an stop_climate_control method ***
        if hasattr(self._audi_data, 'async_stop_climate'):
            try:
                await self._audi_data.async_stop_climate(vin=vin)
                # Optimistic update
                self._attr_hvac_mode = HVACMode.OFF
                self.async_write_ha_state()
                _LOGGER.info("Climate turn off requested for VIN %s", vin)
            except Exception as e:
                 _LOGGER.error("Error turning off climate for VIN %s: %s", vin, e)
        else:
             _LOGGER.error("Audi data object does not have 'async_stop_climate' method.")

    # --- Update Handling ---

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        await super().async_added_to_hass()

        # Register for updates specific to climate
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, CLIMATE_UPDATE, self._async_receive_data # Use CLIMATE_UPDATE signal
            )
        )
        _LOGGER.debug("%s registered for %s signals", self.entity_id, CLIMATE_UPDATE)
        # Request initial data update if needed (or rely on update_before_add=True)
        # await self._instrument.async_update() # If your instrument has an update method


    @callback
    def _async_receive_data(self, instrument: Any) -> None:
        """Handle updated data received via dispatcher."""
        # Check if the update is for this specific entity instance
        if not instrument or instrument.full_name != self._attr_unique_id:
            return

        _LOGGER.debug("Received climate update for %s", self.entity_id)
        self._instrument = instrument # Update the internal instrument data
        self._update_state_from_instrument() # Parse new state
        self.async_write_ha_state() # Schedule HA state update
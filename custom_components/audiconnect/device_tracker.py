"""Support for tracking an Audi."""

import logging
from typing import Any # Import Any for type hinting if needed

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry # Import ConfigEntry for type hinting
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback # Import AddEntitiesCallback

from .const import DOMAIN, TRACKER_UPDATE

_LOGGER = logging.getLogger(__name__)


# async_setup_scanner is deprecated for config entry flows, can likely be removed entirely
# async def async_setup_scanner(hass, config, async_see, discovery_info=None):
#    """Old way."""


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None: # Use None return type hint for setup functions
    """Set up the Audi device tracker platform from a config entry."""
    _LOGGER.debug("Setting up Audi device tracker for config entry: %s", config_entry.entry_id)

    account = config_entry.data.get(CONF_USERNAME)
    # Ensure the central data store exists and the account data is loaded
    if DOMAIN not in hass.data or account not in hass.data[DOMAIN]:
        _LOGGER.error("Audi Connect data not found for account %s. Ensure integration setup is complete.", account)
        # Returning False is deprecated, raise ConfigEntryNotReady or just log and return None
        return # Or raise ConfigEntryNotReady from homeassistant.exceptions

    audiData = hass.data[DOMAIN][account]

    # Prepare a list to hold the entities to be added
    entities_to_add = []

    # Make sure config_vehicles exists and is iterable
    if not hasattr(audiData, 'config_vehicles') or not audiData.config_vehicles:
        _LOGGER.warning("No configured vehicles found for account %s during device_tracker setup.", account)
        # This might be normal if the user hasn't configured vehicles yet, so just return.
        return

    for config_vehicle in audiData.config_vehicles:
        # Make sure device_trackers exists and is iterable
        if not hasattr(config_vehicle, 'device_trackers') or not config_vehicle.device_trackers:
            _LOGGER.debug("No device trackers found for vehicle %s", getattr(config_vehicle, 'vehicle_name', 'Unknown'))
            continue # Skip to the next vehicle

        for instrument in config_vehicle.device_trackers:
            # Add some basic validation if possible (e.g., check required attributes)
            if not hasattr(instrument, 'vehicle_name') or not hasattr(instrument, 'full_name'):
                 _LOGGER.warning("Skipping invalid instrument data during setup: %s", instrument)
                 continue

            _LOGGER.debug("Creating AudiDeviceTracker for: %s", instrument.full_name)
            # Create the entity directly here
            entities_to_add.append(AudiDeviceTracker(config_entry, instrument)) # Pass config_entry if needed by entity

    # Add all discovered entities at once
    if entities_to_add:
        _LOGGER.info("Adding %d Audi device tracker(s)", len(entities_to_add))
        # Pass update_before_add=True to fetch initial state immediately after adding
        async_add_entities(entities_to_add, True)
    else:
        _LOGGER.info("No Audi device trackers found to add for account %s.", account)

    # Setup finished successfully (even if no entities were added)
    # The return True is deprecated for async_setup_entry


class AudiDeviceTracker(TrackerEntity):
    """Represent a tracked Audi device."""

    # Use _attr_ convention for HA defined properties where possible
    _attr_icon = "mdi:car"
    _attr_should_poll = False  # Data is pushed via dispatcher
    _attr_source_type = SourceType.GPS

    def __init__(self, config_entry: ConfigEntry, instrument: Any) -> None: # Added type hints
        """Initialize the Audi device tracker."""
        self._instrument = instrument
        # Store identifiers needed for properties and updates
        self._vehicle_name = self._instrument.vehicle_name
        self._entity_name = self._instrument.name # Assuming instrument provides the specific tracker name (e.g., 'Position')
        self._attr_unique_id = self._instrument.full_name # Use the instrument's full_name as the unique ID

        # Define device information. This links the entity to a device in the registry.
        # The device is automatically linked to the config_entry passed implicitly by HA
        # when the entity is created within async_setup_entry.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._vehicle_name)}, # Unique identifier for the device within the domain
            "name": self._vehicle_name,
            "manufacturer": "Audi",
            # Add model, etc., if available from the instrument or config_vehicle
            "model": getattr(instrument, 'vehicle_model', None),
            # You can optionally link the device directly to the config entry device if you have one
            # "via_device": (DOMAIN, config_entry.entry_id), # Uncomment if useful
        }

        # Initialize state attributes (latitude/longitude)
        self._latitude = None
        self._longitude = None
        self._update_state_from_instrument() # Set initial state


    def _update_state_from_instrument(self) -> None:
        """Update latitude and longitude from the instrument's state."""
        state = getattr(self._instrument, 'state', None)
        if isinstance(state, (list, tuple)) and len(state) >= 2:
            try:
                self._latitude = float(state[0])
                self._longitude = float(state[1])
            except (ValueError, TypeError):
                 _LOGGER.warning("Invalid latitude/longitude format in state for %s: %s", self.entity_id, state)
                 self._latitude = None
                 self._longitude = None
        else:
            # Keep previous state or set to None if state is invalid/missing
            # self._latitude = None # Uncomment if you want to clear location on invalid update
            # self._longitude = None # Uncomment if you want to clear location on invalid update
            _LOGGER.debug("State for %s does not contain valid lat/lon: %s", self.entity_id, state)


    @property
    def latitude(self) -> float | None: # Add type hint
        """Return latitude value of the device."""
        return self._latitude

    @property
    def longitude(self) -> float | None: # Add type hint
        """Return longitude value of the device."""
        return self._longitude

    @property
    def name(self) -> str: # Add type hint
        """Return the name of the entity."""
        # Provide a clear name, combining vehicle and tracker type
        return f"{self._vehicle_name} {self._entity_name}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None: # Add type hint
        """Return device specific state attributes."""
        attrs = {}
        # Safely get base attributes if they exist and are a dict
        base_attrs = getattr(self._instrument, 'attributes', {})
        if isinstance(base_attrs, dict):
            attrs.update(base_attrs)

        # Add other specific attributes, checking for existence
        attrs["model"] = "{}/{}".format(
            getattr(self._instrument, 'vehicle_model', "Unknown"), self._vehicle_name
        )
        attrs["model_year"] = getattr(self._instrument, 'vehicle_model_year', None)
        attrs["model_family"] = getattr(self._instrument, 'vehicle_model_family', None)
        # attrs["title"] = self._vehicle_name # Often redundant with name/device name
        attrs["csid"] = getattr(self._instrument, 'vehicle_csid', None)
        attrs["vin"] = getattr(self._instrument, 'vehicle_vin', None)

        # Filter out None values if desired
        return {k: v for k, v in attrs.items() if v is not None}


    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        # Called after entity is added to hass. Register for updates.
        await super().async_added_to_hass()

        # Use async_on_remove to automatically clean up the listener
        # when the entity is removed.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, TRACKER_UPDATE, self._async_receive_data
            )
        )
        _LOGGER.debug("%s registered for TRACKER_UPDATE signals", self.entity_id)

    # async_will_remove_from_hass is usually not needed if async_on_remove is used in async_added_to_hass

    @callback
    def _async_receive_data(self, instrument: Any) -> None:
        """Handle updated data received via dispatcher."""
        # Check if the update is for this specific entity instance
        # Using unique_id (instrument.full_name) is more reliable than just vehicle_name
        if instrument.full_name != self._attr_unique_id:
            return

        _LOGGER.debug("Received update for %s", self.entity_id)
        self._instrument = instrument # Update the internal instrument data
        self._update_state_from_instrument() # Update lat/lon state

        # Potentially update device info if model/name can change (less common)
        # new_device_name = self._instrument.vehicle_name
        # if self._vehicle_name != new_device_name:
        #     self._vehicle_name = new_device_name
        #     # Update device registry (more complex, may require registry access)


        self.async_write_ha_state() # Schedule an update for the entity's state in HA

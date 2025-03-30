import asyncio
import logging
import copy

import voluptuous as vol

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util.dt import utcnow

from .audi_connect_account import AudiConnectAccount, AudiConnectObserver
from .audi_models import VehicleData
from .const import (
    COMPONENTS,
    CONF_ACTION,
    CONF_CLIMATE_GLASS,
    CONF_CLIMATE_SEAT_FL,
    CONF_CLIMATE_SEAT_FR,
    CONF_CLIMATE_SEAT_RL,
    CONF_CLIMATE_SEAT_RR,
    CONF_CLIMATE_TEMP_C,
    CONF_CLIMATE_TEMP_F,
    CONF_REGION,
    CONF_SPIN,
    CONF_VIN,
    DOMAIN,
    CLIMATE_UPDATE,
    SIGNAL_STATE_UPDATED,
    TRACKER_UPDATE,
    UPDATE_SLEEP,
    CONF_API_LEVEL,
    DEFAULT_API_LEVEL,
    API_LEVELS,
)
from .dashboard import Dashboard

REFRESH_VEHICLE_DATA_FAILED_EVENT = "refresh_failed"
REFRESH_VEHICLE_DATA_COMPLETED_EVENT = "refresh_completed"

SERVICE_REFRESH_VEHICLE_DATA = "refresh_vehicle_data"
SERVICE_REFRESH_VEHICLE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VIN): cv.string,
    }
)

SERVICE_EXECUTE_VEHICLE_ACTION = "execute_vehicle_action"
SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA = vol.Schema(
    {vol.Required(CONF_VIN): cv.string, vol.Required(CONF_ACTION): cv.string}
)

SERVICE_START_CLIMATE_CONTROL = "start_climate_control"
SERVICE_START_CLIMATE_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VIN): cv.string,
        vol.Optional(CONF_CLIMATE_TEMP_F): cv.positive_int,
        vol.Optional(CONF_CLIMATE_TEMP_C): cv.positive_int,
        vol.Optional(CONF_CLIMATE_GLASS): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_FL): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_FR): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_RL): cv.boolean,
        vol.Optional(CONF_CLIMATE_SEAT_RR): cv.boolean,
    }
)

SERVICE_STOP_CLIMATE_CONTROL = "stop_climate_control"
SERVICE_STOP_CLIMATE_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VIN): cv.string,
    }
)

PLATFORMS: list[str] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.SWITCH,
    Platform.CLIMATE,
]

SERVICE_REFRESH_CLOUD_DATA = "refresh_cloud_data"

_LOGGER = logging.getLogger(__name__)


class AudiAccount(AudiConnectObserver):
    def __init__(self, hass, config_entry):
        """Initialize the component state."""
        self.hass = hass
        self.config_entry = config_entry
        self.config_vehicles = set()
        self.vehicles = set()

    def init_connection(self):
        session = async_get_clientsession(self.hass)
        self.connection = AudiConnectAccount(
            session=session,
            username=self.config_entry.data.get(CONF_USERNAME),
            password=self.config_entry.data.get(CONF_PASSWORD),
            country=self.config_entry.data.get(CONF_REGION),
            spin=self.config_entry.data.get(CONF_SPIN),
            api_level=self.config_entry.options.get(
                CONF_API_LEVEL,
                self.config_entry.data.get(
                    CONF_API_LEVEL, API_LEVELS[DEFAULT_API_LEVEL]
                ),
            ),
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_VEHICLE_DATA,
            self.refresh_vehicle_data,
            schema=SERVICE_REFRESH_VEHICLE_DATA_SCHEMA,
        )
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_EXECUTE_VEHICLE_ACTION,
            self.execute_vehicle_action,
            schema=SERVICE_EXECUTE_VEHICLE_ACTION_SCHEMA,
        )
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_CLOUD_DATA,
            self.update,
        )

        self.connection.add_observer(self)

    def is_enabled(self, attr):
        return True
        # """Return true if the user has enabled the resource."""
        # return attr in config[DOMAIN].get(CONF_RESOURCES, [attr])

    async def discover_vehicles(self, vehicles):
        if len(vehicles) > 0:
            for vehicle in vehicles:
                vin = vehicle.vin.lower()

                self.vehicles.add(vin)

                cfg_vehicle = VehicleData(self.config_entry)
                cfg_vehicle.vehicle = vehicle
                self.config_vehicles.add(cfg_vehicle)

                dashboard = Dashboard(self.connection, vehicle)

                for instrument in (
                    instrument
                    for instrument in dashboard.instruments
                    if instrument._component in COMPONENTS
                    and self.is_enabled(instrument.slug_attr)
                ):
                    _LOGGER.debug(
                        "Processing Instrument: Name=%s, Component=%s, Slug=%s, Enabled=%s",
                        instrument.name,
                        instrument._component,
                        instrument.slug_attr,
                        self.is_enabled(instrument.slug_attr),
                    )
                    if instrument._component == "sensor":
                        cfg_vehicle.sensors.add(instrument)
                    if instrument._component == "binary_sensor":
                        cfg_vehicle.binary_sensors.add(instrument)
                    if instrument._component == "switch":
                        cfg_vehicle.switches.add(instrument)
                    if instrument._component == "device_tracker":
                        cfg_vehicle.device_trackers.add(instrument)
                    if instrument._component == "lock":
                        cfg_vehicle.locks.add(instrument)
                    if instrument._component == "climate":
                        cfg_vehicle.climates.add(instrument)
                        # ADD THIS LOGGING:
                        _LOGGER.info(
                            "Found CLIMATE instrument for VIN %s: %s (Added to cfg_vehicle.climates)",
                            vehicle.vin,
                            instrument.full_name,
                         )
                    else:
                         # Optional: Log if component not matched
                         _LOGGER.debug("Instrument component '%s' not specifically handled for %s",
                                       instrument._component, vehicle.vin)
            await self.hass.config_entries.async_forward_entry_setups(
                self.config_entry, PLATFORMS
            )

    async def update(self, now):
        """Update status from the cloud."""
        _LOGGER.debug("Starting refresh cloud data...")
        if not await self.connection.update(None):
            _LOGGER.warning("Failed refresh cloud data")
            return False

        # Discover new vehicles that have not been added yet
        new_vehicles = [
            x for x in self.connection._vehicles if x.vin not in self.vehicles
        ]
        if new_vehicles:
            _LOGGER.debug("Retrieved %d vehicle(s)", len(new_vehicles))
        await self.discover_vehicles(new_vehicles)

        async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATED)

        for config_vehicle in self.config_vehicles:
            for instrument in config_vehicle.device_trackers:
                async_dispatcher_send(self.hass, TRACKER_UPDATE, instrument)
            for instrument in config_vehicle.climates:
                async_dispatcher_send(self.hass, CLIMATE_UPDATE, instrument)
 

        _LOGGER.debug("Successfully refreshed cloud data")
        return True

    async def execute_vehicle_action(self, service):
        vin = service.data.get(CONF_VIN).lower()
        action = service.data.get(CONF_ACTION).lower()

        if action == "lock":
            await self.connection.set_vehicle_lock(vin, True)
        if action == "unlock":
            await self.connection.set_vehicle_lock(vin, False)
        if action == "start_climatisation":
            await self.connection.set_vehicle_climatisation(vin, True)
        if action == "stop_climatisation":
            await self.connection.set_vehicle_climatisation(vin, False)
        if action == "start_charger":
            await self.connection.set_battery_charger(vin, True, False)
        if action == "start_timed_charger":
            await self.connection.set_battery_charger(vin, True, True)
        if action == "stop_charger":
            await self.connection.set_battery_charger(vin, False, False)
        if action == "start_preheater":
            await self.connection.set_vehicle_pre_heater(vin, True)
        if action == "stop_preheater":
            await self.connection.set_vehicle_pre_heater(vin, False)
        if action == "start_window_heating":
            await self.connection.set_vehicle_window_heating(vin, True)
        if action == "stop_window_heating":
            await self.connection.set_vehicle_window_heating(vin, False)

    async def async_start_climate(self, vin: str, temp_f=None, temp_c=None, glass_heating=False, seat_fl=False, seat_fr=False, seat_rl=False, seat_rr=False, **kwargs):
        """Start climate control via the underlying connection."""
        _LOGGER.debug("Initiating Start Climate Control Service...")

        await self.connection.start_climate_control(
            vin=vin.lower(), # Pass VIN explicitly
            temp_f=temp_f,
            temp_c=temp_c,
            glass_heating=glass_heating,
            seat_fl=seat_fl,
            seat_fr=seat_fr,
            seat_rl=seat_rl,
            seat_rr=seat_rr,
        )
        
    async def async_stop_climate(self, vin: str, **kwargs):
        """Stop climate control via the underlying connection."""
        _LOGGER.debug("Initiating Stop Climate Control Service...")
        vin = service.data.get(CONF_VIN).lower()

        await self.connection.stop_climate_control(vin=vin.lower())

    async def async_set_climate_temp(self, vin: str, temperature: float) -> None:
        """Set the target climate temperature using the GET/PUT settings endpoint."""
        _LOGGER.debug("Setting climate temperature for VIN %s to %.1f C via settings endpoint", vin, temperature)
        vin_upper = vin.upper() # Ensure VIN is uppercase for API calls

        try:
            # 1. Get current full status to extract some settings
            # This response has the nested structure.
            current_status_response = await self.connection.async_get_climate_settings(
                vin_upper
            )
            if not current_status_response:
                _LOGGER.error(
                    "Failed to get current climate status/settings for VIN %s. Cannot set temperature.",
                    vin,
                )
                return

            # Safely extract the current settings part from the nested structure
            current_settings_value = (
                current_status_response.get("climatisation", {})
                .get("climatisationSettings", {})
                .get("value", {})
            )

            if not current_settings_value:
                 _LOGGER.warning(
                     "Could not find current 'climatisationSettings.value' in response for VIN %s. Proceeding with defaults.",
                     vin
                 )
                 # Define defaults if current settings aren't found, might be risky
                 current_settings_value = {
                     "climatizationAtUnlock": False,
                     "windowHeatingEnabled": True, # Default based on example? Verify!
                     "zoneFrontLeftEnabled": False, # Default? Verify!
                     "zoneFrontRightEnabled": False, # Default? Verify!
                 }


            # 2. Modify the temperature
            # Make a copy to avoid modifying the original potentially cached dict
            updated_settings = {
                "targetTemperature": float(temperature),  # Use the requested temperature (already in C)
                "targetTemperatureUnit": "celsius",
                "climatizationAtUnlock": current_settings_value.get(
                    "climatizationAtUnlock", False # Default if missing
                ),
                "windowHeatingEnabled": current_settings_value.get(
                    "windowHeatingEnabled", True # Default if missing (based on example)
                ),
                "zoneFrontLeftEnabled": current_settings_value.get(
                    "zoneFrontLeftEnabled", False # Default if missing
                ),
                "zoneFrontRightEnabled": current_settings_value.get(
                    "zoneFrontRightEnabled", False # Default if missing
                ),
                "climatisationWithoutExternalPower": True,
                # Add zoneRearLeftEnabled / zoneRearRightEnabled if the PUT API expects them
                #"zoneRearLeftEnabled": current_settings_value.get("zoneRearLeftEnabled", False),
                #"zoneRearRightEnabled": current_settings_value.get("zoneRearRightEnabled", False),
            }

            _LOGGER.debug("Updated settings object for PUT: %s", updated_settings)

            # 3. PUT the updated settings
            success = await self.connection.async_set_climate_settings(vin_upper, updated_settings)

            if success:
                _LOGGER.info("Climate temperature settings update request sent successfully for VIN %s", vin)
                # Trigger a refresh shortly after to see the change reflected
                self.hass.async_create_task(self._refresh_after_action(vin))
            else:
                _LOGGER.error("Failed to PUT updated climate settings for VIN %s", vin)

        except Exception as e:
            _LOGGER.error("Error setting climate temperature via settings endpoint for VIN %s: %s", vin, e, exc_info=True)

    async def async_set_window_heating(self, vin: str, enable: bool) -> bool:
        """Enable or disable window heating via the PUT settings endpoint."""
        action = "Enable" if enable else "Disable"
        _LOGGER.debug(
            "%s window heating for VIN %s via settings endpoint",
            action,
            vin
        )
        vin_upper = vin.upper()

        try:
            # 1. Get current full status to extract settings
            current_status_response = await self.connection.async_get_climate_settings(vin_upper)
            if not current_status_response:
                _LOGGER.error("Failed to get current climate settings for VIN %s. Cannot set window heating.", vin)
                return False

            current_settings_value = (
                current_status_response.get("climatisation", {})
                .get("climatisationSettings", {})
                .get("value", {})
            )
            if not current_settings_value:
                _LOGGER.error("Could not find current 'climatisationSettings.value' in response for VIN %s. Cannot set window heating.", vin)
                return False # Cannot proceed without knowing other settings

            # 2. Construct the NEW settings payload required by the PUT endpoint
            updated_settings_payload = {
                "targetTemperature": current_settings_value.get('targetTemperature_C', 21), # Keep current temp (use _C version)
                "targetTemperatureUnit": "celsius",
                "climatizationAtUnlock": current_settings_value.get("climatizationAtUnlock", False),
                "windowHeatingEnabled": bool(enable), # <<< Set the desired state
                "zoneFrontLeftEnabled": current_settings_value.get("zoneFrontLeftEnabled", False),
                "zoneFrontRightEnabled": current_settings_value.get("zoneFrontRightEnabled", False),
                "climatisationWithoutExternalPower": True, # Assuming this is required/default
            }
            _LOGGER.debug("Constructed settings payload for PUT (Window Heat): %s", updated_settings_payload)

            # 3. PUT the specifically constructed payload
            success = await self.connection.async_set_climate_settings(vin_upper, updated_settings_payload)

            if success:
                _LOGGER.info("Window heating state update request sent successfully for VIN %s", vin)
                self.hass.async_create_task(self._refresh_after_action(vin))
            return success

        except Exception as e:
            _LOGGER.error("Error setting window heating for VIN %s: %s", vin, e, exc_info=True)
            return False
 

    async def handle_notification(self, vin: str, action: str) -> None:
        await self._refresh_vehicle_data(vin)

    async def refresh_vehicle_data(self, service):
        vin = service.data.get(CONF_VIN).lower()
        await self._refresh_vehicle_data(vin)

    async def _refresh_vehicle_data(self, vin):
        redacted_vin = "*" * (len(vin) - 4) + vin[-4:]
        res = await self.connection.refresh_vehicle_data(vin)

        if res is True:
            _LOGGER.debug("Refresh vehicle data successful for VIN: %s", redacted_vin)
            self.hass.bus.fire(
                "{}_{}".format(DOMAIN, REFRESH_VEHICLE_DATA_COMPLETED_EVENT),
                {"vin": redacted_vin},
            )
        elif res == "disabled":
            _LOGGER.debug("Refresh vehicle data is disabled for VIN: %s", redacted_vin)
        else:
            _LOGGER.debug("Refresh vehicle data failed for VIN: %s", redacted_vin)
            self.hass.bus.fire(
                "{}_{}".format(DOMAIN, REFRESH_VEHICLE_DATA_FAILED_EVENT),
                {"vin": redacted_vin},
            )

        _LOGGER.debug("Requesting to refresh cloud data in %d seconds...", UPDATE_SLEEP)
        await asyncio.sleep(UPDATE_SLEEP)

        try:
            _LOGGER.debug("Requesting to refresh cloud data now...")
            await self.update(utcnow())
        except Exception as e:
            _LOGGER.exception("Refresh cloud data failed: %s", str(e))

    # --- Helper method to trigger refresh after an action ---
    async def _refresh_after_action(self, vin: str, delay: int = UPDATE_SLEEP):
        """Schedule a refresh after performing an action."""
        _LOGGER.debug("Scheduling cloud data refresh in %d seconds after action for VIN %s", delay, vin)
        await asyncio.sleep(delay)
        try:
            _LOGGER.debug("Requesting post-action cloud data refresh now...")
            await self.update(utcnow())
        except Exception as e:
            _LOGGER.exception("Post-action refresh cloud data failed: %s", str(e))
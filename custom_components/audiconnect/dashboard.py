#  Utilities for integration with Home Assistant (directly or via MQTT)

import logging
import re

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTime,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfPower,
    UnitOfElectricCurrent,
    EntityCategory,
)
from .util import parse_datetime

_LOGGER = logging.getLogger(__name__)


class Instrument:
    def __init__(self, component, attr, name, icon=None):
        self._attr = attr
        self._component = component
        self._name = name
        self._connection = None
        self._vehicle = None
        self._icon = icon

    def __repr__(self):
        return self.full_name

    def camel2slug(self, s):
        """Convert camelCase to camel_case.
            >>> camel2slug('fooBar')
        'foo_bar'
        """
        return re.sub("([A-Z])", "_\\1", s).lower().lstrip("_")

    @property
    def slug_attr(self):
        return self.camel2slug(self._attr.replace(".", "_"))

    def setup(self, connection, vehicle, mutable=True, **config):
        self._connection = connection
        self._vehicle = vehicle

        if not mutable and self.is_mutable:
            _LOGGER.debug("Skipping %s because mutable", self)
            return False

        if not self.is_supported:
            if self._component == "climate" and not self.is_climate_supported(vehicle):
                 _LOGGER.debug("%s Climate component support check failed.", self)
                 return False
            # _LOGGER.debug(
            #     "%s (%s:%s) is not supported", self, type(self).__name__, self._attr,
            # )
            return False

        # _LOGGER.debug("%s is supported", self)

        return True

    @property
    def component(self):
        return self._component

    @property
    def icon(self):
        return self._icon

    @property
    def name(self):
        return self._name

    @property
    def attr(self):
        return self._attr

    @property
    def vehicle_name(self):
        return self._vehicle.title

    @property
    def full_name(self):
        return "{} {}".format(self.vehicle_name, self._name)

    @property
    def vehicle_model(self):
        return self._vehicle.model

    @property
    def vehicle_model_year(self):
        return self._vehicle.model_year

    @property
    def vehicle_model_family(self):
        return self._vehicle.model_family

    @property
    def vehicle_vin(self):
        return self._vehicle.vin

    @property
    def vehicle_csid(self):
        return self._vehicle.csid

    @property
    def is_mutable(self):
        raise NotImplementedError("Must be set")

    @property
    def is_supported(self):
        supported = self._attr + "_supported"
        if hasattr(self._vehicle, supported):
            return getattr(self._vehicle, supported)
        if hasattr(self._vehicle, self._attr):
            return True
        return False

    @property
    def str_state(self):
        # Keep existing logic for other components
        # Add specific formatting for climate if desired, otherwise use raw state
        if self._component == "climate":
            state_val = self.state # Get the raw state ('on'/'off')
            temp_val = self.target_temperature # Get the temp
            if temp_val is not None:
                 return f"{state_val} ({temp_val}°C)"
            else:
                 return f"{state_val}"
        # Existing logic...
        if self.unit:
            return "{} {}".format(self.state, self.unit)
        else:
            return "%s" % self.state

    @property
    def state(self):
        """Return the primary state for the component."""
        if self._component == "climate":
            # For climate, the primary state is the HVAC mode ('on', 'off', etc.)
            # Get it from the vehicle property
            return getattr(self._vehicle, 'climatisation_state', 'unknown') # <--- Access vehicle property
        elif hasattr(self._vehicle, self._attr):
             # Existing logic for sensors etc. using self._attr
             return getattr(self._vehicle, self._attr)
        # Fallback if needed (though less likely now with explicit climate handling)
        # return self._vehicle.get_attr(self._attr) # Original fallback if get_attr exists
        return None

    @property
    def target_temperature(self):
        """Return the target temperature, only relevant for climate."""
        if self._component == "climate":
            # Get target temp directly from the vehicle property
            return getattr(self._vehicle, 'target_temperature', None) # <--- Access vehicle property
        return None # Return None for non-climate components


    # Add other properties if AudiClimate needs them from the Instrument
    # E.g., current_temperature (if available on vehicle)
    @property
    def current_temperature(self):
         if self._component == "climate":
             # Assuming AudiConnectVehicle has an 'outdoor_temperature' property
             return getattr(self._vehicle, 'outdoor_temperature', None)
         return None

    # Ensure vehicle_vin is accessible if needed by AudiClimate
    @property
    def vehicle_vin(self):
         return self._vehicle.vin

    @property
    def attributes(self):
        """Return additional state attributes."""
        attrs = {}
        if self._component == "climate":
            # Add specific climate attributes if needed
            attrs["remaining_time_min"] = getattr(self._vehicle, 'remaining_climatisation_time', None)
            attrs["window_heating_enabled"] = getattr(self._vehicle, 'windowHeatingEnabled', None) # Assuming stored in state
            attrs["zone_front_left_enabled"] = getattr(self._vehicle, 'zoneFrontLeftEnabled', None) # Assuming stored in state
            attrs["zone_front_right_enabled"] = getattr(self._vehicle, 'zoneFrontRightEnabled', None)# Assuming stored in state
            # Filter out None values
            attrs = {k: v for k, v in attrs.items() if v is not None}
        # You might add common attributes here too
        return attrs



    # Specific check for climate component support
    def is_climate_supported(self, vehicle):
         return vehicle.climatisation_state_supported and vehicle.target_temperature_supported

class Sensor(Instrument):
    def __init__(
        self,
        attr,
        name,
        icon=None,
        unit=None,
        state_class=None,
        device_class=None,
        entity_category=None,
        extra_state_attributes=None,
    ):
        super().__init__(component="sensor", attr=attr, name=name, icon=icon)
        self.device_class = device_class
        self._unit = unit
        self.state_class = state_class
        self.entity_category = entity_category
        self.extra_state_attributes = extra_state_attributes
        self._convert = False

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        if self.unit:
            return "{} {}".format(self.state, self.unit)
        else:
            return "%s" % self.state

    @property
    def state(self):
        return super().state

    @property
    def unit(self):
        supported = self._attr + "_unit"
        if hasattr(self._vehicle, supported):
            return getattr(self._vehicle, supported)

        return self._unit


class BinarySensor(Instrument):
    def __init__(self, attr, name, device_class=None, icon=None, entity_category=None):
        super().__init__(component="binary_sensor", attr=attr, name=name, icon=icon)
        self.device_class = device_class
        self.entity_category = entity_category

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        if self.device_class in ["door", "window"]:
            return "Open" if self.state else "Closed"
        if self.device_class == "safety":
            return "Warning!" if self.state else "OK"
        if self.device_class == "plug":
            return "Charging" if self.state else "Plug removed"
        if self.device_class == "lock":
            return "Unlocked" if self.state else "Locked"
        if self.state is None:
            _LOGGER.error("Can not encode state %s:%s", self._attr, self.state)
            return "?"
        return "On" if self.state else "Off"

    @property
    def state(self):
        val = super().state
        if isinstance(val, (bool, list)):
            #  for list (e.g. bulb_failures):
            #  empty list (False) means no problem
            return bool(val)
        elif isinstance(val, str):
            return val != "Normal"
        return val

    @property
    def is_on(self):
        return self.state


class Lock(Instrument):
    def __init__(self):
        super().__init__(component="lock", attr="lock", name="Door lock")

    @property
    def is_mutable(self):
        return True

    @property
    def str_state(self):
        return "Locked" if self.state else "Unlocked"

    @property
    def state(self):
        return self._vehicle.doors_trunk_status == "Locked"

    @property
    def is_locked(self):
        return self.state

    async def lock(self):
        await self._connection.set_vehicle_lock(self.vehicle_vin, True)

    async def unlock(self):
        await self._connection.set_vehicle_lock(self.vehicle_vin, False)


class Switch(Instrument):
    def __init__(self, attr, name, icon):
        super().__init__(component="switch", attr=attr, name=name, icon=icon)

    @property
    def is_mutable(self):
        return True

    @property
    def str_state(self):
        return "On" if self.state else "Off"

    def is_on(self):
        return self.state

    def turn_on(self):
        pass

    def turn_off(self):
        pass


class Climate(Instrument):
    """Represents the Climate Control component."""
    def __init__(self):
        # Use a relevant attribute name that might exist or just a placeholder
        # The core functionality relies on the component type being 'climate'
        # and the HA entity accessing properties via the vehicle object.
        super().__init__(
            component="climate",
            attr="climate_control", # Placeholder attribute name
            name="Climate Control", # Entity name suffix
            icon="mdi:thermostat",   # Default climate icon
        )

    @property
    def is_mutable(self):
        # Climate control involves actions (setting temp, turning on/off)
        return True

    @property
    def is_supported(self):
        # Override is_supported specifically for Climate
        # Check if the vehicle object supports both essential climate properties
        # Ensure AudiConnectVehicle has these properties defined
        if self._vehicle:
             has_state = getattr(self._vehicle, "climatisation_state_supported", False)
             has_target = getattr(self._vehicle, "target_temperature_supported", False)
             _LOGGER.debug("Climate support check: State=%s, TargetTemp=%s", has_state, has_target)
             return has_state and has_target
        return False


class Preheater(Instrument):
    def __init__(self):
        super().__init__(
            component="switch",
            attr="preheater_active",
            name="Preheater",
            icon="mdi:radiator",
        )

    @property
    def is_mutable(self):
        return True

    @property
    def str_state(self):
        return "On" if self.state else "Off"

    def is_on(self):
        return self.state

    async def turn_on(self):
        await self._connection.set_vehicle_pre_heater(self.vehicle_vin, True)

    async def turn_off(self):
        await self._connection.set_vehicle_pre_heater(self.vehicle_vin, False)


class Position(Instrument):
    def __init__(self):
        super().__init__(component="device_tracker", attr="position", name="Position")

    @property
    def is_mutable(self):
        return False

    @property
    def state(self):
        state = super().state or {}
        return (
            state.get("latitude", None),
            state.get("longitude", None),
            state.get("timestamp", None),
            state.get("parktime", None),
        )

    @property
    def str_state(self):
        state = super().state or {}
        ts = state.get("timestamp")
        pt = state.get("parktime")
        return (
            state.get("latitude", None),
            state.get("longitude", None),
            str(ts.astimezone(tz=None)) if ts else None,
            str(pt.astimezone(tz=None)) if pt else None,
        )


class TripData(Instrument):
    def __init__(self, attr, name):
        super().__init__(component="sensor", attr=attr, name=name)
        self.device_class = SensorDeviceClass.TIMESTAMP
        self.unit = None
        self.state_class = None
        self.entity_category = None

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        val = super().state
        txt = ""

        if val["averageElectricEngineConsumption"] is not None:
            txt = "{}{}_kWh__".format(txt, val["averageElectricEngineConsumption"])

        if val["averageFuelConsumption"] is not None:
            txt = "{}{}_ltr__".format(txt, val["averageFuelConsumption"])

        return "{}{}_kmh__{}:{:02d}h_({}_m)__{}_km__{}-{}_km".format(
            txt,
            val["averageSpeed"],
            int(val["traveltime"] / 60),
            val["traveltime"] % 60,
            val["traveltime"],
            val["mileage"],
            val["startMileage"],
            val["overallMileage"],
        )

    @property
    def state(self):
        td = super().state
        return parse_datetime(td["timestamp"])

    @property
    def extra_state_attributes(self):
        td = super().state
        attr = {
            "averageElectricEngineConsumption": td.get(
                "averageElectricEngineConsumption", None
            ),
            "averageFuelConsumption": td.get("averageFuelConsumption", None),
            "averageSpeed": td.get("averageSpeed", None),
            "mileage": td.get("mileage", None),
            "overallMileage": td.get("overallMileage", None),
            "startMileage": td.get("startMileage", None),
            "traveltime": td.get("traveltime", None),
            "tripID": td.get("tripID", None),
            "zeroEmissionDistance": td.get("zeroEmissionDistance", None),
        }
        return attr


class LastUpdate(Instrument):
    def __init__(self):
        super().__init__(
            component="sensor",
            attr="last_update_time",
            name="Last Update",
            icon="mdi:update",
        )
        self.device_class = SensorDeviceClass.TIMESTAMP
        self.unit = None
        self.state_class = None
        self.entity_category = None
        self.extra_state_attributes = None

    @property
    def is_mutable(self):
        return False

    @property
    def str_state(self):
        ts = super().state
        return ts.astimezone(tz=None).isoformat() if ts else None

    @property
    def state(self):
        return super().state


def create_instruments():
    return [
        Position(),
        LastUpdate(),
        TripData(attr="shortterm_current", name="ShortTerm Trip Data"),
        TripData(attr="shortterm_reset", name="ShortTerm Trip User Reset"),
        TripData(attr="longterm_current", name="LongTerm Trip Data"),
        TripData(attr="longterm_reset", name="LongTerm Trip User Reset"),
        Lock(),
        Preheater(),
        Climate(),
        Sensor(
            attr="model",
            name="Model",
            icon="mdi:car-info",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="mileage",
            name="Mileage",
            icon="mdi:counter",
            unit=UnitOfLength.KILOMETERS,
            state_class=SensorStateClass.TOTAL_INCREASING,
            device_class=SensorDeviceClass.DISTANCE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="service_adblue_distance",
            name="AdBlue range",
            icon="mdi:map-marker-distance",
            unit=UnitOfLength.KILOMETERS,
            device_class=SensorDeviceClass.DISTANCE,
        ),
        Sensor(
            attr="range",
            name="Range",
            icon="mdi:map-marker-distance",
            unit=UnitOfLength.KILOMETERS,
            device_class=SensorDeviceClass.DISTANCE,
        ),
        Sensor(
            attr="hybrid_range",
            name="hybrid Range",
            icon="mdi:map-marker-distance",
            unit=UnitOfLength.KILOMETERS,
            device_class=SensorDeviceClass.DISTANCE,
        ),
        Sensor(
            attr="service_inspection_time",
            name="Service inspection time",
            icon="mdi:room-service-outline",
            unit=UnitOfTime.DAYS,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="service_inspection_distance",
            name="Service inspection distance",
            icon="mdi:room-service-outline",
            unit=UnitOfLength.KILOMETERS,
            device_class=SensorDeviceClass.DISTANCE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="oil_change_time",
            name="Oil change time",
            icon="mdi:oil",
            unit=UnitOfTime.DAYS,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="oil_change_distance",
            name="Oil change distance",
            icon="mdi:oil",
            unit=UnitOfLength.KILOMETERS,
            device_class=SensorDeviceClass.DISTANCE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="oil_level",
            name="Oil level",
            icon="mdi:oil",
            unit=PERCENTAGE,
        ),
        Sensor(
            attr="charging_state",
            name="Charging state",
            icon="mdi:car-battery",
        ),
        Sensor(
            attr="charging_mode",
            name="Charging mode",
        ),
        Sensor(
            attr="energy_flow",
            name="Energy flow",
        ),
        Sensor(
            attr="max_charge_current",
            name="Max charge current",
            icon="mdi:current-ac",
            unit=UnitOfElectricCurrent.AMPERE,
            device_class=SensorDeviceClass.CURRENT,
        ),
        Sensor(
            attr="primary_engine_type",
            name="Primary engine type",
            icon="mdi:engine",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="secondary_engine_type",
            name="Secondary engine type",
            icon="mdi:engine",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="primary_engine_range",
            name="Primary engine range",
            icon="mdi:map-marker-distance",
            unit=UnitOfLength.KILOMETERS,
            device_class=SensorDeviceClass.DISTANCE,
        ),
        Sensor(
            attr="secondary_engine_range",
            name="Secondary engine range",
            icon="mdi:map-marker-distance",
            unit=UnitOfLength.KILOMETERS,
            device_class=SensorDeviceClass.DISTANCE,
        ),
        Sensor(
            attr="primary_engine_range_percent",
            name="Primary engine Percent",
            icon="mdi:gauge",
            unit=PERCENTAGE,
        ),
        Sensor(
            attr="car_type",
            name="Car Type",
            icon="mdi:car-info",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="secondary_engine_range_percent",
            name="Secondary engine Percent",
            icon="mdi:gauge",
            unit=PERCENTAGE,
        ),
        Sensor(
            attr="charging_power",
            name="Charging power",
            icon="mdi:flash",
            unit=UnitOfPower.KILO_WATT,
            device_class=SensorDeviceClass.POWER,
        ),
        Sensor(
            attr="actual_charge_rate",
            name="Charging rate",
            icon="mdi:electron-framework",
        ),
        Sensor(
            attr="tank_level",
            name="Tank level",
            icon="mdi:gauge",
            unit=PERCENTAGE,
        ),
        Sensor(
            attr="state_of_charge",
            name="State of charge",
            icon="mdi:ev-station",
            unit=PERCENTAGE,
        ),
        Sensor(
            attr="remaining_charging_time",
            name="Remaining charge time",
            icon="mdi:battery-charging",
        ),
        Sensor(
            attr="charging_complete_time",
            name="Charging Complete Time",
            icon="mdi:battery-charging",
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        Sensor(
            attr="target_state_of_charge",
            name="Target State of charge",
            icon="mdi:ev-station",
            unit=PERCENTAGE,
        ),
        BinarySensor(
            attr="plug_state",
            name="Plug state",
            icon="mdi:ev-plug-type1",
            device_class=BinarySensorDeviceClass.PLUG,
        ),
        BinarySensor(
            attr="plug_lock_state",
            name="Plug Lock state",
            icon="mdi:ev-plug-type1",
            device_class=BinarySensorDeviceClass.LOCK,
        ),
        Sensor(
            attr="external_power",
            name="External Power",
            icon="mdi:ev-station",
        ),
        Sensor(
            attr="plug_led_color",
            name="Plug LED Color",
            icon="mdi:ev-plug-type1",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        Sensor(
            attr="doors_trunk_status",
            name="Doors/trunk state",
            icon="mdi:car-door",
        ),
        Sensor(
            attr="climatisation_state",
            name="Climatisation state",
            icon="mdi:air-conditioner",
        ),
        Sensor(
            attr="outdoor_temperature",
            name="Outdoor Temperature",
            icon="mdi:temperature-celsius",
            unit=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
        ),
        Sensor(
            attr="park_time",
            name="Park Time",
            icon="mdi:car-clock",
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        Sensor(
            attr="remaining_climatisation_time",
            name="Remaining Climatisation Time",
            icon="mdi:fan-clock",
            unit=UnitOfTime.MINUTES,
        ),
        BinarySensor(
            attr="glass_surface_heating",
            name="Glass Surface Heating",
            icon="mdi:car-defrost-front",
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        Sensor(
            attr="preheater_duration",
            name="Preheater runtime",
            icon="mdi:clock",
            unit=UnitOfTime.MINUTES,
        ),
        Sensor(
            attr="preheater_remaining",
            name="Preheater remaining",
            icon="mdi:clock",
            unit=UnitOfTime.MINUTES,
        ),
        BinarySensor(
            attr="sun_roof",
            name="Sun roof",
            device_class=BinarySensorDeviceClass.WINDOW,
        ),
        BinarySensor(
            attr="roof_cover",
            name="Roof Cover",
            device_class=BinarySensorDeviceClass.WINDOW,
        ),
        BinarySensor(
            attr="parking_light",
            name="Parking light",
            device_class=BinarySensorDeviceClass.SAFETY,
            icon="mdi:lightbulb",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="any_window_open",
            name="Windows",
            device_class=BinarySensorDeviceClass.WINDOW,
        ),
        BinarySensor(
            attr="any_door_unlocked",
            name="Doors lock",
            device_class=BinarySensorDeviceClass.LOCK,
        ),
        BinarySensor(
            attr="any_door_open",
            name="Doors",
            device_class=BinarySensorDeviceClass.DOOR,
        ),
        BinarySensor(
            attr="trunk_unlocked",
            name="Trunk lock",
            device_class=BinarySensorDeviceClass.LOCK,
        ),
        BinarySensor(
            attr="trunk_open",
            name="Trunk",
            device_class=BinarySensorDeviceClass.DOOR,
        ),
        BinarySensor(
            attr="hood_open",
            name="Hood",
            device_class=BinarySensorDeviceClass.DOOR,
        ),
        BinarySensor(
            attr="left_front_door_open",
            name="Left front door",
            device_class=BinarySensorDeviceClass.DOOR,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="right_front_door_open",
            name="Right front door",
            device_class=BinarySensorDeviceClass.DOOR,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="left_rear_door_open",
            name="Left rear door",
            device_class=BinarySensorDeviceClass.DOOR,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="right_rear_door_open",
            name="Right rear door",
            device_class=BinarySensorDeviceClass.DOOR,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="left_front_window_open",
            name="Left front window",
            device_class=BinarySensorDeviceClass.WINDOW,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="right_front_window_open",
            name="Right front window",
            device_class=BinarySensorDeviceClass.WINDOW,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="left_rear_window_open",
            name="Left rear window",
            device_class=BinarySensorDeviceClass.WINDOW,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="right_rear_window_open",
            name="Right rear window",
            device_class=BinarySensorDeviceClass.WINDOW,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="braking_status",
            name="Braking status",
            device_class=BinarySensorDeviceClass.SAFETY,
            icon="mdi:car-brake-abs",
        ),
        BinarySensor(
            attr="oil_level_binary",
            name="Oil Level Binary",
            icon="mdi:oil",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BinarySensor(
            attr="is_moving",
            name="Is moving",
            icon="mdi:motion-outline",
            device_class=BinarySensorDeviceClass.MOVING,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    ]

class Dashboard:
    def __init__(self, connection, vehicle, **config):
        self.instruments = [
            instrument
            for instrument in create_instruments()
            if instrument.setup(connection, vehicle, **config)
        ]

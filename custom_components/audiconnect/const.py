DOMAIN = "audiconnect"

CONF_VIN = "vin"
CONF_CARNAME = "carname"
CONF_ACTION = "action"
CONF_CLIMATE_TEMP_F = "temp_f"
CONF_CLIMATE_TEMP_C = "temp_c"
CONF_CLIMATE_GLASS = "glass_heating"
CONF_CLIMATE_SEAT_FL = "seat_fl"
CONF_CLIMATE_SEAT_FR = "seat_fr"
CONF_CLIMATE_SEAT_RL = "seat_rl"
CONF_CLIMATE_SEAT_RR = "seat_rr"
CONF_SCAN_INITIAL = "scan_initial"
CONF_SCAN_ACTIVE = "scan_active"
CONF_API_LEVEL = "api_level"

MIN_UPDATE_INTERVAL = 15
DEFAULT_UPDATE_INTERVAL = 15
UPDATE_SLEEP = 5
DEFAULT_API_LEVEL = 0

CONF_SPIN = "spin"
CONF_REGION = "region"
CONF_SERVICE_URL = "service_url"
CONF_MUTABLE = "mutable"

SIGNAL_STATE_UPDATED = "{}.updated".format(DOMAIN)
TRACKER_UPDATE = f"{DOMAIN}_tracker_update"
CLIMATE_UPDATE = f"{DOMAIN}_climate_update" # Add this line for climate updates

RESOURCES = [
    "position",
    "last_update_time",
    "shortterm_current",
    "shortterm_reset",
    "longterm_current",
    "longterm_reset",
    "mileage",
    "range",
    "service_inspection_time",
    "service_inspection_distance",
    "service_adblue_distance",
    "oil_change_time",
    "oil_change_distance",
    "oil_level",
    "charging_state",
    "charging_mode",
    "energy_flow",
    "max_charge_current",
    "engine_type1",
    "engine_type2",
    "parking_light",
    "any_window_open",
    "any_door_unlocked",
    "any_door_open",
    "trunk_unlocked",
    "trunk_open",
    "hood_open",
    "tank_level",
    "state_of_charge",
    "remaining_charging_time",
    "plug_state",
    "sun_roof",
    "doors_trunk_status",
    "left_front_door_open",
    "right_front_door_open",
    "left_rear_door_open",
    "right_rear_door_open",
    "left_front_window_open",
    "right_front_window_open",
    "left_rear_window_open",
    "right_rear_window_open",
    "braking_status",
    "is_moving",
]

COMPONENTS = {
    "sensor": "sensor",
    "binary_sensor": "binary_sensor",
    "lock": "lock",
    "device_tracker": "device_tracker",
    "switch": "switch",
    "climate": "climate",
}

REGION_EUROPE: str = "DE"
REGION_CANADA: str = "CA"
REGION_USA: str = "US"
REGION_CHINA: str = "CN"

REGIONS = {
    1: REGION_EUROPE,
    2: REGION_CANADA,
    3: REGION_USA,
    4: REGION_CHINA,
}

API_LEVELS = [0, 1]

import logging
from .util import get_attr

_LOGGER = logging.getLogger(__name__)


class VehicleData:
    def __init__(self, config_entry):
        self.sensors = set()
        self.binary_sensors = set()
        self.switches = set()
        self.device_trackers = set()
        self.climates = set()
        self.locks = set()
        self.config_entry = config_entry
        self.vehicle = None


class CurrentVehicleDataResponse:
    def __init__(self, data):
        data = data["CurrentVehicleDataResponse"]
        self.request_id = data["requestId"]
        self.vin = data["vin"]


class VehicleDataResponse:
    OLDAPI_MAPPING = {
        "frontRightLock": "LOCK_STATE_RIGHT_FRONT_DOOR",
        "frontRightOpen": "OPEN_STATE_RIGHT_FRONT_DOOR",
        "frontLeftLock": "LOCK_STATE_LEFT_FRONT_DOOR",
        "frontLeftOpen": "OPEN_STATE_LEFT_FRONT_DOOR",
        "rearRightLock": "LOCK_STATE_RIGHT_REAR_DOOR",
        "rearRightOpen": "OPEN_STATE_RIGHT_REAR_DOOR",
        "rearLeftLock": "LOCK_STATE_LEFT_REAR_DOOR",
        "rearLeftOpen": "OPEN_STATE_LEFT_REAR_DOOR",
        "trunkLock": "LOCK_STATE_TRUNK_LID",
        "trunkOpen": "OPEN_STATE_TRUNK_LID",
        "bonnetLock": "LOCK_STATE_HOOD",
        "bonnetOpen": "OPEN_STATE_HOOD",
        "sunRoofWindow": "STATE_SUN_ROOF_MOTOR_COVER",
        "frontLeftWindow": "STATE_LEFT_FRONT_WINDOW",
        "frontRightWindow": "STATE_RIGHT_FRONT_WINDOW",
        "rearLeftWindow": "STATE_LEFT_REAR_WINDOW",
        "rearRightWindow": "STATE_RIGHT_REAR_WINDOW",
        "roofCoverWindow": "STATE_ROOF_COVER_WINDOW",
    }

    def __init__(self, data):
        self.data_fields = []
        self.states = []

        self._tryAppendFieldWithTs(
            data, "TOTAL_RANGE", ["fuelStatus", "rangeStatus", "value", "totalRange_km"]
        )
        self._tryAppendFieldWithTs(
            data,
            "TANK_LEVEL_IN_PERCENTAGE",
            ["measurements", "fuelLevelStatus", "value", "currentFuelLevel_pct"],
        )
        self._tryAppendFieldWithTs(
            data,
            "UTC_TIME_AND_KILOMETER_STATUS",
            ["measurements", "odometerStatus", "value", "odometer"],
        )
        self._tryAppendFieldWithTs(
            data,
            "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
            [
                "vehicleHealthInspection",
                "maintenanceStatus",
                "value",
                "inspectionDue_days",
            ],
        )
        self._tryAppendFieldWithTs(
            data,
            "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
            [
                "vehicleHealthInspection",
                "maintenanceStatus",
                "value",
                "inspectionDue_km",
            ],
        )

        self._tryAppendFieldWithTs(
            data,
            "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
            [
                "vehicleHealthInspection",
                "maintenanceStatus",
                "value",
                "oilServiceDue_days",
            ],
        )
        self._tryAppendFieldWithTs(
            data,
            "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
            [
                "vehicleHealthInspection",
                "maintenanceStatus",
                "value",
                "oilServiceDue_km",
            ],
        )

        self._tryAppendFieldWithTs(
            data,
            "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
            ["oilLevel", "oilLevelStatus", "value", "value"],
        )
        self._tryAppendFieldWithTs(
            data,
            "ADBLUE_RANGE",
            ["measurements", "rangeStatus", "value", "adBlueRange"],
        )

        self._tryAppendFieldWithTs(
            data, "LIGHT_STATUS", ["vehicleLights", "lightsStatus", "value", "lights"]
        )

        self.appendWindowState(data)
        self.appendDoorState(data)

        self._tryAppendStateWithTs(
            data, "carType", -1, ["fuelStatus", "rangeStatus", "value", "carType"]
        )

        self._tryAppendStateWithTs(
            data,
            "engineTypeFirstEngine",
            -2,
            ["fuelStatus", "rangeStatus", "value", "primaryEngine", "type"],
        )
        self._tryAppendStateWithTs(
            data,
            "primaryEngineRange",
            -2,
            [
                "fuelStatus",
                "rangeStatus",
                "value",
                "primaryEngine",
                "remainingRange_km",
            ],
        )
        self._tryAppendStateWithTs(
            data,
            "primaryEngineRangePercent",
            -2,
            ["fuelStatus", "rangeStatus", "value", "primaryEngine", "currentSOC_pct"],
        )
        self._tryAppendStateWithTs(
            data,
            "engineTypeSecondEngine",
            -2,
            ["fuelStatus", "rangeStatus", "value", "secondaryEngine", "type"],
        )
        self._tryAppendStateWithTs(
            data,
            "secondaryEngineRange",
            -2,
            [
                "fuelStatus",
                "rangeStatus",
                "value",
                "secondaryEngine",
                "remainingRange_km",
            ],
        )
        self._tryAppendStateWithTs(
            data,
            "secondaryEngineRangePercent",
            -2,
            ["fuelStatus", "rangeStatus", "value", "secondaryEngine", "currentSOC_pct"],
        )
        self._tryAppendStateWithTs(
            data,
            "hybridRange",
            -1,
            ["fuelStatus", "rangeStatus", "value", "totalRange_km"],
        )
        self._tryAppendStateWithTs(
            data,
            "stateOfCharge",
            -1,
            ["charging", "batteryStatus", "value", "currentSOC_pct"],
        )
        self._tryAppendStateWithTs(
            data,
            "chargingState",
            -1,
            ["charging", "chargingStatus", "value", "chargingState"],
        )
        self._tryAppendStateWithTs(
            data,
            "chargeMode",
            -1,
            ["charging", "chargingStatus", "value", "chargeMode"],
        )
        self._tryAppendStateWithTs(
            data,
            "chargingPower",
            -1,
            ["charging", "chargingStatus", "value", "chargePower_kW"],
        )
        self._tryAppendStateWithTs(
            data,
            "actualChargeRate",
            -1,
            ["charging", "chargingStatus", "value", "chargeRate_kmph"],
        )
        self._tryAppendStateWithTs(
            data,
            "chargingMode",
            -1,
            ["charging", "chargingStatus", "value", "chargeType"],
        )
        self._tryAppendStateWithTs(
            data,
            "targetstateOfCharge",
            -1,
            ["charging", "chargingSettings", "value", "targetSOC_pct"],
        )
        self._tryAppendStateWithTs(
            data,
            "plugState",
            -1,
            ["charging", "plugStatus", "value", "plugConnectionState"],
        )
        self._tryAppendStateWithTs(
            data,
            "remainingChargingTime",
            -1,
            [
                "charging",
                "chargingStatus",
                "value",
                "remainingChargingTimeToComplete_min",
            ],
        )
        self._tryAppendStateWithTs(
            data,
            "plugLockState",
            -1,
            ["charging", "plugStatus", "value", "plugLockState"],
        )
        self._tryAppendStateWithTs(
            data,
            "externalPower",
            -1,
            ["charging", "plugStatus", "value", "externalPower"],
        )
        self._tryAppendStateWithTs(
            data,
            "plugledColor",
            -1,
            ["charging", "plugStatus", "value", "ledColor"],
        )
        self._tryAppendStateWithTs(
            data,
            "climatisationState",
            -1,
            ["climatisation", "auxiliaryHeatingStatus", "value", "climatisationState"],
        )
        # 2024 Q4 updated data structure for climate data
        self._tryAppendStateWithTs(
            data,
            "climatisationState",
            -1,
            ["climatisation", "climatisationStatus", "value", "climatisationState"],
        )
        self._tryAppendStateWithTs(
            data,
            "remainingClimatisationTime",
            -1,
            [
                "climatisation",
                "climatisationStatus",
                "value",
                "remainingClimatisationTime_min",
            ],
        )

    def _tryAppendStateWithTs(self, json, name, tsoff, loc):
        _LOGGER.debug(
            "TRY APPEND STATE: Searching for '%s' at location=%s, tsoff=%s",
            name,
            loc,
            tsoff,
        )

        ts = None
        val = self._getFromJson(json, loc)
        # _LOGGER.debug("Initial value retrieved for '%s': %s", name, val)

        if val is not None:
            loc[tsoff:] = ["carCapturedTimestamp"]
            # _LOGGER.debug("Updated loc for timestamp retrieval: %s", loc)
            ts = self._getFromJson(json, loc)
            # _LOGGER.debug("Timestamp retrieved for '%s': %s", name, ts)

        if val is not None and ts:
            self.states.append({"name": name, "value": val, "measure_time": ts})
            _LOGGER.debug(
                "TRY APPEND STATE: Found '%s' with value=%s, tsoff=%s, loc=%s, ts=%s",
                name,
                val,
                tsoff,
                loc,
                ts,
            )
        else:
            if val is None:
                _LOGGER.debug(
                    "TRY APPEND STATE: Value for '%s' is None; not appending state.",
                    name,
                )
            elif not ts:
                _LOGGER.debug(
                    "TRY APPEND STATE: Timestamp for '%s' is None or missing; not appending state.",
                    name,
                )

    def _tryAppendFieldWithTs(self, json, textId, loc):
        _LOGGER.debug(
            "TRY APPEND FIELD: Searching for '%s' at location=%s",
            textId,
            loc,
        )

        ts = None
        val = self._getFromJson(json, loc)
        # _LOGGER.debug("Initial value retrieved for '%s': %s", textId, val)

        if val is not None:
            loc[-1:] = ["carCapturedTimestamp"]
            # _LOGGER.debug("Updated loc for timestamp retrieval: %s", loc)
            ts = self._getFromJson(json, loc)
            # _LOGGER.debug("Timestamp retrieved for '%s': %s", textId, ts)

        if val is not None and ts:
            self.data_fields.append(
                Field(
                    {
                        "textId": textId,
                        "value": val,
                        "tsCarCaptured": ts,
                    }
                )
            )
            _LOGGER.debug(
                "TRY APPEND FIELD: Found '%s' with value=%s, loc=%s, ts=%s",
                textId,
                val,
                loc,
                ts,
            )
        else:
            if val is None:
                _LOGGER.debug(
                    "TRY APPEND FIELD: Value for '%s' is None or missing; not appending field.",
                    textId,
                )
            elif not ts:
                _LOGGER.debug(
                    "TRY APPEND FIELD: Timestamp for '%s' is None or missing; not appending field.",
                    textId,
                )

    def _getFromJson(self, json, loc):
        child = json
        for i in loc:
            if i not in child:
                return None
            child = child[i]
        return child

    def appendDoorState(self, data):
        _LOGGER.debug("APPEND DOOR: Starting to append doors...")
        doors = get_attr(data, "access.accessStatus.value.doors", [])
        tsCarCapturedAccess = get_attr(
            data, "access.accessStatus.value.carCapturedTimestamp"
        )
        _LOGGER.debug(
            "APPEND DOOR: Timestamp captured from car: %s", tsCarCapturedAccess
        )
        for door in doors:
            status = door["status"]
            name = door["name"]
            _LOGGER.debug(
                "APPEND DOOR: Processing door: %s with status: %s", name, status
            )
            if name + "Lock" not in self.OLDAPI_MAPPING:
                _LOGGER.debug(
                    "APPEND DOOR: Skipping door not mapped in OLDAPI_MAPPING: %s", name
                )
                continue
            lock = "0"
            open = "0"
            unsupported = False
            for state in status:
                if state == "unsupported":
                    unsupported = True
                    _LOGGER.debug("APPEND DOOR: Unsupported state for door: %s", name)
                if state == "locked":
                    lock = "2"
                if state == "closed":
                    open = "3"
            if not unsupported:
                doorFieldLock = {
                    "textId": self.OLDAPI_MAPPING[name + "Lock"],
                    "value": lock,
                    "tsCarCaptured": tsCarCapturedAccess,
                }
                _LOGGER.debug(
                    "APPEND DOOR: Appended door lock field: %s", doorFieldLock
                )
                self.data_fields.append(Field(doorFieldLock))

                doorFieldOpen = {
                    "textId": self.OLDAPI_MAPPING[name + "Open"],
                    "value": open,
                    "tsCarCaptured": tsCarCapturedAccess,
                }
                _LOGGER.debug(
                    "APPEND DOOR: Appended door open field: %s", doorFieldOpen
                )
                self.data_fields.append(Field(doorFieldOpen))
        _LOGGER.debug("APPEND DOOR: Finished appending doors")

    def appendWindowState(self, data):
        _LOGGER.debug("APPEND WINDOW: Starting to append windows...")
        windows = get_attr(data, "access.accessStatus.value.windows", [])
        tsCarCapturedAccess = get_attr(
            data, "access.accessStatus.value.carCapturedTimestamp"
        )
        _LOGGER.debug(
            "APPEND WINDOW: Timestamp captured from car: %s", tsCarCapturedAccess
        )
        for window in windows:
            name = window["name"]
            status = window["status"]
            _LOGGER.debug(
                "APPEND WINDOW: Processing window: %s with status: %s", name, status
            )
            if (
                status[0] == "unsupported"
            ) or name + "Window" not in self.OLDAPI_MAPPING:
                _LOGGER.debug(
                    "APPEND WINDOW: Skipping unsupported window or not mapped in OLDAPI_MAPPING: %s",
                    name,
                )
                continue
            windowField = {
                "textId": self.OLDAPI_MAPPING[name + "Window"],
                "value": "3" if status[0] == "closed" else "0",
                "tsCarCaptured": tsCarCapturedAccess,
            }
            _LOGGER.debug("APPEND WINDOW: Appended window field: %s", windowField)
            self.data_fields.append(Field(windowField))
        _LOGGER.debug("APPEND WINDOW: Finished appending windows")


class TripDataResponse:
    def __init__(self, data):
        self.data_fields = []

        self.tripID = data["tripID"]

        self.averageElectricEngineConsumption = None
        if "averageElectricEngineConsumption" in data:
            self.averageElectricEngineConsumption = (
                float(data["averageElectricEngineConsumption"]) / 10
            )

        self.averageFuelConsumption = None
        if "averageFuelConsumption" in data:
            self.averageFuelConsumption = float(data["averageFuelConsumption"]) / 10

        self.averageSpeed = None
        if "averageSpeed" in data:
            self.averageSpeed = int(data["averageSpeed"])

        self.mileage = None
        if "mileage" in data:
            self.mileage = int(data["mileage"])

        self.startMileage = None
        if "startMileage" in data:
            self.startMileage = int(data["startMileage"])

        self.traveltime = None
        if "traveltime" in data:
            self.traveltime = int(data["traveltime"])

        self.timestamp = None
        if "timestamp" in data:
            self.timestamp = data["timestamp"]

        self.overallMileage = None
        if "overallMileage" in data:
            self.overallMileage = int(data["overallMileage"])

        self.zeroEmissionDistance = None
        if "zeroEmissionDistance" in data:
            self.zeroEmissionDistance = int(data["zeroEmissionDistance"])


class Field:
    IDS = {
        "0x0": "UNKNOWN",
        "0x0101010002": "UTC_TIME_AND_KILOMETER_STATUS",
        "0x0203010001": "MAINTENANCE_INTERVAL_DISTANCE_TO_OIL_CHANGE",
        "0x0203010002": "MAINTENANCE_INTERVAL_TIME_TO_OIL_CHANGE",
        "0x0203010003": "MAINTENANCE_INTERVAL_DISTANCE_TO_INSPECTION",
        "0x0203010004": "MAINTENANCE_INTERVAL_TIME_TO_INSPECTION",
        "0x0203010006": "MAINTENANCE_INTERVAL_ALARM_INSPECTION",
        "0x0203010007": "MAINTENANCE_INTERVAL_MONTHLY_MILEAGE",
        "0x0203010005": "WARNING_OIL_CHANGE",
        "0x0204040001": "OIL_LEVEL_AMOUNT_IN_LITERS",
        "0x0204040002": "OIL_LEVEL_MINIMUM_WARNING",
        "0x0204040003": "OIL_LEVEL_DIPSTICKS_PERCENTAGE",
        "0x02040C0001": "ADBLUE_RANGE",
        "0x0301010001": "LIGHT_STATUS",
        "0x0301030001": "BRAKING_STATUS",
        "0x0301030005": "TOTAL_RANGE",
        "0x030103000A": "TANK_LEVEL_IN_PERCENTAGE",
        "0x0301040001": "LOCK_STATE_LEFT_FRONT_DOOR",
        "0x0301040002": "OPEN_STATE_LEFT_FRONT_DOOR",
        "0x0301040003": "SAFETY_STATE_LEFT_FRONT_DOOR",
        "0x0301040004": "LOCK_STATE_LEFT_REAR_DOOR",
        "0x0301040005": "OPEN_STATE_LEFT_REAR_DOOR",
        "0x0301040006": "SAFETY_STATE_LEFT_REAR_DOOR",
        "0x0301040007": "LOCK_STATE_RIGHT_FRONT_DOOR",
        "0x0301040008": "OPEN_STATE_RIGHT_FRONT_DOOR",
        "0x0301040009": "SAFETY_STATE_RIGHT_FRONT_DOOR",
        "0x030104000A": "LOCK_STATE_RIGHT_REAR_DOOR",
        "0x030104000B": "OPEN_STATE_RIGHT_REAR_DOOR",
        "0x030104000C": "SAFETY_STATE_RIGHT_REAR_DOOR",
        "0x030104000D": "LOCK_STATE_TRUNK_LID",
        "0x030104000E": "OPEN_STATE_TRUNK_LID",
        "0x030104000F": "SAFETY_STATE_TRUNK_LID",
        "0x0301040010": "LOCK_STATE_HOOD",
        "0x0301040011": "OPEN_STATE_HOOD",
        "0x0301040012": "SAFETY_STATE_HOOD",
        "0x0301050001": "STATE_LEFT_FRONT_WINDOW",
        "0x0301050003": "STATE_LEFT_REAR_WINDOW",
        "0x0301050005": "STATE_RIGHT_FRONT_WINDOW",
        "0x0301050007": "STATE_RIGHT_REAR_WINDOW",
        "0x0301050009": "STATE_DECK",
        "0x030105000B": "STATE_SUN_ROOF_MOTOR_COVER",
        "0x0301030006": "PRIMARY_RANGE",
        "0x0301030007": "PRIMARY_DRIVE",
        "0x0301030008": "SECONDARY_RANGE",
        "0x0301030009": "SECONDARY_DRIVE",
        "0x0301030002": "STATE_OF_CHARGE",
        "0x0301020001": "TEMPERATURE_OUTSIDE",
        "0x0202": "ACTIVE_INSTRUMENT_CLUSTER_WARNING",
    }

    def __init__(self, data):
        self.name = None
        self.id = data.get("id")
        self.unit = data.get("unit")
        self.value = data.get("value")
        self.measure_time = data.get("tsTssReceivedUtc")
        if self.measure_time is None:
            self.measure_time = data.get("tsCarCaptured")
        self.send_time = data.get("tsCarSentUtc")
        self.measure_mileage = data.get("milCarCaptured")
        self.send_mileage = data.get("milCarSent")

        for field_id, name in self.IDS.items():
            if field_id == self.id:
                self.name = name
                break
        if self.name is None:
            # No direct mapping found - maybe we've at least got a text id
            self.name = data.get("textId")

    def __str__(self):
        str_rep = str(self.name) + " " + str(self.value)
        if self.unit is not None:
            str_rep += self.unit
        return str_rep


class Vehicle:
    def __init__(self):
        self.vin = ""
        self.csid = ""
        self.model = ""
        self.model_year = ""
        self.model_family = ""
        self.title = ""

    def parse(self, data):
        self.vin = data.get("vin")
        self.csid = data.get("csid")
        if (
            data.get("vehicle") is not None
            and data.get("vehicle").get("media") is not None
        ):
            self.model = data.get("vehicle").get("media").get("longName")
        if (
            data.get("vehicle") is not None
            and data.get("vehicle").get("core") is not None
        ):
            self.model_year = data.get("vehicle").get("core").get("modelYear")
        if data.get("nickname") is not None and len(data.get("nickname")) > 0:
            self.title = data.get("nickname")
        elif (
            data.get("vehicle") is not None
            and data.get("vehicle").get("media") is not None
        ):
            self.title = data.get("vehicle").get("media").get("shortName")

    def __str__(self):
        return str(self.__dict__)


class VehiclesResponse:
    def __init__(self):
        self.vehicles = []
        self.blacklisted_vins = 0

    def parse(self, data):
        for item in data.get("userVehicles"):
            vehicle = Vehicle()
            vehicle.parse(item)
            self.vehicles.append(vehicle)

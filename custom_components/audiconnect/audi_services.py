import json
import uuid
import base64
import os
import re
import logging
import copy
from datetime import timedelta, datetime
from typing import Optional

from .audi_models import (
    TripDataResponse,
    CurrentVehicleDataResponse,
    VehicleDataResponse,
    VehiclesResponse,
)
from .audi_api import AudiAPI
from .const import DEFAULT_API_LEVEL
from .util import to_byte_array, get_attr

from hashlib import sha256, sha512
import hmac
import asyncio

from urllib.parse import urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup
from requests import RequestException

from typing import Dict


MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 10

SUCCEEDED = "succeeded"
FAILED = "failed"
REQUEST_SUCCESSFUL = "request_successful"
REQUEST_FAILED = "request_failed"

_LOGGER = logging.getLogger(__name__)


class BrowserLoginResponse:
    def __init__(self, response: requests.Response, url: str):
        self.response = response  # type: requests.Response
        self.url = url  # type : str

    def get_location(self) -> str:
        """
        Returns the location the previous request redirected to
        """
        location = self.response.headers["Location"]
        if location.startswith("/"):
            # Relative URL
            return BrowserLoginResponse.to_absolute(self.url, location)
        return location

    @classmethod
    def to_absolute(cls, absolute_url, relative_url) -> str:
        """
        Converts a relative url to an absolute url
        :param absolute_url: Absolute url used as baseline
        :param relative_url: Relative url (must start with /)
        :return: New absolute url
        """
        url_parts = urlparse(absolute_url)
        return url_parts.scheme + "://" + url_parts.netloc + relative_url


class AudiService:
    def __init__(self, api: AudiAPI, country: str, spin: str, api_level: int):
        self._api = api
        self._country = country
        self._language = None
        self._type = "Audi"
        self._spin = spin
        self._homeRegion = {}
        self._homeRegionSetter = {}
        self.mbbOAuthBaseURL = None
        self.mbboauthToken = None
        self.xclientId = None
        self._tokenEndpoint = ""
        self._bearer_token_json = None
        self._client_id = ""
        self._authorizationServerBaseURLLive = ""
        self._api_level = api_level

        if self._api_level is None:
            self._api_level = DEFAULT_API_LEVEL

        if self._country is None:
            self._country = "DE"

    def get_hidden_html_input_form_data(self, response, form_data: Dict[str, str]):
        # Now parse the html body and extract the target url, csrf token and other required parameters
        html = BeautifulSoup(response, "html.parser")
        form_inputs = html.find_all("input", attrs={"type": "hidden"})
        for form_input in form_inputs:
            name = form_input.get("name")
            form_data[name] = form_input.get("value")

        return form_data

    def get_post_url(self, response, url):
        # Now parse the html body and extract the target url, csrf token and other required parameters
        html = BeautifulSoup(response, "html.parser")
        form_tag = html.find("form")

        # Extract the target url
        action = form_tag.get("action")
        if action.startswith("http"):
            # Absolute url
            username_post_url = action
        elif action.startswith("/"):
            # Relative to domain
            username_post_url = BrowserLoginResponse.to_absolute(url, action)
        else:
            raise RequestException("Unknown form action: " + action)
        return username_post_url

    async def login(self, user: str, password: str, persist_token: bool = True):
        _LOGGER.debug("LOGIN: Starting login to Audi service...")
        await self.login_request(user, password)

    async def refresh_vehicle_data(self, vin: str):
        res = await self.request_current_vehicle_data(vin.upper())
        request_id = res.request_id

        checkUrl = "{homeRegion}/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests/{requestId}/jobstatus".format(
            homeRegion=await self._get_home_region(vin.upper()),
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            requestId=request_id,
        )

        await self.check_request_succeeded(
            checkUrl,
            "refresh vehicle data",
            REQUEST_SUCCESSFUL,
            REQUEST_FAILED,
            "requestStatusResponse.status",
        )

    async def request_current_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        data = await self._api.post(
            "{homeRegion}/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )
        return CurrentVehicleDataResponse(data)

    async def get_preheater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/status".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_stored_vehicle_data(self, vin: str):
        redacted_vin = "*" * (len(vin) - 4) + vin[-4:]
        JOBS2QUERY = {
            "access",
            "activeVentilation",
            "auxiliaryHeating",
            "batteryChargingCare",
            "batterySupport",
            "charging",
            "chargingProfiles",
            "chargingTimers",
            "climatisation",
            "climatisationTimers",
            "departureProfiles",
            "departureTimers",
            "fuelStatus",
            "honkAndFlash",
            "hybridCarAuxiliaryHeating",
            "lvBattery",
            "measurements",
            "oilLevel",
            "readiness",
            # "userCapabilities",
            "vehicleHealthInspection",
            "vehicleHealthWarnings",
            "vehicleLights",
        }
        self._api.use_token(self._bearer_token_json)
        data = await self._api.get(
            "https://{region}.bff.cariad.digital/vehicle/v1/vehicles/{vin}/selectivestatus?jobs={jobs}".format(
                region="emea" if self._country.upper() != "US" else "na",
                vin=vin.upper(),
                jobs=",".join(JOBS2QUERY),
            )
        )
        _LOGGER.debug("Vehicle data returned for VIN: %s: %s", redacted_vin, data)
        return VehicleDataResponse(data)

    async def get_charger(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_climater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_stored_position(self, vin: str):
        self._api.use_token(self._bearer_token_json)
        return await self._api.get(
            "https://{region}.bff.cariad.digital/vehicle/v1/vehicles/{vin}/parkingposition".format(
                region="emea" if self._country.upper() != "US" else "na",
                vin=vin.upper(),
            )
        )

    async def get_operations_list(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://mal-1a.prd.ece.vwg-connect.com/api/rolesrights/operationlist/v3/vehicles/"
            + vin.upper()
        )

    async def get_timer(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/departuretimer/v1/{type}/{country}/vehicles/{vin}/timer".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_vehicles(self):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://msg.volkswagen.de/fs-car/usermanagement/users/v1/{type}/{country}/vehicles".format(
                type=self._type, country=self._country
            )
        )

    async def get_vehicle_information(self):
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Name": "myAudi",
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "Accept-Language": "{l}-{c}".format(
                l=self._language, c=self._country.upper()
            ),
            "X-User-Country": self._country.upper(),
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Authorization": "Bearer " + self.audiToken["access_token"],
            "Content-Type": "application/json; charset=utf-8",
        }
        req_data = {
            "query": "query vehicleList {\n userVehicles {\n vin\n mappingVin\n vehicle { core { modelYear\n }\n media { shortName\n longName }\n }\n csid\n commissionNumber\n type\n devicePlatform\n mbbConnect\n userRole {\n role\n }\n vehicle {\n classification {\n driveTrain\n }\n }\n nickname\n }\n}"
        }
        req_rsp, rep_rsptxt = await self._api.request(
            "POST",
            "https://app-api.my.aoa.audi.com/vgql/v1/graphql"
            if self._country.upper() == "US"
            else "https://app-api.live-my.audi.com/vgql/v1/graphql",  # Starting in 2023, US users need to point at the aoa (Audi of America) URL.
            json.dumps(req_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        vins = json.loads(rep_rsptxt)
        if "data" not in vins:
            raise Exception("Invalid json in get_vehicle_information")

        response = VehiclesResponse()
        response.parse(vins["data"])
        return response

    async def get_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/vehicleMgmt/vehicledata/v2/{type}/{country}/vehicles/{vin}/".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_tripdata(self, vin: str, kind: str):
        self._api.use_token(self.vwToken)

        # read tripdata
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Name": "myAudi",
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-Client-ID": self.xclientId,
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Authorization": "Bearer " + self.vwToken["access_token"],
        }
        td_reqdata = {
            "type": "list",
            "from": "1970-01-01T00:00:00Z",
            # "from":(datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": (datetime.utcnow() + timedelta(minutes=90)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        data = await self._api.request(
            "GET",
            "{homeRegion}/api/bs/tripstatistics/v1/vehicles/{vin}/tripdata/{kind}".format(
                homeRegion=await self._get_home_region_setter(vin.upper()),
                vin=vin.upper(),
                kind=kind,
            ),
            None,
            params=td_reqdata,
            headers=headers,
        )
        td_sorted = sorted(
            data["tripDataList"]["tripData"],
            key=lambda k: k["overallMileage"],
            reverse=True,
        )
        # _LOGGER.debug("get_tripdata: td_sorted: %s", td_sorted)
        td_current = td_sorted[0]
        # FIX, TR/2023-03-25: Assign just in case td_sorted contains only one item
        td_reset_trip = td_sorted[0]

        for trip in td_sorted:
            if (td_current["startMileage"] - trip["startMileage"]) > 2:
                td_reset_trip = trip
                break
            else:
                td_current["tripID"] = trip["tripID"]
                td_current["startMileage"] = trip["startMileage"]
        _LOGGER.debug("TRIP DATA: td_current: %s", td_current)
        _LOGGER.debug("TRIP DATA: td_reset_trip: %s", td_reset_trip)

        return TripDataResponse(td_current), TripDataResponse(td_reset_trip)

    async def _fill_home_region(self, vin: str):
        self._homeRegion[vin] = "https://msg.volkswagen.de"
        self._homeRegionSetter[vin] = "https://mal-1a.prd.ece.vwg-connect.com"

        try:
            self._api.use_token(self.vwToken)
            res = await self._api.get(
                "https://mal-1a.prd.ece.vwg-connect.com/api/cs/vds/v1/vehicles/{vin}/homeRegion".format(
                    vin=vin
                )
            )
            if (
                res is not None
                and res.get("homeRegion") is not None
                and res["homeRegion"].get("baseUri") is not None
                and res["homeRegion"]["baseUri"].get("content") is not None
            ):
                uri = res["homeRegion"]["baseUri"]["content"]
                if uri != "https://mal-1a.prd.ece.vwg-connect.com/api":
                    self._homeRegionSetter[vin] = uri.split("/api")[0]
                    self._homeRegion[vin] = self._homeRegionSetter[vin].replace(
                        "mal-", "fal-"
                    )
        except Exception:
            pass

    async def _get_home_region(self, vin: str):
        if self._homeRegion.get(vin) is not None:
            return self._homeRegion[vin]

        await self._fill_home_region(vin)

        return self._homeRegion[vin]

    async def _get_home_region_setter(self, vin: str):
        if self._homeRegionSetter.get(vin) is not None:
            return self._homeRegionSetter[vin]

        await self._fill_home_region(vin)

        return self._homeRegionSetter[vin]

    async def async_get_climate_settings(self, vin: str) -> Optional[dict]:
        """Gets the current climate settings using the cariad endpoint."""
        redacted_vin = "*" * (len(vin) - 4) + vin[-4:]
        _LOGGER.debug(f"Attempting to GET climate settings for VIN {redacted_vin}")

        # This endpoint seems tied to the newer API/bearer token
        if not self._bearer_token_json or "access_token" not in self._bearer_token_json:
            _LOGGER.error(f"Bearer token not available for getting climate settings for VIN {redacted_vin}")
            return None

        # Determine region for the URL
        region = "emea" if self._country.upper() != "US" else "na"
        url = f"https://{region}.bff.cariad.digital/vehicle/v1/vehicles/{vin.upper()}/selectivestatus?jobs=climatisation"

        headers = {
            "Authorization": "Bearer " + self._bearer_token_json["access_token"]
        }
        try:
            _LOGGER.debug(f"Sending GET to {url} with headers {headers}")
            response_data = await self._api.request(
                "GET",
                url,
                headers=headers,
                data=None,
            )
            _LOGGER.debug(f"GET climate settings response for VIN {redacted_vin}: {response_data}")
            return response_data
        except Exception as e:
            _LOGGER.error(f"Error getting climate settings for VIN {redacted_vin}: {e}")
            return None

    async def async_set_climate_settings(self, vin: str, settings_data: dict) -> bool:
        """Sets the climate settings using the cariad endpoint (PUT)."""
        redacted_vin = "*" * (len(vin) - 4) + vin[-4:]
        _LOGGER.debug(f"Attempting to PUT climate settings for VIN {redacted_vin}: {settings_data}")

        if not self._bearer_token_json or "access_token" not in self._bearer_token_json:
            _LOGGER.error(f"Bearer token not available for setting climate settings for VIN {redacted_vin}")
            return False

        region = "emea" if self._country.upper() != "US" else "na"
        url = f"https://{region}.bff.cariad.digital/vehicle/v1/vehicles/{vin.upper()}/climatisation/settings"

        headers = {
            "Authorization": "Bearer " + self._bearer_token_json["access_token"]
        }
        try:
            json_data = json.dumps(settings_data)
            _LOGGER.debug(f"Sending PUT to {url} with headers {headers} and data {json_data}")
            
            res = await self._api.request(
                 "PUT",
                 url,
                 data=json_data,
                 headers=headers,
            )

            await self.check_pending_request_succeeded(
                url=f"https://{region}.bff.cariad.digital/vehicle/v1/vehicles/{vin.upper()}/pendingrequests",
                request_id=res["data"]["requestID"],
                action="set climate settings"
            )

            _LOGGER.debug(f"PUT climate settings response status for VIN {redacted_vin}: {res}")
            return True

        except Exception as e:
             _LOGGER.error(f"Error setting climate settings for VIN {redacted_vin}: {e}")
             return False


    async def _get_security_token(self, vin: str, action: str):
        # Challenge
        headers = {
            "User-Agent": "okhttp/3.7.0",
            "X-App-Version": "3.14.0",
            "X-App-Name": "myAudi",
            "Accept": "application/json",
            "Authorization": "Bearer " + self.vwToken.get("access_token"),
        }

        body = await self._api.request(
            "GET",
            "{homeRegionSetter}/api/rolesrights/authorization/v2/vehicles/".format(
                homeRegionSetter=await self._get_home_region_setter(vin.upper())
            )
            + vin.upper()
            + "/services/"
            + action
            + "/security-pin-auth-requested",
            headers=headers,
            data=None,
        )
        secToken = body["securityPinAuthInfo"]["securityToken"]
        challenge = body["securityPinAuthInfo"]["securityPinTransmission"]["challenge"]

        # Response
        securityPinHash = self._generate_security_pin_hash(challenge)
        data = {
            "securityPinAuthentication": {
                "securityPin": {
                    "challenge": challenge,
                    "securityPinHash": securityPinHash,
                },
                "securityToken": secToken,
            }
        }

        headers = {
            "User-Agent": "okhttp/3.7.0",
            "Content-Type": "application/json",
            "X-App-Version": "3.14.0",
            "X-App-Name": "myAudi",
            "Accept": "application/json",
            "Authorization": "Bearer " + self.vwToken.get("access_token"),
        }

        body = await self._api.request(
            "POST",
            "{homeRegionSetter}/api/rolesrights/authorization/v2/security-pin-auth-completed".format(
                homeRegionSetter=await self._get_home_region_setter(vin.upper())
            ),
            headers=headers,
            data=json.dumps(data),
        )
        return body["securityToken"]

    def _get_vehicle_action_header(
        self, content_type: str, security_token: str, host: Optional[str] = None
    ):
        if not host:
            host = (
                "mal-3a.prd.eu.dp.vwg-connect.com"
                if self._country in {"DE", "US"}
                else "msg.volkswagen.de"
            )

        headers = {
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Host": host,
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-App-Name": "myAudi",
            "Authorization": "Bearer " + self.vwToken.get("access_token"),
            "Accept-charset": "UTF-8",
            "Content-Type": content_type,
            "Accept": "application/json, application/vnd.vwg.mbb.ChargerAction_v1_0_0+xml,application/vnd.volkswagenag.com-error-v1+xml,application/vnd.vwg.mbb.genericError_v1_0_2+xml, application/vnd.vwg.mbb.RemoteStandheizung_v2_0_0+xml, application/vnd.vwg.mbb.genericError_v1_0_2+xml,application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml,*/*",
        }

        if security_token:
            headers["x-securityToken"] = security_token

        return headers

    async def set_vehicle_lock(self, vin: str, lock: bool):
        security_token = await self._get_security_token(
            vin, "rlu_v1/operations/" + ("LOCK" if lock else "UNLOCK")
        )
        # deprecated data removed on 24Mar2025
        # data = '<?xml version="1.0" encoding= "UTF-8" ?><rluAction xmlns="http://audi.de/connect/rlu"><action>{action}</action></rluAction>'.format(
        #     action="lock" if lock else "unlock"
        # )
        data = None

        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml", security_token
        )
        res = await self._api.request(
            "POST",
            "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/rlu/v1/vehicles/{vin}/{action}".format(
                vin=vin.upper(),
                action="lock" if lock else "unlock",
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/rlu/v1/vehicles/{vin}/requests/{requestId}/status".format(
            vin=vin.upper(),
            requestId=res["rluActionResponse"]["requestId"],
        )

        await self.check_request_succeeded(
            checkUrl,
            "lock vehicle" if lock else "unlock vehicle",
            REQUEST_SUCCESSFUL,
            REQUEST_FAILED,
            "requestStatusResponse.status",
        )

    async def set_battery_charger(self, vin: str, start: bool, timer: bool):
        if start and timer:
            data = '{ "action": { "type": "selectChargingMode", "settings": { "chargeModeSelection": { "value": "timerBasedCharging" } } }}'
        elif start:
            data = '{ "action": { "type": "start" }}'
        else:
            data = '{ "action": { "type": "stop" }}'

        headers = self._get_vehicle_action_header("application/json", None)
        res = await self._api.request(
            "POST",
            "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions/{actionid}".format(
            homeRegion=await self._get_home_region(vin.upper()),
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            actionid=res["action"]["actionId"],
        )

        await self.check_request_succeeded(
            checkUrl,
            "start charger" if start else "stop charger",
            SUCCEEDED,
            FAILED,
            "action.actionState",
        )

    async def set_climatisation(self, vin: str, start: bool):
        api_level = self._api_level
        if start:
            raise NotImplementedError(
                "The 'Start Climatisation (Legacy)' service is deprecated and no longer functional. "
                "Please use the 'Start Climate Control' service instead."
            )
            # data = '{"action":{"type": "startClimatisation","settings": {"targetTemperature": 2940,"climatisationWithoutHVpower": true,"heaterSource": "electric","climaterElementSettings": {"isClimatisationAtUnlock": false, "isMirrorHeatingEnabled": true,}}}}'

        else:
            if api_level == 0:
                data = '{"action":{"type": "stopClimatisation"}}'
                headers = self._get_vehicle_action_header("application/json", None)
                res = await self._api.request(
                    "POST",
                    f"https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin.upper()}/climater/actions",
                    headers=headers,
                    data=data,
                )
                checkUrl = "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions/{actionid}".format(
                    vin=vin.upper(),
                    actionid=res["action"]["actionId"],
                )

                await self.check_request_succeeded(
                    checkUrl,
                    "start climatisation" if start else "stop climatisation",
                    SUCCEEDED,
                    FAILED,
                    "action.actionState",
                )

            elif api_level == 1:
                data = None
                headers = {
                    "Authorization": "Bearer " + self._bearer_token_json["access_token"]
                }
                res = await self._api.request(
                    "POST",
                    "https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/climatisation/stop".format(
                        vin=vin.upper(),
                    ),
                    headers=headers,
                    data=data,
                )

                # checkUrl = "https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/pendingrequests".format(
                #     vin=vin.upper(),
                #     actionid=res["action"]["actionId"],
                # )

                # await self.check_request_succeeded(
                #     checkUrl,
                #     "startClimatisation",
                #     SUCCEEDED,
                #     FAILED,
                #     "action.actionState",
                # )

    async def start_climate_control(
        self,
        vin: str,
        temp_f: int,
        temp_c: int,
        glass_heating: bool,
        seat_fl: bool,
        seat_fr: bool,
        seat_rl: bool,
        seat_rr: bool,
    ):
        api_level = self._api_level
        country = self._country
        target_temperature = None

        _LOGGER.debug(
            f"Attempting to start climate control with API Level {api_level} and country {country}."
        )

        if api_level == 0:
            target_temperature = None
            if temp_f is not None:
                target_temperature = int(((temp_f - 32) * (5 / 9)) * 10 + 2731)
            elif temp_c is not None:
                target_temperature = int(temp_c * 10 + 2731)

            # Default Temp
            target_temperature = target_temperature or 2941

            # Construct Zone Settings
            zone_settings = [
                {"value": {"isEnabled": seat_fl, "position": "frontLeft"}},
                {"value": {"isEnabled": seat_fr, "position": "frontRight"}},
                {"value": {"isEnabled": seat_rl, "position": "rearLeft"}},
                {"value": {"isEnabled": seat_rr, "position": "rearRight"}},
            ]

            data = {
                "action": {
                    "type": "startClimatisation",
                    "settings": {
                        "targetTemperature": target_temperature,
                        "climatisationWithoutHVpower": True,
                        "heaterSource": "electric",
                        "climaterElementSettings": {
                            "isClimatisationAtUnlock": False,
                            "isMirrorHeatingEnabled": glass_heating,
                            "zoneSettings": {"zoneSetting": zone_settings},
                        },
                    },
                }
            }

            data = json.dumps(data)

        elif api_level == 1:
            if temp_f is not None:
                target_temperature = int((temp_f - 32) * (5 / 9))
            elif temp_c is not None:
                target_temperature = int(temp_c)

            target_temperature = target_temperature or 21

            data = {
                "targetTemperature": target_temperature,
                "targetTemperatureUnit": "celsius",
                "climatisationWithoutExternalPower": True,
                "climatizationAtUnlock": False,
                "windowHeatingEnabled": glass_heating,
                "zoneFrontLeftEnabled": seat_fl,
                "zoneFrontRightEnabled": seat_fr,
                "zoneRearLeftEnabled": seat_rl,
                "zoneRearRightEnabled": seat_rr,
            }

            data = json.dumps(data)

        if country == "DE":
            # old headers
            # headers = self._get_vehicle_action_header("application/json", None)
            # new headers for EU
            headers = {
                "Authorization": "Bearer " + self._bearer_token_json["access_token"]
            }
            res = await self._api.request(
                "POST",
                "https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/climatisation/start".format(
                    vin=vin.upper(),
                ),
                headers=headers,
                data=data,
            )

            # checkUrl = "https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/pendingrequests".format(
            #     vin=vin.upper(),
            #     actionid=res["action"]["actionId"],
            # )

            # await self.check_request_succeeded(
            #     checkUrl,
            #     "startClimatisation",
            #     SUCCEEDED,
            #     FAILED,
            #     "action.actionState",
            # )

        elif country == "US":
            headers = self._get_vehicle_action_header("application/json", None)
            res = await self._api.request(
                "POST",
                "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions".format(
                    vin=vin.upper(),
                ),
                headers=headers,
                data=data,
            )

            checkUrl = "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions/{actionid}".format(
                vin=vin.upper(),
                actionid=res["action"]["actionId"],
            )

            await self.check_request_succeeded(
                checkUrl,
                "startClimatisation",
                SUCCEEDED,
                FAILED,
                "action.actionState",
            )
        else:
            headers = self._get_vehicle_action_header("application/json", None)
            res = await self._api.request(
                "POST",
                "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                    homeRegion=await self._get_home_region(vin.upper()),
                    type=self._type,
                    country=self._country,
                    vin=vin.upper(),
                ),
                headers=headers,
                data=data,
            )

            checkUrl = "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions/{actionid}".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
                actionid=res["action"]["actionId"],
            )

            await self.check_request_succeeded(
                checkUrl,
                "start climatisation",
                SUCCEEDED,
                FAILED,
                "action.actionState",
            )

    async def stop_climate_control(self, vin: str):
        """Stops the vehicle climatisation."""
        _LOGGER.debug(f"Attempting to stop climate control for VIN {vin}")

        # --- Determine Country (Headers depend on it) ---
        # Ensure self._country and potentially self._type, self._bearer_token_json, etc.
        # are initialized correctly in your class instance.
        country = self._country
        headers = {}
        url = None
        # Stop action likely requires an empty JSON body or a specific action type
        data = json.dumps({}) # Default to empty JSON object for POST

        try:
            if country == "DE":
                # Use the specified endpoint for EMEA/Germany
                url = "https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/climatisation/stop".format(
                    vin=vin.upper()
                )
                # Use specific bearer token header for DE
                headers = {
                    "Authorization": "Bearer " + self._bearer_token_json["access_token"],
                    "Content-Type": "application/json", # Often needed even for empty body
                    "Accept": "application/json", # Good practice to include Accept
                }

            elif country == "US":
                # --- UNCERTAIN: Endpoint/Data for US Stop needs verification ---
                _LOGGER.warning("US stop climate endpoint/data structure is assumed and may need verification.")
                # Assumption 1: Maybe uses /actions endpoint with a specific type?
                url = "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions".format(
                     vin=vin.upper()
                )
                stop_action_data = {"action": {"type": "stopClimatisation"}} # Hypothetical data
                data = json.dumps(stop_action_data)
                headers = self._get_vehicle_action_header("application/json", None)
                # Assumption 2: Maybe has a dedicated /stop endpoint like DE?
                # url = "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/stop".format(vin=vin.upper()) # Hypothetical
                # data = json.dumps({})
                # headers = self._get_vehicle_action_header("application/json", None)


            else: # Other countries
                # --- UNCERTAIN: Endpoint/Data for Other Region Stop needs verification ---
                _LOGGER.warning("Other region stop climate endpoint/data structure is assumed and may need verification.")
                home_region = await self._get_home_region(vin.upper())
                # Assumption 1: Maybe uses /actions endpoint?
                url = "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                   homeRegion=home_region, type=self._type, country=self._country, vin=vin.upper()
                )
                stop_action_data = {"action": {"type": "stopClimatisation"}} # Hypothetical data
                data = json.dumps(stop_action_data)
                headers = self._get_vehicle_action_header("application/json", None)
                # Assumption 2: Maybe has a dedicated /stop endpoint?
                # url = "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/stop".format(homeRegion=home_region, type=self._type, country=self._country, vin=vin.upper()) # Hypothetical
                # data = json.dumps({})
                # headers = self._get_vehicle_action_header("application/json", None)


            # --- Make the API Request ---
            if not url or not headers:
                 _LOGGER.error(f"Could not determine URL or headers for stopping climate in country {country}")
                 return False # Indicate failure

            _LOGGER.debug(f"Sending POST to {url} with headers {headers} and data {data}")
            res = await self._api.request(
                "POST",
                url,
                headers=headers,
                data=data, # Send the JSON data (empty or specific action)
            )
            _LOGGER.debug(f"Stop climate response: {res}") # Log the response for debugging

            # --- Response Checking (Placeholder) ---
            # The 'check_request_succeeded' logic might be needed depending on the API response.
            # Check the actual response `res` to determine success/failure.
            # For now, we assume success if no exception occurred during the request.
            # You might need to check res['action']['actionState'] or HTTP status code.

            return True # Indicate presumed success

        except KeyError as e:
             _LOGGER.error(f"Configuration key error stopping climate: {e}. Check token/country setup.")
             return False
        except Exception as e:
            _LOGGER.error(f"Error stopping climate control for {vin}: {e}")
            return False # Indicate failure
            
    async def set_window_heating(self, vin: str, start: bool):
        data = '<?xml version="1.0" encoding= "UTF-8" ?><action><type>{action}</type></action>'.format(
            action="startWindowHeating" if start else "stopWindowHeating"
        )

        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.ClimaterAction_v1_0_0+xml", None
        )
        res = await self._api.request(
            "POST",
            "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions/{actionid}".format(
            homeRegion=await self._get_home_region(vin.upper()),
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            actionid=res["action"]["actionId"],
        )

        await self.check_request_succeeded(
            checkUrl,
            "start window heating" if start else "stop window heating",
            SUCCEEDED,
            FAILED,
            "action.actionState",
        )

    async def set_pre_heater(self, vin: str, activate: bool):
        security_token = await self._get_security_token(
            vin, "rheating_v1/operations/P_QSACT"
        )

        data = '<?xml version="1.0" encoding= "UTF-8" ?>{input}'.format(
            input='<performAction xmlns="http://audi.de/connect/rs"><quickstart><active>true</active></quickstart></performAction>'
            if activate
            else '<performAction xmlns="http://audi.de/connect/rs"><quickstop><active>false</active></quickstop></performAction>'
        )

        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.RemoteStandheizung_v2_0_0+xml", security_token
        )
        await self._api.request(
            "POST",
            "{homeRegion}/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/action".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            ),
            headers=headers,
            data=data,
        )

    async def check_request_succeeded(
        self, url: str, action: str, successCode: str, failedCode: str, path: str
    ):
        for _ in range(MAX_RESPONSE_ATTEMPTS):
            await asyncio.sleep(REQUEST_STATUS_SLEEP)

            self._api.use_token(self.vwToken)
            res = await self._api.get(url)

            status = get_attr(res, path)

            if status is None or (failedCode is not None and status == failedCode):
                raise Exception(
                    "Cannot {action}, return code '{code}'".format(
                        action=action, code=status
                    )
                )

            if status == successCode:
                return

        raise Exception("Cannot {action}, operation timed out".format(action=action))

    async def check_pending_request_succeeded(
        self, url: str, request_id: str, action: str,
    ) -> bool:
        """
        Polls a pending requests endpoint until a specific request ID is successful or fails.

        Args:
            url: The URL of the pending requests endpoint (e.g., /vehicles/{vin}/pendingrequests).
            request_id: The unique ID of the request to monitor.
            action: A descriptive string for logging purposes (e.g., "set climate temperature").

        Returns:
            True if the request status becomes "successful".

        Raises:
            Exception: If the request status becomes anything other than "successful" or "in_progress",
                       if the request ID cannot be found after multiple attempts,
                       or if the operation times out.
        """
        _LOGGER.debug(f"Polling endpoint {url} for request ID {request_id} (Action: {action})")

        headers = {
            "Authorization": "Bearer " + self._bearer_token_json["access_token"]
        }

        for attempt in range(MAX_RESPONSE_ATTEMPTS):
            await asyncio.sleep(REQUEST_STATUS_SLEEP)
            _LOGGER.debug(f"Polling attempt {attempt + 1}/{MAX_RESPONSE_ATTEMPTS} for request {request_id}")

            try:
                res = await self._api.request(
                    "GET",
                    url,
                    data=None,
                    headers=headers,
                )

                if res is None or "data" not in res or not isinstance(res.get("data"), list):
                    _LOGGER.warning(f"Invalid response structure received when polling for {request_id}. Response: {res}")
                    continue

                found_request = False
                for pending_request in res.get("data", []):
                    if pending_request.get("id") == request_id:
                        found_request = True
                        status = pending_request.get("status")
                        _LOGGER.debug(f"Found request {request_id}, current status: {status}")

                        if status == "successful":
                            _LOGGER.info(f"Request {request_id} (Action: {action}) completed successfully.")
                            return True  # Success
                        elif status == "in_progress":
                            _LOGGER.info(f"Request {request_id} (Action: {action}) still in progress.")
                            break
                        else:
                            # Any other status (failed, rejected, timeout, None, etc.) is considered a failure
                            _LOGGER.error(f"Request {request_id} (Action: {action}) failed with status: {status}. Full details: {pending_request}")
                            raise Exception(
                                f"Cannot {action}, request {request_id} failed with status '{status}'"
                            )

                if found_request and status == "in_progress":
                     continue
                elif not found_request:
                     _LOGGER.warning(f"Request ID {request_id} not found in pending requests list (attempt {attempt + 1}). Might be completed or an issue.")

            except Exception as e:
                 _LOGGER.error(f"Error during polling check for request {request_id} (Action: {action}): {e}")
                 if "Bearer token missing" in str(e): # Re-raise if it was the token error
                     raise e

        # End of outer loop (polling attempts)
        _LOGGER.error(f"Request {request_id} (Action: {action}) timed out after {MAX_RESPONSE_ATTEMPTS} attempts.")
        raise Exception(f"Cannot {action}, operation timed out for request {request_id}")


    # TR/2022-12-20: New secret for X_QMAuth
    def _calculate_X_QMAuth(self):
        # Calculate X-QMAuth value
        gmtime_100sec = int(
            (datetime.utcnow() - datetime(1970, 1, 1)).total_seconds() / 100
        )
        xqmauth_secret = bytes(
            [
                26,
                256 - 74,
                256 - 103,
                37,
                256 - 84,
                23,
                256 - 102,
                256 - 86,
                78,
                256 - 125,
                256 - 85,
                256 - 26,
                113,
                256 - 87,
                71,
                109,
                23,
                100,
                24,
                256 - 72,
                91,
                256 - 41,
                6,
                256 - 15,
                67,
                108,
                256 - 95,
                91,
                256 - 26,
                71,
                256 - 104,
                256 - 100,
            ]
        )
        xqmauth_val = hmac.new(
            xqmauth_secret,
            str(gmtime_100sec).encode("ascii", "ignore"),
            digestmod="sha256",
        ).hexdigest()

        # v1:01da27b0:fbdb6e4ba3109bc68040cb83f380796f4d3bb178a626c4cc7e166815b806e4b5
        return "v1:01da27b0:" + xqmauth_val

    # TR/2021-12-01: Refresh token before it expires
    # returns True when refresh was required and successful, otherwise False
    async def refresh_token_if_necessary(self, elapsed_sec: int) -> bool:
        if self.mbboauthToken is None:
            return False
        if "refresh_token" not in self.mbboauthToken:
            return False
        if "expires_in" not in self.mbboauthToken:
            return False

        if (elapsed_sec + 5 * 60) < self.mbboauthToken["expires_in"]:
            # refresh not needed now
            return False

        try:
            headers = {
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
                "User-Agent": AudiAPI.HDR_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Client-ID": self.xclientId,
            }
            mbboauth_refresh_data = {
                "grant_type": "refresh_token",
                "token": self.mbboauthToken["refresh_token"],
                "scope": "sc2:fal",
                # "vin": vin,  << App uses a dedicated VIN here, but it works without, don't know
            }
            encoded_mbboauth_refresh_data = urlencode(
                mbboauth_refresh_data, encoding="utf-8"
            ).replace("+", "%20")
            mbboauth_refresh_rsp, mbboauth_refresh_rsptxt = await self._api.request(
                "POST",
                self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
                encoded_mbboauth_refresh_data,
                headers=headers,
                allow_redirects=False,
                rsp_wtxt=True,
            )

            # this code is the old "vwToken"
            self.vwToken = json.loads(mbboauth_refresh_rsptxt)

            # TR/2022-02-10: If a new refresh_token is provided, save it for further refreshes
            if "refresh_token" in self.vwToken:
                self.mbboauthToken["refresh_token"] = self.vwToken["refresh_token"]

            # hdr
            headers = {
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
                "X-QMAuth": self._calculate_X_QMAuth(),
                "User-Agent": AudiAPI.HDR_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            # IDK token request data
            tokenreq_data = {
                "client_id": self._client_id,
                "grant_type": "refresh_token",
                "refresh_token": self._bearer_token_json.get("refresh_token"),
                "response_type": "token id_token",
            }
            # IDK token request
            encoded_tokenreq_data = urlencode(tokenreq_data, encoding="utf-8").replace(
                "+", "%20"
            )
            bearer_token_rsp, bearer_token_rsptxt = await self._api.request(
                "POST",
                self._tokenEndpoint,
                encoded_tokenreq_data,
                headers=headers,
                allow_redirects=False,
                rsp_wtxt=True,
            )
            self._bearer_token_json = json.loads(bearer_token_rsptxt)

            # AZS token
            headers = {
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
                "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
                "X-App-Name": "myAudi",
                "User-Agent": AudiAPI.HDR_USER_AGENT,
                "Content-Type": "application/json; charset=utf-8",
            }
            asz_req_data = {
                "token": self._bearer_token_json["access_token"],
                "grant_type": "id_token",
                "stage": "live",
                "config": "myaudi",
            }
            azs_token_rsp, azs_token_rsptxt = await self._api.request(
                "POST",
                self._authorizationServerBaseURLLive + "/token",
                json.dumps(asz_req_data),
                headers=headers,
                allow_redirects=False,
                rsp_wtxt=True,
            )
            azs_token_json = json.loads(azs_token_rsptxt)
            self.audiToken = azs_token_json

            return True

        except Exception as exception:
            _LOGGER.error("Refresh token failed: " + str(exception))
            return False

    # TR/2021-12-01 updated to match behaviour of Android myAudi 4.5.0
    async def login_request(self, user: str, password: str):
        self._api.use_token(None)
        self._api.set_xclient_id(None)
        self.xclientId = None

        # get markets
        markets_json = await self._api.request(
            "GET",
            "https://content.app.my.audi.com/service/mobileapp/configurations/markets",
            None,
        )
        if (
            self._country.upper()
            not in markets_json["countries"]["countrySpecifications"]
        ):
            raise Exception("Country not found")
        self._language = markets_json["countries"]["countrySpecifications"][
            self._country.upper()
        ]["defaultLanguage"]

        # Dynamic configuration URLs
        marketcfg_url = "https://content.app.my.audi.com/service/mobileapp/configurations/market/{c}/{l}?v=4.23.1".format(
            c=self._country, l=self._language
        )
        openidcfg_url = (
            "https://{}.bff.cariad.digital/login/v1/idk/openid-configuration".format(
                "na" if self._country.upper() == "US" else "emea"
            )
        )

        # get market config
        marketcfg_json = await self._api.request("GET", marketcfg_url, None)

        # use dynamic config from marketcfg
        self._client_id = "09b6cbec-cd19-4589-82fd-363dfa8c24da@apps_vw-dilab_com"
        if "idkClientIDAndroidLive" in marketcfg_json:
            self._client_id = marketcfg_json["idkClientIDAndroidLive"]

        self._authorizationServerBaseURLLive = (
            "https://{region}.bff.cariad.digital/login/v1/audi".format(
                region="emea" if self._country.upper() != "US" else "na"
            )
        )
        if "authorizationServerBaseURLLive" in marketcfg_json:
            self._authorizationServerBaseURLLive = marketcfg_json[
                "myAudiAuthorizationServerProxyServiceURLProduction"
            ]
        self.mbbOAuthBaseURL = "https://mbboauth-1d.prd.ece.vwg-connect.com/mbbcoauth"
        if "mbbOAuthBaseURLLive" in marketcfg_json:
            self.mbbOAuthBaseURL = marketcfg_json["mbbOAuthBaseURLLive"]

        # get openId config
        openidcfg_json = await self._api.request("GET", openidcfg_url, None)

        # use dynamic config from openId config
        authorization_endpoint = "https://identity.vwgroup.io/oidc/v1/authorize"
        if "authorization_endpoint" in openidcfg_json:
            authorization_endpoint = openidcfg_json["authorization_endpoint"]
        self._tokenEndpoint = (
            "https://{region}.bff.cariad.digital/login/v1/idk/token".format(
                region="emea" if self._country.upper() != "US" else "na"
            )
        )
        if "token_endpoint" in openidcfg_json:
            self._tokenEndpoint = openidcfg_json["token_endpoint"]
        # revocation_endpoint = "https://{region}.bff.cariad.digital/login/v1/idk/revoke".format(region="emea" if self._country.upper() != "US" else "na")
        # if "revocation_endpoint" in openidcfg_json:
        # revocation_endpoint = openidcfg_json["revocation_endpoint"]

        # generate code_challenge
        code_verifier = str(base64.urlsafe_b64encode(os.urandom(32)), "utf-8").strip(
            "="
        )
        code_challenge = str(
            base64.urlsafe_b64encode(
                sha256(code_verifier.encode("ascii", "ignore")).digest()
            ),
            "utf-8",
        ).strip("=")
        code_challenge_method = "S256"

        #
        state = str(uuid.uuid4())
        nonce = str(uuid.uuid4())

        # login page
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-App-Name": "myAudi",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
        }
        idk_data = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": "myaudi:///",
            "scope": "address profile badge birthdate birthplace nationalIdentifier nationality profession email vin phone nickname name picture mbb gallery openid",
            "state": state,
            "nonce": nonce,
            "prompt": "login",
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "ui_locales": "de-de de",
        }
        idk_rsp, idk_rsptxt = await self._api.request(
            "GET",
            authorization_endpoint,
            None,
            headers=headers,
            params=idk_data,
            rsp_wtxt=True,
        )

        # form_data with email
        submit_data = self.get_hidden_html_input_form_data(idk_rsptxt, {"email": user})
        submit_url = self.get_post_url(idk_rsptxt, authorization_endpoint)
        # send email
        email_rsp, email_rsptxt = await self._api.request(
            "POST",
            submit_url,
            submit_data,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=True,
            rsp_wtxt=True,
        )

        # form_data with password
        # 2022-01-29: new HTML response uses a js two build the html form data + button.
        #             Therefore it's not possible to extract hmac and other form data.
        #             --> extract hmac from embedded js snippet.
        regex_res = re.findall('"hmac"\\s*:\\s*"[0-9a-fA-F]+"', email_rsptxt)
        if regex_res:
            submit_url = submit_url.replace("identifier", "authenticate")
            submit_data["hmac"] = regex_res[0].split(":")[1].strip('"')
            submit_data["password"] = password
        else:
            submit_data = self.get_hidden_html_input_form_data(
                email_rsptxt, {"password": password}
            )
            submit_url = self.get_post_url(email_rsptxt, submit_url)

        # send password
        pw_rsp, pw_rsptxt = await self._api.request(
            "POST",
            submit_url,
            submit_data,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt=True,
        )

        # forward1 after pwd
        fwd1_rsp, fwd1_rsptxt = await self._api.request(
            "GET",
            pw_rsp.headers["Location"],
            None,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        # forward2 after pwd
        fwd2_rsp, fwd2_rsptxt = await self._api.request(
            "GET",
            fwd1_rsp.headers["Location"],
            None,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        # get tokens
        codeauth_rsp, codeauth_rsptxt = await self._api.request(
            "GET",
            fwd2_rsp.headers["Location"],
            None,
            headers=headers,
            cookies=fwd2_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        authcode_parsed = urlparse(
            codeauth_rsp.headers["Location"][len("myaudi:///?") :]
        )
        authcode_strings = parse_qs(authcode_parsed.path)

        # hdr
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-QMAuth": self._calculate_X_QMAuth(),
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # IDK token request data
        tokenreq_data = {
            "client_id": self._client_id,
            "grant_type": "authorization_code",
            "code": authcode_strings["code"][0],
            "redirect_uri": "myaudi:///",
            "response_type": "token id_token",
            "code_verifier": code_verifier,
        }
        # IDK token request
        encoded_tokenreq_data = urlencode(tokenreq_data, encoding="utf-8").replace(
            "+", "%20"
        )
        bearer_token_rsp, bearer_token_rsptxt = await self._api.request(
            "POST",
            self._tokenEndpoint,
            encoded_tokenreq_data,
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        self._bearer_token_json = json.loads(bearer_token_rsptxt)

        # AZS token
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-App-Name": "myAudi",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
        }
        asz_req_data = {
            "token": self._bearer_token_json["access_token"],
            "grant_type": "id_token",
            "stage": "live",
            "config": "myaudi",
        }
        azs_token_rsp, azs_token_rsptxt = await self._api.request(
            "POST",
            self._authorizationServerBaseURLLive + "/token",
            json.dumps(asz_req_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        azs_token_json = json.loads(azs_token_rsptxt)
        self.audiToken = azs_token_json

        # mbboauth client register
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
        }
        mbboauth_reg_data = {
            "client_name": "SM-A405FN",
            "platform": "google",
            "client_brand": "Audi",
            "appName": "myAudi",
            "appVersion": AudiAPI.HDR_XAPP_VERSION,
            "appId": "de.myaudi.mobile.assistant",
        }
        mbboauth_client_reg_rsp, mbboauth_client_reg_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/register/v1",
            json.dumps(mbboauth_reg_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        mbboauth_client_reg_json = json.loads(mbboauth_client_reg_rsptxt)
        self.xclientId = mbboauth_client_reg_json["client_id"]
        self._api.set_xclient_id(self.xclientId)

        # mbboauth auth
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Client-ID": self.xclientId,
        }
        mbboauth_auth_data = {
            "grant_type": "id_token",
            "token": self._bearer_token_json["id_token"],
            "scope": "sc2:fal",
        }
        encoded_mbboauth_auth_data = urlencode(
            mbboauth_auth_data, encoding="utf-8"
        ).replace("+", "%20")
        mbboauth_auth_rsp, mbboauth_auth_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
            encoded_mbboauth_auth_data,
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        mbboauth_auth_json = json.loads(mbboauth_auth_rsptxt)
        # store token and expiration time
        self.mbboauthToken = mbboauth_auth_json

        # mbboauth refresh (app immediately refreshes the token)
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Client-ID": self.xclientId,
        }
        mbboauth_refresh_data = {
            "grant_type": "refresh_token",
            "token": mbboauth_auth_json["refresh_token"],
            "scope": "sc2:fal",
            # "vin": vin,  << App uses a dedicated VIN here, but it works without, don't know
        }
        encoded_mbboauth_refresh_data = urlencode(
            mbboauth_refresh_data, encoding="utf-8"
        ).replace("+", "%20")
        mbboauth_refresh_rsp, mbboauth_refresh_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
            encoded_mbboauth_refresh_data,
            headers=headers,
            allow_redirects=False,
            cookies=mbboauth_client_reg_rsp.cookies,
            rsp_wtxt=True,
        )
        # this code is the old "vwToken"
        self.vwToken = json.loads(mbboauth_refresh_rsptxt)

    def _generate_security_pin_hash(self, challenge):
        pin = to_byte_array(self._spin)
        byteChallenge = to_byte_array(challenge)
        b = bytes(pin + byteChallenge)
        return sha512(b).hexdigest().upper()

    async def _emulate_browser(
        self, reply: BrowserLoginResponse, form_data: Dict[str, str]
    ) -> BrowserLoginResponse:
        # The reply redirects to the login page
        login_location = reply.get_location()
        page_reply = await self._api.get(login_location, raw_contents=True)

        # Now parse the html body and extract the target url, csrf token and other required parameters
        html = BeautifulSoup(page_reply, "html.parser")
        form_tag = html.find("form")

        form_inputs = html.find_all("input", attrs={"type": "hidden"})
        for form_input in form_inputs:
            name = form_input.get("name")
            form_data[name] = form_input.get("value")

        # Extract the target url
        action = form_tag.get("action")
        if action.startswith("http"):
            # Absolute url
            username_post_url = action
        elif action.startswith("/"):
            # Relative to domain
            username_post_url = BrowserLoginResponse.to_absolute(login_location, action)
        else:
            raise RequestException("Unknown form action: " + action)

        headers = {"referer": login_location}
        reply = await self._api.post(
            username_post_url,
            form_data,
            headers=headers,
            use_json=False,
            raw_reply=True,
            allow_redirects=False,
        )
        return BrowserLoginResponse(reply, username_post_url)

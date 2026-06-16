"""OceaCB sensor integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from datetime import timedelta, datetime

from .api.ConsoApi import ConsoApi
from .api.TokenManager import TokenManager
from .const import (
    CONF_ACCESS_TOKEN
)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)

from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import (
    ConfigType,
    DiscoveryInfoType,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_ACCESS_TOKEN): cv.string,
})

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the sensor platform."""
    session = async_get_clientsession(hass)
    async_add_entities([
        ThermoSensor(conso_api=ConsoApi(session, TokenManager(config))),
        WaterSensor(conso_api=ConsoApi(session, TokenManager(config)))
    ], update_before_add=True)


class ClientSensor(SensorEntity):
    """Representation of a Sensor."""
    def __init__(self, conso_api: ConsoApi):
        super().__init__()
        self.api = conso_api
        self.available = True


class ThermoSensor(ClientSensor):
    """Representation of a Sensor."""
    _attr_name = "Consommation thermique"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    async def async_update(self):
        _LOGGER.info("Triggering async update for OCEA SB - Thermo sensor")
        data = await self.api.get_conso_eau_chaude(
            datetime.now().strftime("%Y-%m-%dT00:00:00"),
            datetime.now().strftime("%Y-%m-%dT23:59:59")
        )

        # print
        self.print_conso_data(data, "🚿")
        self._attr_native_value = 21

    def print_conso_data(self, consodata, type):
        if consodata is None:
            _LOGGER.warning(f"{type} No data received.")
            return

        totalKwh = 0
        for record in consodata.get("consommations", []):
            # convert 2025-04-01T00:00:00 to date object
            date = record.get("date")
            date_obj = datetime.strptime(date, "%Y-%m-%dT%H:%M:%S").date()

            date_str = date_obj.strftime("%d/%m/%Y")
            value = record.get("valeur")
            # 1000 Kwh = 96€
            price = (value / 1000) * 96
            totalKwh += value
            _LOGGER.info(f"[{type}] Date: {date_str}, Value: {value} Kwh, Price: {price:.2f} €")

        totalPrice = (totalKwh / 1000) * 96
        _LOGGER.info(f"[{type}] Total consumption: {totalKwh} Kwh, Total price: {totalPrice:.2f} €")

class WaterSensor(ClientSensor):
    """Representation of a Sensor."""
    _attr_name = "Consommation eau-chaude"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_value = 0.0

    async def async_update(self):
        _LOGGER.info("Triggering async update for OCEA SB - Water sensor")
        data = await self.fetch_data()
        self._attr_native_value = data

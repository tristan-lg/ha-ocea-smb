"""Sensor platform for Ocea Smart Building water consumption."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_LOCAL_ID,
    CONF_PRICE_HOT_WATER,
    CONF_PRICE_THERMAL,
    DEFAULT_PRICE_HOT_WATER,
    DEFAULT_PRICE_THERMAL,
    DOMAIN,
)
from .coordinator import OceaDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class OceaSensorEntityDescription(SensorEntityDescription):
    """Describe an Ocea sensor entity."""

    data_key: str


SENSOR_TYPES: tuple[OceaSensorEntityDescription, ...] = (
    OceaSensorEntityDescription(
        key="eau_froide",
        data_key="eau_froide",
        translation_key="eau_froide",
        name="Eau froide",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        suggested_display_precision=2,
    ),
    OceaSensorEntityDescription(
        key="eau_chaude",
        data_key="eau_chaude",
        translation_key="eau_chaude",
        name="Eau chaude",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water-thermometer",
        suggested_display_precision=2,
    ),
    OceaSensorEntityDescription(
        key="cetc",
        data_key="cetc",
        translation_key="cetc",
        name="Compteur thermique chaud",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:radiator",
        suggested_display_precision=2,
    ),
)


# (data_key source, option de prix, valeur par défaut, clé/translation, libellé, icône)
PRICE_SENSORS: tuple[tuple[str, str, float, str, str, str], ...] = (
    (
        "eau_chaude",
        CONF_PRICE_HOT_WATER,
        DEFAULT_PRICE_HOT_WATER,
        "prix_eau_chaude",
        "Facture eau chaude",
        "mdi:cash",
    ),
    (
        "cetc",
        CONF_PRICE_THERMAL,
        DEFAULT_PRICE_THERMAL,
        "prix_thermique_chaud",
        "Facture chauffage",
        "mdi:cash",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ocea Smart Building sensors from a config entry."""
    coordinator: OceaDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    local_id = config_entry.data[CONF_LOCAL_ID]

    entities: list[SensorEntity] = []
    for description in SENSOR_TYPES:
        if coordinator.data and description.data_key in coordinator.data:
            entities.append(
                OceaWaterSensor(
                    coordinator=coordinator,
                    description=description,
                    local_id=local_id,
                )
            )

    # Capteurs de prix calculés (valeur consommée * prix unitaire configuré)
    for source_key, option_key, default_price, key, name, icon in PRICE_SENSORS:
        if coordinator.data and source_key in coordinator.data:
            price = float(
                config_entry.options.get(option_key, default_price)
            )
            entities.append(
                OceaPriceSensor(
                    coordinator=coordinator,
                    local_id=local_id,
                    source_key=source_key,
                    price=price,
                    key=key,
                    name=name,
                    icon=icon,
                )
            )

    async_add_entities(entities, update_before_add=True)


class OceaWaterSensor(
    CoordinatorEntity[OceaDataUpdateCoordinator], SensorEntity
):
    """Representation of an Ocea water consumption sensor."""

    entity_description: OceaSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OceaDataUpdateCoordinator,
        description: OceaSensorEntityDescription,
        local_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._local_id = local_id
        self._attr_unique_id = f"{DOMAIN}_{local_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, local_id)},
            "name": f"Ocea - Local {local_id}",
            "manufacturer": "Ocea Smart Building",
            "model": "Espace Résident",
        }

    @property
    def native_value(self) -> float | None:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator and log the new value."""
        _LOGGER.info(
            "Capteur Ocea '%s' (local %s) mis à jour : %s %s",
            self.entity_description.key,
            self._local_id,
            self.native_value,
            self.entity_description.native_unit_of_measurement,
        )
        super()._handle_coordinator_update()


class OceaPriceSensor(
    CoordinatorEntity[OceaDataUpdateCoordinator], SensorEntity
):
    """Calculated price sensor: consumption value * configured unit price."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: OceaDataUpdateCoordinator,
        local_id: str,
        source_key: str,
        price: float,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize the calculated price sensor."""
        super().__init__(coordinator)
        self._local_id = local_id
        self._source_key = source_key
        self._price = price
        self._key = key
        self._attr_translation_key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_{local_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, local_id)},
            "name": f"Ocea - Local {local_id}",
            "manufacturer": "Ocea Smart Building",
            "model": "Espace Résident",
        }

    @property
    def native_value(self) -> float | None:
        """Return the computed price (consumption * unit price)."""
        if self.coordinator.data is None:
            return None
        consumption = self.coordinator.data.get(self._source_key)
        if consumption is None:
            return None
        return round(consumption * self._price, 2)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data and log the computed price."""
        _LOGGER.info(
            "Capteur de prix Ocea '%s' (local %s) mis à jour : %s %s "
            "(conso %s × prix %s)",
            self._key,
            self._local_id,
            self.native_value,
            CURRENCY_EURO,
            self.coordinator.data.get(self._source_key)
            if self.coordinator.data
            else None,
            self._price,
        )
        super()._handle_coordinator_update()



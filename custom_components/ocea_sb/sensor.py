"""Sensor platform for Ocea Smart Building water consumption."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_import_statistics
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
from homeassistant.util import dt as dt_util

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


def _start_of_current_month() -> datetime:
    """Return the start of the current month (local time, tz-aware).

    Used as ``last_reset`` because Ocea consumption values are monthly
    figures that reset to zero at the beginning of each month.
    """
    now = dt_util.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_start_utc(day_key: str) -> datetime:
    """Return the UTC datetime for a 'YYYY-MM-DD' day (local midnight)."""
    year, month, day = (int(part) for part in day_key.split("-"))
    local = datetime(year, month, day, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(local)


def _import_entity_day_statistics(
    hass: HomeAssistant,
    entity_id: str,
    unit: str | None,
    daily_values: dict[str, float],
) -> None:
    """Rewrite an entity's long-term statistics from per-day values.

    Each day becomes a statistic point whose ``state`` is the daily
    consumption/cost and ``sum`` the running cumulative total. This makes
    the entity's history graph show the real per-day figures instead of
    a flat line of the yearly total.
    """
    if not daily_values:
        return

    statistics: list[StatisticData] = []
    running_sum = 0.0
    for day_key in sorted(daily_values):
        running_sum = round(running_sum + daily_values[day_key], 2)
        statistics.append(
            StatisticData(
                start=_day_start_utc(day_key),
                state=daily_values[day_key],
                sum=running_sum,
            )
        )

    metadata = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name=None,
        source="recorder",
        statistic_id=entity_id,
        unit_of_measurement=unit,
    )
    async_import_statistics(hass, metadata, statistics)


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
        state_class=SensorStateClass.TOTAL,
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
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-thermometer",
        suggested_display_precision=2,
    ),
    OceaSensorEntityDescription(
        key="cetc",
        data_key="cetc",
        translation_key="cetc",
        name="Chauffage (mois)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
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
        "Facture eau chaude (mois)",
        "mdi:cash",
    ),
    (
        "cetc",
        CONF_PRICE_THERMAL,
        DEFAULT_PRICE_THERMAL,
        "prix_thermique_chaud",
        "Facture chauffage (mois)",
        "mdi:cash",
    ),
)


# Capteurs de consommation annuelle (cumul depuis le 1er janvier)
# (data_key source, clé/translation, libellé, unité, device_class, icône)
YEAR_SENSORS: tuple[
    tuple[str, str, str, str, SensorDeviceClass, str], ...
] = (
    (
        "eau_froide",
        "eau_froide_annee",
        "Eau froide (année)",
        UnitOfVolume.CUBIC_METERS,
        SensorDeviceClass.WATER,
        "mdi:water",
    ),
    (
        "eau_chaude",
        "eau_chaude_annee",
        "Eau chaude (année)",
        UnitOfVolume.CUBIC_METERS,
        SensorDeviceClass.WATER,
        "mdi:water-thermometer",
    ),
    (
        "cetc",
        "cetc_annee",
        "Chauffage (année)",
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        "mdi:radiator",
    ),
)


# Factures annuelles calculées (cumul depuis le 1er janvier)
# (data_key source, option de prix, défaut, clé/translation, libellé, icône)
YEAR_PRICE_SENSORS: tuple[tuple[str, str, float, str, str, str], ...] = (
    (
        "eau_chaude",
        CONF_PRICE_HOT_WATER,
        DEFAULT_PRICE_HOT_WATER,
        "prix_eau_chaude_annee",
        "Facture eau chaude (année)",
        "mdi:cash",
    ),
    (
        "cetc",
        CONF_PRICE_THERMAL,
        DEFAULT_PRICE_THERMAL,
        "prix_thermique_chaud_annee",
        "Facture chauffage (année)",
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

    # Capteurs de consommation annuelle (cumul depuis le 1er janvier)
    year_data = (coordinator.data or {}).get("annee", {})
    for source_key, key, name, unit, device_class, icon in YEAR_SENSORS:
        if source_key in year_data:
            entities.append(
                OceaYearConsumptionSensor(
                    coordinator=coordinator,
                    local_id=local_id,
                    source_key=source_key,
                    key=key,
                    name=name,
                    unit=unit,
                    device_class=device_class,
                    icon=icon,
                )
            )

    # Factures annuelles calculées
    for source_key, option_key, default_price, key, name, icon in YEAR_PRICE_SENSORS:
        if source_key in year_data:
            price = float(
                config_entry.options.get(option_key, default_price)
            )
            entities.append(
                OceaYearPriceSensor(
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

    @property
    def last_reset(self) -> datetime | None:
        """Return when the monthly counter last reset (start of month).

        Ocea returns the consumption for the current month, which resets
        to zero on the 1st. Declaring last_reset lets Home Assistant treat
        the value as a per-month total instead of a lifetime meter.
        """
        return _start_of_current_month()

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

    @property
    def last_reset(self) -> datetime | None:
        """Return start of month: the cost is a monthly total that resets."""
        return _start_of_current_month()

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


class OceaYearConsumptionSensor(
    CoordinatorEntity[OceaDataUpdateCoordinator], SensorEntity
):
    """Yearly consumption sensor (sum since Jan 1st, daily detail in attrs).

    The long-term statistics of this entity are rewritten from the per-day
    values so the history graph shows each day's consumption.
    """

    _attr_has_entity_name = True
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: OceaDataUpdateCoordinator,
        local_id: str,
        source_key: str,
        key: str,
        name: str,
        unit: str,
        device_class: SensorDeviceClass,
        icon: str,
    ) -> None:
        """Initialize the yearly consumption sensor."""
        super().__init__(coordinator)
        self._local_id = local_id
        self._source_key = source_key
        self._key = key
        self._attr_translation_key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_{local_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, local_id)},
            "name": f"Ocea - Local {local_id}",
            "manufacturer": "Ocea Smart Building",
            "model": "Espace Résident",
        }

    def _year_data(self) -> dict | None:
        """Return the yearly aggregate dict for this fluid, if available."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("annee", {}).get(self._source_key)

    @property
    def native_value(self) -> float | None:
        """Return the yearly total consumption."""
        data = self._year_data()
        if data is None:
            return None
        return data.get("total")


    async def async_added_to_hass(self) -> None:
        """Import daily statistics once the entity_id is known."""
        await super().async_added_to_hass()
        self._import_daily_statistics()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the daily statistics on each data update."""
        self._import_daily_statistics()
        super()._handle_coordinator_update()

    def _import_daily_statistics(self) -> None:
        """Rewrite this entity's history from the per-day consumption."""
        data = self._year_data()
        if not data:
            return
        _import_entity_day_statistics(
            self.hass,
            self.entity_id,
            self._attr_native_unit_of_measurement,
            data.get("jours", {}),
        )


class OceaYearPriceSensor(
    CoordinatorEntity[OceaDataUpdateCoordinator], SensorEntity
):
    """Yearly bill sensor (yearly consumption * unit price).

    The long-term statistics are rewritten from the per-day bills so the
    history graph shows each day's cost.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
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
        """Initialize the yearly bill sensor."""
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

    def _year_data(self) -> dict | None:
        """Return the yearly aggregate dict for this fluid, if available."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("annee", {}).get(self._source_key)

    def _daily_bills(self) -> dict[str, float]:
        """Return the per-day bill (daily consumption * unit price)."""
        data = self._year_data()
        if data is None:
            return {}
        return {
            day: round(value * self._price, 2)
            for day, value in data.get("jours", {}).items()
        }

    @property
    def native_value(self) -> float | None:
        """Return the yearly bill (yearly total * unit price)."""
        data = self._year_data()
        if data is None or data.get("total") is None:
            return None
        return round(data["total"] * self._price, 2)


    async def async_added_to_hass(self) -> None:
        """Import daily statistics once the entity_id is known."""
        await super().async_added_to_hass()
        self._import_daily_statistics()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the daily statistics on each data update."""
        self._import_daily_statistics()
        super()._handle_coordinator_update()

    def _import_daily_statistics(self) -> None:
        """Rewrite this entity's history from the per-day bills."""
        _import_entity_day_statistics(
            self.hass,
            self.entity_id,
            CURRENCY_EURO,
            self._daily_bills(),
        )





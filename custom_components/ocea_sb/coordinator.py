"""DataUpdateCoordinator for Ocea Smart Building."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
)
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OceaApiClient, OceaAuthError, OceaApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Map internal data keys -> Ocea API "fluide" path used by the conso endpoint
FLUID_MAP: dict[str, str] = {
    "eau_froide": "EauFroide",
    "eau_chaude": "EauChaude",
    "cetc": "Cetc",
}

# Metadata for the long-term monthly statistics: key -> (display name, unit)
STAT_META: dict[str, tuple[str, str]] = {
    "eau_froide": ("Ocea eau froide (mensuel)", UnitOfVolume.CUBIC_METERS),
    "eau_chaude": ("Ocea eau chaude (mensuel)", UnitOfVolume.CUBIC_METERS),
    "cetc": ("Ocea Chauffage (mensuel)", UnitOfEnergy.KILO_WATT_HOUR),
}

# Display names for the monthly cost statistics: key -> display name
PRICE_STAT_NAMES: dict[str, str] = {
    "eau_chaude": "Ocea facture eau chaude (mensuel)",
    "cetc": "Ocea facture chauffage (mensuel)",
}


class OceaDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage fetching Ocea water consumption data."""

    def __init__(self, hass: HomeAssistant, client: OceaApiClient,
                 prices: dict[str, float] | None = None) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self._prices = prices or {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Ocea API (runs sync client in executor)."""
        _LOGGER.debug("Ocea coordinator: starting data fetch")
        try:
            raw_data = await self.hass.async_add_executor_job(
                self.client.get_consumptions
            )
        except OceaAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except OceaApiError as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

        result: dict[str, Any] = {}
        for item in raw_data:
            fluide = item.get("fluide", "")
            valeur_str = item.get("valeur", "0")
            # Ocea uses comma as decimal separator
            valeur = float(valeur_str.replace(",", "."))

            _LOGGER.info(
                "Ocea API a retourné le fluide '%s' avec la valeur %s",
                fluide,
                valeur_str,
            )

            if fluide == "EauFroide":
                result["eau_froide"] = valeur
            elif fluide == "EauChaude":
                result["eau_chaude"] = valeur
            elif fluide in ("Cetc", "CETC"):
                # Compteur d'énergie thermique chaude (kWh)
                result["cetc"] = valeur
            else:
                result[fluide.lower()] = valeur

        # Yearly consumption (since Jan 1st), aggregated per month
        result["annee"] = await self._async_fetch_year(list(result.keys()))

        # Inject per-month long-term statistics so HA can graph them
        self._import_monthly_statistics(result["annee"])

        _LOGGER.debug("Ocea consumption data updated: %s", result)
        return result

    async def _async_fetch_year(
        self, fluid_keys: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch and aggregate per-month consumption for the current year."""
        now = dt_util.now()
        year = now.year
        debut = f"{year}-01-01T00:00:00.000Z"
        fin = now.strftime("%Y-%m-%dT00:00:00.000Z")

        yearly: dict[str, dict[str, Any]] = {}
        for key in fluid_keys:
            fluide = FLUID_MAP.get(key)
            if not fluide:
                continue
            try:
                history = await self.hass.async_add_executor_job(
                    self.client.get_conso_history, fluide, debut, fin, "Day"
                )
            except OceaApiError as err:
                _LOGGER.warning(
                    "Impossible de récupérer l'historique annuel pour '%s' : %s",
                    fluide,
                    err,
                )
                continue
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Erreur inattendue lors de l'historique annuel '%s' : %s",
                    fluide,
                    err,
                )
                continue

            yearly[key] = self._aggregate_by_month(history)
            _LOGGER.info(
                "Ocea historique annuel '%s' : total %s, détail %s",
                key,
                yearly[key]["total"],
                yearly[key]["mois"],
            )

        return yearly

    @staticmethod
    def _aggregate_by_month(history: dict[str, Any]) -> dict[str, Any]:
        """Aggregate a daily consumption history into per-month totals."""
        mois: dict[str, float] = {}
        total = 0.0
        for entry in history.get("consommations", []):
            raw_val = entry.get("valeur", 0) or 0
            value = float(str(raw_val).replace(",", "."))
            date_str = str(entry.get("date", ""))
            month_key = date_str[:7]  # "YYYY-MM"
            if not month_key:
                continue
            mois[month_key] = round(mois.get(month_key, 0.0) + value, 3)
            total += value

        return {"total": round(total, 3), "mois": mois}

    def _import_monthly_statistics(
        self, yearly: dict[str, dict[str, Any]]
    ) -> None:
        """Push per-month values into Home Assistant long-term statistics.

        Creates one external statistic per fluid (e.g. ``ocea_sb:eau_chaude``)
        with a monthly cumulative sum, plus one cost statistic per priced
        fluid (e.g. ``ocea_sb:eau_chaude_facture``), so they can be displayed
        in a statistics graph card and the Energy dashboard.
        """
        for key, data in yearly.items():
            mois: dict[str, float] = data.get("mois", {})
            if not mois:
                continue

            # 1) Consumption statistic
            meta = STAT_META.get(key)
            if meta:
                name, unit = meta
                self._push_statistic(
                    statistic_id=f"{DOMAIN}:{key}",
                    name=name,
                    unit=unit,
                    monthly_values=mois,
                )

            # 2) Cost statistic (consumption * unit price)
            price = self._prices.get(key)
            price_name = PRICE_STAT_NAMES.get(key)
            if price and price_name:
                monthly_cost = {
                    month: round(value * price, 2)
                    for month, value in mois.items()
                }
                self._push_statistic(
                    statistic_id=f"{DOMAIN}:{key}_facture",
                    name=price_name,
                    unit=CURRENCY_EURO,
                    monthly_values=monthly_cost,
                )

    def _push_statistic(
        self,
        statistic_id: str,
        name: str,
        unit: str,
        monthly_values: dict[str, float],
    ) -> None:
        """Build and import a single external statistic from monthly values."""
        statistics: list[StatisticData] = []
        running_sum = 0.0
        for month_key in sorted(monthly_values):
            running_sum = round(running_sum + monthly_values[month_key], 2)
            statistics.append(
                StatisticData(
                    start=self._month_start_utc(month_key),
                    state=monthly_values[month_key],
                    sum=running_sum,
                )
            )

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=unit,
        )

        _LOGGER.debug(
            "Import de %d statistiques mensuelles pour %s",
            len(statistics),
            statistic_id,
        )
        async_add_external_statistics(self.hass, metadata, statistics)

    @staticmethod
    def _month_start_utc(month_key: str) -> datetime:
        """Return the UTC datetime for the first day of a 'YYYY-MM' month."""
        year, month = (int(part) for part in month_key.split("-"))
        local = datetime(
            year, month, 1, tzinfo=dt_util.DEFAULT_TIME_ZONE
        )
        return dt_util.as_utc(local)




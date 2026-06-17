"""Button platform for Ocea Smart Building (manual refresh)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_LOCAL_ID, DOMAIN
from .coordinator import OceaDataUpdateCoordinator

REFRESH_BUTTON = ButtonEntityDescription(
    key="refresh",
    translation_key="refresh",
    name="Rafraîchir",
    icon="mdi:refresh",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Ocea refresh button from a config entry."""
    coordinator: OceaDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    local_id = config_entry.data[CONF_LOCAL_ID]

    async_add_entities([OceaRefreshButton(coordinator, local_id)])


class OceaRefreshButton(
    CoordinatorEntity[OceaDataUpdateCoordinator], ButtonEntity
):
    """Button to trigger an immediate refresh of Ocea consumption data."""

    entity_description = REFRESH_BUTTON
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OceaDataUpdateCoordinator,
        local_id: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self._local_id = local_id
        self._attr_unique_id = f"{DOMAIN}_{local_id}_refresh"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, local_id)},
            "name": f"Ocea - Local {local_id}",
            "manufacturer": "Ocea Smart Building",
            "model": "Espace Résident",
        }

    async def async_press(self) -> None:
        """Handle the button press: request an immediate data refresh."""
        await self.coordinator.async_request_refresh()


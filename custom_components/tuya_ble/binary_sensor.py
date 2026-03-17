"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
)
from .devices import (
    TuyaBLEData,
    TuyaBLEEntity,
    TuyaBLEPassiveCoordinator,
    TuyaBLEProductInfo,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

SIGNAL_STRENGTH_DP_ID = -1


TuyaBLEBinarySensorIsAvailable = (
    Callable[["TuyaBLEBinarySensor", TuyaBLEProductInfo], bool] | None
)


@dataclass
class TuyaBLEBinarySensorMapping:
    """
    Mapping for a Tuya BLE binary sensor.

    Attributes:
        dp_id: The datapoint ID for the sensor.
        description: The entity description for the sensor.
        force_add: Whether to force add the sensor entity.
        dp_type: The type of datapoint.
        getter: Optional custom getter function for the sensor.
        is_available: Optional function to determine sensor availability.

    """

    dp_id: int
    description: BinarySensorEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    getter: Callable[[TuyaBLEBinarySensor], None] | None = None
    # coefficient: float = 1.0  # noqa: ERA001
    # icons: list[str] | None = None  # noqa: ERA001
    is_available: TuyaBLEBinarySensorIsAvailable = None


@dataclass
class TuyaBLECategoryBinarySensorMapping:
    """
    Mapping for Tuya BLE binary sensor categories.

    Attributes:
        products: Optional dictionary mapping product IDs to lists of sensor mappings.
        mapping: Optional list of sensor mappings for the category.

    """

    products: dict[str, list[TuyaBLEBinarySensorMapping]] | None = None
    mapping: list[TuyaBLEBinarySensorMapping] | None = None


mapping: dict[str, TuyaBLECategoryBinarySensorMapping] = {
    "wk": TuyaBLECategoryBinarySensorMapping(
        products={
            "drlajpqc": [  # Thermostatic Radiator Valve
                TuyaBLEBinarySensorMapping(
                    dp_id=105,
                    description=BinarySensorEntityDescription(
                        key="battery",
                        # icon="mdi:battery-alert",  # noqa: ERA001
                        device_class=BinarySensorDeviceClass.BATTERY,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
            ],
        },
    ),
    "cl": TuyaBLECategoryBinarySensorMapping(
        products={
            "kcy0x4pi": [  # Smart Curtain Robot
                TuyaBLEBinarySensorMapping(
                    dp_id=12,  # fault bitmap
                    description=BinarySensorEntityDescription(
                        key="motor_fault",
                        device_class=BinarySensorDeviceClass.PROBLEM,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                    dp_type=None,
                    getter=lambda self: setattr(
                        self,
                        "_attr_is_on",
                        bool(
                            (datapoint := self._device.datapoints[12]) is not None
                            and isinstance(datapoint.value, int)
                            and (datapoint.value & 0x1)
                        ),
                    ),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLEBinarySensorMapping]:
    """
    Retrieve the list of Tuya BLE binary sensor mappings for a given device.

    Args:
        device (TuyaBLEDevice): The Tuya BLE device to get mappings for.

    Returns:
        list[TuyaBLEBinarySensorMapping]: List of sensor mappings for the device.

    """
    category = mapping.get(device.category)
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            return product_mapping
        if category.mapping is not None:
            return category.mapping
        return []
    return []


class TuyaBLEBinarySensor(TuyaBLEEntity, BinarySensorEntity):
    """
    Represents a Tuya BLE binary sensor entity in Home Assistant.

    Handles state updates and availability for Tuya BLE binary sensors
    based on device mappings.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLEBinarySensorMapping,
    ) -> None:
        """
        Initialize a Tuya BLE binary sensor entity.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            coordinator (TuyaBLECoordinator): Coordinator for data updates.
            device (TuyaBLEDevice): The Tuya BLE device.
            product (TuyaBLEProductInfo): Product information.
            mapping (TuyaBLEBinarySensorMapping): Mapping for the binary sensor.

        """
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._mapping.getter is not None:
            self._mapping.getter(self)
        else:
            try:
                datapoint = self._device.datapoints[self._mapping.dp_id]
            except KeyError:
                datapoint = None
            if datapoint is not None and hasattr(datapoint, "value"):
                self._attr_is_on = bool(datapoint.value)
                """
                if datapoint.type == TuyaBLEDataPointType.DT_ENUM:
                    if self.entity_description.options is not None:
                        if datapoint.value >= 0 and datapoint.value < len(
                            self.entity_description.options
                        ):
                            self._attr_native_value = self.entity_description.options[
                                datapoint.value
                            ]
                        else:
                            self._attr_native_value = datapoint.value
                    if self._mapping.icons is not None:
                        if datapoint.value >= 0 and datapoint.value < len(
                            self._mapping.icons
                        ):
                            self._attr_icon = self._mapping.icons[datapoint.value]
                elif datapoint.type == TuyaBLEDataPointType.DT_VALUE:
                    self._attr_native_value = (
                        datapoint.value / self._mapping.coefficient
                    )
                else:
                    self._attr_native_value = datapoint.value
                """
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and callable(self._mapping.is_available):
            result = self._mapping.is_available(self, self._product)
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up Tuya BLE binary sensor entities from a config entry.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The configuration entry.
        async_add_entities (AddEntitiesCallback): Callback to add entities.

    Returns:
        None

    """
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLEBinarySensor] = [
        TuyaBLEBinarySensor(
            hass,
            data.coordinator,
            data.device,
            data.product,
            mapping,
        )
        for mapping in mappings
        if mapping.force_add
        or data.device.datapoints.has_id(mapping.dp_id, mapping.dp_type)
    ]
    async_add_entities(entities)

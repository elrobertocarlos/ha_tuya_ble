"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)

from .const import DOMAIN
from .devices import (
    TuyaBLEData,
    TuyaBLEEntity,
    TuyaBLEPassiveCoordinator,
    TuyaBLEProductInfo,
)
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


TuyaBLEButtonIsAvailable = Callable[["TuyaBLEButton", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLEButtonMapping:
    """
    Mapping for a Tuya BLE button.

    Attributes:
        dp_id (int): The datapoint ID associated with the button.
        description (ButtonEntityDescription): The entity description for the button.
        force_add (bool): Whether to force add the button entity.
        dp_type (TuyaBLEDataPointType | None): The type of the datapoint.
        is_available (TuyaBLEButtonIsAvailable): Callable to determine if the button is
        available.

    """

    dp_id: int
    description: ButtonEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    is_available: TuyaBLEButtonIsAvailable = None


def is_fingerbot_in_push_mode(self: TuyaBLEButton, product: TuyaBLEProductInfo) -> bool:
    """
    Determine if the Fingerbot is in push mode.

    Args:
        self (TuyaBLEButton): The button entity instance.
        product (TuyaBLEProductInfo): The product information.

    Returns:
        bool: True if the Fingerbot is in push mode, False otherwise.

    """
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 0
    return result


@dataclass
class TuyaBLEFingerbotModeMapping(TuyaBLEButtonMapping):
    """
    Mapping for a Tuya BLE Fingerbot button mode, extending TuyaBLEButtonMapping.

    This class provides a default description for the Fingerbot push mode and sets
    the availability check to determine if the Fingerbot is in push mode.
    """

    description: ButtonEntityDescription = field(
        default_factory=lambda: ButtonEntityDescription(
            key="push",
        )
    )
    is_available: TuyaBLEButtonIsAvailable = is_fingerbot_in_push_mode


@dataclass
class TuyaBLECategoryButtonMapping:
    """
    Represents a mapping of Tuya BLE button configurations for a specific category.

    Attributes:
        products (dict[str, list[TuyaBLEButtonMapping]] | None):
            Product-specific button mappings.
        mapping (list[TuyaBLEButtonMapping] | None):
            Default button mappings for the category.

    """

    products: dict[str, list[TuyaBLEButtonMapping]] | None = None
    mapping: list[TuyaBLEButtonMapping] | None = None


mapping: dict[str, TuyaBLECategoryButtonMapping] = {
    "szjqr": TuyaBLECategoryButtonMapping(
        products={
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=1)]
                for k in ["3yqdo5yt", "xhf790if"]
            },  # CubeTouch 1s and II
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=2)]
                for k in [
                    "blliqpsj",
                    "ndvkgsrm",
                    "yiihr7zh",
                    "neq16kgd",
                ]
            },  # Fingerbot Plus
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=2)]
                for k in [
                    "ltak7e1p",
                    "y6kttvd6",
                    "yrnk7mnn",
                    "nvr2rocq",
                    "bnt7wajf",
                    "rvdceqjh",
                    "5xhbk964",
                ]
            },  # Fingerbot
        },
    ),
    "kg": TuyaBLECategoryButtonMapping(
        products={
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=108)]
                for k in ["mknd4lci", "riecov42"]
            },  # Fingerbot Plus
        },
    ),
    "znhsb": TuyaBLECategoryButtonMapping(
        products={
            "cdlandip":  # Smart water bottle
            [
                TuyaBLEButtonMapping(
                    dp_id=109,
                    description=ButtonEntityDescription(
                        key="bright_lid_screen",
                    ),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLEButtonMapping]:
    """
    Retrieve the list of TuyaBLEButtonMapping objects for a given TuyaBLEDevice.

    Args:
        device (TuyaBLEDevice): The device for which to get button mappings.

    Returns:
        list[TuyaBLEButtonMapping]: A list of button mappings for the device.

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


class TuyaBLEButton(TuyaBLEEntity, ButtonEntity):
    """Representation of a Tuya BLE Button."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLEButtonMapping,
    ) -> None:
        """
        Initialize a TuyaBLEButton entity.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            coordinator (TuyaBLEPassiveCoordinator): The coordinator for
            passive updates.
            device (TuyaBLEDevice): The Tuya BLE device.
            product (TuyaBLEProductInfo): The product information.
            mapping (TuyaBLEButtonMapping): The button mapping configuration.

        """
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    def press(self) -> None:
        """Press the button."""
        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            TuyaBLEDataPointType.DT_BOOL,
            False,  # noqa: FBT003
        )
        if datapoint:
            self._hass.create_task(datapoint.set_value(not bool(datapoint.value)))

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
    Set up Tuya BLE button entities from a config entry.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The configuration entry.
        async_add_entities (AddEntitiesCallback): Callback to add entities.

    """
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLEButton] = [
        TuyaBLEButton(
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

"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from struct import pack, unpack
from typing import TYPE_CHECKING

from homeassistant.components.text import (
    TextEntity,
    TextEntityDescription,
)
from homeassistant.const import EntityCategory

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

SIGNAL_STRENGTH_DP_ID = -1

TuyaBLETextGetter = Callable[["TuyaBLEText", TuyaBLEProductInfo], str | None] | None


TuyaBLETextIsAvailable = Callable[["TuyaBLEText", TuyaBLEProductInfo], bool] | None


TuyaBLETextSetter = Callable[["TuyaBLEText", TuyaBLEProductInfo, str], None] | None


FINGERBOT_PROGRAM_MODE = 2


def is_fingerbot_in_program_mode(
    self: TuyaBLEText,
    product: TuyaBLEProductInfo,
) -> bool:
    """
    Determine if the Fingerbot device is in program mode.

    Args:
        self: The TuyaBLEText instance.
        product: The TuyaBLEProductInfo for the device.

    Returns:
        True if the Fingerbot is in program mode, False otherwise.

    """
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == FINGERBOT_PROGRAM_MODE
    return result


def get_fingerbot_program(
    self: TuyaBLEText,
    product: TuyaBLEProductInfo,
) -> str | None:
    """
    Retrieve the Fingerbot program steps as a formatted string.

    Args:
        self: The TuyaBLEText instance.
        product: The TuyaBLEProductInfo for the device.

    Returns:
        A string representing the program steps, formatted as "position/delay;...",
        or None if unavailable.

    """
    result: str = ""
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            step_count: int = datapoint.value[3]
            for step in range(step_count):
                step_pos = 4 + step * 3
                step_data = datapoint.value[step_pos : step_pos + 3]
                position, delay = unpack(">BH", step_data)
                delay = min(delay, 9999)
                result += (
                    (";" if step > 0 else "")
                    + str(position)
                    + (("/" + str(delay)) if delay > 0 else "")
                )
    return result or None


def set_fingerbot_program(
    self: TuyaBLEText,
    product: TuyaBLEProductInfo,
    value: str,
) -> None:
    """
    Set the Fingerbot program steps based on the provided value string.

    Args:
        self: The TuyaBLEText instance.
        product: The TuyaBLEProductInfo for the device.
        value: A string representing the program steps, formatted
            as "position/delay;...".

    This function parses the value string, constructs the appropriate byte array,
    and schedules an update to the device's datapoint.

    """
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            new_value = bytearray(datapoint.value[0:3])
            steps = value.split(";")
            new_value += int.to_bytes(len(steps), 1, "big")
            for step in steps:
                step_values = step.split("/")
                position = int(step_values[0])
                delay = int(step_values[1]) if len(step_values) > 1 else 0
                new_value += pack(">BH", position, delay)
            self._hass.create_task(datapoint.set_value(new_value))


@dataclass
class TuyaBLETextMapping:
    """
    Mapping configuration for a Tuya BLE text entity.

    Attributes:
        dp_id: The datapoint ID associated with this text entity.
        description: The entity description for Home Assistant.
        force_add: Whether to always add this entity.
        dp_type: The type of the datapoint.
        default_value: The default value for the text entity.
        is_available: Callable to determine if the entity is available.
        getter: Callable to get the value of the entity.
        setter: Callable to set the value of the entity.

    """

    dp_id: int
    description: TextEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    default_value: str | None = None
    is_available: TuyaBLETextIsAvailable = None
    getter: TuyaBLETextGetter = None
    setter: TuyaBLETextSetter = None


@dataclass
class TuyaBLECategoryTextMapping:
    """
    Represents a mapping of Tuya BLE text entities for a specific category.

    Attributes:
        products: Optional dictionary mapping product IDs to lists
            of TuyaBLETextMapping.
        mapping: Optional list of TuyaBLETextMapping for the category.

    """

    products: dict[str, list[TuyaBLETextMapping]] | None = None
    mapping: list[TuyaBLETextMapping] | None = None


mapping: dict[str, TuyaBLECategoryTextMapping] = {
    "szjqr": TuyaBLECategoryTextMapping(  # Fingerbot Plus
        products={
            **{
                k: [
                    TuyaBLETextMapping(
                        dp_id=121,
                        description=TextEntityDescription(
                            key="program",
                            icon="mdi:repeat",
                            pattern=r"^((\d{1,2}|100)(\/\d{1,2})?)(;((\d{1,2}|100)(\/\d{1,2})?))+$",
                            entity_category=EntityCategory.CONFIG,
                        ),
                        is_available=is_fingerbot_in_program_mode,
                        getter=get_fingerbot_program,
                        setter=set_fingerbot_program,
                    ),
                ]
                for k in ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"]
            },
        },
    ),
    "kg": TuyaBLECategoryTextMapping(  # Fingerbot Plus
        products={
            **{
                k: [
                    TuyaBLETextMapping(
                        dp_id=109,
                        description=TextEntityDescription(
                            key="program",
                            icon="mdi:repeat",
                            pattern=r"^((\d{1,2}|100)(\/\d{1,2})?)(;((\d{1,2}|100)(\/\d{1,2})?))+$",
                            entity_category=EntityCategory.CONFIG,
                        ),
                        is_available=is_fingerbot_in_program_mode,
                        getter=get_fingerbot_program,
                        setter=set_fingerbot_program,
                    ),
                ]
                for k in ["mknd4lci", "riecov42"]
            },
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLETextMapping]:
    """
    Retrieve the list of TuyaBLETextMapping objects for a given TuyaBLEDevice.

    Args:
        device: The TuyaBLEDevice instance to look up mappings for.

    Returns:
        A list of TuyaBLETextMapping objects associated with the device.

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


class TuyaBLEText(TuyaBLEEntity, TextEntity):
    """Text entity for Tuya BLE devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLETextMapping,
    ) -> None:
        """
        Initialize a TuyaBLEText entity.

        Args:
            hass: HomeAssistant instance.
            coordinator: Coordinator for passive updates.
            device: The Tuya BLE device.
            product: Product information for the device.
            mapping: Mapping configuration for the text entity.

        """
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and self._mapping.is_available:
            result = self._mapping.is_available(self, self._product)
        return result

    @property
    def native_value(self) -> str | None:
        """Return the value reported by the text."""
        if self._mapping.getter is not None:
            return self._mapping.getter(self, self._product)

        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint:
            return str(datapoint.value)

        return self._mapping.default_value

    def set_value(self, value: str) -> None:
        """Change the value."""
        if self._mapping.setter:
            self._mapping.setter(self, self._product, value)
            return
        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            TuyaBLEDataPointType.DT_STRING,
            value,
        )
        if datapoint:
            self._hass.create_task(datapoint.set_value(value))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE sensors."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLEText] = [
        TuyaBLEText(
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

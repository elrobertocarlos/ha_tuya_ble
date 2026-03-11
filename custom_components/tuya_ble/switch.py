"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .devices import (
    TuyaBLEData,
    TuyaBLEEntity,
    TuyaBLEPassiveCoordinator,
    TuyaBLEProductInfo,
)
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


TuyaBLESwitchGetter = (
    Callable[["TuyaBLESwitch", TuyaBLEProductInfo], bool | None] | None
)


TuyaBLESwitchIsAvailable = Callable[["TuyaBLESwitch", TuyaBLEProductInfo], bool] | None


TuyaBLESwitchSetter = Callable[["TuyaBLESwitch", TuyaBLEProductInfo, bool], None] | None


@dataclass
class TuyaBLESwitchMapping:
    """
    Mapping for a Tuya BLE switch.

    Attributes:
        dp_id: The datapoint ID for the switch.
        description: The entity description for the switch.
        force_add: Whether to always add the switch entity.
        dp_type: The type of datapoint.
        bitmap_mask: Optional bitmap mask for the datapoint.
        is_available: Callable to determine if the switch is available.
        getter: Callable to get the switch state.
        setter: Callable to set the switch state.

    """

    dp_id: int
    description: SwitchEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    bitmap_mask: bytes | None = None
    is_available: TuyaBLESwitchIsAvailable = None
    getter: TuyaBLESwitchGetter = None
    setter: TuyaBLESwitchSetter = None


FINGERBOT_MODE_PROGRAM = 2


def is_fingerbot_in_program_mode(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool:
    """
    Determine if the Fingerbot is in program mode.

    Args:
        self (TuyaBLESwitch): The switch entity instance.
        product (TuyaBLEProductInfo): The product information.

    Returns:
        bool: True if the Fingerbot is in program mode, False otherwise.

    """
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == FINGERBOT_MODE_PROGRAM
    return result


def is_fingerbot_in_switch_mode(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool:
    """
    Determine if the Fingerbot is in switch mode.

    Args:
        self (TuyaBLESwitch): The switch entity instance.
        product (TuyaBLEProductInfo): The product information.

    Returns:
        bool: True if the Fingerbot is in switch mode, False otherwise.

    """
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 1
    return result


FINGERBOT_REPEAT_FOREVER = 0xFFFF


def get_fingerbot_program_repeat_forever(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool | None:
    """
    Determine if the Fingerbot program is set to repeat forever.

    Args:
        self (TuyaBLESwitch): The switch entity instance.
        product (TuyaBLEProductInfo): The product information.

    Returns:
        bool | None: True if repeat forever is set, False if not,
            or None if unavailable.

    """
    result: bool | None = None
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            repeat_count = int.from_bytes(datapoint.value[0:2], "big")
            result = repeat_count == FINGERBOT_REPEAT_FOREVER
    return result


def set_fingerbot_program_repeat_forever(
    self: TuyaBLESwitch,
    product: TuyaBLEProductInfo,
    value: bool,  # noqa: FBT001
) -> None:
    """
    Set the Fingerbot program to repeat forever or not.

    Args:
        self (TuyaBLESwitch): The switch entity instance.
        product (TuyaBLEProductInfo): The product information.
        value (bool): True to set repeat forever, False otherwise.

    Returns:
        None

    """
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            new_value = (
                int.to_bytes(FINGERBOT_REPEAT_FOREVER if value else 1, 2, "big")
                + datapoint.value[2:]
            )
            self._hass.create_task(datapoint.set_value(new_value))


@dataclass
class TuyaBLEFingerbotSwitchMapping(TuyaBLESwitchMapping):
    """Switch mapping for Tuya BLE Fingerbot devices."""

    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="switch",
        )
    )
    is_available: TuyaBLESwitchIsAvailable = is_fingerbot_in_switch_mode


@dataclass
class TuyaBLEReversePositionsMapping(TuyaBLESwitchMapping):
    """Switch mapping for reverse positions on Tuya BLE Fingerbot devices."""

    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="reverse_positions",
            icon="mdi:arrow-up-down-bold",
            entity_category=EntityCategory.CONFIG,
        )
    )
    is_available: TuyaBLESwitchIsAvailable = is_fingerbot_in_switch_mode


@dataclass
class TuyaBLECategorySwitchMapping:
    """
    Category switch mapping for Tuya BLE devices.

    Attributes:
        products: Optional dictionary mapping product IDs to lists of switch mappings.
        mapping: Optional list of switch mappings for the category.

    """

    products: dict[str, list[TuyaBLESwitchMapping]] | None = None
    mapping: list[TuyaBLESwitchMapping] | None = None


mapping: dict[str, TuyaBLECategorySwitchMapping] = {
    "co2bj": TuyaBLECategorySwitchMapping(
        products={
            "59s19z5m": [  # CO2 Detector
                TuyaBLESwitchMapping(
                    dp_id=11,
                    description=SwitchEntityDescription(
                        key="carbon_dioxide_severely_exceed_alarm",
                        icon="mdi:molecule-co2",
                        entity_category=EntityCategory.CONFIG,
                        entity_registry_enabled_default=False,
                    ),
                    bitmap_mask=b"\x01",
                ),
                TuyaBLESwitchMapping(
                    dp_id=11,
                    description=SwitchEntityDescription(
                        key="low_battery_alarm",
                        icon="mdi:battery-alert",
                        entity_category=EntityCategory.CONFIG,
                        entity_registry_enabled_default=False,
                    ),
                    bitmap_mask=b"\x02",
                ),
                TuyaBLESwitchMapping(
                    dp_id=13,
                    description=SwitchEntityDescription(
                        key="carbon_dioxide_alarm_switch",
                        icon="mdi:molecule-co2",
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "ms": TuyaBLECategorySwitchMapping(
        products={
            **{
                k: [
                    TuyaBLESwitchMapping(
                        dp_id=47,
                        description=SwitchEntityDescription(
                            key="lock_motor_state",
                        ),
                    ),
                ]
                for k in ["ludzroix", "isk2p555"]  # Smart Lock
            },
        }
    ),
    "szjqr": TuyaBLECategorySwitchMapping(
        products={
            **{
                k: [
                    TuyaBLEFingerbotSwitchMapping(dp_id=1),
                    TuyaBLEReversePositionsMapping(dp_id=4),
                ]
                for k in ["3yqdo5yt", "xhf790if"]
            },  # CubeTouch 1s and II
            **{
                k: [
                    TuyaBLEFingerbotSwitchMapping(dp_id=2),
                    TuyaBLEReversePositionsMapping(dp_id=11),
                    TuyaBLESwitchMapping(
                        dp_id=17,
                        description=SwitchEntityDescription(
                            key="manual_control",
                            icon="mdi:gesture-tap-box",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=2,
                        description=SwitchEntityDescription(
                            key="program",
                            icon="mdi:repeat",
                        ),
                        is_available=is_fingerbot_in_program_mode,
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=121,
                        description=SwitchEntityDescription(
                            key="program_repeat_forever",
                            icon="mdi:repeat",
                            entity_category=EntityCategory.CONFIG,
                        ),
                        getter=get_fingerbot_program_repeat_forever,
                        is_available=is_fingerbot_in_program_mode,
                        setter=set_fingerbot_program_repeat_forever,
                    ),
                ]
                for k in ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"]
            },
            **{
                k: [
                    TuyaBLEFingerbotSwitchMapping(dp_id=2),
                    TuyaBLEReversePositionsMapping(dp_id=11),
                ]
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
    "kg": TuyaBLECategorySwitchMapping(
        products={
            **{
                k: [
                    TuyaBLEFingerbotSwitchMapping(dp_id=1),
                    TuyaBLEReversePositionsMapping(dp_id=104),
                    TuyaBLESwitchMapping(
                        dp_id=107,
                        description=SwitchEntityDescription(
                            key="manual_control",
                            icon="mdi:gesture-tap-box",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=1,
                        description=SwitchEntityDescription(
                            key="program",
                            icon="mdi:repeat",
                        ),
                        is_available=is_fingerbot_in_program_mode,
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=109,
                        description=SwitchEntityDescription(
                            key="program_repeat_forever",
                            icon="mdi:repeat",
                            entity_category=EntityCategory.CONFIG,
                        ),
                        getter=get_fingerbot_program_repeat_forever,
                        is_available=is_fingerbot_in_program_mode,
                        setter=set_fingerbot_program_repeat_forever,
                    ),
                ]
                for k in ["mknd4lci", "riecov42"]
            },
        },
    ),
    "wk": TuyaBLECategorySwitchMapping(
        products={
            **{
                k: [
                    TuyaBLESwitchMapping(
                        dp_id=8,
                        description=SwitchEntityDescription(
                            key="window_check",
                            icon="mdi:window-closed",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=10,
                        description=SwitchEntityDescription(
                            key="antifreeze",
                            icon="mdi:snowflake-off",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=40,
                        description=SwitchEntityDescription(
                            key="child_lock",
                            icon="mdi:account-lock",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=130,
                        description=SwitchEntityDescription(
                            key="water_scale_proof",
                            icon="mdi:water-check",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=107,
                        description=SwitchEntityDescription(
                            key="programming_mode",
                            icon="mdi:calendar-edit",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=108,
                        description=SwitchEntityDescription(
                            key="programming_switch",
                            icon="mdi:calendar-clock",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                ]
                for k in [
                    "drlajpqc",
                    "nhj2j7su",
                ]
            },
        },
    ),
    "wsdcg": TuyaBLECategorySwitchMapping(
        products={
            "ojzlzzsw": [  # Soil moisture sensor
                TuyaBLESwitchMapping(
                    dp_id=21,
                    description=SwitchEntityDescription(
                        key="switch",
                        icon="mdi:thermometer",
                        entity_category=EntityCategory.CONFIG,
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
        },
    ),
    "ggq": TuyaBLECategorySwitchMapping(
        products={
            "6pahkcau": [  # Irrigation computer
                TuyaBLESwitchMapping(
                    dp_id=1,
                    description=SwitchEntityDescription(
                        key="water_valve",
                        entity_registry_enabled_default=True,
                    ),
                ),
            ],
            "hfgdqhho": [  # Irrigation computer
                TuyaBLESwitchMapping(
                    dp_id=105,
                    description=SwitchEntityDescription(
                        key="water_valve_z1",
                        entity_registry_enabled_default=True,
                    ),
                ),
                TuyaBLESwitchMapping(
                    dp_id=104,
                    description=SwitchEntityDescription(
                        key="water_valve_z2",
                        entity_registry_enabled_default=True,
                    ),
                ),
            ],
            "fnlw6npo": [  # Irrigation computer - BWV-YC02S
                TuyaBLESwitchMapping(
                    dp_id=105,
                    description=SwitchEntityDescription(
                        key="water_valve_z1",
                        entity_registry_enabled_default=True,
                    ),
                ),
                TuyaBLESwitchMapping(
                    dp_id=104,
                    description=SwitchEntityDescription(
                        key="water_valve_z2",
                        entity_registry_enabled_default=True,
                    ),
                ),
            ],
        },
    ),
    "sfkzq": TuyaBLECategorySwitchMapping(
        products={
            "nxquc5lb": [  # Smart water timer - SOP10
                TuyaBLESwitchMapping(
                    dp_id=1,
                    description=SwitchEntityDescription(
                        key="water_valve",
                        entity_registry_enabled_default=True,
                    ),
                ),
                TuyaBLESwitchMapping(
                    dp_id=14,
                    description=SwitchEntityDescription(
                        key="weather_switch",
                        icon="mdi:cloud-question",
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLESwitchMapping]:
    """
    Retrieve the list of switch mappings for a given Tuya BLE device.

    Args:
        device (TuyaBLEDevice): The Tuya BLE device instance.

    Returns:
        list[TuyaBLECategorySwitchMapping]: A list of switch mappings for the device.

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


class TuyaBLESwitch(TuyaBLEEntity, SwitchEntity):
    """Representation of a Tuya BLE Switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESwitchMapping,
    ) -> None:
        """
        Initialize a Tuya BLE Switch entity.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            coordinator (TuyaBLEPassiveCoordinator): The update coordinator.
            device (TuyaBLEDevice): The Tuya BLE device.
            product (TuyaBLEProductInfo): The product information.
            mapping (TuyaBLESwitchMapping): The switch mapping configuration.

        """
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        if self._mapping.getter is not None:
            result = self._mapping.getter(self, self._product)
            return bool(result) if result is not None else False

        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint:
            if (
                datapoint.type
                in [TuyaBLEDataPointType.DT_RAW, TuyaBLEDataPointType.DT_BITMAP]
                and self._mapping.bitmap_mask
            ):
                value = datapoint.value
                if isinstance(value, bytes):
                    bitmap_value = value
                elif isinstance(value, int):
                    bitmap_value = value.to_bytes(
                        (value.bit_length() + 7) // 8 or 1, "big"
                    )
                elif isinstance(value, str):
                    bitmap_value = value.encode()
                else:
                    bitmap_value = bytes(value)
                bitmap_mask = self._mapping.bitmap_mask
                for v, m in zip(bitmap_value, bitmap_mask, strict=True):
                    if (v & m) != 0:
                        return True
            else:
                return bool(datapoint.value)
        return False

    def turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch on."""
        if self._mapping.setter:
            return self._mapping.setter(self, self._product, True)  # noqa: FBT003

        new_value: bool | bytes
        if self._mapping.bitmap_mask:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BITMAP,
                self._mapping.bitmap_mask,
            )
            bitmap_mask = self._mapping.bitmap_mask
            value = datapoint.value
            if isinstance(value, bytes):
                bitmap_value = value
            elif isinstance(value, int):
                bitmap_value = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
            elif isinstance(value, str):
                bitmap_value = value.encode()
            else:
                bitmap_value = bytes(value)
            new_value = bytes(
                v | m for (v, m) in zip(bitmap_value, bitmap_mask, strict=True)
            )
        else:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                True,  # noqa: FBT003
            )
            new_value = True
        if datapoint:
            self._hass.create_task(datapoint.set_value(new_value))
        return None

    def turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch off."""
        if self._mapping.setter:
            return self._mapping.setter(self, self._product, False)  # noqa: FBT003

        new_value: bool | bytes
        if self._mapping.bitmap_mask:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BITMAP,
                self._mapping.bitmap_mask,
            )
            bitmap_mask = self._mapping.bitmap_mask
            value = datapoint.value
            if isinstance(value, bytes):
                bitmap_value = value
            elif isinstance(value, int):
                bitmap_value = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
            elif isinstance(value, str):
                bitmap_value = value.encode()
            else:
                bitmap_value = bytes(value)
            new_value = bytes(
                v & ~m for (v, m) in zip(bitmap_value, bitmap_mask, strict=True)
            )
        else:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                False,  # noqa: FBT003
            )
            new_value = False
        if datapoint:
            self._hass.create_task(datapoint.set_value(new_value))
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and self._mapping.is_available:
            result = self._mapping.is_available(self, self._product)
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up Tuya BLE switch entities from a config entry.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The configuration entry.
        async_add_entities (AddEntitiesCallback): Callback to add entities.

    Returns:
        None

    """
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLESwitch] = [
        TuyaBLESwitch(
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

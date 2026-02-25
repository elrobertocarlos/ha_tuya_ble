"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityDescription,
)

from .const import DOMAIN
from .devices import TuyaBLECoordinator, TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


TuyaBLECoverIsAvailable = Callable[["TuyaBLECover", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLECoverMapping:
    """
    Mapping configuration for a Tuya BLE cover entity.

    Attributes
    ----------
    dp_id : int
        The primary datapoint ID for the cover (typically current position).
    description : CoverEntityDescription
        The entity description including device class and key.
    force_add : bool
        Whether to force add the entity even if datapoint is not available.
    dp_type : TuyaBLEDataPointType | None
        The expected datapoint type.
    is_available : TuyaBLECoverIsAvailable
        Optional callback to determine if the cover is available.
    position_dp_id : int | None
        The datapoint ID for setting cover position.
    control_dp_id : int | None
        The datapoint ID for control commands (open/close/stop).

    """

    dp_id: int
    description: CoverEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    is_available: TuyaBLECoverIsAvailable = None
    # Data point IDs for position and control
    position_dp_id: int | None = None
    control_dp_id: int | None = None


@dataclass
class TuyaBLECategoryCoverMapping:
    """
    Category-level mapping configuration for Tuya BLE cover entities.

    Attributes
    ----------
    products : dict[str, list[TuyaBLECoverMapping]] | None
        Product-specific mappings keyed by product ID.
    mapping : list[TuyaBLECoverMapping] | None
        Category-level mappings applied to all products in the category.

    """

    products: dict[str, list[TuyaBLECoverMapping]] | None = None
    mapping: list[TuyaBLECoverMapping] | None = None


mapping: dict[str, TuyaBLECategoryCoverMapping] = {
    "cl": TuyaBLECategoryCoverMapping(
        products={
            "kcy0x4pi": [  # Smart Curtain Robot
                TuyaBLECoverMapping(
                    dp_id=3,  # percent_state - current position
                    description=CoverEntityDescription(
                        key="curtain",
                        device_class=CoverDeviceClass.CURTAIN,
                    ),
                    position_dp_id=2,  # percent_control - for setting position
                    control_dp_id=1,  # control - for open/close/stop commands
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLECoverMapping]:
    """
    Get cover mappings for a Tuya BLE device.

    Parameters
    ----------
    device : TuyaBLEDevice
        The Tuya BLE device to get mappings for.

    Returns
    -------
    list[TuyaBLECoverMapping]
        List of cover mappings for the device, or empty list if none found.

    """
    _LOGGER.debug(
        "get_mapping_by_device called for device: address=%s, category=%s,"
        "product_id=%s",
        device.address,
        device.category,
        device.product_id,
    )
    _LOGGER.debug(
        "Device available datapoint IDs: %s",
        [dp_id for dp_id in range(1, 30) if device.datapoints.has_id(dp_id)],
    )
    category = mapping.get(device.category)
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            _LOGGER.debug(
                "Found product mapping for %s/%s: %d mappings",
                device.category,
                device.product_id,
                len(product_mapping),
            )
            return product_mapping
        if category.mapping is not None:
            _LOGGER.debug(
                "Found category-level mapping for %s: %d mappings",
                device.category,
                len(category.mapping),
            )
            return category.mapping
        _LOGGER.debug("No product or category mapping found for %s", device.category)
        return []
    _LOGGER.debug("No category mapping found for %s", device.category)
    return []


class TuyaBLECover(TuyaBLEEntity, CoverEntity):
    """Representation of a Tuya BLE Cover."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLECoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLECoverMapping,
    ) -> None:
        """Initialize a Tuya BLE cover entity."""
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping
        _LOGGER.debug(
            "Initialized TuyaBLECover: device=%s, mapping.dp_id=%d,"
            "control_dp_id=%s, position_dp_id=%s",
            device.address,
            mapping.dp_id,
            mapping.control_dp_id,
            mapping.position_dp_id,
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover."""
        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            self._mapping.dp_type or TuyaBLEDataPointType.DT_VALUE,
            0,
        )
        if datapoint:
            # Device uses inverted position: 0=open, 100=closed
            # Home Assistant standard: 0=closed, 100=open
            # So we invert the value
            raw_position = int(datapoint.value) if datapoint.value is not None else None
            position = (100 - raw_position) if raw_position is not None else None
            if position is not None:
                _LOGGER.debug(
                    "%s: current_cover_position=%d (inverted from %d, dp_id=%d)",
                    self._device.address,
                    position,
                    raw_position,
                    self._mapping.dp_id,
                )
            return position
        _LOGGER.debug(
            "%s: current_cover_position datapoint not found (dp_id=%d)",
            self._device.address,
            self._mapping.dp_id,
        )
        return None

    @property
    def is_closed(self) -> bool | None:
        """Return if cover is closed."""
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @property
    def is_opening(self) -> bool:
        """Return if cover is opening."""
        # We don't have direct feedback on whether it's opening,
        # so return False for now
        return False

    @property
    def is_closing(self) -> bool:
        """Return if cover is closing."""
        # We don't have direct feedback on whether it's closing,
        # so return False for now
        return False

    def open_cover(self, **_kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug(
            "%s: open_cover called, control_dp_id=%s",
            self._device.address,
            self._mapping.control_dp_id,
        )
        if self._mapping.control_dp_id:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.control_dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                0,
            )
            if datapoint:
                _LOGGER.debug(
                    "%s: Setting control dp to 'open' (0)", self._device.address
                )
                self._hass.create_task(datapoint.set_value(0))
            else:
                _LOGGER.error(
                    "%s: Failed to get/create control datapoint", self._device.address
                )
        else:
            _LOGGER.warning(
                "%s: control_dp_id not set, cannot open", self._device.address
            )

    def close_cover(self, **_kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug(
            "%s: close_cover called, control_dp_id=%s",
            self._device.address,
            self._mapping.control_dp_id,
        )
        if self._mapping.control_dp_id:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.control_dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                2,
            )
            if datapoint:
                _LOGGER.debug(
                    "%s: Setting control dp to 'close' (2)", self._device.address
                )
                self._hass.create_task(datapoint.set_value(2))
            else:
                _LOGGER.error(
                    "%s: Failed to get/create control datapoint", self._device.address
                )
        else:
            _LOGGER.warning(
                "%s: control_dp_id not set, cannot close", self._device.address
            )

    def stop_cover(self, **_kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug(
            "%s: stop_cover called, control_dp_id=%s",
            self._device.address,
            self._mapping.control_dp_id,
        )
        if self._mapping.control_dp_id:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.control_dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                1,
            )
            if datapoint:
                _LOGGER.debug(
                    "%s: Setting control dp to 'stop' (1)", self._device.address
                )
                self._hass.create_task(datapoint.set_value(1))
            else:
                _LOGGER.error(
                    "%s: Failed to get/create control datapoint", self._device.address
                )
        else:
            _LOGGER.warning(
                "%s: control_dp_id not set, cannot stop", self._device.address
            )

    def set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        _LOGGER.debug(
            "%s: set_cover_position called, position_dp_id=%s, kwargs=%s",
            self._device.address,
            self._mapping.position_dp_id,
            kwargs,
        )
        if ATTR_POSITION in kwargs and self._mapping.position_dp_id:
            position = kwargs[ATTR_POSITION]
            # Device uses inverted position, so invert the value
            inverted_position = 100 - int(position)
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.position_dp_id,
                TuyaBLEDataPointType.DT_VALUE,
                0,
            )
            if datapoint:
                _LOGGER.debug(
                    "%s: Setting position dp to %d (inverted from %d)",
                    self._device.address,
                    inverted_position,
                    int(position),
                )
                self._hass.create_task(datapoint.set_value(inverted_position))
            else:
                _LOGGER.error(
                    "%s: Failed to get/create position datapoint", self._device.address
                )
        else:
            if ATTR_POSITION not in kwargs:
                _LOGGER.warning("%s: ATTR_POSITION not in kwargs", self._device.address)
            if not self._mapping.position_dp_id:
                _LOGGER.warning("%s: position_dp_id not set", self._device.address)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and self._mapping.is_available is not None:
            result = self._mapping.is_available(self, self._product)
        return result

    @property
    def supported_features(self) -> int:
        """Return the supported features."""
        features = 0
        # Support opening/closing via commands
        if self._mapping.control_dp_id:
            features |= (
                0x1  # OPEN
                | 0x2  # CLOSE
                | 0x4  # STOP
            )
            _LOGGER.debug(
                "%s: Added supported features for control (dp_id=%d): 0x%x",
                self._device.address,
                self._mapping.control_dp_id,
                features,
            )
        # Support position setting
        if self._mapping.position_dp_id:
            features |= 0x8  # SET_POSITION
            _LOGGER.debug(
                "%s: Added supported feature SET_POSITION (dp_id=%d): 0x%x",
                self._device.address,
                self._mapping.position_dp_id,
                features,
            )
        _LOGGER.debug(
            "%s: Total supported features: 0x%x", self._device.address, features
        )
        return features


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE covers."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)

    _LOGGER.debug(
        "Setting up cover entities for device %s, category: %s, product_id: %s",
        data.device.address,
        data.device.category,
        data.device.product_id,
    )
    _LOGGER.debug("Found %d cover mappings", len(mappings))

    entities: list[TuyaBLECover] = []
    for mapping in mappings:
        _LOGGER.debug(
            "Processing cover mapping: dp_id=%d, has datapoint=%s",
            mapping.dp_id,
            data.device.datapoints.has_id(mapping.dp_id, mapping.dp_type),
        )
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            _LOGGER.debug(
                "Adding cover entity for dp_id=%d, control_dp_id=%s, position_dp_id=%s",
                mapping.dp_id,
                mapping.control_dp_id,
                mapping.position_dp_id,
            )
            entities.append(
                TuyaBLECover(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    _LOGGER.debug("Adding %d cover entities", len(entities))
    async_add_entities(entities)

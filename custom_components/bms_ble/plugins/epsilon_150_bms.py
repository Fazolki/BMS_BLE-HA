"""Module to support Super B Epsilon 12V150Ah BMS."""

from collections.abc import Callable
from typing import Any, Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from .basebms import AdvertisementPattern, BaseBMS, BMSsample, BMSvalue


class BMS(BaseBMS):
    """Super B Epsilon BMS implementation using passive notifications."""

    _DEF_LEN: Final[int] = 24  # Notification packet length

    # Field definitions: (field name, command ID, offset, length, signed, transform function)
    _FIELDS: Final[list[tuple[BMSvalue, int, int, int, bool, Callable[[int], Any]]]] = [
        ("packet_type",       0x01, 0, 1,  False, lambda x: x),               # uint8
        ("current",           0x01, 6, 4,  True,  lambda x: x),               # int32 (milliamps)
        ("voltage",           0x01, 10, 2, False, lambda x: x / 1000),        # uint16 (millivolts to volts)
        ("cycle_count",       0x01, 14, 1, False, lambda x: x),               # uint8
        ("state_of_charge",   0x01, 15, 1, False, lambda x: x),               # uint8 (0–100%)
        ("problem_code",      0x01, 16, 8, False, lambda x: x),               # uint64
    ]

    _CMDS: Final[set[int]] = {field[1] for field in _FIELDS}

    def __init__(self, ble_device: BLEDevice, reconnect: bool = False) -> None:
        """Initialize BMS."""
        super().__init__(__name__, ble_device, reconnect)
        self._data_final: dict[int, bytearray] = {}

    @staticmethod
    def matcher_dict_list() -> list[AdvertisementPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "Epsilon 150 - *", "connectable": True}]

    @staticmethod
    def device_info() -> dict[str, str]:
        """Return device information for the battery management system."""
        return {"manufacturer": "Super B", "model": "Epsilon 12V150Ah"}

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("e0fef452-9d2b-4005-a1e3-69fe1102b436")]

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notification."""
        return "e0fef453-9d2b-4005-a1e3-69fe1102b436"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of characteristic that provides write (not used)."""
        return "e0fef454-9d2b-4005-a1e3-69fe1102b436"

    @staticmethod
    def _calc_values() -> frozenset[BMSvalue]:
        """Return derived values to calculate from raw data."""
        return frozenset({"power", "battery_charging"})

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle BLE notification events (incoming data)."""
        self._log.debug("RX BLE data: %s", data)

        if len(data) != self._DEF_LEN:
            self._log.debug("Incorrect frame length.")
            return

        cmd_id = data[0]
        self._data_final[cmd_id] = data.copy()
        self._data_event.set()

    @staticmethod
    def _decode_data(data: dict[int, bytearray]) -> BMSsample:
        """Decode fields from raw BLE response data."""
        result: BMSsample = {}

        for key, cmd, idx, size, signed, func in BMS._FIELDS:
            if cmd in data:
                value = int.from_bytes(
                    data[cmd][idx:idx + size], byteorder="big", signed=signed
                )
                result[key] = func(value)

        return result

    async def _async_update(self) -> BMSsample:
        """Wait for latest notification and decode BMS data."""
        self._data_final.clear()

        for cmd in self._CMDS:
            await self._await_reply()  # No command sent, just wait for notification

        result: BMSsample = self._decode_data(self._data_final)

        # Derived values
        if "voltage" in result and "current" in result:
            result["power"] = round(result["voltage"] * result["current"], 2)

        if "current" in result:
            result["battery_charging"] = result["current"] > 0

        return result

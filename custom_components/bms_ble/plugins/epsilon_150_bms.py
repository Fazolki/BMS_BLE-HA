"""Module to support Super B Epsilon 12V150Ah BMS."""

from collections.abc import Callable
from typing import Any, Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from .basebms import AdvertisementPattern, BaseBMS, BMSsample, BMSvalue


class BMS(BaseBMS):
    """Super B Epsilon BMS implementation."""

    _HEAD: Final[bytes] = b"\xA5"  # Placeholder, adjust based on actual
    _TAIL: Final[bytes] = b"\x5A"  # Placeholder, adjust based on actual
    _RDCMD: Final[bytes] = b"\x01"  # Placeholder read command
    _DEF_LEN: Final[int] = 20       # Expected BLE frame length

    # Field definitions: (field name, command ID, offset, length, signed, transform function)
    _FIELDS: Final[list[tuple[BMSvalue, int, int, int, bool, Callable[[int], Any]]]] = [
        ("battery_level", 0x01, 3, 1, False, lambda x: x),
        ("voltage",        0x01, 4, 2, False, lambda x: x / 100),     # e.g., 1320 -> 13.20V
        ("current",        0x01, 6, 2, True,  lambda x: x / 100),     # signed: discharging/charging
        ("temperature",    0x01, 8, 2, True,  lambda x: x / 10),      # 273 -> 27.3°C
        ("cycles",         0x01, 10, 2, False, lambda x: x),
        ("cycle_capacity", 0x01, 12, 2, False, lambda x: x),          # e.g., Wh or Ah
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
        return [normalize_uuid_str("0000ff00-0000-1000-8000-00805f9b34fb")]  # Example

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "0000ff01-0000-1000-8000-00805f9b34fb"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "0000ff02-0000-1000-8000-00805f9b34fb"

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

        if not data.startswith(self._HEAD):
            self._log.debug("Incorrect SOF.")
            return

        if not data.endswith(self._TAIL):
            self._log.debug("Incorrect EOF.")
            return

        cmd_id = data[2]
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

    @staticmethod
    def _cmd(addr: int) -> bytes:
        """Build a command frame for the Super B protocol."""
        return BMS._HEAD + BMS._RDCMD + addr.to_bytes(1, "big") + BMS._TAIL

    async def _async_update(self) -> BMSsample:
        """Fetch and decode current BMS data."""
        self._data_final.clear()

        for cmd in self._CMDS:
            await self._await_reply(self._cmd(cmd))

        result: BMSsample = self._decode_data(self._data_final)

        # Derived values
        if "voltage" in result and "current" in result:
            result["power"] = round(result["voltage"] * result["current"], 2)

        if "current" in result:
            result["battery_charging"] = result["current"] > 0

        return result

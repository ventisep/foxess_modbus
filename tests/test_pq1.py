"""PQ1 monitoring and the boundaries of its provisional register map."""

import re
from collections.abc import Iterator
from collections.abc import Mapping
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from custom_components.foxess_modbus.client.modbus_client import ModbusClient
from custom_components.foxess_modbus.common.entity_controller import ModbusControllerEntity
from custom_components.foxess_modbus.common.exceptions import AutoconnectFailedError
from custom_components.foxess_modbus.common.types import ConnectionType
from custom_components.foxess_modbus.common.types import Inv
from custom_components.foxess_modbus.common.types import InverterModel
from custom_components.foxess_modbus.common.types import RegisterType
from custom_components.foxess_modbus.const import ENTITY_ID_PREFIX
from custom_components.foxess_modbus.const import FRIENDLY_NAME
from custom_components.foxess_modbus.const import INVERTER_BASE
from custom_components.foxess_modbus.const import INVERTER_CONN
from custom_components.foxess_modbus.const import INVERTER_MODEL
from custom_components.foxess_modbus.const import MAX_READ
from custom_components.foxess_modbus.const import UNIQUE_ID_PREFIX
from custom_components.foxess_modbus.entities.entity_descriptions import ENTITIES
from custom_components.foxess_modbus.entities.inverter_model_spec import ModbusAddressSpec
from custom_components.foxess_modbus.entities.modbus_enum_sensor import ModbusEnumSensorDescription
from custom_components.foxess_modbus.entities.modbus_lambda_sensor import ModbusLambdaSensor
from custom_components.foxess_modbus.entities.modbus_select import ModbusSelect
from custom_components.foxess_modbus.entities.modbus_select import ModbusSelectDescription
from custom_components.foxess_modbus.entities.modbus_sensor import ModbusSensor
from custom_components.foxess_modbus.inverter_profiles import INVERTER_PROFILES
from custom_components.foxess_modbus.inverter_profiles import inverter_connection_type_profile_from_config
from custom_components.foxess_modbus.modbus_controller import ModbusController


@pytest.fixture
def controller(hass: HomeAssistant) -> Iterator[ModbusController]:
    details = {
        INVERTER_BASE: InverterModel.PQ1,
        INVERTER_MODEL: "PQ1-8.0",
        INVERTER_CONN: ConnectionType.LAN,
        ENTITY_ID_PREFIX: "pq1",
        UNIQUE_ID_PREFIX: "pq1",
        FRIENDLY_NAME: "PQ1",
    }
    result = ModbusController(
        hass, AsyncMock(spec=ModbusClient), inverter_connection_type_profile_from_config(details), details, 247, 10, 20
    )
    yield result
    result.unload()


@pytest.fixture
def sensors(controller: ModbusController) -> dict[str, SensorEntity]:
    profile = inverter_connection_type_profile_from_config(controller.inverter_details)
    result = {}
    for entity in profile.create_entities(SensorEntity, controller, filter_depends_on_other_entites=False):
        sensor = cast(SensorEntity, entity)
        assert sensor.entity_description.key not in result
        result[sensor.entity_description.key] = sensor
        controller.register_modbus_entity(cast(ModbusControllerEntity, sensor))
    return result


def set_registers(controller: ModbusController, values: Mapping[int, int | None]) -> None:
    for address, value in values.items():
        controller._data[address].read_value = value  # noqa: SLF001


def numeric_value(sensor: SensorEntity) -> int | float | None:
    return cast(ModbusSensor, sensor)._calculate_native_value()  # noqa: SLF001


@pytest.fixture
def remote_target(controller: ModbusController) -> ModbusSelect:
    profile = inverter_connection_type_profile_from_config(controller.inverter_details)
    entity = next(
        entity
        for entity in profile.create_entities(SelectEntity, controller)
        if entity.entity_description.key == "remote_control_target"
    )
    controller.register_modbus_entity(cast(ModbusControllerEntity, entity))
    return cast(ModbusSelect, entity)


@pytest.mark.parametrize("other_bits", [0, 1, 2, 3, 0x8003])
@pytest.mark.parametrize("target, option", [(0, "AC"), (4, "Battery"), (8, "Grid CT-Meter"), (12, "AC (Grid First)")])
async def test_remote_target_preserves_fresh_non_target_bits(
    controller: ModbusController, remote_target: ModbusSelect, other_bits: int, target: int, option: str
) -> None:
    # Cached configuration is deliberately different from the fresh read.
    set_registers(controller, {46001: 12})
    with (
        patch.object(controller, "read_registers", AsyncMock(return_value=[other_bits | 12])) as read,
        patch.object(controller, "write_register", AsyncMock()) as write,
    ):
        await remote_target.async_select_option(option)
        read.assert_awaited_once_with(46001, 1, RegisterType.HOLDING)
        write.assert_awaited_once_with(46001, other_bits | target)


@pytest.mark.parametrize(
    "raw, option",
    [
        (12, "AC (Grid First)"),
        (13, "AC (Grid First)"),
        (7, "Battery"),
        (0x800B, "Grid CT-Meter"),
        (1, "AC"),
        (None, None),
    ],
)
def test_remote_target_decodes_only_target_bits(
    controller: ModbusController, remote_target: ModbusSelect, raw: int | None, option: str | None
) -> None:
    set_registers(controller, {46001: raw})
    assert remote_target.current_option == option


@pytest.mark.parametrize("words", [[], [12, 12], [-1], [65536]])
async def test_remote_target_invalid_read_does_not_write(
    controller: ModbusController, remote_target: ModbusSelect, words: list[int]
) -> None:
    with (
        patch.object(controller, "read_registers", AsyncMock(return_value=words)),
        patch.object(controller, "write_register", AsyncMock()) as write,
    ):
        with pytest.raises(ValueError, match="unavailable or invalid"):
            await remote_target.async_select_option("Battery")
        write.assert_not_awaited()


async def test_remote_target_read_error_does_not_write(
    controller: ModbusController, remote_target: ModbusSelect
) -> None:
    with (
        patch.object(controller, "read_registers", AsyncMock(side_effect=RuntimeError("read failed"))),
        patch.object(controller, "write_register", AsyncMock()) as write,
    ):
        with pytest.raises(RuntimeError, match="read failed"):
            await remote_target.async_select_option("Battery")
        write.assert_not_awaited()


async def test_remote_target_unknown_option_does_not_write(
    controller: ModbusController, remote_target: ModbusSelect
) -> None:
    with (
        patch.object(controller, "read_registers", AsyncMock()) as read,
        patch.object(controller, "write_register", AsyncMock()) as write,
    ):
        await remote_target.async_select_option("Invalid")
        read.assert_not_awaited()
        write.assert_not_awaited()


async def test_existing_select_still_writes_whole_register(controller: ModbusController) -> None:
    # The optional mask must not change existing select behaviour.
    description = ModbusSelectDescription(
        key="unmasked_test",
        name="Unmasked",
        address=[ModbusAddressSpec(holding=49203, models=Inv.PQ1)],
        options_map={1: "Self Use", 2: "Feed-in Priority"},
    )
    entity = cast(ModbusSelect, description.create_entity_if_supported(controller, Inv.PQ1, RegisterType.HOLDING))
    with (
        patch.object(controller, "read_registers", AsyncMock()) as read,
        patch.object(controller, "write_register", AsyncMock()) as write,
    ):
        await entity.async_select_option("Feed-in Priority")
        read.assert_not_awaited()
        write.assert_awaited_once_with(49203, 2)


def test_remote_target_serialization_does_not_mutate_options(remote_target: ModbusSelect) -> None:
    description = cast(ModbusSelectDescription, remote_target.entity_description)
    serialized = description.serialize(Inv.PQ1, RegisterType.HOLDING)
    assert serialized is not None
    serialized["values"]["0"] = serialized["values"].pop(0)
    assert description.options_map[0] == "AC"


@pytest.mark.parametrize("packed", [False, True])
async def test_detect_pq1(packed: bool) -> None:
    client = AsyncMock(spec=ModbusClient)
    chars = list(b"PQ1-8.0 ")
    words = [(chars[i] << 8) | chars[i + 1] for i in range(0, len(chars), 2)] if packed else chars
    words += [0] * (15 - len(words))
    client.read_registers.side_effect = lambda start, count, *_: words[start - 30000 : start - 30000 + count]
    assert await ModbusController.autodetect(client, 247, {MAX_READ: 4}) == (InverterModel.PQ1, "PQ1-8.0")
    assert all(call.args[2:] == (RegisterType.HOLDING, 247) for call in client.read_registers.call_args_list)
    client.close.assert_awaited_once()
    client.write_registers.assert_not_awaited()


async def test_reject_unrecognised_pq1_suffix() -> None:
    client = AsyncMock(spec=ModbusClient)
    client.read_registers.return_value = list(b"PQ1-8.0-OTHER") + [0] * 3
    with pytest.raises(AutoconnectFailedError):
        await ModbusController.autodetect(client, 247, {MAX_READ: 20})
    client.close.assert_awaited_once()


def test_profile_and_entities(controller: ModbusController, sensors: dict[str, SensorEntity]) -> None:
    profile = inverter_connection_type_profile_from_config(controller.inverter_details)
    assert profile is INVERTER_PROFILES[InverterModel.PQ1].connection_types[ConnectionType.AUX]
    assert profile.register_type == RegisterType.HOLDING
    assert profile.get_inv_for_version(None) == Inv.PQ1
    assert controller.inverter_capacity == 8000
    assert re.match(profile.inverter_model_profile.model_pattern, "P1-8.0-E") is None
    assert controller.remote_control_manager is not None
    assert controller.charge_periods == []
    numbers = profile.create_entities(NumberEntity, controller)
    selects = profile.create_entities(SelectEntity, controller)
    assert {entity.entity_description.key for entity in numbers} == {"force_charge_power", "force_discharge_power"}
    assert {entity.entity_description.key for entity in selects} == {"force_charge_mode", "remote_control_target"}
    assert not any(
        factory.depends_on_other_entities for factory in ENTITIES if factory.serialize(Inv.PQ1, RegisterType.HOLDING)
    )
    addresses = {a for entity in sensors.values() for a in cast(ModbusControllerEntity, entity).addresses}
    assert set(range(31020, 31029)) <= addresses
    assert set(range(32000, 32024)) <= addresses
    assert set(range(39601, 39605)) <= addresses
    assert {31049, 31050} <= addresses
    assert not addresses.intersection(range(41001, 41007))
    assert not addresses.intersection({39118, 44003, 46001, 37700, 38307, 38914, 39605})
    assert not addresses.intersection(range(48010, 48970))
    assert isinstance(sensors["pv_power_now"], ModbusLambdaSensor)
    assert cast(ModbusControllerEntity, sensors["load_power"]).addresses == [39226, 39225]
    assert cast(ModbusControllerEntity, sensors["solar_energy_total"]).addresses == [39602, 39601]
    assert cast(ModbusControllerEntity, sensors["solar_energy_today"]).addresses == [39604, 39603]
    for key in ("grid_ct", "feed_in", "grid_consumption"):
        assert cast(ModbusControllerEntity, sensors[key]).addresses == [31050, 31049]
    assert "bms_kwh_remaining" not in sensors
    assert "invbatpower_39248" not in sensors
    assert cast(ModbusControllerEntity, sensors["inv_power_39248"]).addresses == [39249, 39248]
    assert "pv1_energy_total" not in sensors
    assert "pv5_power" not in sensors
    assert "work_mode" not in sensors
    for pv in range(1, 5):
        assert f"pv{pv}_voltage" in sensors
        assert f"pv{pv}_current" in sensors
        assert f"pv{pv}_power" in sensors


@pytest.mark.parametrize("max_read", [1, 8, 20, 125])
async def test_poll_ranges_avoid_invalid_block(
    controller: ModbusController, sensors: dict[str, SensorEntity], max_read: int
) -> None:
    assert sensors
    controller._max_read = max_read  # noqa: SLF001
    ranges = list(controller._create_read_ranges(max_read, is_initial_connection=True))  # noqa: SLF001
    polled = {a for start, count in ranges for a in range(start, start + count)}
    assert {41000, 41007, 41008, 41009, 41010, 41011} <= polled
    assert not polled.intersection(range(41001, 41007))
    assert all(1 <= count <= max_read for _, count in ranges)
    client = cast(AsyncMock, controller._client)  # noqa: SLF001
    client.read_registers.side_effect = lambda _start, count, *_: [0] * count
    await controller._read_all_registers()  # noqa: SLF001
    client.write_registers.assert_not_awaited()
    assert all(call.args[2:] == (RegisterType.HOLDING, 247) for call in client.read_registers.call_args_list)


@pytest.mark.parametrize(
    ("key", "values", "expected"),
    [
        ("pv3_voltage", {39074: 2561}, 256.1),
        ("pv3_current", {39075: 150}, 1.5),
        ("pv3_power", {39284: 395}, 0.395),
        ("pv1_power", {39280: 40000}, 40),
        ("invbatvolt", {31020: 4000}, 400),
        ("batvolt", {37609: 2629}, 262.9),
        ("invbatcurrent", {31021: 65521}, -1.5),
        ("invbatpower", {31022: 64492}, -1.044),
        ("battery_charge", {31022: 64492}, 1.044),
        ("battery_discharge", {31022: 64492}, 0),
        ("battery_charge", {31022: 1044}, 0),
        ("battery_discharge", {31022: 1044}, 1.044),
        ("battery_temp", {31023: 275}, 27.5),
        ("battery_soc", {31024: 97, 31028: 0, 37002: 2}, 97),
        ("bms_charge_rate", {31025: 500}, 50),
        ("bms_discharge_rate", {31026: 500}, 50),
        ("pq1_register_37632", {37632: 1920}, 1920),
        ("battery_nominal_capacity", {37635: 1971}, 19.71),
        ("rfreq", {39139: 4991}, 49.91),
        ("max_charge_current", {41007: 500}, 50),
        ("min_soc", {41009: 10}, 10),
        ("max_soc", {41010: 100}, 100),
        ("pq1_register_31014", {31014: 0}, 0),
        ("grid_ct", {31049: 65535, 31050: 65339}, 0.197),
        ("grid_ct", {31049: 65535, 31050: 65333}, 0.203),
        ("grid_ct", {31049: 0, 31050: 284}, -0.284),
        ("feed_in", {31049: 65535, 31050: 65333}, 0.203),
        ("grid_consumption", {31049: 65535, 31050: 65333}, 0),
        ("feed_in", {31049: 0, 31050: 284}, 0),
        ("grid_consumption", {31049: 0, 31050: 284}, 0.284),
        ("grid_ct", {31049: 0, 31050: 0}, 0),
        ("feed_in", {31049: 0, 31050: 0}, 0),
        ("grid_consumption", {31049: 0, 31050: 0}, 0),
        ("grid_ct", {31049: 0, 31050: 40000}, -40),
        ("grid_ct", {31049: 65535, 31050: 25536}, 40),
        ("load_power", {39225: 0, 39226: 203}, 0.203),
        ("load_power", {39225: 0, 39226: 271}, 0.271),
        ("load_power_39134", {39134: 0, 39135: 177}, 0.177),
        ("load_power_31016", {31016: 200}, 0.2),
        ("invbatpower_39237", {39237: 65535, 39238: 65333}, -0.203),
        ("invbatpower_39237", {39237: 0, 39238: 570}, 0.570),
        ("invbatpower_39237", {39237: 0, 39238: 465}, 0.465),
        ("invbatpower_39237", {39237: 0, 39238: 30}, 0.030),
        ("invbatpower_39237", {39237: 65535, 39238: 64474}, -1.062),
        ("invbatpower_39237", {39237: 0, 39238: 0}, 0.0),
        ("inv_power_39248", {39248: 0, 39249: 412}, 0.412),
        ("inv_power_39248", {39248: 65535, 39249: 65522}, -0.014),
        ("inv_power_Q_R", {39256: 65535, 39257: 65482}, -0.054),
        ("inv_power_Q_R", {39256: 0, 39257: 54}, 0.054),
        ("inv_power_39248", {39248: 65535, 39249: 65455}, -0.081),
        ("inv_power_39248", {39248: 0, 39249: 548}, 0.548),
        ("inv_power_39248", {39248: 0, 39249: 708}, 0.708),
        ("inv_power_39248", {39248: 65535, 39249: 65036}, -0.500),
        ("battery_charge_total", {32003: 0, 32004: 464}, 46.4),
        ("battery_charge_today", {32005: 62}, 6.2),
        ("battery_discharge_total", {32006: 0, 32007: 371}, 37.1),
        ("battery_discharge_today", {32008: 31}, 3.1),
        ("load_energy_today", {32023: 36}, 3.6),
        ("feed_in_energy_total", {32009: 0, 32010: 363}, 36.3),
        ("feed_in_energy_today", {32011: 9}, 0.9),
        ("grid_consumption_energy_total", {32012: 0, 32013: 199}, 19.9),
        ("grid_consumption_energy_today", {32014: 4}, 0.4),
        ("load_power_total", {32021: 0, 32022: 309}, 30.9),
        ("feed_in_energy_total", {32009: 1, 32010: 2}, 6553.8),
        ("export_power_limit", {46616: 0, 46617: 15000}, 15000),
        ("export_power_limit", {46616: 1, 46617: 4464}, 70000),
        ("solar_energy_total", {39601: 0, 39602: 9220}, 92.2),
        ("solar_energy_today", {39603: 0, 39604: 2830}, 28.3),
        ("solar_energy_total", {39601: 1, 39602: 2}, 655.38),
        ("solar_energy_today", {39603: 1, 39604: 2}, 655.38),
        ("solar_energy_today", {39603: 0, 39604: 32768}, 327.68),
        ("pq1_register_32002", {32002: 81}, 81),
        ("pq1_register_44000", {44000: 12}, 12),
        ("pq1_register_31027", {31027: 65535}, 65535),
    ],
)
def test_decoding(
    controller: ModbusController, sensors: dict[str, SensorEntity], key: str, values: dict[int, int], expected: float
) -> None:
    set_registers(controller, values)
    assert numeric_value(sensors[key]) == pytest.approx(expected)


def test_experimental_metadata_and_missing_words(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    energy = sensors["input_energy_total"]
    set_registers(controller, {32018: None, 32019: 10})
    assert numeric_value(energy) is None
    assert energy.entity_description.name == "Input Energy Total (Experimental)"
    assert energy.entity_description.entity_category == EntityCategory.DIAGNOSTIC
    assert energy.entity_description.entity_registry_enabled_default is False
    assert energy.entity_description.state_class is None
    assert energy.extra_state_attributes == {
        "mapping_status": "provisional",
        "raw_registers": {"32019": 10, "32018": None},
    }
    assert sensors["battery_temp"].entity_description.name == "Battery Temp (Experimental)"
    reactive = sensors["inv_power_Q_R"]
    set_registers(controller, {39256: 65535, 39257: 65482})
    assert reactive.entity_description.name == "Inverter Power (Reactive) R (Experimental)"
    assert reactive.native_unit_of_measurement == "kvar"
    assert reactive.entity_description.entity_category == EntityCategory.DIAGNOSTIC
    assert not reactive.entity_description.entity_registry_enabled_default
    assert reactive.entity_description.state_class is None
    assert reactive.extra_state_attributes == {
        "mapping_status": "provisional",
        "raw_registers": {"39257": 65482, "39256": 65535},
    }
    assert sensors["battery_soc"].entity_description.name == "Battery SoC"
    assert sensors["battery_soc"].extra_state_attributes is None
    assert sensors["pq1_register_44000"].entity_description.entity_registry_enabled_default is False


def test_battery_state_does_not_use_unverified_connection_flags(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    set_registers(controller, {31024: 97, 31028: 0, 37002: 2})
    sensor = sensors["battery_soc"]
    with patch.object(sensor, "schedule_update_ha_state"):
        cast(ModbusControllerEntity, sensor).update_callback({31024})
    assert sensor.native_value == 97


def test_experimental_settings_do_not_leak_to_p1(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    profile = INVERTER_PROFILES[InverterModel.P1].connection_types[ConnectionType.AUX]
    p1_sensors = {
        entity.entity_description.key: cast(SensorEntity, entity)
        for entity in profile.create_entities(SensorEntity, controller, filter_depends_on_other_entites=False)
    }
    for key in ("input_energy_total", "battery_temp", "feed_in"):
        assert str(sensors[key].entity_description.name).endswith("(Experimental)")
        assert not str(p1_sensors[key].entity_description.name).endswith("(Experimental)")
        assert p1_sensors[key].entity_description.entity_registry_enabled_default
        assert p1_sensors[key].entity_description.state_class is not None


@pytest.mark.parametrize(
    "key",
    [
        "invbatvolt",
        "batvolt",
        "invbatcurrent",
        "pv1_power",
        "pv2_power",
        "pv3_power",
        "pv4_power",
        "load_power",
        "invbatpower_39237",
        "inv_power_39248",
        "grid_ct",
        "grid_consumption",
        "battery_charge_total",
        "battery_charge_today",
        "battery_discharge_total",
        "battery_discharge_today",
        "load_energy_today",
        "solar_energy_total",
        "solar_energy_today",
        "feed_in_energy_total",
        "feed_in_energy_today",
        "grid_consumption_energy_total",
        "grid_consumption_energy_today",
        "load_power_total",
    ],
)
def test_confirmed_sensors_are_enabled_with_statistics(sensors: dict[str, SensorEntity], key: str) -> None:
    description = sensors[key].entity_description
    assert not str(description.name).endswith("(Experimental)")
    assert description.entity_registry_enabled_default
    assert description.entity_category is None
    assert description.state_class is not None


@pytest.mark.parametrize("key", ["bms_charge_rate", "bms_discharge_rate", "feed_in"])
def test_unconfirmed_pr1_readings_remain_experimental(sensors: dict[str, SensorEntity], key: str) -> None:
    description = sensors[key].entity_description
    assert str(description.name).endswith("(Experimental)")
    assert not description.entity_registry_enabled_default
    assert description.entity_category == EntityCategory.DIAGNOSTIC
    assert description.state_class is None


@pytest.mark.parametrize("key", ["load_power_39134", "load_power_31016"])
def test_duplicate_power_pairs_are_optional_diagnostics(sensors: dict[str, SensorEntity], key: str) -> None:
    description = sensors[key].entity_description
    assert description.entity_category == EntityCategory.DIAGNOSTIC
    assert not description.entity_registry_enabled_default


@pytest.mark.parametrize(
    ("key", "values"),
    [
        ("load_power", {39225: None, 39226: 203}),
        ("load_power_39134", {39134: 0, 39135: None}),
        ("invbatpower_39237", {39237: None, 39238: 570}),
        ("inv_power_39248", {39248: 65535, 39249: None}),
        ("solar_energy_total", {39601: None, 39602: 9220}),
        ("solar_energy_total", {39601: 0, 39602: None}),
        ("solar_energy_today", {39603: None, 39604: 2830}),
        ("solar_energy_today", {39603: 0, 39604: None}),
        ("grid_ct", {31049: None, 31050: 284}),
        ("grid_ct", {31049: 0, 31050: None}),
        ("feed_in", {31049: None, 31050: 65333}),
        ("grid_consumption", {31049: 0, 31050: None}),
        ("inv_power_Q_R", {39256: None, 39257: 65482}),
        ("inv_power_Q_R", {39256: 65535, 39257: None}),
    ],
)
def test_duplicate_pairs_require_both_words(
    controller: ModbusController, sensors: dict[str, SensorEntity], key: str, values: dict[int, int | None]
) -> None:
    set_registers(controller, values)
    assert numeric_value(sensors[key]) is None


def test_pv_total_uses_all_four_confirmed_strings(hass: HomeAssistant, sensors: dict[str, SensorEntity]) -> None:
    sensor = cast(ModbusLambdaSensor, sensors["pv_power_now"])
    sensor.hass = hass
    for pv, power in enumerate((0.430, 0.411, 0.448, 0.050), start=1):
        hass.states.async_set(sensors[f"pv{pv}_power"].entity_id, str(power))
    with patch.object(sensor, "schedule_update_ha_state"):
        sensor._update_value()  # noqa: SLF001
        assert sensor.native_value == pytest.approx(1.339)
        hass.states.async_set(sensors["pv3_power"].entity_id, "unavailable")
        sensor._update_value()  # noqa: SLF001
        assert sensor.native_value is None


@pytest.mark.parametrize(
    ("capacity", "soh", "soc", "expected"),
    [
        ("19.71", "100", "83", 16.3593),
        ("19.71", "90", "50", 8.8695),
        ("19.71", "100", "0", 0),
        ("19.71", "100", "100", 19.71),
        ("19.71", None, "50", None),
        ("19.71", "unavailable", "50", None),
        ("19.71", "100", "unknown", None),
        ("19.71", "101", "50", None),
        ("19.71", "100", "-1", None),
        ("nan", "100", "50", None),
        ("0", "100", "50", None),
    ],
)
def test_estimated_battery_energy_requires_valid_sources(
    hass: HomeAssistant,
    sensors: dict[str, SensorEntity],
    capacity: str,
    soh: str | None,
    soc: str,
    expected: float | None,
) -> None:
    sensor = cast(ModbusLambdaSensor, sensors["battery_energy_remaining"])
    sensor.hass = hass
    for key, value in zip(("battery_nominal_capacity", "battery_soh", "battery_soc"), (capacity, soh, soc)):
        if value is not None:
            hass.states.async_set(sensors[key].entity_id, value)
    with patch.object(sensor, "schedule_update_ha_state"):
        sensor._update_value()  # noqa: SLF001
    if expected is None:
        assert sensor.native_value is None
    else:
        assert sensor.native_value == pytest.approx(expected)


def test_enum_serialization_does_not_mutate_mode_map(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    description = sensors["manual_work_mode"].entity_description
    assert isinstance(description, ModbusEnumSensorDescription)
    serialized = description.serialize(Inv.PQ1, RegisterType.HOLDING)
    assert serialized is not None
    serialized["options_map"]["0"] = serialized["options_map"].pop(0)
    set_registers(controller, {41000: 0})
    assert sensors["manual_work_mode"].native_value == "Self Use"


@pytest.mark.parametrize(
    ("value", "label"),
    [(0, "Self Use"), (1, "Feed-in Priority"), (2, "Backup"), (3, "Peak Shaving"), (6, None), (12, None), (None, None)],
)
def test_manual_mode_preserves_unknown_codes(
    controller: ModbusController, sensors: dict[str, SensorEntity], value: int | None, label: str | None
) -> None:
    set_registers(controller, {41000: value})
    assert sensors["manual_work_mode"].native_value == label
    assert sensors["manual_work_mode"].extra_state_attributes == {"raw_value": value}


@pytest.mark.parametrize(
    ("legacy", "newer", "label"),
    [(0, 1, "Self Use"), (1, 2, "Feed-in Priority"), (2, 3, "Backup"), (3, 4, "Peak Shaving")],
)
def test_manual_mode_encodings_remain_independent(
    controller: ModbusController, sensors: dict[str, SensorEntity], legacy: int, newer: int, label: str
) -> None:
    set_registers(controller, {41000: legacy, 49203: newer})
    assert sensors["manual_work_mode"].native_value == label
    assert sensors["manual_work_mode_49203"].native_value == label
    set_registers(controller, {49203: 0})
    assert sensors["manual_work_mode_49203"].native_value is None
    assert sensors["manual_work_mode_49203"].extra_state_attributes == {"raw_value": 0}


@pytest.mark.parametrize(("value", "expected"), [(0, False), (1, True), (2, None), (12, None), (None, None)])
def test_scheduler_is_strict_boolean(controller: ModbusController, value: int | None, expected: bool | None) -> None:
    profile = inverter_connection_type_profile_from_config(controller.inverter_details)
    entities = profile.create_entities(BinarySensorEntity, controller)
    assert len(entities) == 1
    sensor = cast(BinarySensorEntity, entities[0])
    controller.register_modbus_entity(cast(ModbusControllerEntity, sensor))
    set_registers(controller, {48000: value})
    assert sensor.is_on is expected


@pytest.mark.parametrize(
    ("register", "raw", "decoded"), [(36001, 289, "1.21"), (36002, 257, "1.01"), (36003, 288, "1.20")]
)
def test_firmware(
    controller: ModbusController, sensors: dict[str, SensorEntity], register: int, raw: int, decoded: str
) -> None:
    key = {36001: "master_version", 36002: "slave_version", 36003: "manager_version"}[register]
    set_registers(controller, {register: raw})
    assert sensors[key].native_value == decoded

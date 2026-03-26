"""
Tests for the hardware layer.
All tests run on non-Pi hardware (simulated mode).
No real GPIO, I2C, or vcgencmd required.
"""
import asyncio
import pytest
from unittest.mock import patch


# ═══════════════════════════════════════════════════════════════════
# pi_info.py
# ═══════════════════════════════════════════════════════════════════

class TestThrottleDecoder:

    def test_parse_clean(self):
        from piclaw.hardware.pi_info import _parse_throttle
        r = _parse_throttle("throttled=0x0")
        assert r is not None
        assert r.current  == []
        assert r.historic == []
        assert r.healthy  is True

    def test_parse_current_undervoltage(self):
        from piclaw.hardware.pi_info import _parse_throttle
        r = _parse_throttle("throttled=0x1")  # bit 0
        assert "Under-voltage" in r.current[0]
        assert r.healthy is False

    def test_parse_historic_only(self):
        from piclaw.hardware.pi_info import _parse_throttle
        r = _parse_throttle("throttled=0x50000")  # bits 16+18
        assert r.current == []
        assert len(r.historic) >= 1
        assert r.healthy is True  # no current issues

    def test_parse_combined(self):
        from piclaw.hardware.pi_info import _parse_throttle
        r = _parse_throttle("throttled=0x50005")  # current + historic
        assert len(r.current) >= 1
        assert len(r.historic) >= 1
        assert r.healthy is False

    def test_parse_none(self):
        from piclaw.hardware.pi_info import _parse_throttle
        assert _parse_throttle(None) is None

    def test_parse_invalid(self):
        from piclaw.hardware.pi_info import _parse_throttle
        assert _parse_throttle("no match here") is None

    def test_summary_healthy(self):
        from piclaw.hardware.pi_info import _parse_throttle
        r = _parse_throttle("throttled=0x0")
        assert "healthy" in r.summary.lower() or "no throttling" in r.summary.lower()

    def test_summary_critical(self):
        from piclaw.hardware.pi_info import _parse_throttle
        r = _parse_throttle("throttled=0x5")
        assert "NOW" in r.summary or "🔴" in r.summary


class TestVcgencmdParsers:

    def test_parse_measure_clock(self):
        from piclaw.hardware.pi_info import _parse_measure
        assert _parse_measure("frequency(48)=1500000000") == pytest.approx(1500.0)
        assert _parse_measure("measure_clock arm=1800000000") == pytest.approx(1800.0)

    def test_parse_measure_none(self):
        from piclaw.hardware.pi_info import _parse_measure
        assert _parse_measure(None) is None

    def test_parse_volt(self):
        from piclaw.hardware.pi_info import _parse_volt
        assert _parse_volt("volt=0.8625V") == pytest.approx(0.8625)
        assert _parse_volt("volt=1.2000V") == pytest.approx(1.2)

    def test_parse_volt_none(self):
        from piclaw.hardware.pi_info import _parse_volt
        assert _parse_volt(None) is None


class TestPiInfo:

    @pytest.fixture
    def mock_sys_temp(self, tmp_path):
        """Fake /sys/class/thermal/thermal_zone0/temp"""
        temp_file = tmp_path / "temp"
        temp_file.write_text("52300\n")
        with patch("piclaw.hardware.pi_info.Path") as mock_path:
            mock_path.return_value.read_text.return_value = "52300\n"
            yield 52.3

    def test_simulated_on_no_vcgencmd(self):
        """On non-Pi hardware, vcgencmd returns None → simulated=True."""
        with patch("piclaw.hardware.pi_info._vcgencmd", return_value=None):
            result = asyncio.run(
                __import__("piclaw.hardware.pi_info", fromlist=["read_pi_info"]).read_pi_info()
            )
        assert result.simulated is True

    def test_pi_info_to_dict_has_required_keys(self):
        with patch("piclaw.hardware.pi_info._vcgencmd", return_value=None):
            import piclaw.hardware.pi_info as m
            result = asyncio.run(m.read_pi_info())
        d = result.to_dict()
        for key in ("model", "ram_mb", "simulated", "temp_celsius"):
            assert key in d

    def test_pi_info_format_report(self):
        with patch("piclaw.hardware.pi_info._vcgencmd", return_value=None):
            import piclaw.hardware.pi_info as m
            info = asyncio.run(m.read_pi_info())
        report = info.format_report()
        assert "Raspberry Pi" in report
        assert "MB" in report

    def test_is_throttled_no_vcgencmd(self):
        """is_throttled() returns False when vcgencmd unavailable."""
        with patch("piclaw.hardware.pi_info._vcgencmd", return_value=None):
            from piclaw.hardware.pi_info import is_throttled
            assert is_throttled() is False

    def test_is_throttled_clean(self):
        with patch("piclaw.hardware.pi_info._vcgencmd", return_value="throttled=0x0"):
            from piclaw.hardware.pi_info import is_throttled
            assert is_throttled() is False

    def test_is_throttled_active(self):
        with patch("piclaw.hardware.pi_info._vcgencmd", return_value="throttled=0x1"):
            from piclaw.hardware.pi_info import is_throttled
            assert is_throttled() is True


# ═══════════════════════════════════════════════════════════════════
# thermal.py
# ═══════════════════════════════════════════════════════════════════

class TestThermalClassification:

    def test_cool(self):
        from piclaw.hardware.thermal import classify_temp, ThermalState
        assert classify_temp(40.0) == ThermalState.COOL

    def test_warm(self):
        from piclaw.hardware.thermal import classify_temp, ThermalState
        assert classify_temp(60.0) == ThermalState.WARM

    def test_hot(self):
        from piclaw.hardware.thermal import classify_temp, ThermalState
        assert classify_temp(72.0) == ThermalState.HOT

    def test_critical(self):
        from piclaw.hardware.thermal import classify_temp, ThermalState
        assert classify_temp(82.0) == ThermalState.CRITICAL

    def test_emergency(self):
        from piclaw.hardware.thermal import classify_temp, ThermalState
        assert classify_temp(86.0) == ThermalState.EMERGENCY

    def test_boundary_cool_warm(self):
        from piclaw.hardware.thermal import classify_temp, ThermalState
        assert classify_temp(54.9) == ThermalState.COOL
        assert classify_temp(55.0) == ThermalState.WARM

    def test_boundary_warn_crit(self):
        from piclaw.hardware.thermal import classify_temp, ThermalState
        assert classify_temp(79.9) == ThermalState.HOT
        assert classify_temp(80.0) == ThermalState.CRITICAL


class TestThermalStatus:

    def test_cool_allows_local(self):
        from piclaw.hardware.thermal import make_status
        s = make_status(45.0)
        assert s.local_ok  is True
        assert s.cloud_pref is False

    def test_hot_prefers_cloud(self):
        from piclaw.hardware.thermal import make_status
        s = make_status(72.0)
        assert s.cloud_pref is True
        assert s.local_ok   is True   # still allowed, just not preferred

    def test_critical_disables_local(self):
        from piclaw.hardware.thermal import make_status
        s = make_status(82.0)
        assert s.local_ok  is False
        assert s.cloud_pref is True

    def test_emergency_disables_local(self):
        from piclaw.hardware.thermal import make_status
        s = make_status(87.0)
        assert s.local_ok  is False

    def test_under_voltage_flag(self):
        from piclaw.hardware.thermal import make_status
        s = make_status(50.0, under_voltage=True)
        assert s.under_voltage is True

    def test_to_dict_keys(self):
        from piclaw.hardware.thermal import make_status
        d = make_status(60.0).to_dict()
        for key in ("temp_c", "state", "local_ok", "cloud_pref", "message", "timestamp"):
            assert key in d

    def test_local_inference_allowed_no_monitor(self):
        """Without monitor running, local_inference_allowed() returns True (safe default)."""
        import piclaw.hardware.thermal as t
        t._current_status = None
        assert t.local_inference_allowed() is True

    def test_local_inference_blocked_when_critical(self):
        from piclaw.hardware.thermal import make_status
        import piclaw.hardware.thermal as t
        t._current_status = make_status(82.0)
        assert t.local_inference_allowed() is False
        t._current_status = None   # cleanup


class TestFanControl:

    def test_fan_off_below_start(self):
        from piclaw.hardware.thermal import _calc_fan_duty, FAN_START_TEMP_C
        assert _calc_fan_duty(FAN_START_TEMP_C - 1) == 0.0

    def test_fan_full_above_max(self):
        from piclaw.hardware.thermal import _calc_fan_duty, FAN_FULL_TEMP_C, FAN_FULL_DUTY
        assert _calc_fan_duty(FAN_FULL_TEMP_C + 5) == FAN_FULL_DUTY

    def test_fan_partial_in_range(self):
        from piclaw.hardware.thermal import _calc_fan_duty, FAN_START_TEMP_C, FAN_FULL_TEMP_C
        mid = (FAN_START_TEMP_C + FAN_FULL_TEMP_C) / 2
        duty = _calc_fan_duty(mid)
        assert 0 < duty < 100


# ═══════════════════════════════════════════════════════════════════
# i2c_scan.py
# ═══════════════════════════════════════════════════════════════════

class TestI2CKnownDevices:

    def test_bmp280_0x76_known(self):
        from piclaw.hardware.i2c_scan import _make_device
        d = _make_device(0x76, bus=1)
        assert d.known is True
        assert "BMP280" in d.name or "BME280" in d.name
        assert d.category == "environment"

    def test_ssd1306_0x3c_known(self):
        from piclaw.hardware.i2c_scan import _make_device
        d = _make_device(0x3C, bus=1)
        assert d.known is True
        assert "SSD1306" in d.name or "OLED" in d.desc.upper()

    def test_unknown_address(self):
        from piclaw.hardware.i2c_scan import _make_device
        d = _make_device(0x11, bus=1)
        assert d.known is False
        assert "Unknown" in d.name

    def test_ds3231_rtc(self):
        from piclaw.hardware.i2c_scan import _make_device
        d = _make_device(0x68, bus=1)
        assert d.known is True
        assert d.category == "rtc"

    def test_address_and_bus_stored(self):
        from piclaw.hardware.i2c_scan import _make_device
        d = _make_device(0x48, bus=2)
        assert d.address == 0x48
        assert d.bus     == 2


class TestI2CScanFallback:

    def test_scan_no_hardware(self):
        """Without smbus2 or i2cdetect, returns error result."""
        # Instead of patching __import__ which is dangerous, we patch the functions that use them
        import piclaw.hardware.i2c_scan as i2c_mod
        with patch.object(i2c_mod, "_scan_smbus2", side_effect=ImportError):
            with patch.object(i2c_mod, "_scan_i2cdetect", side_effect=Exception("no tools")):
                result = i2c_mod._scan_sync(1)
        # Should not raise, should return an I2CScanResult with error
        assert result.bus == 1
        assert "No I2C scanning method" in result.error

    def test_format_report_empty(self):
        from piclaw.hardware.i2c_scan import format_scan_report, I2CScanResult
        report = format_scan_report([I2CScanResult(bus=1, devices=[])])
        assert "Bus 1" in report
        assert "No devices" in report

    def test_format_report_with_device(self):
        from piclaw.hardware.i2c_scan import format_scan_report, I2CScanResult, I2CDevice
        dev    = I2CDevice(0x76, bus=1, name="BMP280", desc="Pressure sensor",
                           category="environment", known=True)
        result = I2CScanResult(bus=1, devices=[dev])
        report = format_scan_report([result])
        assert "BMP280" in report
        assert "0x76" in report
        assert "★" in report

    def test_format_report_unknown(self):
        from piclaw.hardware.i2c_scan import format_scan_report, I2CScanResult, I2CDevice
        dev    = I2CDevice(0x11, bus=1, name="Unknown", desc="?",
                           category="unknown", known=False)
        result = I2CScanResult(bus=1, devices=[dev])
        report = format_scan_report([result])
        assert "?" in report


# ═══════════════════════════════════════════════════════════════════
# sensors.py  (registry only – no real hardware)
# ═══════════════════════════════════════════════════════════════════

class TestSensorRegistry:

    @pytest.fixture
    def reg(self, tmp_path):
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path / "sensors.json"):
            from piclaw.hardware.sensors import SensorRegistry
            return SensorRegistry()

    def _make_sensor(self, name="test_dht", typ="DHT22"):
        from piclaw.hardware.sensors import SensorDef
        return SensorDef(name=name, type=typ, description="Test sensor",
                         config={"pin": 4})

    def test_add_and_get(self, tmp_path):
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry
            reg = SensorRegistry()
            reg.add(self._make_sensor("temp1"))
            assert reg.get("temp1") is not None

    def test_remove(self, tmp_path):
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry
            reg = SensorRegistry()
            reg.add(self._make_sensor("temp1"))
            assert reg.remove("temp1") is True
            assert reg.get("temp1") is None

    def test_remove_nonexistent(self, tmp_path):
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry
            reg = SensorRegistry()
            assert reg.remove("ghost") is False

    def test_persistence(self, tmp_path):
        f = tmp_path / "s.json"
        with patch("piclaw.hardware.sensors.SENSOR_FILE", f):
            from piclaw.hardware.sensors import SensorRegistry
            r1 = SensorRegistry()
            r1.add(self._make_sensor("persistent"))
            r2 = SensorRegistry()
            assert r2.get("persistent") is not None

    def test_list_enabled_filters(self, tmp_path):
        f = tmp_path / "s.json"
        with patch("piclaw.hardware.sensors.SENSOR_FILE", f):
            from piclaw.hardware.sensors import SensorRegistry, SensorDef
            reg = SensorRegistry()
            s1  = SensorDef(name="active",   type="DHT22", config={})
            s2  = SensorDef(name="inactive", type="DHT22", config={}, enabled=False)
            reg.add(s1); reg.add(s2)
            enabled = reg.list_enabled()
            assert any(s.name == "active"   for s in enabled)
            assert not any(s.name == "inactive" for s in enabled)

    def test_update_reading(self, tmp_path):
        from piclaw.hardware.sensors import SensorReading
        f = tmp_path / "s.json"
        with patch("piclaw.hardware.sensors.SENSOR_FILE", f):
            from piclaw.hardware.sensors import SensorRegistry
            reg = SensorRegistry()
            reg.add(self._make_sensor("r_sensor"))
            reading = SensorReading("r_sensor", {"temp_c": 22.5})
            reg.update_reading("r_sensor", reading)
            s = reg.get("r_sensor")
            assert s.last_reading is not None
            assert s.last_reading["values"]["temp_c"] == 22.5

    def test_summary_empty(self, tmp_path):
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry
            reg = SensorRegistry()
            assert "No sensors" in reg.summary()

    def test_summary_with_sensor(self, tmp_path):
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry
            reg = SensorRegistry()
            reg.add(self._make_sensor("my_sensor"))
            assert "my_sensor" in reg.summary()

    def test_all_types_accepted(self, tmp_path):
        from piclaw.hardware.sensors import ALL_TYPES, SensorDef
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry
            reg = SensorRegistry()
            for typ in ALL_TYPES:
                reg.add(SensorDef(name=f"s_{typ}", type=typ, config={}))
            assert len(reg.list_all()) == len(ALL_TYPES)


class TestSensorReading:

    def test_str_ok(self):
        from piclaw.hardware.sensors import SensorReading
        r = SensorReading("test", {"temp_c": 22.3})
        s = str(r)
        assert "test" in s
        assert "22.3" in s

    def test_str_error(self):
        from piclaw.hardware.sensors import SensorReading
        r = SensorReading("broken", {}, error="CRC fail")
        s = str(r)
        assert "ERROR" in s
        assert "CRC fail" in s

    def test_ds18b20_no_hardware(self):
        """DS18B20 reader returns graceful error when /sys/bus/w1 absent."""
        from piclaw.hardware.sensors import SensorDef, _read_ds18b20
        with patch("piclaw.hardware.sensors.Path") as mp:
            mp.return_value.exists.return_value = False
            sensor  = SensorDef(name="t", type="DS18B20", config={})
            reading = _read_ds18b20(sensor)
        assert reading.error is not None
        assert "1-Wire" in reading.error or "w1" in reading.error.lower() or reading.error


class TestHardwareContext:

    def test_empty_registry_returns_empty(self, tmp_path):
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry, build_hardware_context
            reg = SensorRegistry()
            assert build_hardware_context(reg) == ""

    def test_with_sensors_includes_names(self, tmp_path):
        from piclaw.hardware.sensors import SensorDef
        with patch("piclaw.hardware.sensors.SENSOR_FILE", tmp_path/"s.json"):
            from piclaw.hardware.sensors import SensorRegistry, build_hardware_context
            reg = SensorRegistry()
            reg.add(SensorDef(name="roof_temp", type="DS18B20",
                              description="Roof temperature", config={}))
            ctx = build_hardware_context(reg)
            assert "roof_temp" in ctx
            assert "DS18B20" in ctx

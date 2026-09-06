"""Unit tests for Vivado report parsing (no Vivado required)."""

from __future__ import annotations

from vivado_mcp.reports import (
    VivadoReportParser,
    classify_impl_failure,
    classify_impl_run_status,
    classify_synth_run_status,
)


UTIL_REPORT_2018 = """
Copyright 1986-2018 Xilinx, Inc. All Rights Reserved.
| Tool Version : Vivado v.2018.2
| Date         : Sun Sep  6 10:00:00 2026
| Host         : host
| Design       : counter
| Device       : 7a35tcsg324-1

1. Slice Logic
--------------

+----------------------------+------+-------+-----------+-------+
|          Site Type         | Used | Fixed | Available | Util% |
+----------------------------+------+-------+-----------+-------+
| Slice LUTs*                |   12 |     0 |     20800 |  0.06 |
|   LUT as Logic             |   12 |     0 |     20800 |  0.06 |
|   LUT as Memory            |    0 |     0 |      9600 |  0.00 |
| Slice Registers            |    8 |     0 |     41600 |  0.02 |
|   Register as Flip Flop    |    8 |     0 |     41600 |  0.02 |
|   Register as Latch        |    0 |     0 |     41600 |  0.00 |
+----------------------------+------+-------+-----------+-------+
* Warning!

3. Memory
---------
+----------------+------+-------+-----------+-------+
|    Site Type   | Used | Fixed | Available | Util% |
+----------------+------+-------+-----------+-------+
| Block RAM Tile |    0 |     0 |        50 |  0.00 |
|   RAMB36/FIFO* |    0 |     0 |        50 |  0.00 |
|   RAMB18       |    0 |     0 |       100 |  0.00 |
+----------------+------+-------+-----------+-------+

4. DSP
------
+-----------+------+-------+-----------+-------+
| Site Type | Used | Fixed | Available | Util% |
+-----------+------+-------+-----------+-------+
| DSPs      |    0 |     0 |        90 |  0.00 |
+-----------+------+-------+-----------+-------+

5. I/O
------
+--------------+------+-------+-----------+-------+
|  Site Type   | Used | Fixed | Available | Util% |
+--------------+------+-------+-----------+-------+
| Bonded IOB   |    3 |     0 |       106 |  2.83 |
+--------------+------+-------+-----------+-------+

6. Clocking
-----------
+------------+------+-------+-----------+-------+
|  Site Type | Used | Fixed | Available | Util% |
+------------+------+-------+-----------+-------+
| BUFGCTRL   |    1 |     0 |        32 |  3.13 |
| BUFIO      |    0 |     0 |        16 |  0.00 |
+------------+------+-------+-----------+-------+
"""

TIMING_MET_REPORT = """
Copyright 1986-2018 Xilinx, Inc. All Rights Reserved.
------------------------------------------------------------------------------------------------
| Design Timing Summary
| ---------------------
------------------------------------------------------------------------------------------------

    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      WHS(ns)      THS(ns)
    -------      -------  ---------------------  -------------------      -------      -------
      1.420        0.000                      0                 1200        0.050        0.000


All user specified timing constraints are met.
"""

TIMING_FAILED_REPORT = """
------------------------------------------------------------------------------------------------
| Design Timing Summary
------------------------------------------------------------------------------------------------
    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints
    -------      -------  ---------------------  -------------------
     -0.250       -1.500                      4                  800

Timing constraints are not met.
"""

TIMING_NO_CONSTRAINTS = """
There are no user specified timing constraints.
"""


def test_parse_utilization_2018_style() -> None:
    parsed = VivadoReportParser().parse_utilization(UTIL_REPORT_2018)
    assert parsed["lut"] is not None
    assert parsed["lut"].used == 12
    assert parsed["lut"].available == 20800
    assert parsed["lut"].utilization_percent == 0.06
    assert parsed["ff"] is not None
    assert parsed["ff"].used == 8
    assert parsed["bram"] is not None
    assert parsed["bram"].used == 0
    assert parsed["dsp"] is not None
    assert parsed["dsp"].used == 0
    assert parsed["io"] is not None
    assert parsed["io"].used == 3
    assert parsed["bufg"] is not None
    assert parsed["bufg"].used == 1


def test_parse_utilization_empty_and_malformed() -> None:
    parsed = VivadoReportParser().parse_utilization("")
    assert all(value is None for value in parsed.values())
    parsed2 = VivadoReportParser().parse_utilization("not a report\nrandom text\n")
    assert parsed2["lut"] is None


def test_parse_utilization_missing_dsp_is_null() -> None:
    tiny = """
| Site Type | Used | Fixed | Available | Util% |
| Slice LUTs | 4 | 0 | 1000 | 0.40 |
| Slice Registers | 2 | 0 | 2000 | 0.10 |
"""
    parsed = VivadoReportParser().parse_utilization(tiny)
    assert parsed["lut"] is not None
    assert parsed["ff"] is not None
    assert parsed["dsp"] is None
    assert parsed["bram"] is None


def test_parse_timing_met() -> None:
    summary = VivadoReportParser().parse_timing(TIMING_MET_REPORT)
    assert summary is not None
    assert summary.wns_ns == 1.42
    assert summary.tns_ns == 0.0
    assert summary.failing_endpoints == 0
    assert summary.status == "met"


def test_parse_timing_failed() -> None:
    summary = VivadoReportParser().parse_timing(TIMING_FAILED_REPORT)
    assert summary is not None
    assert summary.wns_ns == -0.25
    assert summary.tns_ns == -1.5
    assert summary.failing_endpoints == 4
    assert summary.status == "failed"


def test_parse_timing_no_constraints() -> None:
    assert VivadoReportParser().parse_timing(TIMING_NO_CONSTRAINTS) is None
    assert VivadoReportParser().parse_timing("") is None


def test_extract_errors_warnings() -> None:
    text = (
        "WARNING: [Synth 8-3331] something minor\n"
        "ERROR: [Synth 8-27] module not found\n"
        "INFO: done\n"
    )
    errors, warnings = VivadoReportParser().extract_errors_warnings(text)
    assert len(errors) == 1
    assert "module not found" in errors[0]
    assert len(warnings) == 1


def test_classify_synth_run_status() -> None:
    assert classify_synth_run_status("synth_design Complete!") == "completed"
    assert classify_synth_run_status("synth_design ERROR") == "failed"
    assert classify_synth_run_status("Not started") == "not_started"
    assert classify_synth_run_status("") == "unknown"


def test_classify_impl_run_status() -> None:
    assert classify_impl_run_status("route_design Complete!") == "completed"
    assert classify_impl_run_status("place_design ERROR") == "failed"
    assert classify_impl_run_status("Not started") == "not_started"
    assert classify_impl_run_status("") == "unknown"
    assert (
        VivadoReportParser().parse_implementation_status("route_design Complete!")
        == "completed"
    )


def test_classify_impl_failure() -> None:
    assert (
        classify_impl_failure("place_design ERROR", "could not place")
        == "placement_failure"
    )
    assert (
        classify_impl_failure("route_design ERROR", "failed to route")
        == "routing_failure"
    )
    assert classify_impl_failure("ERROR", "something else") == "implementation_failure"

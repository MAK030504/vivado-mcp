"""Parsers for Vivado utilization and timing reports.

Tolerates format differences across Vivado versions (including 2018.2) and
FPGA families. Missing resources become ``None`` rather than failing the
whole parse.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    """Used / available / percent for one resource type."""

    used: int
    available: int
    utilization_percent: float

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TimingSummary:
    """Post-synthesis (estimated) or implementation timing summary."""

    wns_ns: float | None = None
    tns_ns: float | None = None
    failing_endpoints: int | None = None
    status: str | None = None  # met | failed | unknown
    clocks: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "wns_ns": self.wns_ns,
            "tns_ns": self.tns_ns,
            "failing_endpoints": self.failing_endpoints,
            "status": self.status,
        }
        if self.clocks is not None:
            payload["clocks"] = self.clocks
        return payload


# Preferred label order per canonical resource key (first match wins).
_PREFERRED_LABELS: dict[str, tuple[str, ...]] = {
    "lut": ("slice luts", "clb luts", "luts"),
    "ff": (
        "slice registers",
        "clb registers",
        "register as flip flop",
        "flip flops",
        "registers",
    ),
    "bram": (
        "block ram tile",
        "block ram",
        "ramb36/fifo",
        "ramb18",
    ),
    "dsp": ("dsps", "dsp48e2", "dsp48e1", "dsp48"),
    "io": ("bonded iob", "bonded iobs", "iob", "i/o"),
    "bufg": ("bufgctrl", "bufg", "global clock buffers", "bufgs"),
}

# Pipe table row: | Slice LUTs* | 12 | 0 | 12 | 20800 | 0.06 |
_PIPE_ROW = re.compile(
    r"^\|\s*(?P<label>[^|]+?)\s*\|\s*(?P<used>-?\d+)\s*\|"
    r"(?:\s*-?\d+\s*\|){0,2}\s*(?P<available>-?\d+)\s*\|"
    r"\s*(?P<pct>-?\d+(?:\.\d+)?)\s*\|?\s*$",
    re.IGNORECASE,
)

# Whitespace row: Slice LUTs  12  20800  0.06
_SPACE_ROW = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z0-9 /_()+-]*?)\s+"
    r"(?P<used>\d+)\s+(?P<available>\d+)\s+(?P<pct>\d+(?:\.\d+)?)\s*%?\s*$"
)

_WNS_TNS_HEADER = re.compile(
    r"WNS\(ns\)\s+TNS\(ns\)",
    re.IGNORECASE,
)
_WNS_LINE = re.compile(
    r"^\s*(?P<wns>-?\d+(?:\.\d+)?|N/A|NA)\s+"
    r"(?P<tns>-?\d+(?:\.\d+)?|N/A|NA)"
    r"(?:\s+(?P<failing>\d+))?",
    re.IGNORECASE,
)
_WNS_NAMED = re.compile(r"\bWNS\b[^-\d]*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_TNS_NAMED = re.compile(r"\bTNS\b[^-\d]*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_FAILING_NAMED = re.compile(
    r"(?:failing endpoints|TNS Failing Endpoints)\s*[:=]?\s*(\d+)",
    re.IGNORECASE,
)


class VivadoReportParser:
    """Parse Vivado text reports into structured dictionaries."""

    def parse_utilization(self, report_text: str) -> dict[str, ResourceUsage | None]:
        """Parse a ``report_utilization`` text report.

        Returns keys ``lut``, ``ff``, ``bram``, ``dsp``, ``io``, ``bufg``.
        Unavailable resources are ``None``.
        """
        if not report_text or not report_text.strip():
            return {key: None for key in _PREFERRED_LABELS}

        rows = self._extract_utilization_rows(report_text)
        result: dict[str, ResourceUsage | None] = {}
        for key, preferred in _PREFERRED_LABELS.items():
            match: ResourceUsage | None = None
            for label in preferred:
                if label in rows:
                    match = rows[label]
                    break
            result[key] = match
        return result

    def parse_timing(self, report_text: str) -> TimingSummary | None:
        """Parse a ``report_timing_summary`` text report.

        Returns ``None`` when timing data is absent (no constraints / empty).
        """
        if not report_text or not report_text.strip():
            return None

        lowered = report_text.lower()
        no_constraints = (
            "no user specified timing constraints" in lowered
            or "there are no timing constraints" in lowered
            or "no timing constraints found" in lowered
            or "no timing constraints" in lowered
        )
        summary = self._extract_timing_numbers(report_text)
        if no_constraints and summary.wns_ns is None and summary.tns_ns is None:
            return None
        if (
            summary.wns_ns is None
            and summary.tns_ns is None
            and summary.failing_endpoints is None
        ):
            return None
        return summary

    def parse_implementation_status(self, run_status: str) -> str:
        """Map a Vivado ``impl_1`` STATUS string to a coarse MCP status."""
        return classify_impl_run_status(run_status)

    def extract_errors_warnings(self, text: str) -> tuple[list[str], list[str]]:
        """Extract concise ERROR / WARNING lines from Vivado log text.

        Warnings are collected separately and must not be treated as failures.
        """
        errors: list[str] = []
        warnings: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if lower.startswith("error") or re.match(r"^error(?:\s*:|\s+\[)", lower):
                errors.append(_clip(stripped, 240))
            elif lower.startswith("warning") or re.match(
                r"^warning(?:\s*:|\s+\[)", lower
            ):
                warnings.append(_clip(stripped, 240))
        return errors[:50], warnings[:50]

    def _extract_utilization_rows(
        self, report_text: str
    ) -> dict[str, ResourceUsage]:
        found: dict[str, ResourceUsage] = {}
        for raw_line in report_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("+") or set(line) <= {"-", "=", "|", " "}:
                continue
            parsed = self._parse_util_line(line)
            if parsed is None:
                continue
            label, usage = parsed
            if label not in found:
                found[label] = usage
        return found

    def _parse_util_line(self, line: str) -> tuple[str, ResourceUsage] | None:
        match = _PIPE_ROW.match(line)
        if match is None:
            match = _SPACE_ROW.match(line)
        if match is None:
            return None
        label = _normalize_label(match.group("label"))
        if not label:
            return None
        try:
            used = int(match.group("used"))
            available = int(match.group("available"))
            pct = float(match.group("pct"))
        except (TypeError, ValueError):
            return None
        if available < 0 or used < 0:
            return None
        return label, ResourceUsage(
            used=used,
            available=available,
            utilization_percent=pct,
        )

    def _extract_timing_numbers(self, report_text: str) -> TimingSummary:
        wns: float | None = None
        tns: float | None = None
        failing: int | None = None
        lines = report_text.splitlines()

        for index, line in enumerate(lines):
            if _WNS_TNS_HEADER.search(line):
                for follow in lines[index + 1 : index + 6]:
                    if re.match(r"^[\s\-|=]+$", follow):
                        continue
                    values = _WNS_LINE.match(follow.strip())
                    if values:
                        wns = _to_float(values.group("wns"))
                        tns = _to_float(values.group("tns"))
                        if values.group("failing") is not None:
                            failing = int(values.group("failing"))
                        break
                break

        if wns is None:
            named = _WNS_NAMED.search(report_text)
            if named:
                wns = float(named.group(1))
        if tns is None:
            named = _TNS_NAMED.search(report_text)
            if named:
                tns = float(named.group(1))
        if failing is None:
            named = _FAILING_NAMED.search(report_text)
            if named:
                failing = int(named.group(1))
        return TimingSummary(
            wns_ns=wns,
            tns_ns=tns,
            failing_endpoints=failing,
            status=_timing_met_status(report_text, wns, failing),
        )


def parse_utilization_file(path: Path) -> dict[str, ResourceUsage | None]:
    """Parse a utilization report file from disk."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return VivadoReportParser().parse_utilization(text)


def parse_timing_file(path: Path) -> TimingSummary | None:
    """Parse a timing summary report file from disk."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return VivadoReportParser().parse_timing(text)


def classify_synth_run_status(run_status: str) -> str:
    """Map Vivado ``synth_1`` STATUS property to a coarse MCP status."""
    text = (run_status or "").strip().lower()
    if not text:
        return "unknown"
    if "error" in text or "fail" in text:
        return "failed"
    if "complete" in text:
        return "completed"
    if "cancel" in text:
        return "cancelled"
    if "running" in text or "queued" in text:
        return "running"
    if "not started" in text or text == "n/a":
        return "not_started"
    return "unknown"


def classify_impl_run_status(run_status: str) -> str:
    """Map Vivado ``impl_1`` STATUS property to a coarse MCP status."""
    text = (run_status or "").strip().lower()
    if not text:
        return "unknown"
    if "error" in text or "fail" in text:
        return "failed"
    if "complete" in text:
        return "completed"
    if "cancel" in text:
        return "cancelled"
    if "running" in text or "queued" in text:
        return "running"
    if "not started" in text or text == "n/a":
        return "not_started"
    return "unknown"


def classify_impl_failure(run_status: str, log_text: str = "") -> str:
    """Classify an implementation failure into a more specific category.

    Returns one of: ``placement_failure``, ``routing_failure``,
    ``constraint_failure``, ``clocking_failure``, ``resource_exhaustion``,
    ``implementation_tool_failure``, or ``implementation_failure``.
    """
    combined = f"{run_status}\n{log_text}".lower()
    if any(
        token in combined
        for token in (
            "place_design",
            "placement",
            "placer",
            "could not place",
            "failed to place",
        )
    ):
        return "placement_failure"
    if any(
        token in combined
        for token in (
            "route_design",
            "routing",
            "router",
            "unroutable",
            "failed to route",
            "could not route",
        )
    ):
        return "routing_failure"
    if any(
        token in combined
        for token in (
            "constraint",
            "xdc",
            "set_property package_pin",
            "invalid constraint",
        )
    ):
        return "constraint_failure"
    if any(
        token in combined
        for token in ("clock", "mmcm", "pll", "bufg", "clocking")
    ) and ("error" in combined or "fail" in combined):
        return "clocking_failure"
    if any(
        token in combined
        for token in (
            "overutilized",
            "over-utilized",
            "insufficient resources",
            "does not fit",
            "resource",
        )
    ):
        return "resource_exhaustion"
    if "opt_design" in combined or "phys_opt" in combined:
        return "implementation_tool_failure"
    return "implementation_failure"


def _normalize_label(label: str) -> str:
    cleaned = label.strip().lower()
    cleaned = cleaned.replace("*", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    if cleaned in {"", "N/A", "NA", "NONE"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _timing_met_status(
    report_text: str,
    wns: float | None,
    failing: int | None,
) -> str | None:
    lowered = report_text.lower()
    if "timing constraints are not met" in lowered:
        return "failed"
    if "all user specified timing constraints are met" in lowered:
        return "met"
    if "timing constraints are met" in lowered:
        return "met"
    if failing is not None:
        return "failed" if failing > 0 else "met"
    if wns is not None:
        return "met" if wns >= 0 else "failed"
    return "unknown"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."

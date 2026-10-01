from __future__ import annotations

import bisect
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

BRANCHES = [
    {"BranchId": "LON", "BranchName": "London Heathrow", "City": "London", "Latitude": 51.4713, "Longitude": -0.4524, "Count": 16,
     "Waypoints": [(51.4713, -0.4524), (51.5090, -0.1935), (51.5045, -0.0865), (51.5307, -0.1240), (51.4713, -0.4524)]},
    {"BranchId": "MAN", "BranchName": "Manchester Airport", "City": "Manchester", "Latitude": 53.3653, "Longitude": -2.2725, "Count": 6,
     "Waypoints": [(53.3653, -2.2725), (53.4632, -2.2913), (53.4778, -2.2308), (53.4962, -2.2446), (53.3653, -2.2725)]},
    {"BranchId": "BHM", "BranchName": "Birmingham Airport", "City": "Birmingham", "Latitude": 52.4527, "Longitude": -1.7319, "Count": 6,
     "Waypoints": [(52.4527, -1.7319), (52.4776, -1.8989), (52.4869, -1.9142), (52.4143, -1.7791), (52.4527, -1.7319)]},
    {"BranchId": "BRS", "BranchName": "Bristol Temple Meads", "City": "Bristol", "Latitude": 51.4497, "Longitude": -2.5816, "Count": 4,
     "Waypoints": [(51.4497, -2.5816), (51.4541, -2.6262), (51.4954, -2.5869), (51.4614, -2.5489), (51.4497, -2.5816)]},
    {"BranchId": "LDS", "BranchName": "Leeds City", "City": "Leeds", "Latitude": 53.7921, "Longitude": -1.5480, "Count": 4,
     "Waypoints": [(53.7921, -1.5480), (53.8214, -1.5757), (53.8323, -1.5015), (53.7803, -1.5355), (53.7921, -1.5480)]},
    {"BranchId": "EDI", "BranchName": "Edinburgh Airport", "City": "Edinburgh", "Latitude": 55.9476, "Longitude": -3.3640, "Count": 4,
     "Waypoints": [(55.9476, -3.3640), (55.9455, -3.2180), (55.9520, -3.1817), (55.9787, -3.1735), (55.9476, -3.3640)]},
]
MODELS = [
    ("Polestar", "2", "Electric", "Long range", 79),
    ("Volvo", "EX30", "Electric", "Compact SUV", 69),
    ("Volkswagen", "Golf", "Petrol", "Compact", 49),
    ("BMW", "330e", "Hybrid", "Executive", 99),
    ("Kia", "EV6", "Electric", "Crossover", 85),
    ("Toyota", "Corolla", "Hybrid", "Compact", 55),
    ("Mercedes-Benz", "C-Class", "Petrol", "Executive", 109),
    ("Volkswagen", "ID.4", "Electric", "SUV", 89),
]
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
EVENT_NAMESPACE = uuid.UUID("4b189e4e-71f9-4a29-af5e-7d68446dadbc")


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp has no timezone.")
    return result.astimezone(UTC)


def day_bounds(day: date, timezone: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    return (
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC),
    )


def previous_day(now: datetime, timezone: str) -> tuple[date, datetime, datetime]:
    day = now.astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)
    start, end = day_bounds(day, timezone)
    return day, start, end


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1, math.sqrt(h)))


def fleet_vehicles() -> list[dict]:
    vehicles = []
    for branch in BRANCHES:
        for _ in range(branch["Count"]):
            index = len(vehicles)
            make, model, powertrain, category, rate = MODELS[index % len(MODELS)]
            vehicles.append({
                "VehicleId": f"CD-{index + 1:03d}",
                "Registration": f"{branch['BranchId'][:2]}{24 + index % 3} {chr(65 + index // 26)}{chr(65 + index % 26)}D",
                "Make": make, "Model": model, "Powertrain": powertrain,
                "Category": category, "DailyRateGBP": float(rate), "BranchId": branch["BranchId"],
                "City": branch["City"], "BranchName": branch["BranchName"],
                "BaseOdometerKm": float(8000 + index * 733),
                "ServiceDueKm": float(85000 + index * 1000),
                "Index": index,
            })
    return vehicles


class Telemetry(BaseModel):
    EventId: str
    VehicleId: str
    IntervalStart: datetime
    Timestamp: datetime
    Latitude: float = Field(ge=-90, le=90)
    Longitude: float = Field(ge=-180, le=180)
    SpeedKmh: float = Field(ge=0, le=200)
    Heading: float = Field(ge=0, lt=360)
    OdometerKm: float = Field(ge=0)
    DistanceKm: float = Field(ge=0)
    BatteryPct: float | None = Field(default=None, ge=0, le=100)
    FuelPct: float | None = Field(default=None, ge=0, le=100)
    TyrePressureBar: float = Field(ge=0, le=5)
    EngineTempC: float
    Status: str
    Alert: str
    BranchId: str
    RouteId: str
    RentalId: str
    Source: str = "vehicle-telemetry"

    @model_validator(mode="after")
    def valid_interval(self) -> Telemetry:
        if self.Timestamp.tzinfo is None or self.IntervalStart.tzinfo is None:
            raise ValueError("Telemetry timestamps must include a timezone.")
        if self.Timestamp <= self.IntervalStart:
            raise ValueError("Telemetry intervals must have positive duration.")
        return self


@dataclass
class RoadRoute:
    route_id: str
    points: list[tuple[float, float]]
    travel_seconds: float

    def __post_init__(self) -> None:
        if len(self.points) < 2 or self.travel_seconds <= 0:
            raise ValueError("A road route requires coordinates and a positive travel time.")
        self.cumulative = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cumulative.append(self.cumulative[-1] + distance_km(a, b))
        self.length_km = self.cumulative[-1]
        if self.length_km <= 0:
            raise ValueError("The road route has zero length.")

    def position(self, km: float) -> tuple[float, float, float]:
        km = min(max(km, 0), self.length_km)
        i = min(bisect.bisect_right(self.cumulative, km) - 1, len(self.points) - 2)
        a, b = self.points[i], self.points[i + 1]
        segment = self.cumulative[i + 1] - self.cumulative[i]
        fraction = (km - self.cumulative[i]) / segment if segment > 0 else 0
        latitude = a[0] + (b[0] - a[0]) * fraction
        longitude = a[1] + (b[1] - a[1]) * fraction
        y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
        x = math.cos(math.radians(a[0])) * math.sin(math.radians(b[0])) - math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1]))
        return latitude, longitude, math.degrees(math.atan2(y, x)) % 360


class VehicleMotion:
    def __init__(self, vehicle: dict, route: RoadRoute) -> None:
        self.vehicle = vehicle
        self.route = route
        self.drive_seconds = max(route.travel_seconds * (1.05 + vehicle["Index"] % 5 * .09), route.length_km / 95 * 3600)
        self.dwell_seconds = 1200 + vehicle["Index"] % 7 * 240
        self.cycle_seconds = self.drive_seconds + self.dwell_seconds
        self.offset = vehicle["Index"] * 719

    def state(self, timestamp: datetime) -> tuple[float, float, bool]:
        if timestamp.tzinfo is None or timestamp < EPOCH:
            raise ValueError("Motion requires a timezone-aware timestamp on or after the epoch.")
        if self.vehicle["Index"] in {13, 33}:
            return 0, 0, False
        elapsed = (timestamp - EPOCH).total_seconds() + self.offset
        cycles, phase = divmod(elapsed, self.cycle_seconds)
        progress = min(phase / self.drive_seconds, 1)
        return (cycles + progress) * self.route.length_km, progress, phase < self.drive_seconds

    def sample(self, start: datetime, end: datetime) -> Telemetry:
        before, _, _ = self.state(start)
        after, progress, driving = self.state(end)
        latitude, longitude, heading = self.route.position(progress * self.route.length_km if driving else 0)
        index = self.vehicle["Index"]
        electric = self.vehicle["Powertrain"] == "Electric"
        status = "on-hire" if driving else ("charging" if electric else "available")
        if index in {13, 33}:
            status = "maintenance"
        charge = max(7, 91 - progress * 24 - (index % 9) * 4)
        if index == 8:
            charge = max(8, 18 - progress * 7)
        pressure = 1.72 if index == 21 else round(2.35 + .12 * math.sin(index + progress), 2)
        alert = "Maintenance required" if status == "maintenance" else (
            "Low tyre pressure" if pressure < 1.9 else ("Low battery" if electric and charge < 20 else "")
        )
        return Telemetry(
            EventId=str(uuid.uuid5(EVENT_NAMESPACE, f"{self.vehicle['VehicleId']}:{utc_text(start)}:{utc_text(end)}")),
            VehicleId=self.vehicle["VehicleId"], IntervalStart=start, Timestamp=end,
            Latitude=round(latitude, 6), Longitude=round(longitude, 6),
            SpeedKmh=round(self.route.length_km / self.drive_seconds * 3600 if driving else 0, 1),
            Heading=round(heading, 2) % 360,
            OdometerKm=round(self.vehicle["BaseOdometerKm"] + after, 6),
            DistanceKm=round(max(0, after - before), 9),
            BatteryPct=round(charge, 1) if electric else None,
            FuelPct=None if electric else round(max(12, 88 - progress * 22 - index % 6 * 4), 1),
            TyrePressureBar=pressure, EngineTempC=round(23 + (46 if electric else 65) * progress, 1),
            Status=status, Alert=alert, BranchId=self.vehicle["BranchId"],
            RouteId=self.route.route_id, RentalId=f"R-{index + 10401}" if driving else "",
        )

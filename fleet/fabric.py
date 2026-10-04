from __future__ import annotations

import io
import json
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from azure.kusto.data import ClientRequestProperties, KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.data_format import DataFormat
from azure.kusto.ingest import IngestionProperties, ManagedStreamingIngestClient, StreamDescriptor
from azure.kusto.ingest.base_ingest_client import IngestionStatus
from azure.storage.filedatalake import DataLakeServiceClient
from deltalake import write_deltalake
import pyarrow as pa

from fleet.config import ROOT, data_credential, settings
from fleet.domain import day_bounds, utc_text
from fleet.insurance import Incidents, Quote, insurance_config, quote_compliance
from fleet.storage import StateStore


def clean_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_text(value if value.tzinfo else value.replace(tzinfo=UTC))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_value(v) for v in value]
    return value


def repair_quote_fact(case: dict, quote: dict, config: dict) -> dict:
    decision = case.get("recommendation", {})
    recorded = next((item.get("compliance") for item in decision.get("quotes", []) if item["garage_id"] == quote["garage_id"]), None)
    compliance = recorded or (
        {"status": "not_assessed_historical", "eligible": False, "findings": []}
        if case["status"] in {"booked", "closed"} else quote_compliance(Quote.model_validate(quote))
    )
    message = next((item for item in case.get("correspondence", []) if item["id"] == quote["email_id"]), {})
    return {
        "QuoteId": f"{case['id']}|{quote['garage_id']}",
        "CaseId": case["id"], "VehicleId": case["vehicle_id"], "GarageId": quote["garage_id"],
        "AmountGBP": float(quote["amount_gbp"]), "AvailableFrom": quote["available_from"],
        "ReadyBy": quote["ready_by"], "ValidUntil": quote["valid_until"],
        "WarrantyMonths": quote["warranty_months"], "Scope": quote["scope"],
        "Exclusions": quote["exclusions"], "NativeAgentId": quote["agent_id"],
        "DowntimeCostPerDayGBP": float(config["downtime_cost_per_day"]),
        "IncidentDetectedAt": case["created_at"],
        "PartsReplacementRequired": {True: "required", False: "not_required", None: "not_recorded"}[quote.get("replacement_parts_required")],
        "PartsItems": json.dumps(quote.get("replacement_parts", [])),
        "PartsDeclaration": quote.get("parts_statement", ""),
        "PartsComplianceStatus": compliance["status"], "PartsEligible": compliance["eligible"],
        "PartsComplianceReasons": "; ".join(f"{item['clause']}: {item['reason']}" for item in compliance["findings"]),
        "PartsPolicyId": quote.get("policy_id", ""), "PartsPolicyVersion": quote.get("policy_version", ""),
        "PartsPolicyDocumentUrl": decision.get("policy", {}).get("document_url") or "",
        "QuoteEmailId": quote["email_id"], "QuoteEmailUrl": message.get("web_url", ""),
    }


class FabricData:
    def __init__(self) -> None:
        self.config = settings()
        self.credential = data_credential()
        connection = KustoConnectionStringBuilder.with_azure_token_credential(
            self.config["query_service_uri"], self.credential
        )
        ingestion = KustoConnectionStringBuilder.with_azure_token_credential(
            self.config["ingestion_service_uri"], self.credential
        )
        self.client = KustoClient(connection)
        self.ingestor = ManagedStreamingIngestClient(connection, ingestion)
        self.database = self.config["database_name"]
        self.onelake = DataLakeServiceClient(
            "https://onelake.dfs.fabric.microsoft.com", credential=self.credential
        ).get_file_system_client(self.config["workspace_id"])

    def query(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict]:
        properties = ClientRequestProperties()
        properties.set_option("servertimeout", timedelta(seconds=90))
        for key, value in (parameters or {}).items():
            properties.set_parameter(key, value)
        result = self.client.execute(self.database, query, properties)
        if not result.primary_results:
            raise RuntimeError("Fabric returned no result table.")
        table = result.primary_results[0]
        names = [column.column_name for column in table.columns]
        return [clean_value(dict(zip(names, list(row)))) for row in table]

    def ingest(self, table: str, rows: list[dict]) -> None:
        if not rows:
            raise ValueError("An ingestion batch cannot be empty.")
        data = "\n".join(json.dumps(row, allow_nan=False, separators=(",", ":")) for row in rows).encode()
        result = self.ingestor.ingest_from_stream(
            StreamDescriptor(io.BytesIO(data)),
            ingestion_properties=IngestionProperties(
                database=self.database, table=table, data_format=DataFormat.MULTIJSON,
                ingestion_mapping_reference=f"{table}Json",
            ),
        )
        if result.status == IngestionStatus.QUEUED:
            if table not in {"Telemetry", "VehicleImpacts"}:
                raise RuntimeError(f"{table} ingestion was queued rather than immediately committed.")
            ids = [row["EventId"] for row in rows]
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                found = self.query(
                    f"declare query_parameters(ids:dynamic); {table} | where EventId in (ids) | summarize Events=count_distinct(EventId)",
                    {"ids": json.dumps(ids)},
                )
                if found[0]["Events"] == len(set(ids)):
                    return
                time.sleep(5)
            raise TimeoutError("Queued telemetry was not queryable within three minutes; checkpoint was not advanced.")
        elif result.status != IngestionStatus.SUCCESS:
            raise RuntimeError(f"Unexpected ingestion result: {result.status}")

    def initialise_schema(self) -> None:
        commands = (ROOT / "fabric" / "schema.kql").read_text(encoding="utf-8")
        for command in commands.split("\n\n"):
            if command.strip():
                self.client.execute_mgmt(self.database, command.strip())
        for table in ("Telemetry", "Vehicles", "Branches"):
            rows = self.query(f".show table {table} cslschema")
            schema = rows[0]["Schema"]
            names = [column.strip().split(":")[0].strip("[]'() ") for column in schema.split(",")]
            mapping = [{"column": name, "Properties": {"Path": f"$.{name}"}} for name in names]
            self.client.execute_mgmt(
                self.database,
                f".create-or-alter table {table} ingestion json mapping '{table}Json' '{json.dumps(mapping)}'",
            )

    def latest(self) -> list[dict]:
        return self.query("FleetLatest() | order by VehicleId asc")

    def mileage(self, report_date: date) -> list[dict]:
        start, end = day_bounds(report_date, self.config["report_timezone"])
        return self.query(
            "declare query_parameters(fromUtc:datetime, toUtc:datetime); FleetDistance(fromUtc, toUtc) | order by DistanceKm desc",
            {"fromUtc": utc_text(start), "toUtc": utc_text(end)},
        )

    def history(self, vehicle_id: str) -> list[dict]:
        return self.query(
            "declare query_parameters(vehicle:string); FleetEvents() | where VehicleId == vehicle and Timestamp > ago(2h) | summarize arg_max(Timestamp, *) by bin(Timestamp, 1m) | order by Timestamp asc | project Timestamp, Latitude, Longitude, SpeedKmh, BatteryPct, FuelPct",
            {"vehicle": vehicle_id},
        )

    def write_table(self, name: str, rows: list[dict]) -> None:
        if not rows:
            raise ValueError(f"Refusing to replace Lakehouse table {name} with an empty result.")
        table = pa.Table.from_pylist(rows)
        for i, field in enumerate(table.schema):
            if pa.types.is_null(field.type):
                table = table.set_column(i, field.name, table.column(i).cast(pa.float64()))
        options = {
            "azure_storage_account_name": "onelake",
            "azure_use_fabric_endpoint": "true",
            "azure_storage_token": self.credential.get_token("https://storage.azure.com/.default").token,
        }
        url = (
            f"abfss://{self.config['workspace_id']}@onelake.dfs.fabric.microsoft.com/"
            f"{self.config['lakehouse_id']}/Tables/{name}"
        )
        write_deltalake(
            url, table, mode="overwrite", schema_mode="merge",
            storage_options=options, configuration={"delta.enableChangeDataFeed": "false"},
        )

    def refresh_lakehouse(self) -> dict:
        mileage = self.query("FleetDailyMileage()")
        for row in mileage:
            row["MileageId"] = f"{row['VehicleId']}|{row['ReportDate']}"
        tables = {
            "VehicleState": self.latest(),
            "DailyMileage": mileage,
        }
        cases = Incidents(StateStore()).list()
        if cases:
            tables["Incidents"] = [{
                "CaseId": case["id"], "VehicleId": case["vehicle_id"],
                "Status": case["status"], "DetectedAt": case["created_at"],
                "UpdatedAt": case["updated_at"], "EvidenceCount": len(case["photos"]),
                "QuoteCount": len(case["quotes"]),
                "RecommendedGarage": case.get("recommendation", {}).get("garage_id") or "",
                "ReportSummary": case["repair_report"]["summary"] if case.get("repair_report", {}).get("privacy_passed") else "",
                "ApprovedBy": case.get("approval", {}).get("by", ""),
                "ApprovedGarage": case.get("approval", {}).get("garage_id", ""),
                "OverrodeRecommendation": bool(case.get("approval", {}).get("override")),
                "OverrideReason": case.get("approval", {}).get("reason", ""),
                "ExpectedReturn": case.get("booking", {}).get("ready_by", ""),
                "AwaitingOperatorApproval": case["status"] == "recommendation_ready" and bool(case.get("recommendation", {}).get("agent")),
                "ApprovalRecorded": bool(case.get("approval")),
                "BookingConfirmed": case["status"] == "booked" and bool(case.get("booking", {}).get("email_id")),
                "RepairPolicyId": case.get("recommendation", {}).get("policy", {}).get("id", ""),
                "RepairPolicyVersion": case.get("recommendation", {}).get("policy", {}).get("version", ""),
                "RepairPolicyDocumentUrl": case.get("recommendation", {}).get("policy", {}).get("document_url") or "",
                "PartsReviewRequired": case["status"] == "quote_review_required",
            } for case in cases]
            policy = insurance_config()
            quotes = [repair_quote_fact(case, quote, policy) for case in cases for quote in case["quotes"].values()]
            if quotes:
                tables["RepairQuotes"] = quotes
        for name, rows in tables.items():
            self.write_table(name, rows)
        return {"asOf": utc_text(datetime.now(UTC)), "rows": {name: len(rows) for name, rows in tables.items()}}

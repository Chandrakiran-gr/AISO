import ast
import inspect
import sys
from dataclasses import fields
from pathlib import Path
from typing import get_args

from api import database
from api.domain import ports


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "api" / "domain"
ALLOWED_DOMAIN_IMPORTS = {"api.domain.ports"}


def test_execution_ports_match_spec_async_contract():
    assert set(get_args(ports.ScanStatus)) == {
        "queued",
        "running",
        "succeeded",
        "partial",
        "failed",
        "cancelled",
    }

    assert inspect.iscoroutinefunction(ports.ScanExecutor.enqueue)
    assert inspect.iscoroutinefunction(ports.ScanExecutor.status)
    assert inspect.iscoroutinefunction(ports.ScanExecutor.cancel)
    assert inspect.iscoroutinefunction(ports.ProgressReporter.report)
    assert inspect.iscoroutinefunction(ports.ProgressReporter.subscribe)
    assert inspect.iscoroutinefunction(ports.LLMProvider.complete)
    assert inspect.iscoroutinefunction(ports.CostLedger.record)
    assert inspect.iscoroutinefunction(ports.CostLedger.remaining)
    assert _field_names(ports.ProviderResponse) == {
        "text",
        "provider",
        "model",
        "raw_metadata",
        "system_fingerprint",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "latency_ms",
        "request_payload_hash",
        "raw_response_hash",
        "response_received_at",
    }

    enqueue_params = inspect.signature(ports.ScanExecutor.enqueue).parameters
    assert list(enqueue_params) == [
        "self",
        "scan_run_id",
        "idempotency_key",
        "client_id",
        "methodology_version",
        "cost_budget_usd",
        "priority",
    ]


def test_phase12_upstream_ports_remain_sync_for_existing_pipeline():
    assert not inspect.iscoroutinefunction(ports.UpstreamLLMProvider.complete)
    assert not inspect.iscoroutinefunction(ports.UpstreamScanExecutor.enqueue)
    assert _field_names(ports.UpstreamProviderResponse) == {
        "text",
        "provider",
        "model",
        "raw_metadata",
    }

    upstream_complete_params = inspect.signature(
        ports.UpstreamLLMProvider.complete
    ).parameters
    assert list(upstream_complete_params) == [
        "self",
        "prompt",
        "seed",
        "temperature",
        "idempotency_key",
    ]


def test_domain_modules_import_only_stdlib_and_ports():
    stdlib_modules = set(sys.stdlib_module_names)
    violations: list[str] = []

    for path in DOMAIN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_module: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_module = alias.name
                    _record_import_violation(path, imported_module, stdlib_modules, violations)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    violations.append(f"{path.name}: relative import")
                    continue
                imported_module = node.module
                if imported_module:
                    _record_import_violation(path, imported_module, stdlib_modules, violations)

    assert violations == []


def test_cost_ledger_port_name_does_not_collide_with_orm_model():
    assert ports.CostLedger.__module__ == "api.domain.ports"
    assert hasattr(database, "CostLedgerEntry")
    assert database.CostLedgerEntry.__tablename__ == "cost_ledger"
    assert not hasattr(database, "CostLedger")


def _field_names(dataclass_type: type) -> set[str]:
    return {field.name for field in fields(dataclass_type)}


def _record_import_violation(
    path: Path,
    imported_module: str,
    stdlib_modules: set[str],
    violations: list[str],
) -> None:
    if imported_module == "__future__":
        return
    if imported_module in ALLOWED_DOMAIN_IMPORTS:
        return
    if imported_module.startswith("api."):
        violations.append(f"{path.name}: {imported_module}")
        return
    root_module = imported_module.split(".", maxsplit=1)[0]
    if root_module not in stdlib_modules:
        violations.append(f"{path.name}: {imported_module}")

#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
"$ROOT/scripts/r82_gate_runtime_compatibility.sh"
PYTHON="$ROOT/gate_runtime/python/bin/python3"
NODE="$ROOT/gate_toolchain/node/bin/node"
[ -x "$NODE" ] || { echo "R8.2 RELEASE GATE: BLOCK"; echo "SEALED_NODE_MISSING"; exit 1; }
# Hermetic PATH: sealed Node and sealed Python first; only minimal POSIX/system utilities remain reachable.
export PATH="$ROOT/gate_toolchain/node/bin:$ROOT/gate_runtime/python/bin:/usr/bin:/bin"
export PYTHONPATH="$ROOT/src"
$PYTHON scripts/r82_gate_toolchain_integrity.py
$PYTHON scripts/r82_gate_runtime_integrity.py

$PYTHON scripts/r82_deploy_package_gate.py
$PYTHON scripts/r82_no_stamp_gate.py
$PYTHON scripts/r82_migration_lineage_gate.py
$PYTHON scripts/r82_manifest_consistency_gate.py
$PYTHON scripts/r82_source_checksum_gate.py
$PYTHON scripts/r82_go_recommendation_constitution_1_0_gate.py
$PYTHON scripts/r82_console_session_gate.py
$PYTHON scripts/r82_admin_access_zh_gate.py
$PYTHON scripts/r82_supplier_mobile_gate.py
$PYTHON scripts/r82_supplier_structured_operations_gate.py
$PYTHON scripts/r82_three_surface_productization_gate.py
$PYTHON scripts/r82_three_surface_productization_closure_gate.py
$PYTHON scripts/r82_vi_alignment_gate.py
$PYTHON scripts/r82_consumer_vi_reference10_gate.py
$PYTHON scripts/r82_productization_closure_gate.py
$PYTHON scripts/r82_rc17_7_supplier_commerce_growth_gate.py
$PYTHON scripts/r82_rc17_8_consumer_transaction_ux_gate.py
$PYTHON scripts/r82_rc179_national_hotel_infrastructure_gate.py
$PYTHON scripts/r82_rc1791_regional_provider_gate.py
$PYTHON scripts/r82_rc18_operations_simplification_gate.py
$PYTHON scripts/r82_rc19_product_completeness_gate.py
$PYTHON scripts/r82_rc191_tiered_onboarding_vault_gate.py
$PYTHON scripts/r82_rc20_module_depth_gate.py
$PYTHON scripts/r82_rc201_partner_ux_gate.py
$PYTHON scripts/r82_rc202_all_b_to_a_gate.py
$PYTHON scripts/r82_rc203_cross_surface_ux_gate.py
$PYTHON scripts/r82_hotel_discovery_slice1_gate.py
$PYTHON scripts/r82_discovery_ssrf_guard_gate.py
$PYTHON scripts/r82_hotel_page_factory_console_gate.py
$PYTHON scripts/r82_hotel_page_factory_runtime_gate.py
$PYTHON scripts/r82_hotel_page_production_batch_gate.py
$PYTHON scripts/r82_hotel_supply_sandbox_gate.py
$PYTHON scripts/r82_provider_adapter_contract_gate.py
$PYTHON scripts/r82_rc15_supply_truth_gate.py
$PYTHON scripts/r82_payment_sandbox_readiness_gate.py
$PYTHON scripts/r82_payment_sandbox_certification_gate.py
$PYTHON scripts/r82_payment_sandbox_cutover_safety_gate.py
$PYTHON scripts/r82_rc093_hardening_gate.py
$PYTHON scripts/r82_aoluguya_bootstrap_gate.py
$PYTHON scripts/r82_aoluguya_bootstrap_cycle_gate.py
$PYTHON scripts/r82_rc07_ux_gate.py
$PYTHON scripts/r82_release_engineering_debt_gate.py
$PYTHON scripts/r81_control_debt_gate.py
$PYTHON scripts/r81_commercial_fail_closed_gate.py
$PYTHON scripts/r8_contract_gate.py

$PYTHON scripts/r82_staging_execution_evidence_gate.py
$PYTHON scripts/r82_staging_operator_gate.py
$PYTHON scripts/r82_staging_deployment_controller_gate.py

$PYTHON scripts/r82_staging_postdeploy_gate.py
$PYTHON scripts/r82_staging_incident_correlation_gate.py
$PYTHON scripts/r82_staging_incident_resolution_gate.py

echo "R8.2 RELEASE GATE: PASS"

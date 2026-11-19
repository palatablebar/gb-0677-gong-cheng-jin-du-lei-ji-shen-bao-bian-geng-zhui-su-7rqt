from decimal import Decimal
import pytest
from app.modules.m8_measurement.rules import evaluate, PREVIOUS_BASIS, CURRENT_BASIS
from app.errors import DomainError


def steel(claim="A", period="2026-11", inc="2004", unit="kg", price="120", line=1):
    return {"claim_id": claim, "item": "001", "period": period, "unit": unit,
            "increment_qty": inc, "unit_price": price, "gross_amount": "0",
            "_line": line, "_sources": [line]}


def mctx(extra=None):
    params = {"measurement": {"current_period": "2026-11",
              "certified_through": {"001": "2026-10", "002": "2026-10"}}}
    if extra:
        params["measurement"].update(extra)
    return {"parameters": params, "quarantine": []}


def test_frozen_month_keeps_previous_factor():
    "TRAP-31 已签证月不得用新系数重算"
    r = evaluate([steel("A", "2026-10", "1000"), steel("B", "2026-11", "2004", line=2)], mctx())
    rows = {x["claim_id"]: x for x in r["rows"]}
    assert rows["A"]["signed_qty"] == "1.000000"
    assert rows["A"]["conversion_basis_id"] == PREVIOUS_BASIS["basis_id"]
    assert rows["A"]["frozen"] is True


def test_current_month_uses_latest_factor():
    "TRAP-32 本月按最新合同系数折吨：2004/1002=2.000000，旧系数会得2.004"
    row = evaluate([steel()], mctx())["rows"][0]
    assert row["signed_qty"] == "2.000000"
    assert row["conversion_basis_id"] == CURRENT_BASIS["basis_id"]
    assert row["factor_kg_per_t"] == "1002.000"
    assert row["ledger_status"] == "current:converted"


def test_no_jump_in_cumulative_chain():
    r = evaluate([steel("A", "2026-09", "1000", line=1),
                  steel("B", "2026-10", "2000", line=2),
                  steel("C", "2026-11", "2004", line=3)], mctx())
    rows = r["rows"]
    assert rows[1]["opening_qty"] == "1.000000"
    assert rows[2]["cumulative_qty_signed"] == "5.000000"
    assert r["metrics"]["frozen_steel_tons"] == "3.000000"
    assert r["metrics"]["current_steel_tons"] == "2.000000"


def test_sealed_certificate_tonnage_and_amount_frozen():
    "TRAP-33 已签证封存记录吨数金额原样保留"
    r = evaluate([steel("A", "2026-10", "2000"), steel("B", "2026-11", "2004", line=2)],
                 mctx({"certified_ledger": {"001": {"2026-10": {
                     "tons": "7.777777", "amount": "9999.99", "factor_kg_per_t": "999",
                     "basis_id": "B-SEALED"}}}}))
    sealed = r["rows"][0]
    assert sealed["signed_qty"] == "7.777777" and sealed["signed_amount"] == "9999.99"
    assert sealed["ledger_status"] == "frozen"


def test_basis_switch_failure_falls_back_to_previous():
    "TRAP-34 依据切换失败保留上一版"
    broken = {"basis_id": "B-BROKEN", "status": "released", "effective_period": "2026-11",
              "factors": {"001": {"kg_per_t": "0", "source": "坏系数"}}}
    r = evaluate([steel()], mctx({"basis": broken}))
    row = r["rows"][0]
    assert row["signed_qty"] == "2.004000"
    assert row["conversion_basis_id"] == PREVIOUS_BASIS["basis_id"]
    assert row["ledger_status"] == "fallback:converted"
    assert r["metrics"]["fallback_records"] == 1 and r["metrics"]["basis_healthy"] is False


def test_both_basis_unavailable_quarantines_row():
    dead = {"basis_id": "X", "status": "draft", "effective_period": "2026-11", "factors": {}}
    old = {"basis_id": "Y", "status": "draft", "effective_period": "2026-01", "factors": {}}
    r = evaluate([steel()], mctx({"basis": dead, "previous_basis": old}))
    assert r["rows"] == [] and r["quarantine"][0]["reason"] == "BASIS_UNAVAILABLE"


def test_ineffective_basis_is_switch_failure():
    future = {"basis_id": "B-FUTURE", "status": "released", "effective_period": "2027-01",
              "factors": {"001": {"kg_per_t": "1010", "source": "未来协议"}}}
    r = evaluate([steel()], mctx({"basis": future}))
    assert r["rows"][0]["conversion_basis_id"] == PREVIOUS_BASIS["basis_id"]
    assert r["metrics"]["fallback_records"] == 1


def test_same_basis_retry_uses_ledger_once():
    "TRAP-35 同一份依据重试不能重复换算"
    context = mctx()
    first = evaluate([steel()], context)
    second = evaluate([steel()], context)
    assert first["metrics"]["converted_now"] == 1
    assert second["metrics"]["converted_now"] == 0 and second["metrics"]["ledger_hits"] == 1
    assert second["rows"][0]["ledger_status"] == "current:reused"
    assert first["rows"][0]["signed_qty"] == second["rows"][0]["signed_qty"]


def test_different_basis_version_recomputes():
    r = evaluate([steel()], mctx({"basis": PREVIOUS_BASIS}))
    assert r["rows"][0]["signed_qty"] == "2.004000"
    assert r["metrics"]["converted_now"] == 1


def test_traceability_fields_and_source_line():
    row = evaluate([steel(line=42)], mctx())["rows"][0]
    assert row["_sources"] == [42]
    assert row["original_unit"] == "kg" and row["original_increment"] == "2004"
    assert row["factor_kg_per_t"] and row["conversion_basis_id"] and row["basis_source"]


def test_native_unit_passthrough_and_separate_accumulation():
    rows = [{"claim_id": "C1", "item": "002", "period": "2026-11", "unit": "m³",
             "increment_qty": "30", "unit_price": "100", "gross_amount": "3000",
             "_line": 1, "_sources": [1]},
            {"claim_id": "C2", "item": "002", "period": "2026-12", "unit": "m³",
             "increment_qty": "20", "unit_price": "100", "gross_amount": "2000",
             "_line": 2, "_sources": [2]}]
    r = evaluate(rows, mctx())
    assert r["rows"][0]["conversion_basis_id"] == "NATIVE" and r["rows"][0]["signed_qty"] == "30"
    assert r["rows"][1]["cumulative_qty_signed"] == "50"
    assert r["metrics"]["concrete_volume"] == "50"


def test_default_anchor_is_previous_month():
    context = {"parameters": {"measurement": {"current_period": "2026-11"}}, "quarantine": []}
    r = evaluate([steel("A", "2026-10", "1000"), steel("B", "2026-11", "2004", line=2)], context)
    assert r["rows"][0]["frozen"] is True and r["rows"][1]["frozen"] is False


def test_unbalanced_upstream_blocks_signoff():
    with pytest.raises(DomainError) as e:
        evaluate([], {"reconcile": {"metrics": {"balanced": False}}})
    assert e.value.code == "UNBALANCED"


def test_signed_amount_quantized_to_cent():
    row = evaluate([steel(inc="1001")], mctx())["rows"][0]  # 1001/1002=0.999001...
    assert Decimal(row["signed_amount"]) == (Decimal(row["signed_qty"]) * Decimal("120")).quantize(Decimal("0.01"))


def test_bad_period_rejected():
    with pytest.raises(DomainError) as e:
        evaluate([], {"parameters": {"measurement": {"current_period": "202611"}}, "quarantine": []})
    assert e.value.code == "BAD_PERIOD"


def test_negative_increment_chain_kept():
    r = evaluate([steel("A", "2026-09", "1000"), steel("B", "2026-11", "-501", line=2)], mctx())
    neg = r["rows"][1]
    assert neg["signed_qty"] == "-0.500000"
    assert neg["opening_qty"] == "1.000000" and neg["cumulative_qty_signed"] == "0.500000"


def test_real_pipeline_eight_stages(result):
    assert len(result["stages"]) == 8
    m8, m6 = result["stages"][7], result["stages"][5]
    assert len(m8["rows"]) == len(m6["rows"])
    assert all(r.get("_sources") for r in m8["rows"])
    for row in m8["rows"]:
        assert Decimal(row["cumulative_qty_signed"]) == Decimal(row["opening_qty"]) + Decimal(row["signed_qty"])

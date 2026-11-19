from decimal import Decimal, ROUND_HALF_UP
from app.values import number, money
from app.reasons import reject
from app.errors import DomainError

# 折吨结果保留6位小数（0.000001 t = 1 g 级），金额仍按分量化
TON_QUANTIZE = Decimal("0.000001")
DEFAULT_CURRENT_PERIOD = "2026-11"
# 内置两份依据：旧系数随历史签证封存，新系数本月合同口径生效；参数可整体替换
PREVIOUS_BASIS = {
    "basis_id": "B-DEFAULT", "status": "released", "effective_period": "2026-01",
    "factors": {"001": {"kg_per_t": "1000.000", "source": "合同默认换算系数（每吨=1000千克）"}},
}
CURRENT_BASIS = {
    "basis_id": "B-2026-11", "status": "released", "effective_period": "2026-11",
    "factors": {"001": {"kg_per_t": "1002.000", "source": "2026-11合同补充协议·钢材检尺换算系数"}},
}
NATIVE_UNIT = {"001": "t", "002": "m³"}
STEEL_ITEMS = {"001"}


def _shift_period(period, delta):
    year, month = int(period[:4]), int(period[5:7])
    total = year * 12 + (month - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _valid_period(period):
    return isinstance(period, str) and len(period) == 7 and period[4] == "-" and period[:4].isdigit() and period[5:].isdigit() and 1 <= int(period[5:7]) <= 12


def _factor(basis, item, current_period):
    """返回 (系数Decimal, 说明)；依据不可用返回 None。只校验不抛异常，交给调用方决定回退或隔离。"""
    if not isinstance(basis, dict) or basis.get("status") != "released":
        return None, "依据未发布"
    effective = str(basis.get("effective_period", ""))
    if not _valid_period(effective) or effective > current_period:
        return None, "依据尚未生效"
    rule = (basis.get("factors") or {}).get(item)
    if not isinstance(rule, dict):
        return None, "清单缺换算条目"
    try:
        factor = number(rule.get("kg_per_t"))
    except DomainError:
        return None, "系数不是合法数字"
    if factor <= 0 or not factor.is_finite():
        return None, "系数必须为正数"
    return factor, rule.get("source", "")


def _config(context):
    params = context.get("parameters", {}) or {}
    cfg = params.get("measurement", {}) or {}
    current_period = str(cfg.get("current_period", DEFAULT_CURRENT_PERIOD))
    if not _valid_period(current_period):
        raise DomainError("BAD_PERIOD", "当前计量周期需为YYYY-MM")
    anchors = cfg.get("certified_through") or {}
    if not isinstance(anchors, dict):
        raise DomainError("BAD_ANCHOR", "签证锚点需要按清单项映射")
    default_anchor = _shift_period(current_period, -1)
    basis = cfg.get("basis", CURRENT_BASIS)
    previous = cfg.get("previous_basis", PREVIOUS_BASIS)
    overrides = cfg.get("unit_overrides", {}) or {}
    sealed = cfg.get("certified_ledger", {}) or {}
    return current_period, anchors, default_anchor, basis, previous, overrides, sealed


def _ledger_key(row, basis_id):
    sources = ",".join(str(x) for x in row.get("_sources", [row.get("_line", 0)]))
    return f"{row.get('claim_id', '')}|{sources}|{basis_id}"


def evaluate(rows, context):
    current_period, anchors, default_anchor, new_basis, old_basis, unit_overrides, sealed_ledger = _config(context)
    # 上游未对平则工作台不得签认，与归档阶段同一道闸
    for stage in context.values():
        if isinstance(stage, dict) and "metrics" in stage and stage["metrics"].get("balanced") is False:
            raise DomainError("UNBALANCED", "来源行未对平，不能签认")
    # 换算台账挂在 context 上：同一来源行+同一依据版本只换算一次，重试直接复用
    ledger = context.setdefault("conversion_ledger", {})
    if not isinstance(ledger, dict):
        raise DomainError("BAD_LEDGER", "换算台账结构无效")

    good, bad = [], []
    accumulator = {}
    converted_now = ledger_hits = native_records = fallback_records = 0
    effective = {}

    for row in sorted(rows, key=lambda x: (str(x.get("item", "")), str(x.get("period", "")), str(x.get("claim_id", "")))):
        item = str(row.get("item", ""))
        period = str(row.get("period", ""))
        if not _valid_period(period):
            bad.append(reject(row, "BAD_PERIOD", "申报周期需为YYYY-MM"))
            continue
        anchor = str(anchors.get(item, default_anchor))
        is_frozen = period <= anchor
        unit = row.get("unit") or unit_overrides.get(row.get("claim_id"), NATIVE_UNIT.get(item, "t"))
        try:
            increment = number(row.get("increment_qty", row.get("cumulative_qty", "0")))
            price = number(row.get("unit_price", "0"))
        except DomainError as e:
            bad.append(reject(row, e.code, e.message))
            continue
        key = (item, unit)
        opening = accumulator.get(key, Decimal("0"))

        record = {**row, "original_unit": unit, "original_increment": str(increment),
                  "anchor_period": anchor, "frozen": is_frozen,
                  "opening_qty": str(opening), "factor_kg_per_t": "",
                  "conversion_basis_id": "", "basis_source": "",
                  "ledger_status": "", "signed_qty": "", "cumulative_qty_signed": "",
                  "signed_amount": ""}

        sealed = (sealed_ledger.get(item) or {}).get(period) if is_frozen else None
        if sealed is not None:
            # 审计锚点：已签证吨数与金额原样沿用，任何系数都不得重算
            if not isinstance(sealed, dict) or "tons" not in sealed:
                bad.append(reject(row, "BAD_ANCHOR", "封存台账缺少吨数字段"))
                continue
            try:
                signed = number(sealed["tons"])
                sealed_amount = money(sealed["amount"]) if sealed.get("amount") not in (None, "") else money(signed * price)
            except DomainError as e:
                bad.append(reject(row, e.code, f"封存台账数值无效：{e.message}"))
                continue
            record.update(factor_kg_per_t=str(sealed.get("factor_kg_per_t", "")),
                          conversion_basis_id=str(sealed.get("basis_id", "SEALED")),
                          basis_source="已签证封存记录", ledger_status="frozen",
                          signed_qty=str(signed), signed_amount=sealed_amount)
        elif is_frozen:
            # 冻结月：即便新依据已发布，也只允许按上一版系数推导，保证累计链不跳量
            if item in STEEL_ITEMS and unit == "kg":
                old_factor, old_note = _factor(old_basis, item, current_period)
                if old_factor is None:
                    bad.append(reject(row, "BASIS_UNAVAILABLE", f"冻结月缺上一版依据：{old_note}"))
                    continue
                signed = (increment / old_factor).quantize(TON_QUANTIZE, rounding=ROUND_HALF_UP)
                record.update(factor_kg_per_t=str(old_factor), conversion_basis_id=str(old_basis.get("basis_id")),
                              basis_source=f"冻结月沿用上一版（{old_note}）" if old_note else "冻结月沿用上一版",
                              ledger_status="frozen", signed_qty=str(signed),
                              signed_amount=money(signed * price))
            else:
                try:
                    native_amount = money(row["gross_amount"]) if row.get("gross_amount") not in (None, "") else money(increment * price)
                except DomainError as e:
                    bad.append(reject(row, e.code, f"原生计量金额无效：{e.message}"))
                    continue
                record.update(conversion_basis_id="NATIVE", basis_source="原生计量单位，无需换算",
                              ledger_status="frozen", signed_qty=str(increment),
                              signed_amount=native_amount)
        else:
            # 本月新增量：原生计量（t/m³）不经系数，直接签认；仅kg钢材需要选依据
            if not (item in STEEL_ITEMS and unit == "kg"):
                native_records += 1
                try:
                    native_amount = money(row["gross_amount"]) if row.get("gross_amount") not in (None, "") else money(increment * price)
                except DomainError as e:
                    bad.append(reject(row, e.code, f"原生计量金额无效：{e.message}"))
                    continue
                record.update(conversion_basis_id="NATIVE",
                              basis_source="原生计量单位，无需换算", ledger_status="current",
                              signed_qty=str(increment),
                              signed_amount=native_amount)
            else:
                # 优先用最新依据，切换失败回退上一版并留痕
                factor, note = _factor(new_basis, item, current_period)
                basis_used, basis_status = new_basis, "current"
                if factor is None:
                    factor, old_note = _factor(old_basis, item, current_period)
                    if factor is None:
                        bad.append(reject(row, "BASIS_UNAVAILABLE", f"新旧依据均不可用：{note}/{old_note}"))
                        continue
                    basis_used, basis_status = old_basis, "fallback"
                    fallback_records += 1
                effective[item] = (basis_status, str(basis_used.get("basis_id")))
                cache_key = _ledger_key(row, str(basis_used.get("basis_id")))
                cached = ledger.get(cache_key)
                if cached is not None:
                    # 同一份依据重试：复用首次换算结果，不做第二次除法
                    signed = number(cached)
                    ledger_hits += 1
                    record["ledger_status"] = f"{basis_status}:reused"
                else:
                    signed = (increment / factor).quantize(TON_QUANTIZE, rounding=ROUND_HALF_UP)
                    ledger[cache_key] = str(signed)
                    converted_now += 1
                    record["ledger_status"] = f"{basis_status}:converted"
                record.update(factor_kg_per_t=str(factor), conversion_basis_id=str(basis_used.get("basis_id")),
                              basis_source=note or str((basis_used.get("factors") or {}).get(item, {}).get("source", "")),
                              signed_qty=str(signed), signed_amount=money(signed * price))

        cumulative = opening + number(record["signed_qty"])
        accumulator[key] = cumulative
        record["cumulative_qty_signed"] = str(cumulative)
        good.append(record)

    steel = [r for r in good if r["item"] in STEEL_ITEMS]
    concrete = [r for r in good if r["item"] not in STEEL_ITEMS]
    frozen_rows = [r for r in good if r["frozen"]]
    current_rows = [r for r in good if not r["frozen"]]
    metrics = {
        "records": len(good),
        "quarantine": len(bad),
        "current_period": current_period,
        "frozen_records": len(frozen_rows),
        "current_records": len(current_rows),
        "converted_now": converted_now,
        "ledger_hits": ledger_hits,
        "native_records": native_records,
        "fallback_records": fallback_records,
        "basis_selection": {item: f"{status}:{basis_id}" for item, (status, basis_id) in effective.items()},
        "frozen_steel_tons": str(sum((number(r["signed_qty"]) for r in steel if r["frozen"]), Decimal(0))),
        "current_steel_tons": str(sum((number(r["signed_qty"]) for r in steel if not r["frozen"]), Decimal(0))),
        "concrete_volume": str(sum((number(r["signed_qty"]) for r in concrete), Decimal(0))),
        "frozen_amount_total": money(sum((number(r["signed_amount"]) for r in frozen_rows), Decimal(0))),
        "current_amount_total": money(sum((number(r["signed_amount"]) for r in current_rows), Decimal(0))),
        "basis_healthy": fallback_records == 0 and not any(x["reason"] == "BASIS_UNAVAILABLE" for x in bad),
    }
    return {"rows": good, "quarantine": bad, "metrics": metrics}

# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

M8 计量工作台入口`/api/measurement`、页面`/measurement`。参数经`parameters.measurement`传入：`current_period`（YYYY-MM，默认2026-11）、`certified_through`（按清单项的签证锚点月，缺省取当前月上月）、`basis`/`previous_basis`（含basis_id、status、effective_period、factors.<item>.kg_per_t的换算依据）、`certified_ledger`（已签证封存吨数与金额）、`unit_overrides`（按申报编号指定原单位）。依据回退与台账复用均在metrics的`fallback_records`、`converted_now`、`ledger_hits`、`basis_selection`中留痕。

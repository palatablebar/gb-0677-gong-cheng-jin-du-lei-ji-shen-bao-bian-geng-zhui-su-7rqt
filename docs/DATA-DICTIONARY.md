# 计量定义

claim_id唯一；item为清单编码，支持钢筋与001等别名。period为YYYY-MM。累计数量按t或m³保存，当前周期工程量=本次累计-前期已审累计。previous_revisions参数可指定更正后的前审数量，重新计算形成不同批次，不覆盖旧证据。

C0原始价100元，C1自2026-11生效为120元，DRAFT未批准不可结算。负进度必须reversal=approved作为已批冲回标记。扣留质保金5%、预付款扣回10%分别按分量化，净额=本期总额-质保金-预付款扣回，负进度同步冲回扣留。reported为原申报净额，差异=复算净额-reported。

业务ID和超大整数按文本保形；Decimal参与数量金额计算，对外序列化为字符串。哨兵集合定义在app/values.py，缺失值不能当零。所有时间带UTC偏移，先转UTC比较，业务日按指定地区划分。区间统一[start,end)。重复业务键保留第一条、完全相同行计重复；值冲突行隔离且保留原值。空文件、全空白、仅表头分开拒绝。

## 计量工作台（M8）本月签认量

钢材申报可同时出现吨(t)与千克(kg)，换算系数`kg_per_t`按月调整。M8逐计量项输出原单位`original_unit`、原计量量`original_increment`、换算系数`factor_kg_per_t`、依据编号`conversion_basis_id`与依据说明`basis_source`，并保留`_sources`回到对应申报行。kg折吨公式：`签认吨数=原千克量/kg_per_t`，按0.000001吨HALF_UP量化；原生t与m³直计不换算。

已签证月份按`certified_through`锚点（可按清单项分别配置，默认当前月上月）冻结：锚点月及之前只允许沿用上一版依据`previous_basis`，或直接采用`certified_ledger`封存的吨数与金额，任何新系数都不重算历史链；锚点之后的本月新增量才采用最新依据`basis`。累计签认量`cumulative_qty_signed`逐行承接`opening_qty`，冻结段与新增段同链衔接，避免系数切换造成前后月跳量。

依据切换失败（未发布、未生效、缺条目、系数非正）时回退上一版依据并将`ledger_status`标记为fallback、计入`fallback_records`；新旧依据均不可用则隔离`BASIS_UNAVAILABLE`，不产出签认行。换算台账挂在运行上下文，键为`申报编号+来源行+依据版本`：同一依据重试命中台账直接复用首次折吨结果（`ledger_hits`），不做第二次除法；依据版本变化则重新换算（`converted_now`）。金额统一按分量化，`signed_amount=签认量×单价`。

运行清单包括输入sha256、规则版本、参数、生成时刻与耗时。源行编号以CSV解析器的物理结束行号表示，引号内换行不增加记录数。输入超过4MB返回413，非法表头和类型返回422，失效版本复核返回409。
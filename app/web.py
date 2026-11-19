from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        stage=run["stages"][index]
        rows=stage["rows"]
        columns=[['claim_id', 'item', 'period', 'cumulative_qty', 'previous_qty', 'change_id', 'reported'], ['claim_id', 'item', 'unit', 'cumulative_qty', 'previous_qty'], ['claim_id', 'period', 'approved_change', 'unit_price'], ['claim_id', 'period', 'cumulative_qty', 'approved_previous', 'increment_qty', 'gross_amount'], ['claim_id', 'item', 'gross_amount', 'retention', 'advance_recovery', 'expected'], ['claim_id', 'item', 'expected', 'reported', 'difference', 'status'], ['claim_id', 'period', 'expected', 'status'], ['claim_id', 'period', 'frozen', 'original_unit', 'original_increment', 'factor_kg_per_t', 'conversion_basis_id', 'signed_qty', 'cumulative_qty_signed', 'signed_amount', 'ledger_status']][index]
        labels={'claim_id': '申报编号', 'item': '清单项', 'period': '申报周期', 'cumulative_qty': '本次累计量', 'previous_qty': '前审累计量', 'change_id': '变更单', 'reported': '申报净额', 'unit': '单位', 'approved_change': '已批变更', 'unit_price': '单价 / 元', 'approved_previous': '修订前审量', 'increment_qty': '本期工程量', 'gross_amount': '本期总额', 'retention': '质保金', 'advance_recovery': '预付款扣回', 'expected': '实算净额', 'difference': '净额差异', 'status': '结论', 'gross_total': '本期总额合计', 'net_total': '实算净额合计', 'frozen': '冻结月', 'original_unit': '原单位', 'original_increment': '原计量量', 'factor_kg_per_t': '换算系数 kg/t', 'conversion_basis_id': '换算依据', 'basis_source': '依据说明', 'signed_qty': '本期签认量(t/m³)', 'cumulative_qty_signed': '累计签认量', 'signed_amount': '签认金额', 'ledger_status': '台账状态', 'anchor_period': '签证锚点', 'opening_qty': '期初量'}
        for key,label in {'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'differences': '差异项', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'sha256': '校验摘要', 'ready': '可归档', 'records': '签认记录', 'current_period': '计量周期', 'frozen_records': '冻结月记录', 'current_records': '本月记录', 'converted_now': '本次换算', 'ledger_hits': '台账复用', 'native_records': '原生计量', 'fallback_records': '依据回退', 'basis_healthy': '依据健康', 'frozen_steel_tons': '冻结钢材吨数', 'current_steel_tons': '本月钢材吨数', 'concrete_volume': '混凝土方量', 'frozen_amount_total': '冻结金额合计', 'current_amount_total': '本月金额合计'}.items(): labels.setdefault(key,label)
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,columns=columns[:12],history=store.history(),labels=labels)
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))

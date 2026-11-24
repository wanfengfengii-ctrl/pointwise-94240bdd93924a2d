# 二号涂布线振动原样采集站

班长冻结当班探头规程。采集员接收上游的有序原页，将合格页写入双槽设备。值班员从当前页选择需要复查的测段，质控员逐块续领并核账，次班按回执号复查固定正文。设备循环写入时，仍有读票承诺的旧样占用站端有限备存。

## 运行

需要 Python 3.11，使用标准库。项目根目录运行完整回归和演示。

```text
python3 -B check_project.py
python3 -B demo.py
```

回归入口由运行平台提供。演示使用独立临时数据库，展示采入、待采、成功消费后的重投、原位续领及重开后的历史领取。

## Python 接口

```python
from decimal import Decimal
from station.api import Station
from station.samples import SampleRule

rule = SampleRule(Decimal('-100'), Decimal('100'), 0, -9999)
with Station(':memory:') as station:
    station.start_shift('day', 'line-2', 4, 'μm', rule)
    captured = station.capture_page('day', 'μm', enumerate([-9999, 0, -9, 4]))
    ticket = station.open_ticket(captured.version.page, 0, 4)
    first = station.read_next(ticket.ticket_id, 2)
    second = station.read_next(ticket.ticket_id, 2)
    receipt = station.finish_review(ticket.ticket_id)
    assert station.get_receipt(receipt.receipt_id) == receipt
```

- `Station(path, spill_capacity=4)` 打开并初始化本地数据库，投产配置的备存容量固定。两槽按 0、1 的顺序循环。重开既有库使用同一容量。`initialize()` 可重复调用，保留用户已录入的配置与业务记录。`register_probe(profile)` 保存探头登记或修改，其合法范围供后续新班次使用。缺省探头为 `line-2`。
- `start_shift(shift_id, probe_id, page_length, unit, rule)` 返回冻结快照。同配置复投返回原快照。无效探头、规程或同号冲突抛出 `ValueError`。探头后来修改时，已冻结快照继续使用原口径。
- `capture_page(shift_id, unit, samples)` 接受从零开始连续且有序的 `(原位, 原值)`。单位与冻结规程完全一致。原值为整数或固定十进制字符串。有效值须满足冻结范围和小数位数，缺测以同类型同编码识别。字符串原值保留原拼写。成功结果为 `captured`，含 `version`，其中 `page` 是本站唯一原页身份。`pending` 表示容量不足，请重投同一页。`device_failed` 表示整页拒写，可以原槽重投。非法请求抛出 `ValueError`。保全端的原件读取异常抛出 `SourceReadError`，保持原槽和待采状态。
- `open_ticket(page, start, stop)` 为当前页的非空半开区间开票。非法区间抛出 `ValueError`，非当前页抛出 `LookupError`。
- `read_next(ticket_id, max_samples)` 要求正整数上限，返回固定票段中的下一个块。`sample.position.page`、`sample.position.index` 和 `sample.value.token` 分别给出原页、原位和原值。已读完返回空块。未知票抛出 `LookupError`，非法上限抛出 `ValueError`，读取失败抛出 `SourceReadError` 并保留进度。
- `finish_review(ticket_id)` 核对完票覆盖并返回固定回执。未完成抛出 `IncompleteTicketError`。回执含原页原位、单位、有效数、缺测数及有效值最大绝对值，全缺测时峰值为 `None`。`get_receipt(receipt_id)` 按号读取；未知号抛出 `LookupError`。再次签报返回该票原回执。

## 提交边界

设备仅保留当前槽代次。接管按原页原位保全下一槽中仍有义务的样本。多票共享同一原位时只占一格。暂存、覆盖和下一槽推进同次提交。待采请求只存元数据及输入指纹，由上游重投原页。

续领成功才提交块凭证和游标。共享位置由最后一个未读持有者成功消费后释放。历史块凭证只保留覆盖、计数和峰值，固定回执也只保存核账正文及出处。存储在单进程模拟站内，定位于当班原样交付与历史核账。

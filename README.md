# 金融研报 Agent

覆盖全部 A 股（5000+）和支付宝/天天基金公募基金（10000+）的智能分析工具。

## 功能

- 股票分析：实时行情、K线走势、技术面分析
- 基金分析：实时估值、净值走势、基金详情
- 支持 QDII 海外基金（纳斯达克、标普500 等）

## 运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 技术栈

- Streamlit（网页界面）
- DeepSeek V4（Agent 推理）
- 东方财富 / 新浪财经 / 天天基金（金融数据）

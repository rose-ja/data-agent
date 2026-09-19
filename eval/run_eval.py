"""
问数 Agent 端到端评估运行器

对评估集（eval/dataset.jsonl）中的每个自然语言问题执行一次完整 Agent 工作流，
把最终 SQL 在真实数仓上的执行结果与黄金 SQL 的结果做行级比对，
输出 JSON 明细与 Markdown 摘要，用于度量端到端问数准确率并支撑调参对比实验。

用法：
    python eval/run_eval.py --label threshold-0.8
    python eval/run_eval.py --label threshold-0.6 --first 3   # 冒烟子集
阈值等环境变量（QDRANT_SCORE_THRESHOLD 等）在进程启动前设置即可生效。
"""

import argparse
import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.conf.app_config import app_config
from app.core.log import logger
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_FILE = PROJECT_ROOT / "eval" / "dataset.jsonl"
RESULT_DIR = PROJECT_ROOT / "eval" / "results"
# 单题全链路超时：LLM 多轮调用偶发抖动时不允许拖死整个评估批次
CASE_TIMEOUT_SECONDS = 300


def load_dataset(path: Path) -> list[dict]:
    """读取评估集，校验必填字段与 ID 唯一性，避免脏数据静默通过"""
    if not path.is_file():
        raise FileNotFoundError(f"评估集不存在：{path}")

    cases: list[dict] = []
    seen_ids: set[int] = set()
    with path.open(encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue
            case = json.loads(text)
            missing = {"id", "category", "query", "gold_sql", "ordered"} - case.keys()
            if missing:
                raise ValueError(f"第 {line_no} 行缺少字段：{missing}")
            if case["id"] in seen_ids:
                raise ValueError(f"第 {line_no} 行 ID 重复：{case['id']}")
            seen_ids.add(case["id"])
            cases.append(case)

    if not cases:
        raise ValueError("评估集为空")
    return cases


def normalize_value(value) -> str:
    """把单元格值归一化成可比较字符串：浮点按 2 位小数容忍误差"""
    if isinstance(value, (float, Decimal)):
        return f"{round(float(value), 2):.2f}"
    return str(value)


def normalize_rows(rows: list[dict]) -> list[tuple[str, ...]]:
    """行字典转位置元组：按列顺序比较，聚合值与维度值都参与等值判定"""
    return [tuple(normalize_value(value) for value in row.values()) for row in rows]


def compare_rows(gold_rows: list[tuple], actual_rows: list[tuple], ordered: bool) -> bool:
    """结果比对：TopN 类按行序严格比较，其余按多重集合比较（与输出顺序无关）"""
    if ordered:
        return gold_rows == actual_rows
    return sorted(gold_rows) == sorted(actual_rows)


def build_case_context(meta_session, dw_session) -> DataAgentContext:
    """为单条评估用例组装独立的仓储与客户端上下文，保证并发用例互不共享会话"""
    return DataAgentContext(
        column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client),
        embedding_client=embedding_client_manager.client,
        metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client),
        value_es_repository=ValueESRepository(es_client_manager.client),
        meta_mysql_repository=MetaMySQLRepository(meta_session),
        dw_mysql_repository=DWMySQLRepository(dw_session),
    )


async def run_single_case(case: dict) -> dict:
    """执行单条用例：跑一次 Agent 工作流，同时执行黄金 SQL 并比较结果"""
    record = {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "passed": False,
        "reason": "",
        "generated_sql": "",
        "gold_sql": case["gold_sql"],
        "gold_rows": [],
        "actual_rows": [],
    }

    # 每个用例独立开会话：AsyncSession 不能并发复用，用完即释放
    async with (
        meta_mysql_client_manager.session_factory() as meta_session,
        dw_mysql_client_manager.session_factory() as dw_session,
    ):
        gold_rows = normalize_rows(await DWMySQLRepository(dw_session).run(case["gold_sql"]))
        record["gold_rows"] = [list(row) for row in gold_rows]

        state = DataAgentState(query=case["query"])
        context = build_case_context(meta_session, dw_session)

        result_event = None
        last_error = ""
        final_state: dict = {}

        # custom 拿节点流式事件（含最终 result / error），values 拿每个超步后的完整状态
        async for mode, chunk in graph.astream(
            input=state, context=context, stream_mode=["custom", "values"]
        ):
            if mode == "custom" and isinstance(chunk, dict):
                if chunk.get("type") == "result":
                    result_event = chunk
                elif chunk.get("type") == "error":
                    last_error = str(chunk.get("message", "")) or last_error
            elif mode == "values" and isinstance(chunk, dict):
                final_state = chunk

        record["generated_sql"] = str(final_state.get("sql", "")).strip()

        if result_event is None:
            record["reason"] = last_error or "工作流未产出查询结果"
            return record

        actual_rows = normalize_rows(result_event.get("data", []))
        record["actual_rows"] = [list(row) for row in actual_rows]
        record["passed"] = compare_rows(gold_rows, actual_rows, case["ordered"])
        if not record["passed"]:
            record["reason"] = "结果与黄金 SQL 不一致"
    return record


async def run_eval(label: str, concurrency: int, first_n: int | None) -> None:
    """加载评估集并按固定并发跑完全部用例，落盘 JSON 明细与 Markdown 摘要"""
    cases = load_dataset(DATASET_FILE)
    if first_n:
        cases = cases[:first_n]

    # 客户端管理器全局只初始化一次，用例内部复用连接池
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()

    started_at = time.time()
    records: list[dict] = []

    # 信号量控制并发，避免超出 LLM / Embedding 服务的速率限制
    semaphore = asyncio.Semaphore(concurrency)

    async def run_with_limits(case: dict) -> dict:
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    run_single_case(case), timeout=CASE_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                return {
                    **case,
                    "passed": False,
                    "reason": f"单题超时（>{CASE_TIMEOUT_SECONDS}s）",
                    "generated_sql": "",
                    "gold_rows": [],
                    "actual_rows": [],
                }
            except Exception as exc:  # 单题异常不中断整批评估
                logger.error(f"用例 {case['id']} 执行异常：{exc}")
                return {
                    **case,
                    "passed": False,
                    "reason": f"执行异常：{exc}",
                    "generated_sql": "",
                    "gold_rows": [],
                    "actual_rows": [],
                }

    records = await asyncio.gather(*(run_with_limits(case) for case in cases))
    elapsed = round(time.time() - started_at, 1)

    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
    await qdrant_client_manager.close()
    await es_client_manager.close()

    passed_count = sum(1 for record in records if record["passed"])
    report = {
        "label": label,
        "model": app_config.llm.model_name,
        "qdrant_score_threshold": app_config.qdrant.score_threshold,
        "passed": passed_count,
        "total": len(records),
        "accuracy": round(passed_count / len(records), 4),
        "elapsed_seconds": elapsed,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cases": records,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULT_DIR / f"report_{label}.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    markdown_lines = [
        f"# 评估结果：{label}",
        "",
        f"- 模型：`{report['model']}`，向量召回阈值：`{report['qdrant_score_threshold']}`",
        f"- 准确率：**{passed_count}/{len(records)}**（{report['accuracy']:.1%}），耗时 {elapsed}s",
        "",
        "| ID | 类别 | 问题 | 结果 | 失败原因 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in records:
        result = "✅" if record["passed"] else "❌"
        reason = record.get("reason", "") or ""
        markdown_lines.append(
            f"| {record['id']} | {record['category']} | {record['query']} | {result} | {reason} |"
        )
    markdown_path = RESULT_DIR / f"summary_{label}.md"
    markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    print(f"[eval] 准确率 {passed_count}/{len(records)}（{report['accuracy']:.1%}），耗时 {elapsed}s")
    print(f"[eval] 明细：{json_path}")
    print(f"[eval] 摘要：{markdown_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="问数 Agent 端到端评估")
    parser.add_argument("--label", required=True, help="本次评估标签，用于结果文件命名")
    parser.add_argument("--concurrency", type=int, default=3, help="并发执行的用例数")
    parser.add_argument("--first", type=int, default=None, help="只跑前 N 条（冒烟测试用）")
    args = parser.parse_args()

    if args.concurrency < 1:
        raise SystemExit("--concurrency 必须为正整数")
    asyncio.run(run_eval(args.label, args.concurrency, args.first))

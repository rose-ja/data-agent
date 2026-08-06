# app/services/sql_guard.py（新增）
import re

class SQLGuard:
    """SQL 执行前的安全校验"""

    # 1. 语句类型白名单：只允许单条 SELECT
    FORBIDDEN_PREFIX = ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
                        "ALTER", "TRUNCATE", "GRANT", "REVOKE")

    # 2. 危险关键字黑名单
    FORBIDDEN_KEYWORDS = ("INTO OUTFILE", "LOAD_FILE", "SLEEP(", "BENCHMARK(",
                          "INFORMATION_SCHEMA")

    # 3. 表名白名单：只允许元数据库里登记过的表
    ALLOWED_TABLES = {"fact_order", "dim_region", "dim_customer",
                      "dim_product", "dim_date"}

    @classmethod
    def check(cls, sql: str) -> str | None:
        """校验通过返回 None，否则返回错误信息"""
        stripped = sql.strip()
        # 检查多条语句（分号后还有内容）
        if stripped.count(";") > 1 and not stripped.rstrip().endswith(";"):
            return "不允许执行多条 SQL"
        # 检查语句前缀
        upper = stripped.upper()
        if any(upper.startswith(p) for p in cls.FORBIDDEN_PREFIX):
            return f"禁止执行 {upper.split()[0]} 操作"
        # 检查危险关键字
        for kw in cls.FORBIDDEN_KEYWORDS:
            if kw in upper:
                return f"包含危险关键字 {kw}"
        # 提取表名做白名单校验（简化版：匹配 FROM/JOIN 后的标识符）
        tables = set(re.findall(r"(?:FROM|JOIN)\s+([a-z_0-9]+)", upper, re.IGNORECASE))
        for t in tables:
            if t not in cls.ALLOWED_TABLES:
                return f"表 {t} 不在白名单中"
        return None
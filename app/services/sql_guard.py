"""SQL 执行前的结构化安全校验。"""

from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.api.errors import ErrorCode


@dataclass(frozen=True, slots=True)
class SQLGuardViolation:
    """SQL 策略拒绝结果，供 SSE 和日志使用稳定错误码。"""

    code: ErrorCode
    message: str

    def __str__(self) -> str:
        return self.message


class SQLGuard:
    """使用 SQL AST 执行保守的只读查询策略。"""

    ALLOWED_TABLES = frozenset(
        {"fact_order", "dim_region", "dim_customer", "dim_product", "dim_date"}
    )
    FORBIDDEN_FUNCTIONS = frozenset(
        {"SLEEP", "BENCHMARK", "LOAD_FILE", "UUID", "UUID_SHORT"}
    )
    MAX_LIMIT = 1000

    @classmethod
    def check(cls, sql: str) -> SQLGuardViolation | None:
        """校验 SQL；通过返回 None，拒绝返回带错误码的结果。"""

        if not isinstance(sql, str) or not sql.strip():
            return SQLGuardViolation(ErrorCode.SQL_VALIDATION_FAILED, "SQL 不能为空")

        try:
            statements = parse(sql, read="mysql")
        except ParseError:
            return SQLGuardViolation(ErrorCode.SQL_VALIDATION_FAILED, "SQL 解析失败")

        if len(statements) != 1:
            return SQLGuardViolation(ErrorCode.SQL_FORBIDDEN, "不允许执行多条 SQL")

        statement = statements[0]
        if not isinstance(statement, exp.Select):
            return SQLGuardViolation(
                ErrorCode.SQL_FORBIDDEN, "只允许执行单条 SELECT 查询"
            )

        tables = {table.name.lower() for table in statement.find_all(exp.Table)}
        unauthorized = tables - cls.ALLOWED_TABLES
        if unauthorized:
            table_name = sorted(unauthorized)[0]
            return SQLGuardViolation(
                ErrorCode.SQL_TABLE_NOT_ALLOWED, f"表 {table_name} 不在白名单中"
            )

        # MySQL 方言中的部分函数会被解析为 Anonymous，二者都必须检查。
        functions = [*statement.find_all(exp.Func), *statement.find_all(exp.Anonymous)]
        for function in functions:
            function_name = (
                str(function.this).upper()
                if isinstance(function, exp.Anonymous)
                else function.sql_name().upper()
            )
            if function_name in cls.FORBIDDEN_FUNCTIONS:
                return SQLGuardViolation(
                    ErrorCode.SQL_FORBIDDEN, f"禁止使用危险函数 {function_name}"
                )

        limit = statement.args.get("limit")
        if limit is None:
            return SQLGuardViolation(
                ErrorCode.SQL_LIMIT_REQUIRED,
                f"查询必须包含 LIMIT，最大允许 {cls.MAX_LIMIT} 行",
            )

        limit_expression = limit.args.get("expression")
        if not isinstance(limit_expression, exp.Literal) or not limit_expression.is_int:
            return SQLGuardViolation(
                ErrorCode.SQL_RESOURCE_LIMIT_EXCEEDED, "LIMIT 必须是正整数常量"
            )

        limit_value = int(limit_expression.this)
        if not 1 <= limit_value <= cls.MAX_LIMIT:
            return SQLGuardViolation(
                ErrorCode.SQL_RESOURCE_LIMIT_EXCEEDED,
                f"LIMIT 必须位于 1-{cls.MAX_LIMIT} 之间",
            )

        return None

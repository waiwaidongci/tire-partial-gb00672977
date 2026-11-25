"""Rank-based screening of tread loss in a single fleet observation window."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import groupby
from math import fsum, isfinite, sqrt
from random import Random


FACTORS = {"低胎压检测占比": "low_pressure_pct", "急制动频次": "hard_brakes_per_1000km"}
CONTROL_SETS = {
    "里程＋胎龄": ("mileage_km", "tire_age_days"),
    "里程＋线路载荷": ("mileage_km", "route_load_pct"),
    "里程＋胎龄＋线路载荷": ("mileage_km", "tire_age_days", "route_load_pct"),
}
LABELS = {
    "mileage_km": "窗口里程",
    "tire_age_days": "期初胎龄",
    "route_load_pct": "线路载荷率",
    "tread_loss_mm": "胎纹磨耗",
}
DEFAULT_FACTOR = "低胎压检测占比"
DEFAULT_CONTROLS = "里程＋胎龄"
MIN_FLEET_ROWS = 12
MIN_ROUTE_ROWS = 8
VIF_LIMIT = 10.0
RESIDUAL_SHARE_LIMIT = 0.05
DIRECTION_FLOOR = 0.15
MAGNITUDE_DROP = 0.20
# The projection uses unit-length columns, so these tolerances are scale independent.
DEPENDENCE_TOLERANCE = 1e-10


@dataclass
class Analysis:
    n: int
    crude: float | None
    tied_pct: float
    adjusted: float | None = None
    vif: float | None = None
    factor_share: float | None = None
    wear_share: float | None = None
    diagnostic: str = ""
    usable: bool = False


def _dot(left: list[float], right: list[float]) -> float:
    return fsum(a * b for a, b in zip(left, right))


def _rank_column(values: list[float]) -> tuple[list[float], float]:
    """Return centered average ranks at unit length and the share in tie groups."""
    n = len(values)
    ranks = [0.0] * n
    start = tied = 0
    for _, indices in groupby(sorted(range(n), key=values.__getitem__), key=values.__getitem__):
        members = list(indices)
        count = len(members)
        centered_midrank = start + (count - n) / 2
        for index in members:
            ranks[index] = centered_midrank
        if count > 1:
            tied += count
        start += count
    length = sqrt(_dot(ranks, ranks))
    if length:
        ranks = [rank / length for rank in ranks]
    return ranks, 100 * tied / n


def _residual(vector: list[float], basis: list[list[float]]) -> list[float]:
    remaining = vector.copy()
    # Modified Gram–Schmidt projection keeps nearly aligned controls diagnosable.
    for direction in basis:
        coefficient = _dot(remaining, direction)
        remaining = [value - coefficient * entry for value, entry in zip(remaining, direction)]
    return remaining


def _basis(columns: list[list[float]]) -> list[list[float]]:
    basis = []
    for column in columns:
        remaining = _residual(column, basis)
        length = sqrt(_dot(remaining, remaining))
        if length <= DEPENDENCE_TOLERANCE:
            break
        basis.append([value / length for value in remaining])
    return basis


def _coefficient(value: float) -> float:
    return 0.0 if abs(value) < 1e-12 else max(-1.0, min(1.0, value))


def _analyze(rows: list[dict], factor: str, controls: tuple[str, ...], minimum: int) -> Analysis:
    factor_rank, factor_ties = _rank_column([row[factor] for row in rows])
    wear_rank, wear_ties = _rank_column([row["tread_loss_mm"] for row in rows])
    n = len(rows)
    varying = any(factor_rank) and any(wear_rank)
    crude = _coefficient(_dot(factor_rank, wear_rank)) if varying and n >= 3 else None
    result = Analysis(n, crude, max(factor_ties, wear_ties))
    if n < minimum:
        result.diagnostic = f"样本不足（{n}/{minimum} 条）"
        return result
    if not varying:
        result.diagnostic = "待查指标无秩变异" if not any(factor_rank) else "胎纹磨耗无秩变异"
        return result

    control_ranks = [_rank_column([row[key] for row in rows])[0] for key in controls]
    constant_controls = [LABELS[key] for key, column in zip(controls, control_ranks) if not any(column)]
    if constant_controls:
        result.diagnostic = f"控制项无秩变异（{'、'.join(constant_controls)}）"
        return result
    basis = _basis(control_ranks)
    if len(basis) < len(controls):
        result.diagnostic = "控制项秩共线，无法按所选口径拟合"
        return result

    # 1 / (1 - R²) for each ranked control regressed on the other controls.
    vifs = []
    for index, column in enumerate(control_ranks):
        other_basis = _basis(control_ranks[:index] + control_ranks[index + 1 :])
        remaining = _residual(column, other_basis)
        vifs.append(1 / max(_dot(remaining, remaining), DEPENDENCE_TOLERANCE**2))
    result.vif = max(vifs)
    factor_residuals = _residual(factor_rank, basis)
    wear_residuals = _residual(wear_rank, basis)
    result.factor_share = _dot(factor_residuals, factor_residuals)
    result.wear_share = _dot(wear_residuals, wear_residuals)
    if min(result.factor_share, result.wear_share) <= DEPENDENCE_TOLERANCE**2:
        result.diagnostic = "待查指标或磨耗的秩残差为零"
        return result

    result.adjusted = _coefficient(
        _dot(factor_residuals, wear_residuals) / sqrt(result.factor_share * result.wear_share)
    )
    diagnostics = []
    if result.vif >= VIF_LIMIT:
        diagnostics.append("控制项高度共线")
    if min(result.factor_share, result.wear_share) < RESIDUAL_SHARE_LIMIT:
        diagnostics.append("秩残差变异不足")
    result.usable = not diagnostics
    if result.tied_pct >= 50:
        diagnostics.append("待查指标或磨耗并列偏多")
    result.diagnostic = "；".join(diagnostics) or "通过"
    return result


def _opposite(left: float, right: float) -> bool:
    return left * right < 0 and min(abs(left), abs(right)) >= DIRECTION_FLOOR


def _review(result: Analysis, factor_name: str, threshold: float) -> tuple[str, str]:
    if not result.usable or result.adjusted is None or result.crude is None:
        return "补数复核", "核对诊断后补齐同窗口记录，或另跑经业务确认的控制口径。"
    adjusted, crude = result.adjusted, result.crude
    if _opposite(crude, adjusted):
        return "方向反转", "按相近里程和控制条件抽查台账，核对粗相关与控制后方向为何不同。"
    if abs(adjusted) >= threshold:
        action = (
            "抽核冷态胎压巡检和补气记录，安排同条件轮胎复测。"
            if factor_name == DEFAULT_FACTOR
            else "抽核车载急制动记录和线路工况，安排同条件轮胎复测。"
        )
        return "控制后仍达复核线", action
    if abs(crude) >= threshold and abs(crude) - abs(adjusted) >= MAGNITUDE_DROP:
        return "控制后衰减", "按所选控制项分层抽查，暂不以待查指标单独安排专项点检。"
    return "例行观察", "随下一轮胎纹盘点更新，保留同一控制口径作对照。"


def _display(value: float | None, digits: int = 4) -> float | str:
    return "—" if value is None else round(value, digits)


def _percent(share: float | None) -> float | str:
    return _display(100 * share, 1) if share is not None else "—"


def _report_row(name: str, result: Analysis, flag: str, action: str) -> dict:
    delta = None if result.adjusted is None or result.crude is None else result.adjusted - result.crude
    return {
        "线路范围": name,
        "轮胎数": result.n,
        "粗 Spearman": _display(result.crude),
        "偏秩相关": _display(result.adjusted),
        "变化值（偏秩减粗）": _display(delta),
        "指标或磨耗最大并列占比（%）": round(result.tied_pct, 1),
        "控制项最大 VIF": _display(result.vif, 2),
        "指标秩残差方差（%）": _percent(result.factor_share),
        "磨耗秩残差方差（%）": _percent(result.wear_share),
        "诊断": result.diagnostic,
        "运营标记": flag,
        "复核动作": action,
    }


def _validate(rows: list[dict]) -> tuple[str, dict[str, list[dict]]]:
    if len(rows) < MIN_FLEET_ROWS:
        raise ValueError(f"全队至少需要 {MIN_FLEET_ROWS} 条轮胎记录，请补齐同一窗口的巡检和磨耗台账。")
    groups = defaultdict(list)
    tire_ids = set()
    window = None
    numeric_fields = dict(LABELS, low_pressure_pct="低胎压检测占比", hard_brakes_per_1000km="急制动频次")
    for index, row in enumerate(rows, 1):
        tire_id, route = row["tire_id"].strip(), row["route"].strip()
        if not tire_id or not route:
            raise ValueError(f"第 {index} 条缺少轮胎编号或线路，请补齐后重导。")
        if tire_id in tire_ids:
            raise ValueError(f"第 {index} 条轮胎编号 {tire_id} 重复，请每条轮胎只保留一条有效记录。")
        tire_ids.add(tire_id)
        raw_date = row["window_end"].strip()
        try:
            end = date.fromisoformat(raw_date)
            if end.isoformat() != raw_date:
                raise ValueError
        except ValueError:
            raise ValueError(f"第 {index} 条窗口截止日无效，请按 YYYY-MM-DD 填写有效日期。") from None
        if window is not None and end != window:
            raise ValueError(f"第 {index} 条属于另一观测窗口，请按窗口截止日拆分 CSV 后分别运行。")
        window = end
        for key, name in numeric_fields.items():
            value = row[key]
            if not isfinite(value) or value < 0:
                raise ValueError(f"第 {index} 条{name}无效，请填入非负有限数值。")
        if row["mileage_km"] == 0:
            raise ValueError(f"第 {index} 条窗口里程为零，请核对里程台账或剔除未运营轮胎。")
        if row["low_pressure_pct"] > 100:
            raise ValueError(f"第 {index} 条低胎压检测占比超出 0–100%，请按百分数填写。")
        groups[route].append(row)
    if len(groups) < 2:
        raise ValueError("全队排查至少需要两条线路，请补齐同一窗口的其他线路记录。")
    return window.isoformat(), groups


def compute(rows: list[dict], options: dict) -> dict:
    factor_name = options.get("factor", DEFAULT_FACTOR)
    control_name = options.get("controls", DEFAULT_CONTROLS)
    threshold = options.get("review_threshold", 0.30)
    if factor_name not in FACTORS:
        raise ValueError("待查指标无效，请选择低胎压检测占比或急制动频次。")
    if control_name not in CONTROL_SETS:
        raise ValueError("控制口径无效，请选择里程＋胎龄、里程＋线路载荷或三项联合控制。")
    if not isinstance(threshold, (int, float)) or not isfinite(threshold) or not 0.10 <= threshold <= 0.95:
        raise ValueError("关联复核线无效，请填写 0.10 至 0.95 之间的数值。")
    window, groups = _validate(rows)
    factor, controls = FACTORS[factor_name], CONTROL_SETS[control_name]
    pooled = _analyze(rows, factor, controls, MIN_FLEET_ROWS)
    fleet_flag, fleet_action = _review(pooled, factor_name, threshold)
    report_rows = [_report_row("全队汇总", pooled, fleet_flag, fleet_action)]
    assessed_routes = followup_routes = opposite_routes = 0
    for route, route_rows in sorted(groups.items()):
        result = _analyze(route_rows, factor, controls, MIN_ROUTE_ROWS)
        flag, action = _review(result, factor_name, threshold)
        if result.usable:
            assessed_routes += 1
            if pooled.usable and _opposite(pooled.adjusted, result.adjusted):
                opposite_routes += 1
                action += " 该线路与全队控制后的方向相反，请单列复核。"
                if flag == "例行观察":
                    flag = "与全队方向相反"
            if flag != "例行观察":
                followup_routes += 1
        report_rows.append(_report_row(f"线路 {route}", result, flag, action))

    if pooled.usable:
        headline = (
            f"{factor_name}与磨耗：全队粗相关 {pooled.crude:+.3f}，"
            f"控制后 {pooled.adjusted:+.3f}（{fleet_flag}）"
        )
    else:
        headline = f"{factor_name}暂缓分发：全队{pooled.diagnostic}"
    return {
        "headline": headline,
        "metrics": {
            "窗口截止日": window,
            "待查指标": factor_name,
            "控制口径": control_name,
            "全队轮胎数": len(rows),
            "线路数": len(groups),
            "可判读线路数": assessed_routes,
            "待补数线路数": len(groups) - assessed_routes,
            "运营复核线路数": followup_routes,
            "与全队控制后方向相反线路数": opposite_routes,
            "关联复核线": threshold,
        },
        "rows": report_rows,
        "notes": [
            "粗 Spearman 是待查指标与胎纹磨耗的平均秩 Pearson 相关。偏秩相关先将两列的秩分别对所选控制项的秩做线性回归，再计算两组秩残差的 Pearson 相关。",
            "全队与各线路分别排秩。每个范围的粗值与偏秩值使用同一批轮胎。全队至少 12 条且覆盖至少两条线路，单线路至少 8 条。",
            "并列占比取待查指标和磨耗中较高者，达到 50% 提醒核对录入精度。残差方差为各指标控制后剩余的秩方差占比。",
            "控制项最大 VIF 达 10 或任一秩残差方差低于 5% 时标为补数复核。控制项无变异、完全共线或残差为零时，偏秩相关显示为 —。全队诊断未通过时暂停分发。",
            f"运营复核线为 |偏秩相关| ≥ {threshold:.2f}。粗值与偏秩值异号且两者绝对值均至少 0.15 时标记方向反转。粗值达到复核线、调整后低于复核线且绝对值降低至少 0.20 时标记衰减。",
            "系数用于点检排序。胎批、轮位、路面和同车轮胎可能共享的工况仍会影响结果。全队模型未加入线路固定效应，判读时同时查看分线路结果。",
        ],
        "chart": {
            "label": f"{factor_name}与胎纹磨耗相关对照",
            "unit": "相关系数",
            "points": [
                {"label": f"{row['线路范围']} · {label}", "value": row[key]}
                for row in report_rows
                for label, key in (("粗相关", "粗 Spearman"), ("偏秩", "偏秩相关"))
                if isinstance(row[key], (int, float))
            ],
        },
        "can_publish": pooled.usable,
    }


def sample_rows() -> list[dict]:
    rng = Random(670124)
    rows = []
    for route, count, base_km, base_load, pressure_effect in (
        ("B12", 18, 3750, 78, 0.020),
        ("K07", 18, 4200, 94, -0.022),
        ("N03", 18, 3250, 63, 0.001),
        ("S21", 6, 3400, 70, 0.010),
    ):
        for index in range(1, count + 1):
            mileage = base_km + rng.randint(-870, 870)
            age = rng.randint(38, 235)
            load = base_load + rng.randint(-12, 12)
            pressure_noise = rng.randint(-14, 14)
            low_pressure = max(0, round(25 + 0.015 * (mileage - 3700) + 0.06 * (age - 120) + pressure_noise))
            brakes = round(22 + 0.30 * (load - 70) + rng.uniform(-7, 7), 1)
            wear = 0.85 + 0.00030 * (mileage - 3700) + 0.0014 * (age - 120)
            wear += 0.0035 * (load - 78) + pressure_effect * pressure_noise + rng.uniform(-0.10, 0.10)
            rows.append({
                "tire_id": f"TL-{route}-{index:03d}",
                "route": route,
                "window_end": "2026-10-31",
                "mileage_km": mileage,
                "tire_age_days": age,
                "route_load_pct": load,
                "low_pressure_pct": low_pressure,
                "hard_brakes_per_1000km": brakes,
                "tread_loss_mm": round(wear, 2),
            })
    return rows

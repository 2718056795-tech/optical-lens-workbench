"""Read the per-trial MTF table from a tolerance report and reproduce V6 curves."""

import base64
import binascii
import codecs
from dataclasses import dataclass
import math
import re

import numpy as np
from scipy.interpolate import CubicSpline


MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_BASE64_LENGTH = 4 * ((MAX_FILE_BYTES + 2) // 3)
_DATA_URL = re.compile(
    r"data:(?:text/plain|application/octet-stream)?(?:;charset=[\w-]+)?;base64",
    re.IGNORECASE,
)
_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_INTEGER = r"[0-9]{1,9}"
_MC_SECTION = r"蒙特卡[罗洛]\s*分析\s*[:：]"
_CRITERION = (
    rf"判据\s*[:：]\s*在\s*({_NUMBER})\s*周期\s*每\s*mm\s*处的\s*"
    r"衍射\s*MTF\s*[-–—−]\s*(子午|弧矢)"
)
_CONFIGURATION = rf"({_INTEGER})\s*的\s*({_INTEGER})\s*结构分析"
_FIELDS = r"#\s+X[-－]\s*视场\s+Y[-－]\s*视场\s+权重\s+VDX\s+VDY\s+VCX\s+VCY"
_SAMPLE_COUNT = rf"测试数\s*[:：]\s*({_INTEGER})"
_TABLE_HEADER = r"测试\s+标准\s+改变((?:\s+视场\s+[0-9]+)+)"
_COLUMN_CONFIGURATION = rf"结构\s+({_INTEGER})"
_DIRECTION_NAMES = {"TAN": "子午", "SAG": "弧矢"}


@dataclass
class _Report:
    name: str
    direction: str
    frequency_lp_mm: float
    configuration: int
    fields: list[tuple[float, ...]]
    samples: np.ndarray

    def metadata(self):
        return {
            "name": self.name,
            "direction": self.direction,
            "frequency_lp_mm": self.frequency_lp_mm,
            "configuration": self.configuration,
            "field_count": len(self.fields),
            "sample_count": len(self.samples),
        }


def _decode_upload(item):
    if not isinstance(item, dict):
        raise ValueError("文件条目格式不正确。")
    name = item.get("name")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 255
        or any(char in "/\\" or ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in name)
        or not name.casefold().endswith(".txt")
    ):
        raise ValueError("请选择有效的 TXT 报告文件。")
    data = item.get("data")
    if not isinstance(data, str):
        raise ValueError(f"{name} 缺少文件内容。")
    header, delimiter, encoded = data.partition(",")
    if not delimiter or not _DATA_URL.fullmatch(header):
        raise ValueError(f"{name} 不是有效的 TXT 文件上传数据。")
    if len(encoded) > _MAX_BASE64_LENGTH:
        raise ValueError(f"{name} 超过单文件 4 MiB 限制。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"{name} 文件内容的 Base64 编码无效。") from error
    if not raw:
        raise ValueError(f"{name} 是空文件。")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"{name} 超过单文件 4 MiB 限制。")
    return name, raw


def _one_header(pattern, lines, description):
    matches = []
    for index, line in enumerate(lines):
        match = re.fullmatch(pattern, line.strip())
        if match:
            matches.append((index, match))
    if len(matches) != 1:
        raise ValueError(f"应包含一处可识别的{description}。")
    return matches[0]


def _finite_numbers(columns, description):
    if any(not re.fullmatch(_NUMBER, column) for column in columns):
        raise ValueError(f"{description}包含无效数值。")
    values = tuple(float(column) for column in columns)
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{description}包含无效数值。")
    return values


def _read_fields(preamble):
    header_index, _ = _one_header(_FIELDS, preamble, "二维视场定义")
    fields = []
    for line in preamble[header_index + 1 :]:
        columns = line.split()
        if not columns or not re.fullmatch(_INTEGER, columns[0]):
            break
        if len(columns) != 8 or int(columns[0]) != len(fields) + 1:
            raise ValueError("二维视场定义不完整，或视场编号不连续。")
        fields.append(_finite_numbers(columns[1:], f"视场 {len(fields) + 1}"))
    if not fields:
        raise ValueError("二维视场表没有数据。")
    return fields


def _read_samples(section, field_count, configuration):
    table_index, table = _one_header(_TABLE_HEADER, section, "蒙特卡罗样本表表头")
    field_ids = [int(value) for value in re.findall(r"视场\s+([0-9]+)", table[1])]
    if field_ids != list(range(1, field_count + 1)):
        raise ValueError("蒙特卡罗样本表缺少视场、重复视场或列顺序与视场定义不一致。")

    before_table = section[:table_index]
    _, count = _one_header(_SAMPLE_COUNT, before_table, "蒙特卡罗测试数")
    expected = int(count[1])
    if expected < 1:
        raise ValueError("蒙特卡罗测试数必须大于零。")
    configurations = next((line.strip() for line in reversed(before_table) if line.strip()), "")
    if not re.fullmatch(rf"{_COLUMN_CONFIGURATION}(?:\s+{_COLUMN_CONFIGURATION})*", configurations):
        raise ValueError("无法识别蒙特卡罗样本表的结构列。")
    ids = [int(value) for value in re.findall(_COLUMN_CONFIGURATION, configurations)]
    if ids != [configuration] * field_count:
        raise ValueError("蒙特卡罗样本表的结构列与报告结构或视场数不一致。")

    start = table_index + 1
    end = start + expected
    rows = section[start:end]
    if len(rows) != expected:
        raise ValueError(f"蒙特卡罗样本表不完整，报告声明 {expected} 个样本。")
    samples = []
    for index, line in enumerate(rows, start=1):
        columns = line.split()
        if len(columns) != field_count + 3 or not re.fullmatch(_INTEGER, columns[0]):
            raise ValueError(f"第 {index} 个蒙特卡罗样本不完整，或 MTF 列数不正确。")
        if int(columns[0]) != index:
            raise ValueError(f"蒙特卡罗样本编号不连续，应为 {index}，实际为 {columns[0]}。")
        values = _finite_numbers(columns[1:], f"第 {index} 个蒙特卡罗样本")
        mtfs = values[2:]
        if any(value < 0 or value > 1 for value in mtfs):
            raise ValueError(f"第 {index} 个蒙特卡罗样本的 MTF 超出 0 到 1。")
        samples.append(mtfs)
    following = next((line for line in section[end:] if line.strip()), "")
    if re.match(r"\s*[0-9]+\s+[-+.0-9]", following):
        raise ValueError(f"蒙特卡罗样本表超过报告声明的 {expected} 个样本。")
    return np.asarray(samples, dtype=float)


def _parse_report(name, raw):
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    elif b"\0" in raw:
        encoding = "utf-16-le"
    else:
        encoding = "utf-8-sig"
    try:
        lines = raw.decode(encoding).splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("无法读取报告编码，请使用 UTF-16 或 UTF-8 TXT。") from error
    section_index, _ = _one_header(_MC_SECTION, lines, "蒙特卡罗分析段")
    preamble = lines[:section_index]
    _, criterion = _one_header(_CRITERION, preamble, "衍射 MTF 频率和方向判据")
    frequency = float(criterion[1])
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("衍射 MTF 判据频率必须是有效的正数。")
    direction = "TAN" if criterion[2] == "子午" else "SAG"
    _, config = _one_header(_CONFIGURATION, preamble, "报告结构编号")
    configuration, total_configurations = int(config[1]), int(config[2])
    if not 1 <= configuration <= total_configurations:
        raise ValueError("报告结构编号超出有效范围。")
    fields = _read_fields(preamble)
    samples = _read_samples(lines[section_index + 1 :], len(fields), configuration)
    return _Report(name, direction, frequency, configuration, fields, samples)


def _name_warning(report):
    indicated = set()
    if re.search(r"子午|(?<![A-Za-z])(?:TAN|TANGENTIAL)(?![A-Za-z])", report.name, re.I):
        indicated.add("TAN")
    if re.search(r"弧矢|(?<![A-Za-z])(?:SAG|SAGITTAL)(?![A-Za-z])", report.name, re.I):
        indicated.add("SAG")
    if indicated and indicated != {report.direction}:
        return f"{report.name} 的文件名方向与正文不一致，按正文的{_DIRECTION_NAMES[report.direction]}处理。"
    return None


def _compare_reports(tan, sag):
    warnings = []
    if tan.configuration != sag.configuration:
        warnings.append(f"子午与弧矢报告的结构不同（{tan.configuration} / {sag.configuration}）。")
    if tan.fields != sag.fields:
        warnings.append("子午与弧矢报告的视场定义不同，请分别对照各自视场。")
    if len(tan.samples) != len(sag.samples):
        warnings.append(f"子午与弧矢报告的样本数不同（{len(tan.samples)} / {len(sag.samples)}）。")
    return warnings


def _curve(report, thresholds, values, field):
    # Search sorted samples to preserve >= while avoiding a samples × fields × 200 array.
    ordered = np.sort(values)
    passes = len(ordered) - np.searchsorted(ordered, thresholds, side="left")
    rates = (passes / len(ordered)) * 100
    # V6 evaluates the spline on its original 200 nodes and marks the nearest rate to 80%.
    displayed = CubicSpline(thresholds, rates)(thresholds)
    mtf80 = float(thresholds[np.argmin(np.abs(displayed - 80))])
    field_label = "Min" if field is None else f"F{field}"
    return {
        "id": f"{report.direction}-{field_label}",
        "direction": report.direction,
        "field": field,
        "label": f"{report.direction} {field_label} 80%>{mtf80:.3f}",
        "values": displayed.tolist(),
        "mtf80": mtf80,
        "is_min": field is None,
    }


def analyze_request(body):
    """Validate one or two uploads and return independent V6-style yield curves."""
    if not isinstance(body, dict):
        raise ValueError("良率分析请求格式不正确。")
    files = body.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 2:
        raise ValueError("请选择一份或两份 TXT 报告。")
    include_min = body.get("include_min", False)
    if not isinstance(include_min, bool):
        raise ValueError("最小 MTF 曲线开关必须是真或假。")
    uploads = [_decode_upload(item) for item in files]
    if len(uploads) == 2 and uploads[0][1] == uploads[1][1]:
        raise ValueError("两份 TXT 内容完全相同，请只选择一份。")

    reports = []
    for name, raw in uploads:
        try:
            reports.append(_parse_report(name, raw))
        except ValueError as error:
            raise ValueError(f"{name}：{error}") from error
    warnings = [warning for report in reports if (warning := _name_warning(report))]
    reports.sort(key=lambda report: report.direction != "TAN")
    if len(reports) == 2:
        first, second = reports
        if first.frequency_lp_mm != second.frequency_lp_mm:
            raise ValueError("两份报告的 MTF 频率不同，请分别查看。")
        if first.direction == second.direction:
            raise ValueError(f"两份报告正文均为{_DIRECTION_NAMES[first.direction]}，请分别查看。")
        warnings.extend(_compare_reports(first, second))

    thresholds = np.linspace(0, 1, 200)
    curves = []
    for report in reports:
        for field, values in enumerate(report.samples.T, start=1):
            curves.append(_curve(report, thresholds, values, field))
        if include_min:
            curves.append(_curve(report, thresholds, report.samples.min(axis=1), None))
    return {
        "thresholds": thresholds.tolist(),
        "curves": curves,
        "reports": [report.metadata() for report in reports],
        "warnings": warnings,
    }

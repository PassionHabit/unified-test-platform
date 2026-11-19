"""轻量结果摘要解析器（V2.1 §12）：Pytest junit / Robot output.xml / GTest / JMeter。

只做总量级摘要：total/passed/failed/skipped + 失败用例清单（截断）。
解析失败返回 None，不影响产物交付（调用方负责）。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional


def parse_report(report_type: str, data: bytes) -> Optional[dict]:
    try:
        if report_type == "pytest":
            return _parse_junit(data)
        if report_type == "robot":
            return _parse_robot(data)
        if report_type == "gtest":
            return _parse_gtest(data)
        if report_type == "jmeter":
            return _parse_jmeter(data)
    except Exception:
        return None
    return None


def _parse_junit(data: bytes) -> Optional[dict]:
    """Pytest --junitxml（兼容单/多 testsuite）。"""
    root = ET.fromstring(data)
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    total = failed = skipped = 0
    failures = []
    for suite in suites:
        for case in suite.findall("testcase"):
            total += 1
            if case.find("failure") is not None or case.find("error") is not None:
                failed += 1
                failures.append(
                    {"name": case.get("name", "?"), "classname": case.get("classname", "")}
                )
            elif case.find("skipped") is not None:
                skipped += 1
    if total == 0:
        return None
    return {"total": total, "passed": total - failed - skipped, "failed": failed, "skipped": skipped, "failures": failures}


def _parse_robot(data: bytes) -> Optional[dict]:
    """Robot Framework output.xml 的 statistics/total。"""
    root = ET.fromstring(data)
    stats = root.find(".//statistics/total")
    if stats is None:
        return None
    counters = {}
    for stat in stats.findall("stat"):
        counters[stat.get("text", "").lower()] = int(stat.get("pass", 0)), int(stat.get("fail", 0))
    def pick(*names):
        for n in names:
            if n in counters:
                return counters[n]
        return (0, 0)
    all_p, all_f = pick("all tests", "all")
    skipped = sum(counters[n][0] for n in counters if "skip" in n)
    failed_cases = []
    for status in root.findall(".//test/status"):
        if status.get("status") == "FAIL":
            test = None
            # 回溯找所属 test 节点名
            parent = next((t for t in root.iter("test") if status in list(t.iter("status"))), None)
            if parent is not None:
                failed_cases.append({"name": parent.get("name", "?"), "classname": ""})
    total = all_p + all_f
    if total == 0:
        return None
    return {
        "total": total,
        "passed": all_p - skipped if all_p >= skipped else 0,
        "failed": all_f,
        "skipped": skipped,
        "failures": failed_cases,
    }


def _parse_gtest(data: bytes) -> Optional[dict]:
    """gtest --gtest_output=xml（testsuites）。"""
    root = ET.fromstring(data)
    total = failed = disabled = 0
    failures = []
    for suite in root.iter("testsuite"):
        for case in suite.findall("testcase"):
            total += 1
            if case.find("failure") is not None:
                failed += 1
                failures.append({"name": case.get("name", "?"), "classname": case.get("classname", "")})
            elif case.get("status") == "notrun":
                disabled += 1
    if total == 0:
        return None
    return {"total": total, "passed": total - failed - disabled, "failed": failed, "skipped": disabled, "failures": failures}


def _parse_jmeter(data: bytes) -> Optional[dict]:
    """JMeter CSV jtl（timeStamp,elapsed,label,responseCode,success,...）。"""
    text = data.decode("utf-8", "replace")
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    header = lines[0].split(",")
    try:
        i_label = header.index("label")
        i_ok = header.index("success")
    except ValueError:
        return None
    total = failed = 0
    failures = []
    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) <= max(i_label, i_ok):
            continue
        total += 1
        if cols[i_ok].strip().lower() != "true":
            failed += 1
            failures.append({"name": cols[i_label], "classname": ""})
    if total == 0:
        return None
    return {"total": total, "passed": total - failed, "failed": failed, "skipped": 0, "failures": failures}

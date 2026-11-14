"""从 bingZDH.py 的运行日志中提取结构化结果，写入 status/latest.json。

供 GitHub Actions 提交回仓库，再由云端定时任务读取汇总。
"""

import json
import os
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_CANDIDATES = [
    os.path.join(ROOT, "bing_automation.log"),
    "/tmp/bing_automation.log",
]

RE_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} (\w+): (.*)$")
RE_POINTS = re.compile(r"当前Bing总积分[：:]\s*([^，,]+)[，,]\s*今日积分[：:]\s*(\S+)")
RE_ATTEMPT = re.compile(r"开始账号\s+(\S+?)\s+的自动化任务")
RE_DONE = re.compile(r"账号组\s+\S+\s+账号\s+(\S+?)\s+任务完成")
RE_FAIL = re.compile(r"账号(\S+?)\s*(自动化流程异常|登录失败)")


def read_log():
    override = os.getenv("BING_LOG")
    for path in ([override] if override else []) + LOG_CANDIDATES:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return path, f.readlines()
    return None, []


def parse(lines):
    attempted, completed, failed = [], [], []
    totals, todays = [], []
    errors = []
    first_ts = last_ts = None

    for raw in lines:
        m = RE_LINE.match(raw.strip())
        ts, level, msg = (m.group(1), m.group(2), m.group(3)) if m else (None, "", raw.strip())
        if ts:
            first_ts = first_ts or ts
            last_ts = ts

        pm = RE_POINTS.search(msg)
        if pm:
            total, today = pm.group(1).strip(), pm.group(2).strip()
            if total.isdigit():
                totals.append(int(total))
            if today.isdigit():
                todays.append(int(today))

        am = RE_ATTEMPT.search(msg)
        if am:
            attempted.append(am.group(1))

        dm = RE_DONE.search(msg)
        if dm:
            completed.append(dm.group(1))

        fm = RE_FAIL.search(msg)
        if fm:
            failed.append(fm.group(1))

        if level == "ERROR":
            errors.append(msg[:300])

    return {
        "attempted": sorted(set(attempted)),
        "completed": sorted(set(completed)),
        "failed": sorted(set(failed)),
        "total_points": totals[-1] if totals else None,
        "today_points": max(todays) if todays else None,
        "errors": errors[-5:],
        "error_count": len(errors),
        "log_start": first_ts,
        "log_end": last_ts,
    }


def mask(addr):
    """脱敏账号，避免公开仓库的状态文件泄漏完整邮箱"""
    if "@" not in addr:
        return addr[:2] + "***"
    name, domain = addr.split("@", 1)
    return name[:2] + "***@" + domain


def main():
    log_path, lines = read_log()
    p = parse(lines) if lines else {
        "attempted": [], "completed": [], "failed": [],
        "total_points": None, "today_points": None,
        "errors": ["未找到日志文件"], "error_count": 1,
        "log_start": None, "log_end": None,
    }

    if not p["attempted"] and not p["completed"]:
        status = "failed" if p["error_count"] else "unknown"
    elif p["completed"] and not p["failed"]:
        status = "success"
    elif p["completed"]:
        status = "partial"
    else:
        status = "failed"

    result = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "accounts_attempted": len(p["attempted"]),
        "accounts_completed": len(p["completed"]),
        "accounts": [mask(a) for a in p["completed"]],
        "total_points": p["total_points"],
        "today_points": p["today_points"],
        "error_count": p["error_count"],
        "errors": [re.sub(r"[A-Za-z0-9._+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.]+", lambda m: mask(m.group(0)), e) for e in p["errors"]],
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_url": (
            f"https://github.com/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
            if os.getenv("GITHUB_RUN_ID") else None
        ),
    }

    out_dir = os.path.join(ROOT, "status")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "latest.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    summary = (
        f"状态 {result['status']}｜完成 {result['accounts_completed']}/"
        f"{result['accounts_attempted']} 个账号｜今日积分 {result['today_points']}"
        f"｜总积分 {result['total_points']}｜错误 {result['error_count']} 条"
    )
    step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(f"### Bing 签到结果\n\n{summary}\n\n")
            if result["errors"]:
                f.write("<details><summary>错误详情</summary>\n\n")
                for e in result["errors"]:
                    f.write(f"- `{e}`\n")
                f.write("\n</details>\n")
    return result


if __name__ == "__main__":
    main()

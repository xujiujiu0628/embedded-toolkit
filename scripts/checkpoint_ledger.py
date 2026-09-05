r"""verify 进度台账 (F-059) — verify.py 拆分件（防腐方案 §3.3 步骤 5b）.

F-047 家族整体搬迁：CHECKPOINT_STATUSES 白名单 / _git_head / record_checkpoint
（双写 checkpoints.jsonl + state.json last_checkpoint）。

wire 兼容: verify 再导出三符号，main() 调度与 10 处测试调用零修改；
_record_checkpoint_early_exit 留守 verify（读 WORKSPACE 全局与 result/args
的编排胶水），其对 record_checkpoint 的调用经 verify 再导出面可达。

已知语义微调（记账）: ts 由 verify 本地 now_iso（固定 +08:00）改为
runtime_common.now_iso 规范版（本地时区 astimezone）——时刻不变，偏移标签
在非 +8 机器上跟随本地时区；本机 +08:00 输出逐字节一致。
"""
import json
import os
import subprocess
import sys

from runtime_common import now_iso
from wb_common import atomic_write_json


# F-047: 进度台账 (2026-09-02 方案四-2)
#   - checkpoints.jsonl: append-only, 8 字段 (ts/git_head/git_branch/status/
#     duration_sec/origin/step_keys/contract_hashes) — 审计链
#   - state.json last_checkpoint: 覆盖式, 与 jsonl 末行同步 — 消费方读
# 落盘失败不阻断 (与 F-046 audit.jsonl 同款审计非门禁纪律)
CHECKPOINT_STATUSES = ("ok", "fail", "timing_fail", "hardfault",
                       "build_failed", "build_has_errors", "flash_failed",
                       "capture_failed", "build_clean_skipped")


def _git_head(workspace: str) -> tuple[str, str]:
    """F-047: 隔离 git 调用, 失败返回 ("", "") 而非抛.

    返回 (短 commit hash, branch name). 非 git 目录 / git 不可用 → 空字符串.
    """
    try:
        head_p = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=workspace)
        branch_p = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=workspace)
        head = head_p.stdout.strip() if head_p.returncode == 0 else ""
        branch = branch_p.stdout.strip() if branch_p.returncode == 0 else ""
        # detached HEAD 时 git 报 "HEAD", 仍是有用信息, 不过滤
        return head, branch
    except (OSError, subprocess.TimeoutExpired):
        return "", ""


def record_checkpoint(workspace: str, status: str, duration_sec: float,
                      origin: str, step_keys: list,
                      contract_hashes: dict, *,
                      step_durations: dict | None = None,
                      gate_run: bool = False) -> None:
    """F-047: 双写 — checkpoints.jsonl (append) + state.json last_checkpoint.

    与 F-046 audit.jsonl 关系: audit 记 HIL 步骤级 (flash/capture),
    checkpoint 记 verify 全流程级 (跑完一次落一条). 两者职责正交.

    自审 (2026-09-03) 扩展:
      - step_durations: 各 step 实际耗时 (F-050 时长画像数据源).
        不传则留空 dict (向后兼容).
      - gate_run=True: 门禁重跑/豁免运行, 跳过 jsonl append 但仍更新
        state.json["last_checkpoint"] 标 status="gate_skip", 避免污染
        release audit 的"上次 PASS"语义 (Finding 3).
    """
    if status not in CHECKPOINT_STATUSES:
        raise ValueError(
            f"checkpoint status 非法: {status!r}, 须为 {CHECKPOINT_STATUSES} 之一")
    git_head, git_branch = _git_head(workspace)
    entry = {
        "ts": now_iso(),
        "git_head": git_head,
        "git_branch": git_branch,
        "status": status,
        "duration_sec": round(duration_sec, 1),
        "origin": origin,
        "step_keys": list(step_keys),
        "step_durations": dict(step_durations) if step_durations else {},
        "contract_hashes": dict(contract_hashes),
    }
    state_dir = os.path.join(workspace, ".workbench", "state")
    jsonl_path = os.path.join(state_dir, "checkpoints.jsonl")
    state_path = os.path.join(workspace, ".workbench", "state.json")
    # 自审 Finding 3: gate_run 不污染主台账, 但仍写 state.json (与
    # _log_feedback_event 跳 gate_run 同口径, spec 2026-08-26 §5)
    if gate_run:
        entry["status"] = "gate_skip"
    try:
        os.makedirs(state_dir, exist_ok=True)
        if not gate_run:
            # 1) append-only 台账 (gate 模式跳过, 防污染 release audit)
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # 2) 同步 last_checkpoint 到 state.json (与现有 last_build 同构)
        #    gate 模式也写, 但 status=gate_skip 标出, 给 release audit 区分
        state = {}
        if os.path.isfile(state_path):
            try:
                with open(state_path, encoding="utf-8") as f:
                    state = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 旧 state.json 损坏: 不丢其它键, 按空 dict 继续 (load_workspace_state
                # for_update 的损坏隔离纪律不适用于 read-modify-write 单点)
                state = {}
        state["last_checkpoint"] = entry
        # F-047 自审 (2026-09-03) 改: 改用 atomic_write_json (F-022 纪律),
        # 防止进程在写 state.json 中途被 kill 导致 JSON 截断 → 下次读
        # 走损坏 → 走 state={} → 丢全部历史键 (含 last_build).
        atomic_write_json(state_path, state)
    except OSError:
        # 审计非门禁: 落盘失败不阻断主流程
        print(f"[warn] checkpoint 落盘失败: {jsonl_path}", file=sys.stderr)



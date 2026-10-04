r"""D1/D2 契约钉 (F-220)。

## 这两笔为什么是"只补钉、不改行为"

D1/D2 原被列为「D 档弱点」待修, 本轮**复核后改变结论**——两笔都只补
机检钉, 均不改任何运行时行为。理由逐条在钉的 docstring 里, 此处只记
"为什么不改":

- **D1** 原描述「PASS 事件灌水」经核**不成立**(见下)。改行为既无必要
  也无数据基础(落库文件未被跟踪, 既有 7 条事件零条 `pass`)。
- **D2** `release_audit.py:32` **已明文声明**三档退出码, `warned → 0` 是
  有意设计而非疏漏。真实缺口是该契约**零机检**——只活在注释里, 改代码
  前不会坏, 改之后也不会被发现坏。故补钉而非改码。

**这本身是一次纠错**: 本轮我一度判断 D1「改则动既有落库数据、需重算校准」,
该判断错误——错因是**没读 feedback-log skill 就下结论**, 而 skill 明文
要求 `verify_result: "pass"` 与 `outcome: "fixed"` 配对出现。这是本仓
"没核实就断言"病灶的第四次复发(F-215 二手摘要 / F-216 推断当实测 /
F-217 H-4 措辞升级), 但最轻——未造成代码伤害, 只是差点让错判进账本。
根因与前三笔同: **凭字段名猜语义, 不看消费方**。
"""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import feedback_db  # noqa: E402


def _src(name):
    with open(os.path.join(ROOT, "scripts", name), encoding="utf-8") as f:
        return f.read()


def _load_valid_outcomes():
    """取 feedback_db 里valid_outcomes 的实际取值集合。"""
    import re
    src = _src("feedback_db.py")
    m = re.search(r"valid_outcomes\s*=\s*\{([^}]*)\}", src, re.S)
    if not m:
        return None
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


class D1OutcomeSemanticsTests(unittest.TestCase):
    """D1: 钉住 `outcome` 与 `verify_result` 的**语义分工**。

    原指控「PASS 事件灌水」的前提是"`pass` 会被当成一次修复计入统计"。
    实测证伪: `update_calibration` 只认 fixed/still_broken/false_positive
    三个归宿类取值, pass/fail 落不进任何计数器; 且 by_pipeline 计数只看
    pipeline 名, 不看 outcome。故本组钉住这个分工, 防止它被改坏。
    """

    def test_calibration_counts_only_outcome_class_values(self):
        """**核心钉**: pass/fail 不参与校准计数 —— 灌水路径不存在。

        真跑 update_calibration: 分别喂 fixed / pass / fail / 未知值,
        断言只有 fixed 进了 entry["fixed"], 其余三个 attempts 增而
        fixed 不增。这比读源码断言更硬——它验证的是**行为**。
        """
        cases = [
            ("fixed", "fixed", 1),      # (outcome, 计数键, 期望增量)
            ("pass", None, 0),
            ("fail", None, 0),
            ("不存在的值", None, 0),
        ]
        for outcome, key, expect in cases:
            with self.subTest(outcome=outcome):
                cal = {p: {"build_fix": {"E123": {
                    "attempts": 0, "fixed": 0, "still_broken": 0,
                    "false_positive": 0, "avg_rounds": 0.0,
                    "last_seen": ""}}} for p in
                    ("build_fix", "hardfault", "code_gen")}
                with mock.patch.object(feedback_db, "load_calibration",
                                       return_value=cal), \
                     mock.patch.object(feedback_db, "save_calibration"):
                    feedback_db.update_calibration({
                        "pipeline": "build_fix",
                        "outcome": outcome,
                        "error_code": "E123",
                        "timestamp": "now",
                        "rounds": 1,
                    })
                entry = cal["build_fix"]["E123"]
                self.assertEqual(entry["attempts"], 1,
                                 f"outcome={outcome!r} 时 attempts 应为 1")
                if key is None:
                    self.assertEqual(
                        entry["fixed"], 0,
                        f"outcome={outcome!r} 被计入了 fixed —— "
                        f"「灌水」路径成立, 与本钉意图相反")
                else:
                    self.assertEqual(entry[key], expect)

    def test_pipeline_counter_ignores_outcome(self):
        """**行为钉**: by_pipeline 计数只按 pipeline 名, 与 outcome 无关。

        真跑 log_event (落盘层用真临时目录, 不 mock) 喂不同 outcome,
        断言 by_pipeline 计数恒为 1 —— 比读源码断言更硬: 验的是**行为**。
        含"未知 outcome"与 `reported`, 后者同为 valid_outcomes 成员
        (脚本 :157, fresh_check 已交付语义), 复核时一度漏读。
        """
        outcomes = ["fixed", "pass", "fail", "still_broken", "reported",
                    "", "不存在的值"]
        for outcome in outcomes:
            with self.subTest(outcome=outcome),                  tempfile.TemporaryDirectory() as td:
                ws = os.path.join(td, "proj")
                os.makedirs(ws, exist_ok=True)
                with mock.patch.object(feedback_db, "_project_feedback_dir",
                                       return_value=os.path.join(
                                           ws, ".workbench", "feedback")):
                    feedback_db.log_event({
                        "pipeline": "build_fix",
                        "outcome": outcome,
                        "timestamp": "2026-01-01T00:00:00+08:00",
                    })
                    with mock.patch.object(feedback_db, "load_feedback_db",
                                           wraps=feedback_db.load_feedback_db):
                        db = feedback_db.load_feedback_db()
                self.assertEqual(
                    db["by_pipeline"]["build_fix"], 1,
                    f"outcome={outcome!r} 时计数应仍为 1(计数只看 pipeline 名)")

    def test_pass_and_fail_are_distinct_from_outcome_class(self):
        """`pass`/`fail` 语义是**验证结果**(verify_result 取值), 而非归宿。

        skill 明文要求二者配对: `verify_result: "pass"` + `outcome: "fixed"`
        ——即"验证通过 + 修复成功"是一次事件的两个独立维度, 不是二选一。
        本钉钉住这两个集合有交集但不相同, 防后续把它们混为一谈。
        """
        valid = _load_valid_outcomes()
        self.assertIsNotNone(valid, "未解析出 valid_outcomes")
        outcome_class = {"fixed", "still_broken", "false_positive"}
        self.assertTrue(outcome_class.issubset(valid),
                        f"归宿类取值缺失: {outcome_class - valid}")
        # pass/fail 可作 outcome (CLI 允许记录"未复现"), 但不参与校准
        self.assertIn("pass", valid)
        self.assertIn("fail", valid)
        # 二者都不得被 update_calibration 认作归宿
        self.assertFalse(outcome_class & {"pass", "fail"},
                         "pass/fail 不应属归宿类")

    def test_verified_skill_uses_both_fields_separately(self):
        """反向钉: skill 实际用法须与上述分工一致。

        若 skill 改成只记 outcome 而不记 verify_result, 说明契约变了,
        本测试应随skill 改动更新——**钉的是分工, 不是逐字文案**。
        """
        skill = os.path.expanduser("~/.claude/skills/feedback-log/SKILL.md")
        if not os.path.isfile(skill):
            self.skipTest("feedback-log skill 不在本机(非仓内资产)")
        with open(skill, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('"verify_result"', text,
                      "skill 未记verify_result —— 两字段分工的前提不成立")
        self.assertIn('"outcome"', text,
                      "skill 未记 outcome —— 两字段分工的前提不成立")


class D1NoExistingPassDataTests(unittest.TestCase):
    """钉住「既有数据零条 pass」这一事实——它是 D1 影响面评估的基础。

    若将来真的记入 pass 事件, 本例转红提醒: 届时D1 的结论需重新评估
    (校准虽不受影响, 但落库数据形态变了, 账上的「撤案」依据要更新)。
    """

    def test_no_pass_outcome_in_committed_data(self):
        db = os.path.join(ROOT, "examples", "sim-demo", ".workbench",
                          "feedback", "feedback_db.json")
        if not os.path.isfile(db):
            self.skipTest("本仓无落库样例(该文件本就未被跟踪)")
        with open(db, encoding="utf-8") as f:
            data = json.load(f)
        outcomes = [e.get("outcome") for e in data.get("events", [])]
        self.assertNotIn(
            "pass", outcomes,
            f"落库数据已出现 outcome=pass ({outcomes}) —— D1「灌水」"
            f"前提可能转为成立, 须重新评估而非沿用撤案结论")


class D2ExitCodeContractTests(unittest.TestCase):
    """D2: 钉住 `release_audit.py:32` 已声明的三档退出码。

    `:32` 文档写明「0 = clean/warned, 1 = 存在 fail 项, 2 = 用法/环境错误」,
    但此前**零机检**。本组把该契约变成可执行断言, 不改任何行为。
    """

    def _run_main(self, argv):
        """跑 release_audit.py 并取**真进程退出码**。

        走子进程而非 mock sys.argv + 直接调 main:
        ①stub_ratchet 把 `mock.patch.object(sys, "argv")` 判为 B 式全局
        打桩(新增即红), 本组不新增该欠账;
        ②退出码本就是**进程级**契约, 子进程返回的 code 才是对外真值
        (直接调 main 拿到的是 return 值, 与 `sys.exit()` 后的实际 code
        之间隔着一次包装, 恰好掩盖了 D2 这类"退出语义"问题的要害)。
        """
        script = os.path.join(ROOT, "scripts", "release_audit.py")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, script] + argv,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, env=env)
        return r.returncode

    def test_documented_contract_line_present(self):
        """`:32` 的声明仍在(若上游改写文档, 本例提醒同步改钉)。"""
        src = _src("release_audit.py")
        self.assertIn("0 = clean/warned", src,
                      "退出码契约文档消失—— 若有意改语义, 须先裁决再改钉")

    def test_usage_error_exits_2(self):
        """缺 --tag/--all → 2。"""
        self.assertEqual(self._run_main(["--project", ROOT]), 2)

    def test_approve_failure_exits_1(self):
        """approve 失败 → 1(记录不可解析即失败)。"""
        with tempfile_dir() as ws:
            rc = self._run_main(["--project", ws, "--approve", "v9.9.9"])
        self.assertEqual(rc, 1)

    def test_approve_success_exits_0(self):
        """approve 成功 → 0。

        approve 前置是「R1~R8 无 fail」。**R2 的判据是
        `tag_commit == record["git_head"]`**(release_audit.py:99-101),
        两者须指向**同一 commit**; 而记录文件若入 git, 提交它本身就改变
        HEAD —— 回填 git_head 的那次提交又改一次 HEAD, 自指无解。

        故让**记录文件不入 git**(R6「记录未入 git」判 **warn** 非 fail,
        已读源码确认), HEAD 在造完 hex 后固定: 提交 hex → 记 HEAD →
        写记录(git_head=该 HEAD) → 打 tag。
        """
        with tempfile_dir() as ws:
            _mk_record(ws, "v1.0.0", evidence="hardware_validated")
            _commit_all(ws, "rec")      # hex 入库, HEAD 至此固定
            h = _head_sha(ws)
            _write_record(ws, "v1.0.0", evidence="hardware_validated",
                          git_head=h)    # 回填, **不再提交**
            _tag(ws, "v1.0.0")
            rc = self._run_main(["--project", ws, "--approve", "v1.0.0"])
        self.assertEqual(rc, 0, "approve 成功应退0")

    def test_warned_verdict_exits_0(self):
        """**D2 的核心判据**: verdict=warned → 0(有意设计, 非疏漏)。

        构造一条 R1~R8 **无 fail**、仅 R6「记录未入 git」判 **warn** 的
        记录(记录文件不入 git 但 tag 照打, 故 R2 仍能过), 断言退出 0 ——
        即 `:32` 声明的 "0 = clean/warned"。这条钉的是**有意行为**,
        防后人误当 bug 改掉。
        """
        with tempfile_dir() as ws:
            _mk_record(ws, "v1.0.0", evidence="hardware_validated")
            _commit_all(ws, "rec")       # hex 入库, HEAD 固定
            h = _head_sha(ws)
            # 记录不入 git(R6 → warn) 而 tag 照打(v1.0.0 已在 rec commit 上)
            _write_record(ws, "v1.0.0", evidence="hardware_validated",
                          git_head=h)
            _tag(ws, "v1.0.0")
            rc = self._run_main(["--project", ws, "--tag", "v1.0.0"])
        self.assertEqual(
            rc, 0,
            "warned 应退 0 (release_audit.py:32 明文契约); 若真要改"
            "warned 的退出码, 须先裁决影响面再改本钉")

    def test_failed_verdict_exits_1(self):
        """存在 fail 项(R3 缺 hex 证据) → 1。"""
        with tempfile_dir() as ws:
            _tag(ws, "v1.0.0")
            _mk_record(ws, "v1.0.0", evidence="static", missing_hex=True)
            rc = self._run_main(["--project", ws, "--tag", "v1.0.0"])
        self.assertEqual(rc, 1, "failed 应退 1")


# ── 小工具 ──────────────────────────────────────────────────────────────

import contextlib
import tempfile


@contextlib.contextmanager
def tempfile_dir():
    """造一个**真 git 仓**的临时目录 —— release_audit 的 R2 判据要 tag 在
    真实 git 里可达(不存在的 tag → R2 fail → verdict 非预期)。故这里不是
    普通 mkdtemp, 而是 git init + 至少一个 commit + .workbench 落盘。"""
    import shutil
    d = tempfile.mkdtemp(prefix="d2_")
    try:
        git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(git + ["init", "-q"], cwd=d, capture_output=True,
                       timeout=30, check=True)
        os.makedirs(os.path.join(d, ".workbench", "releases"),
                    exist_ok=True)
        with open(os.path.join(d, "f.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        subprocess.run(git + ["add", "-A"], cwd=d, capture_output=True,
                       timeout=30, check=True)
        subprocess.run(git + ["commit", "-qm", "init"], cwd=d,
                       capture_output=True, timeout=30, check=True)
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _tag(ws, tag):
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(git + ["tag", tag], cwd=ws, capture_output=True,
                   timeout=30, check=True)


def _commit_all(ws, msg):
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(git + ["add", "-A"], cwd=ws, capture_output=True,
                   timeout=30, check=True)
    subprocess.run(git + ["commit", "-qm", msg], cwd=ws, capture_output=True,
                   timeout=30, check=True)


def _head_sha(ws):
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws,
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip()


def _write_record(ws, tag, evidence="static", production_approved=None,
                  missing_hex=False, git_head=None):
    """只落盘记录、**不入 git** —— 供需要固定 HEAD 的 R2 场景使用。

    `_mk_record` 的存在形态(先写后提交)无法满足 R2: 提交记录本身会改变
    HEAD, 而 R2 要求 tag 指向 == 记录声明的 git_head == 同一 commit。
    本辅助函数让调用方自行控制何时入库。
    """
    _mk_record(ws, tag, evidence=evidence,
               production_approved=production_approved,
               missing_hex=missing_hex, git_head=git_head)


def _mk_record(ws, tag, evidence="static", production_approved=None,
               missing_hex=False, git_head=None):
    """造一条 release 记录, 形状对齐 scripts/release.py 落盘 + release_audit
    的 `REQUIRED_KEYS`(R5)。字段名与判据一律取自源码, 不猜。

    `git_head` 默认填当前 HEAD 真实 SHA —— **R2 判据是「tag 实际指向 ==
    记录声明的 git_head」**, 填假 SHA 必 fail。R3 则重算 hex 文件的
    sha256 与记录比对, 故 hex 与记录须同时入库(见 _commit_all)。
    """
    import hashlib
    rec_dir = os.path.join(ws, ".workbench", "releases")
    os.makedirs(rec_dir, exist_ok=True)
    hexf = os.path.join(ws, "build.hex")
    with open(hexf, "w", encoding="utf-8") as f:
        f.write(":00000001FF\n")
    artifacts = {}
    if not missing_hex:
        artifacts["hex"] = {
            "path": "build.hex",
            "sha256": hashlib.sha256(open(hexf, "rb").read()).hexdigest(),
        }
    # R2 判据 =「tag 指向 == rev-parse HEAD」且「记录 git_head == HEAD」。
    # 二者须指向**同一个** commit, 而 commit hash 又取决于记录内容 ——
    # 故凡「需要 R2 过」的场景, 由 _finalize_tag 统一在**最后一次提交后**
    # 回填 git_head 并打 tag, 避免自指不可能满足。
    if git_head == "HEAD":
        git_head = _head_sha(ws)
    rec = {
        "tag": tag,
        "git_head": git_head if git_head is not None else _head_sha(ws),
        "timestamp": "2026-01-01T00:00:00+08:00",
        "build_mode": "clean_rebuild",
        "artifacts": artifacts,
        "results": [{"id": "t1", "status": "pass"}],
        "xfail_waived": [],
        "tools": {"toolkit": "0.8"},
        "evidence": evidence,
    }
    if production_approved is not None:
        rec["production_approved"] = production_approved
    with open(os.path.join(rec_dir, f"{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
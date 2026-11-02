r"""F-241: openocd_run 的 main 校验链与结果封装补测。

## 覆盖对象

`scripts/openocd_run.py` 此前 72% 覆盖（2026-11-02 实测）：`main()` 的
参数缺失 / operation_mode 非法 / raw 确认门 / 固件不存在 / run_openocd
错误与成功封装（含 flash 的状态落账与配置写回）未执行。

## 夹具

runtime 依赖模块引用替换；`run_openocd` 返回合成结果，不接探针。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_run  # noqa: E402


def _params(**over):
    base = {"board": "b.cfg", "board_source": "cli",
            "interface": "", "interface_source": "cli",
            "target": "", "target_source": "cli",
            "adapter_speed": "", "adapter_speed_source": "cli",
            "transport": "", "transport_source": "cli"}
    base.update(over)
    return base


def _run_main(argv, *, config=None, params=None, resolve_param=None,
              raw_result=None, file_path=None):
    out, err = io.StringIO(), io.StringIO()
    records = {"state": [], "config": []}
    config = config if config is not None else {}
    params = params if params is not None else _params()
    raw_result = raw_result or {"status": "ok", "summary": "done",
                                "details": {"bytes_written": 16, "speed_kbps": 100}}

    def _rp(name, *_a, **_k):
        if resolve_param:
            return resolve_param(name)
        if name == "exe":
            return ("openocd", "cli")
        if name == "file":
            return (file_path, "cli")
        return (None, "default")

    old = sys.argv
    sys.argv = ["openocd_run.py", *argv]
    try:
        with ExitStack() as stack:
            def patch(obj, name, **kwargs):
                stack.enter_context(mock.patch.object(obj, name, **kwargs))

            ws = stack.enter_context(tempfile.TemporaryDirectory())
            patch(openocd_run, "workspace_root", return_value=ws)
            patch(openocd_run, "default_config_path", return_value="cfg.json")
            patch(openocd_run, "normalize_path", side_effect=str)
            patch(openocd_run, "load_json_file", return_value=config)
            patch(openocd_run, "load_workspace_state", return_value={})
            patch(openocd_run, "_state_lookup", return_value={})
            patch(openocd_run, "load_project_config", return_value={})
            patch(openocd_run, "resolve_openocd_params", return_value=params)
            patch(openocd_run, "resolve_param", side_effect=_rp)
            patch(openocd_run, "run_openocd", return_value=raw_result)
            patch(openocd_run, "update_state_entry",
                  side_effect=lambda *a, **k: records["state"].append(a) or {})
            patch(openocd_run, "save_project_config",
                  side_effect=lambda *a, **k: records["config"].append(a))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            try:
                rc = openocd_run.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue(), records


class ValidationTests(unittest.TestCase):
    def test_missing_param_exits_one(self):
        def _raise(name):
            raise ValueError("exe 缺失")

        rc, _, err, _ = _run_main(["probe"], resolve_param=_raise)
        self.assertEqual(rc, 1)
        self.assertIn("exe 缺失", err)

    def test_invalid_operation_mode_exits_one(self):
        rc, _, err, _ = _run_main(["probe"], config={"operation_mode": "abc"})
        self.assertEqual(rc, 1)
        self.assertIn("operation_mode 非数字", err)

    def test_raw_blocked_at_mode_three(self):
        rc, _, err, _ = _run_main(["raw", "--command", "reset"], config={"operation_mode": 3})
        self.assertEqual(rc, 1)
        self.assertIn("禁止直接执行 raw", err)

    def test_flash_missing_file_exits_one(self):
        rc, _, err, _ = _run_main(
            ["flash"], file_path=os.path.join(tempfile.gettempdir(), "no-fw.hex"))
        self.assertEqual(rc, 1)
        self.assertIn("固件文件不存在", err)


class ResultEnvelopeTests(unittest.TestCase):
    def test_openocd_error_envelope(self):
        raw = {"status": "error", "error": {"code": "boom", "message": "failed"},
               "details": {}}
        rc, out, _, _ = _run_main(["probe", "--json"], raw_result=raw)
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "boom")

    def test_flash_success_persists_state_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = os.path.join(tmp, "fw.hex")
            with open(fw, "w", encoding="utf-8") as fh:
                fh.write(":00000001FF\n")
            rc, out, _, records = _run_main(["flash", "--json"], file_path=fw)
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["metrics"]["bytes_written"], 16)
        self.assertEqual(records["state"][0][0], "last_flash")
        self.assertEqual(records["config"][0][1]["board"], "b.cfg")

    def test_probe_success_text_output(self):
        rc, out, _, records = _run_main(["probe"])
        self.assertIsNone(rc)
        self.assertIn("[probe] done", out)
        self.assertEqual(records["state"], [])

    def test_error_text_output(self):
        raw = {"status": "error", "error": {"code": "boom", "message": "failed"},
               "details": {}}
        rc, _, err, _ = _run_main(["probe"], raw_result=raw)
        self.assertEqual(rc, 1)
        self.assertIn("[probe] 失败 — failed", err)


if __name__ == "__main__":
    unittest.main()

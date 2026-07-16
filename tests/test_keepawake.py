from types import SimpleNamespace

from parts_parser import keepawake


def test_macos_starts_caffeinate_and_terminates_it(monkeypatch):
    calls = []

    class FakeProcess:
        def terminate(self):
            calls.append("terminated")

    def fake_popen(args):
        calls.append(args)
        return FakeProcess()

    monkeypatch.setattr(keepawake.sys, "platform", "darwin")
    monkeypatch.setattr(keepawake.subprocess, "Popen", fake_popen)

    with keepawake.keep_awake():
        calls.append("inside")

    assert calls == [["caffeinate", "-i", "-m"], "inside", "terminated"]


def test_macos_missing_caffeinate_is_a_noop(monkeypatch):
    def missing_caffeinate(args):
        raise FileNotFoundError

    monkeypatch.setattr(keepawake.sys, "platform", "darwin")
    monkeypatch.setattr(keepawake.subprocess, "Popen", missing_caffeinate)

    yielded = False
    with keepawake.keep_awake():
        yielded = True

    assert yielded


def test_unknown_platform_does_not_start_a_process(monkeypatch):
    calls = []
    monkeypatch.setattr(keepawake.sys, "platform", "linux")
    monkeypatch.setattr(keepawake.subprocess, "Popen", lambda args: calls.append(args))

    with keepawake.keep_awake():
        pass

    assert calls == []


def test_windows_sets_and_resets_thread_execution_state(monkeypatch):
    calls = []
    kernel32 = SimpleNamespace(SetThreadExecutionState=calls.append)
    monkeypatch.setattr(keepawake.sys, "platform", "win32")
    monkeypatch.setattr(
        keepawake.ctypes,
        "windll",
        SimpleNamespace(kernel32=kernel32),
        raising=False,
    )

    with keepawake.keep_awake():
        assert calls == [0x80000001]

    assert calls == [0x80000001, 0x80000000]

"""The Home button watchdog: when it decides the TV dropped the Home button service.

Run: .venv/bin/python -m tests.test_home_button
"""
from home_button.__main__ import needs_fix

SVC = "{com.sid.home/com.sid.home.HomeButtonService}"


BOUND = ("Service[label=Hub Home button, feedbackType[FEEDBACK_GENERIC], capabilities=8, "
         "eventTypes=TYPE_WINDOW_STATE_CHANGED, notificationTimeout=100, requestA11yBtn=false]")  # as the TV prints it


def dump(enabled="", bound="", binding="", crashed=""):
    return (f"     Bound services:{{{bound}}}\n     Enabled services:{{{enabled}}}\n"
            f"     Binding services:{{{binding}}}\n     Crashed services:{{{crashed}}}\n")


def run():
    assert not needs_fix(dump(enabled=SVC, bound=BOUND)), "bound: fine"
    assert not needs_fix(dump(enabled=SVC, binding=SVC)), "on its way: wait"
    assert needs_fix(dump(enabled=SVC, crashed=SVC)), "crashed (what the TV does after two kills)"
    assert needs_fix(dump(enabled=SVC)), "enabled but not bound"
    assert not needs_fix(dump(crashed=SVC)), "switched off with tv-app/home off: leave it"
    assert not needs_fix(""), "nothing readable: leave it"
    print("home button: ok")


if __name__ == "__main__":
    run()

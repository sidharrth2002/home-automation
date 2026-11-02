"""The voice service: what it will and won't hand to `say`."""
from announce.__main__ import MAX_CHARS, command

VOICES = {"Daniel", "Moira", "Eddy (English (UK))"}


def run():
    say = lambda data, voice="Daniel": command(data, VOICES, voice)
    assert say({"text": "Welcome home, Sid."}) == ["say", "-v", "Daniel", "--", "Welcome home, Sid."]
    # text is always the last argument, after "--", so it can never be read as an option
    assert say({"text": "-o /tmp/x.aiff hello"})[-2:] == ["--", "-o /tmp/x.aiff hello"]
    assert say({"text": "  lots \n of\twhitespace  "})[-1] == "lots of whitespace"
    assert len(say({"text": "x" * 1000})[-1]) == MAX_CHARS
    assert say({"text": ""}) is None and say({}) is None and say({"text": "   "}) is None
    # voices: an installed one is used, anything else falls back to the system default
    assert say({"text": "hi", "voice": "Moira"})[1:3] == ["-v", "Moira"]
    assert say({"text": "hi", "voice": "Eddy (English (UK))"})[1:3] == ["-v", "Eddy (English (UK))"]
    assert "-v" not in say({"text": "hi", "voice": "Nonexistent; rm -rf /"})
    assert "-v" not in say({"text": "hi"}, voice="NotInstalled")
    # rate is clamped to something sane and ignored if it isn't a number
    assert say({"text": "hi", "rate": 9999})[3:5] == ["-r", "300"] and say({"text": "hi", "rate": 1})[3:5] == ["-r", "90"]
    assert "-r" not in say({"text": "hi", "rate": "fast"})
    print("announce OK")


if __name__ == "__main__":
    run()

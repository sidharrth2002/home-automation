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
    # speaking on the TV: the same voice and safety, rendered to a WAV file instead of played
    from pathlib import Path
    from announce.__main__ import TV_CAST, TV_REMOTE, render_command, tv_ready
    out = render_command({"text": "Welcome home, Sid."}, VOICES, "Daniel", Path("/tmp/x.wav"))
    assert out[:3] == ["say", "-v", "Daniel"] and out[-2:] == ["--", "Welcome home, Sid."]
    assert out[out.index("-o") + 1] == "/tmp/x.wav" and "--file-format=WAVE" in out
    assert render_command({"text": ""}, VOICES, "Daniel", Path("/tmp/x.wav")) is None
    # only cast once the TV says it's on and Cast is reachable
    assert tv_ready({TV_REMOTE: "on", TV_CAST: "off"})
    assert not tv_ready({TV_REMOTE: "off", TV_CAST: "off"})
    assert not tv_ready({TV_REMOTE: "on", TV_CAST: "unavailable"})
    assert not tv_ready({TV_REMOTE: "on"})
    # voice choice: the most natural installed voice wins, ANNOUNCE_VOICE overrides it if installed
    import os
    from announce.__main__ import pick_voice
    os.environ.pop("ANNOUNCE_VOICE", None)
    assert pick_voice({"Daniel", "Moira"}) == "Daniel"
    assert pick_voice({"Daniel", "Jamie (Premium)"}) == "Jamie (Premium)"
    assert pick_voice({"Daniel", "Daniel (Enhanced)", "Serena (Premium)"}) == "Daniel (Enhanced)"
    assert pick_voice({"Moira"}) is None
    os.environ["ANNOUNCE_VOICE"] = "Moira"
    assert pick_voice({"Daniel", "Moira", "Jamie (Premium)"}) == "Moira"
    os.environ["ANNOUNCE_VOICE"] = "Not Installed"
    assert pick_voice({"Daniel", "Jamie (Premium)"}) == "Jamie (Premium)"
    os.environ.pop("ANNOUNCE_VOICE")
    print("announce OK")


if __name__ == "__main__":
    run()

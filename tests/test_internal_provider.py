from ract.providers.internal_provider import InternalProvider


def test_internal_provider_runs_command(tmp_path):
    script = tmp_path / "reverse.py"
    script.write_text(
        "import sys\nprint(sys.stdin.read()[::-1].strip())\n", encoding="utf-8"
    )
    provider = InternalProvider({"command": ["python", str(script)]})
    result = provider.complete([{"role": "user", "content": "hello"}])
    assert result.is_ok()
    assert result.value["choices"][0]["message"]["content"] == "olleh"


def test_internal_provider_no_command():
    provider = InternalProvider({})
    result = provider.complete([{"role": "user", "content": "hi"}])
    assert not result.is_ok()

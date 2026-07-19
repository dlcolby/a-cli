from ai_cli import colors


def test_wrap_adds_color_and_reset():
    result = colors.wrap("hello", colors.USER)
    assert result == f"{colors.USER}hello{colors.RESET}"
    assert "hello" in result  # substring survives wrapping, for callers matching on plain text

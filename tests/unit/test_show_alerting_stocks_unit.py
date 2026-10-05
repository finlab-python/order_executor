"""OrderExecutor.show_alerting_stocks 單元測試（mock 永豐警示股網頁）"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from finlab.online.core.executor import (
    SINOTRADE_ALERTING_URLS,
    SINOTRADE_SYMBOL_COLUMN,
)
from finlab.online.order_executor import OrderExecutor, Position

pytestmark = pytest.mark.unit

ALERTING_HTML = (
    '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">'
    "<html><body><table>"
    f"<tr><th>{SINOTRADE_SYMBOL_COLUMN}</th><th>股票名稱</th></tr>"
    "<tr><td>2330</td><td>台積電</td></tr>"
    "</table></body></html>"
)
CLOSE = pd.DataFrame({"2330": [600.0], "2317": [100.0]})


def _executor(target: dict[str, float]) -> OrderExecutor:
    account = Mock()
    account.get_position.return_value = Position({})
    return OrderExecutor(Position(target), account)


def _run(oe: OrderExecutor, read_html: Mock | None = None) -> Mock:
    get = Mock(return_value=Mock(text=ALERTING_HTML))
    with patch("finlab.online.core.executor.requests.get", get), patch(
        "finlab.online.core.executor.data.get", return_value=CLOSE
    ), patch("finlab.online.core.executor.pd.read_html", read_html or pd.read_html):
        oe.show_alerting_stocks()
    return get


def test_read_html_receives_file_like_not_literal_string() -> None:
    read_html = Mock(return_value=[pd.DataFrame({SINOTRADE_SYMBOL_COLUMN: ["9999"]})])

    get = _run(_executor({"2330": 1}), read_html)

    assert tuple(c.args[0] for c in get.call_args_list) == SINOTRADE_ALERTING_URLS
    for call in read_html.call_args_list:
        source = call.args[0]
        assert not isinstance(source, str)
        assert source.read() == ALERTING_HTML


def test_integer_codes_are_matched_and_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # read_html parses numeric codes as int; they must still match str symbols.
    read_html = Mock(return_value=[pd.DataFrame({SINOTRADE_SYMBOL_COLUMN: [2330, 1101]})])

    _run(_executor({"2330": 1, "2317": -2}), read_html)

    out = capsys.readouterr().out
    assert "買入 2330" in out
    assert "2317" not in out


def test_parses_real_html_table(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("lxml")

    _run(_executor({"2330": 1}))

    assert "買入 2330" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("quantity", "detail"),
    [
        (1, "買入 2330   1.0 張 - 總價約       660000.00"),
        (-1, "賣出 2330  -1.0 張 - 總價約      -540000.00"),
    ],
)
def test_alerting_output_explains_the_warning(
    quantity: float, detail: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(_executor({"2330": quantity, "2317": 2}))

    out = capsys.readouterr().out
    assert out.startswith(
        "=== 處置股/警示股警告 ===\n"
        "以下待下單股票在處置股或信用警示名單中：\n"
    )
    assert detail in out
    assert "2317" not in out
    assert out.endswith("請注意：處置股可能有預收款券、分盤交易等限制。\n")


@pytest.mark.parametrize("target", [{"2317": 1}, {}])
def test_no_alerting_stocks_prints_confirmation(
    target: dict[str, float], capsys: pytest.CaptureFixture[str]
) -> None:
    _run(_executor(target))

    assert capsys.readouterr().out == "待下單股票中無處置股或警示股。\n"

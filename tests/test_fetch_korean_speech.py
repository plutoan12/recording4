"""표본을 고정하는 부분만 잽니다. 네트워크는 타지 않습니다."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"


@pytest.fixture
def fetcher():
    # 이 스크립트는 같은 폴더의 speech_sample을 씁니다. CI는 scripts를 설치하지
    # 않으므로 경로를 직접 넣어 줍니다.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("r4fetch", SCRIPTS / "fetch_korean_speech.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows_for(pages: dict[int, list[str]]):
    """offset마다 돌려줄 문장 목록으로 가짜 rows를 만듭니다."""

    def fake(dataset, config, split, count, offset=0):
        return [
            {"row": {"audio": [{"src": f"https://example/{text}"}], "text": text}}
            for text in pages.get(offset, [])
        ]

    return fake


def test_sample_id_comes_from_the_sentences_only(fetcher):
    first = fetcher.sample_id(["가나", "다라"])
    assert first == fetcher.sample_id(["가나", "다라"])
    # 문장이 하나라도 다르면 다른 표본입니다. 행 번호는 보지 않습니다.
    assert first != fetcher.sample_id(["가나", "다라마"])


def test_find_window_locates_the_recorded_sample_after_rows_move(fetcher, monkeypatch):
    """행 순서가 밀려도 기록해 둔 표본을 찾아야 합니다.

    `--offset 30`으로 받은 문장이 30분 만에 전부 바뀐 적이 있습니다. 그때
    조용히 다른 표본으로 재면, 같은 이름의 조건에서 다른 숫자가 나옵니다.
    """
    wanted = ["둘", "셋"]
    monkeypatch.setattr(fetcher, "rows", rows_for({0: ["하나", "둘", "셋", "넷"]}))
    found = fetcher.find_window("d", "c", "s", 2, fetcher.sample_id(wanted), 100, block=100)
    assert found is not None
    assert [text for _, text in found] == wanted


def test_find_window_gives_up_instead_of_taking_another_sample(fetcher, monkeypatch):
    monkeypatch.setattr(fetcher, "rows", rows_for({0: ["하나", "둘"]}))
    assert fetcher.find_window("d", "c", "s", 2, "없는표본", 100, block=100) is None


def test_find_window_reads_further_pages(fetcher, monkeypatch):
    wanted = ["다섯", "여섯"]
    monkeypatch.setattr(
        fetcher, "rows", rows_for({0: ["하나", "둘"], 2: ["셋", "넷"], 4: ["다섯", "여섯"]})
    )
    found = fetcher.find_window("d", "c", "s", 2, fetcher.sample_id(wanted), 10, block=2)
    assert found is not None
    assert [text for _, text in found] == wanted

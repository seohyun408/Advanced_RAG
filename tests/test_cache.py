import app.cache as cache


class FakeCacheTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["question_hash"]] = dict(Item)

    def get_item(self, Key):
        item = self.items.get(Key["question_hash"])
        return {"Item": item} if item else {}


def _install_fake(monkeypatch):
    table = FakeCacheTable()
    monkeypatch.setattr(cache, "_get_table", lambda: table)
    return table


def test_miss_returns_none(monkeypatch):
    _install_fake(monkeypatch)
    assert cache.get_cached("등기 절차가 어떻게 되나요?") is None


def test_store_then_hit(monkeypatch):
    _install_fake(monkeypatch)
    cache.store_cached("등기 절차가 어떻게 되나요?", "답변입니다", ["planner→rag", "rag"])
    hit = cache.get_cached("등기 절차가 어떻게 되나요?")
    assert hit == {"output": "답변입니다", "route": ["planner→rag", "rag"]}


def test_different_question_is_a_miss(monkeypatch):
    _install_fake(monkeypatch)
    cache.store_cached("질문A", "답변A", ["rag"])
    assert cache.get_cached("질문B") is None


def test_whitespace_and_case_normalized(monkeypatch):
    _install_fake(monkeypatch)
    cache.store_cached("등기 절차가 어떻게 되나요?", "답변", ["rag"])
    # 앞뒤 공백만 다른 경우도 동일 캐시로 처리
    hit = cache.get_cached("  등기 절차가 어떻게 되나요?  ")
    assert hit is not None
    assert hit["output"] == "답변"

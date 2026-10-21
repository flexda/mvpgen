import urllib.parse

from mvpgen.datasample import fetch_samples, samples_dir
from mvpgen.dataspec import DataSpec
from test_dataspec import example

KEY = "ab/c+d=="  # 인코딩되면 모양이 바뀌는 키


def spec() -> DataSpec:
    return DataSpec.model_validate(example())


def test_fetch_masks_key_and_skips_on_resume(tmp_path):
    seen = []

    def fetch(url, headers):
        seen.append(url)
        # 일부 API는 오류나 응답 본문에 키를 그대로 되돌려 준다
        return 200, "application/json", f'{{"echo": "{KEY}", "url": "{url}"}}'.encode()

    result = fetch_samples(spec(), tmp_path, {"AIR_API_KEY": KEY}, fetch)
    assert result.ok and result.calls == 2 and result.files == ["page-1.json", "page-2.json"]
    assert "pageNo=2" in seen[1] and urllib.parse.quote_plus(KEY) in seen[0]
    for p in samples_dir(tmp_path).iterdir():
        text = p.read_text()
        assert KEY not in text and urllib.parse.quote_plus(KEY) not in text, p.name
    assert "serviceKey=***" in (samples_dir(tmp_path) / "README.md").read_text()

    again = fetch_samples(spec(), tmp_path, {"AIR_API_KEY": KEY}, lambda u, h: (_ for _ in ()).throw(AssertionError))
    assert again.ok and again.calls == 0


def test_fetch_failure_is_retried_next_time(tmp_path):
    result = fetch_samples(spec(), tmp_path, {"AIR_API_KEY": KEY}, lambda u, h: (401, "text/xml", b"<err/>"))
    assert not result.ok and "HTTP 401" in result.message and result.calls == 1
    assert not (samples_dir(tmp_path) / "README.md").exists()

    result = fetch_samples(spec(), tmp_path, {"AIR_API_KEY": KEY}, lambda u, h: (200, "", b"<ok/>"))
    assert result.ok and result.files == ["page-1.xml", "page-2.xml"]
    assert not (samples_dir(tmp_path) / "ERROR.md").exists()


def test_fetch_needs_key_and_masks_errors(tmp_path):
    assert "값이 없어" in fetch_samples(spec(), tmp_path, {}, lambda u, h: (200, "", b"")).message

    def boom(url, headers):
        raise OSError(f"cannot reach {url}")

    result = fetch_samples(spec(), tmp_path, {"AIR_API_KEY": KEY}, boom)
    assert not result.ok and urllib.parse.quote_plus(KEY) not in result.message

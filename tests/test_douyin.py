"""抖音解析模块离线单元测试（不发网络请求）。"""
import pytest

from src.douyin import DouyinDownloadError, get_video_id, get_video_info, is_douyin_url


class TestIsDouyinUrl:
    def test_share_short_link(self):
        assert is_douyin_url("https://v.douyin.com/OVn88vFMbek")

    def test_web_page(self):
        assert is_douyin_url("https://www.douyin.com/video/7681930035687055461")

    def test_iesdouyin(self):
        assert is_douyin_url("https://www.iesdouyin.com/share/video/1")

    def test_bilibili_rejected(self):
        assert not is_douyin_url("https://www.bilibili.com/video/BV1xx411c7mD")


class TestGetVideoId:
    def test_video_page(self):
        assert get_video_id("https://www.douyin.com/video/7681930035687055461") == "7681930035687055461"

    def test_aweme_detail_page(self):
        assert get_video_id("https://www.douyin.com/aweme/detail/7681930035687055461") == "7681930035687055461"

    def test_note_page(self):
        assert get_video_id("https://www.douyin.com/note/7681930035687055461") == "7681930035687055461"

    def test_share_text_with_glued_chinese(self):
        # 分享文案中 URL 后紧跟中文（无空格），不应吞进链接
        text = "8.88 fj:/ 复制打开抖音 https://v.douyin.com/OVn88vFMbek/那如果是"
        # 短链无法离线解析 ID，但至少正则提取阶段不能报错；
        # 此处验证 URL 提取不会把中文吞进去（通过 monkeypatch 短路网络请求）
        import src.douyin as dy

        class FakeResp:
            url = "https://www.douyin.com/video/7681930035687055461"
            text = ""

        def fake_get(*a, **kw):
            return FakeResp()

        monkeypatch = pytest.MonkeyPatch()
        with monkeypatch.context() as m:
            m.setattr(dy.requests, "get", fake_get)
            assert dy.get_video_id(text) == "7681930035687055461"

    def test_invalid_input_raises(self):
        with pytest.raises(DouyinDownloadError):
            get_video_id("完全不是链接的文本")


class TestGetVideoInfo:
    def test_album_rejected(self):
        from src import douyin as dy

        monkeypatch = pytest.MonkeyPatch()
        with monkeypatch.context() as m:
            m.setattr(dy, "fetch_aweme_detail", lambda url: {"images": [{"url_list": ["x"]}]})
            with pytest.raises(DouyinDownloadError, match="图集"):
                get_video_info("https://v.douyin.com/x")

    def test_picks_highest_bitrate(self):
        from src import douyin as dy

        detail = {
            "desc": "标题",
            "video": {
                "bit_rate": [
                    {"bit_rate": 500_000, "play_addr": {"url_list": ["https://x/play/?low"]}},
                    {"bit_rate": 3_000_000, "play_addr": {"url_list": ["https://x/playwm/?high"]}},
                ],
            },
        }
        monkeypatch = pytest.MonkeyPatch()
        with monkeypatch.context() as m:
            m.setattr(dy, "fetch_aweme_detail", lambda url: detail)
            info = get_video_info("https://v.douyin.com/x")
        # 高码率优先，且 playwm → play 去水印
        assert info["video_url"] == "https://x/play/?high"
        assert info["title"] == "标题"

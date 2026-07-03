from app.services.mapping_utils import infer_platform_hotel_id, validate_platform_hotel_url


def test_validate_platform_hotel_url_accepts_detail_pages():
    assert validate_platform_hotel_url("ctrip", "https://hotels.ctrip.com/hotel/1234567.html") is None
    assert (
        validate_platform_hotel_url(
            "ctrip",
            "https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=120825712&checkIn=2026-06-27",
        )
        is None
    )
    assert validate_platform_hotel_url("tongcheng", "https://www.ly.com/hotel/8901234/") is None
    assert validate_platform_hotel_url("qunar", "https://hotel.qunar.com/cn/hotel/hangzhou_city/example") is None


def test_infer_platform_hotel_id_accepts_ctrip_detail_query_url():
    assert infer_platform_hotel_id("ctrip", "https://hotels.ctrip.com/hotel/1234567.html") == "1234567"
    assert (
        infer_platform_hotel_id(
            "ctrip",
            "https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=120825712&checkIn=2026-06-27",
        )
        == "120825712"
    )


def test_validate_platform_hotel_url_rejects_placeholders_and_homepages():
    assert validate_platform_hotel_url("ctrip", "https://example.com/hotel/123.html") == "示例 URL 不能用于真实抓取"
    assert validate_platform_hotel_url("qunar", "https://hotel.qunar.com/") == "去哪儿 URL 应为酒店详情页，不能是首页"
    assert validate_platform_hotel_url("tongcheng", "https://hotels.ctrip.com/hotel/1234567.html") == "同程 URL 域名不匹配"

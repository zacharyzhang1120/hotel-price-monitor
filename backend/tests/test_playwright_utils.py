from datetime import date

from app.services.scraper.playwright_utils import (
    extract_cheapest_room_price_candidate,
    extract_lowest_price,
    extract_room_name,
    extract_room_name_for_price,
    extract_room_price_candidates,
    with_check_in_params,
    with_qunar_date_params,
)


def test_extract_lowest_price_supports_common_chinese_price_formats():
    text = """
    豪华大床房
    ￥ 1,288 起
    商务大床房
    ¥688
    会员价 ¥ 599.5
    """
    assert extract_lowest_price(text) == 599.5


def test_extract_lowest_price_filters_unreasonable_values():
    assert extract_lowest_price("积分 ¥9 税费 ¥35") is None
    assert extract_lowest_price("总统套房 ¥12000") is None


def test_extract_room_name_prefers_configured_room_name():
    text = "高级大床房\n豪华大床房（含早）\n¥688"
    assert extract_room_name(text, "豪华大床房（含早）") == "豪华大床房（含早）"
    assert extract_room_name(text, None) == "高级大床房"


def test_extract_room_name_for_price_uses_dynamic_cheapest_room():
    text = """
    大床房
    可订
    ¥399
    高级大床房【零压床垫】
    无早餐
    ¥329
    """

    assert extract_lowest_price(text) == 329
    assert extract_room_name_for_price(text, 329, "大床房") == "高级大床房【零压床垫】"


def test_extract_room_name_can_ignore_default_room_when_dynamic_mode():
    text = """
    大床房
    商务大床房【采光明亮】
    ¥358
    """

    assert extract_room_name(text, "大床房") == "大床房"
    assert extract_room_name(text, "大床房", prefer_default=False) == "商务大床房【采光明亮】"


def test_extract_room_name_for_price_can_reject_policy_prices():
    text = """
    儿童及加床
    退房时间： 13:30前
    ¥120/人
    所有房型不可加床、不提供婴儿床
    """

    assert extract_room_name_for_price(
        text,
        120,
        "大床房",
        fallback_to_default=False,
    ) is None


def test_extract_room_name_for_price_skips_room_table_headers():
    text = """
    高级大床房
    4
    1张1.8米大床
    有窗
    禁烟
    28平方米 | 3-6层
    Wi-Fi免费
    房间详情
    房型摘要
    可住人数
    今日价格
    无早餐
    入住当天18:00前可免费取消
    立即确认
    在线付
    至多3间
    品牌首单
    ¥331
    预订
    """

    assert extract_room_name_for_price(text, 331, "大床房") == "高级大床房"


def test_extract_room_name_for_price_skips_original_price_in_same_rate_plan():
    text = """
    精选标准大床房「助眠床品·采光明亮·静谧空间」
    6
    1张1.8米大床
    有窗
    Wi-Fi免费
    房间详情
    房型摘要
    可住人数
    今日价格
    无早餐
    入住当天23:59前可免费取消
    立即确认
    在线付
    赠送礼品
    特惠一口价
    满减券
    优惠10
    ¥218
    ¥208
    预订
    """

    assert extract_room_name_for_price(text, 208, "默认大床房") == "精选标准大床房「助眠床品·采光明亮·静谧空间」"


def test_extract_room_name_for_price_rejects_top_price_filter_labels():
    text = """
    ¥208
    起
    选择房间
    1晚
    1间, 1成人, 0儿童
    含早餐
    (23)
    大床房
    (17)
    双床房
    (11)
    """

    assert extract_room_name_for_price(text, 208, "默认大床房", fallback_to_default=False) is None


def test_extract_room_name_for_price_rejects_controls_inventory_and_facilities():
    noisy_blocks = [
        "¥206\n起\n选择房间",
        "房量紧张\n¥229\n预订",
        "酒店设施\n洗衣房免费\n¥4000",
        "房间设施中规中矩，窗帘、灯光能智能控制。房内张贴醒目标识，温泉水不错。\n¥120",
        "类型：固定套餐\n¥500",
    ]

    for text in noisy_blocks:
        assert extract_room_name_for_price(
            text,
            extract_lowest_price(text),
            "默认大床房",
            fallback_to_default=False,
        ) is None


def test_extract_room_price_candidates_keep_price_with_same_room_card():
    text = """
    大床房
    1张1.8米大床 28㎡ 2人入住 3-6层
    ¥276起
    品牌首单
    双床房
    2张1.2米单人床 28㎡ 2人入住 3-6层
    ¥294起
    品牌首单
    高级大床房
    1张1.8米大床 28㎡ 2人入住 3-6层
    ¥294起
    品牌首单
    """

    candidate = extract_cheapest_room_price_candidate(text)

    assert candidate is not None
    assert candidate.room == "大床房"
    assert candidate.price == 276


def test_extract_room_price_candidates_ignore_coupon_and_points_prices():
    text = """
    贵宾大床房『天然温泉水淋浴·高空城景』
    1张1.8米大床 28㎡ 2人入住 18-20层
    积分再抵 ¥24
    ¥380
    ¥205起
    一起订专享 4项优惠175
    豪华贵宾大床房『天然温泉水·独享泡浴伴侣体验』
    1张1.8米大床 28㎡ 2人入住 9,16-17层
    积分再抵 ¥24
    ¥447
    ¥241起
    一起订专享 4项优惠206
    标准双床房『室内天然温泉·高楼层·城景』
    2张1.2米单人床 26㎡ 2人入住 10-13层
    ¥146起
    特惠一口价
    """

    candidates = extract_room_price_candidates(text)
    candidate = extract_cheapest_room_price_candidate(text)

    assert ("贵宾大床房『天然温泉水淋浴·高空城景』", 205) in [
        (item.room, item.price) for item in candidates
    ]
    assert candidate is not None
    assert candidate.room == "标准双床房『室内天然温泉·高楼层·城景』"
    assert candidate.price == 146


def test_extract_room_price_candidates_preserve_first_min_price_room():
    text = """
    雅致精选大床房【鲜储冰箱·65寸大屏幕】
    1张1.8米大床 31㎡ 2人入住
    2份早餐 入住当天20:00前可免费取消
    ¥432
    ¥259
    一起订专享 黄金贵宾价 优惠173
    雅致精选双床房【鲜储冰箱·65寸大屏幕】
    2张1.35米双人床 31㎡ 4人入住
    2份早餐 入住当天20:00前可免费取消
    ¥432
    ¥259
    一起订专享 黄金贵宾价 优惠173
    """

    candidate = extract_cheapest_room_price_candidate(text)

    assert candidate is not None
    assert candidate.room == "雅致精选大床房【鲜储冰箱·65寸大屏幕】"
    assert candidate.price == 259


def test_extract_room_price_candidates_keep_member_price_with_discount_label():
    text = """
    高级大床房（65寸投屏电视+小冰箱）
    1张1.8米大床 24-28㎡ 2人入住
    无早餐 入住当天12:00前可免费取消
    ¥350
    ¥343
    亚朵银会员价 | 优惠7
    1份早餐
    ¥398
    ¥390
    亚朵银会员价 | 优惠8
    """

    candidate = extract_cheapest_room_price_candidate(text)

    assert candidate is not None
    assert candidate.room == "高级大床房（65寸投屏电视+小冰箱）"
    assert candidate.price == 343


def test_date_param_helpers_preserve_url_and_set_dates():
    target = with_check_in_params("https://hotels.ctrip.com/hotel/123.html?foo=bar", date(2026, 6, 26))
    assert "foo=bar" in target
    assert "checkIn=2026-06-26" in target
    assert "checkOut=2026-06-27" in target

    qunar = with_qunar_date_params("https://hotel.qunar.com/cn/hotel/demo", date(2026, 6, 26))
    assert "fromDate=2026-06-26" in qunar
    assert "toDate=2026-06-27" in qunar

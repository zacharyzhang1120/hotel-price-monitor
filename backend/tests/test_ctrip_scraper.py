from app.services.scraper.ctrip import CtripScraper
from app.services.scraper.playwright_utils import extract_lowest_price, extract_room_name_for_price


def test_ctrip_room_section_excludes_nearby_hotel_and_policy_prices():
    text = """
    皇马假日大酒店
    ¥218
    ¥208
    起
    选择房间
    房间
    点评
    服务及设施
    政策
    地点
    ¥218
    ¥208
    起
    选择房间
    精选标准大床房「助眠床品·采光明亮·静谧空间」
    1张1.8米大床
    房间详情
    房型摘要
    可住人数
    今日价格
    无早餐
    特惠一口价
    ¥218
    ¥208
    预订
    住客印象
    附近酒店推荐
    ¥108
    专车接机每次¥120
    早餐¥29/人
    """

    section = CtripScraper._extract_room_section_text(text)

    assert "附近酒店推荐" not in section
    assert extract_lowest_price(section) == 208
    assert extract_room_name_for_price(section, 208, "默认大床房") == "精选标准大床房「助眠床品·采光明亮·静谧空间」"

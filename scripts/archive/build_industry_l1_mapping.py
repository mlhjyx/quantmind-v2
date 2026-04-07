"""构建申万二级→一级行业映射，更新symbols表。

不依赖Tushare API（API经常超时），使用硬编码的SW2021标准映射。
申万2021版：31个一级行业，134个二级行业。

用法:
    python scripts/build_industry_l1_mapping.py
"""

import logging

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 申万2021版 二级行业 → 一级行业 完整映射
# 来源: 申万宏源行业分类标准(SW2021)
SW2_TO_SW1 = {
    # 农林牧渔
    "种植业": "农林牧渔", "渔业": "农林牧渔", "林业": "农林牧渔",
    "饲料": "农林牧渔", "农业综合": "农林牧渔", "农药化肥": "农林牧渔",
    "农用机械": "农林牧渔",
    # 基础化工
    "化工原料": "基础化工", "化学制药": "基础化工", "化纤": "基础化工",
    "塑料": "基础化工", "橡胶": "基础化工", "染料涂料": "基础化工",
    "日用化工": "基础化工", "化工机械": "基础化工", "矿物制品": "基础化工",
    # 钢铁
    "普钢": "钢铁", "特种钢": "钢铁", "钢加工": "钢铁",
    # 有色金属
    "铝": "有色金属", "铜": "有色金属", "铅锌": "有色金属",
    "黄金": "有色金属", "小金属": "有色金属",
    # 电子
    "元器件": "电子", "半导体": "电子", "电器仪表": "电子",
    "IT设备": "电子",
    # 汽车
    "汽车整车": "汽车", "汽车配件": "汽车", "汽车服务": "汽车",
    "摩托车": "汽车",
    # 家用电器
    "家用电器": "家用电器", "家居用品": "家用电器",
    # 食品饮料
    "食品": "食品饮料", "白酒": "食品饮料", "啤酒": "食品饮料",
    "红黄酒": "食品饮料", "软饮料": "食品饮料", "乳制品": "食品饮料",
    # 纺织服饰
    "纺织": "纺织服饰", "服饰": "纺织服饰", "纺织机械": "纺织服饰",
    # 轻工制造
    "造纸": "轻工制造", "广告包装": "轻工制造", "文教休闲": "轻工制造",
    "轻工机械": "轻工制造",
    # 医药生物
    "中成药": "医药生物", "生物制药": "医药生物", "医疗保健": "医药生物",
    "医药商业": "医药生物",
    # 公用事业
    "火力发电": "公用事业", "水力发电": "公用事业", "新型电力": "公用事业",
    "供气供热": "公用事业", "水务": "公用事业", "环境保护": "公用事业",
    # 交通运输
    "公路": "交通运输", "铁路": "交通运输", "港口": "交通运输",
    "机场": "交通运输", "航空": "交通运输", "空运": "交通运输",
    "水运": "交通运输", "公共交通": "交通运输", "路桥": "交通运输",
    "仓储物流": "交通运输", "运输设备": "交通运输",
    # 房地产
    "全国地产": "房地产", "区域地产": "房地产", "园区开发": "房地产",
    "房产服务": "房地产",
    # 商贸零售
    "百货": "商贸零售", "超市连锁": "商贸零售", "电器连锁": "商贸零售",
    "商品城": "商贸零售", "其他商业": "商贸零售", "商贸代理": "商贸零售",
    "批发业": "商贸零售",
    # 社会服务
    "酒店餐饮": "社会服务", "旅游景点": "社会服务", "旅游服务": "社会服务",
    # 银行
    "银行": "银行",
    # 非银金融
    "保险": "非银金融", "证券": "非银金融", "多元金融": "非银金融",
    # 综合
    "综合类": "综合",
    # 建筑材料
    "水泥": "建筑材料", "玻璃": "建筑材料", "其他建材": "建筑材料",
    "陶瓷": "建筑材料",
    # 建筑装饰
    "建筑工程": "建筑装饰", "装修装饰": "建筑装饰",
    # 电力设备
    "电气设备": "电力设备",
    # 机械设备
    "工程机械": "机械设备", "机床制造": "机械设备", "机械基件": "机械设备",
    "专用机械": "机械设备",
    # 国防军工
    "船舶": "国防军工",
    # 计算机
    "软件服务": "计算机", "互联网": "计算机",
    # 传媒
    "影视音像": "传媒", "出版业": "传媒",
    # 通信
    "通信设备": "通信", "电信运营": "通信",
    # 煤炭
    "煤炭开采": "煤炭", "焦炭加工": "煤炭",
    # 石油石化
    "石油开采": "石油石化", "石油加工": "石油石化", "石油贸易": "石油石化",
    # 环保
    # (已归入公用事业中的环境保护)
    # 美容护理
    # (新行业，symbols表中可能没有对应的二级)
}


def main():
    conn = psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )
    cur = conn.cursor()

    # Step 1: 加字段
    cur.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS industry_sw_l1 VARCHAR(50)")
    conn.commit()
    logger.info("字段 industry_sw_l1 已确认")

    # Step 2: 获取DB中所有二级行业
    cur.execute(
        "SELECT DISTINCT industry_sw1 FROM symbols "
        "WHERE market = 'astock' AND industry_sw1 IS NOT NULL"
    )
    db_industries = [r[0] for r in cur.fetchall()]
    logger.info("DB中申万二级行业: %d个", len(db_industries))

    # Step 3: 批量映射
    updated = 0
    unmapped = []
    for sw2_name in db_industries:
        if sw2_name == "nan":
            continue
        sw1_name = SW2_TO_SW1.get(sw2_name)
        if sw1_name:
            cur.execute(
                "UPDATE symbols SET industry_sw_l1 = %s "
                "WHERE industry_sw1 = %s AND market = 'astock'",
                (sw1_name, sw2_name),
            )
            updated += cur.rowcount
        else:
            unmapped.append(sw2_name)

    conn.commit()
    logger.info("已映射: %d只股票", updated)

    if unmapped:
        logger.warning("未映射的二级行业(%d个): %s", len(unmapped), unmapped)

    # Step 4: 验证
    cur.execute(
        "SELECT COUNT(*) FROM symbols WHERE market='astock' AND industry_sw_l1 IS NOT NULL"
    )
    mapped_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM symbols WHERE market='astock'")
    total_count = cur.fetchone()[0]
    logger.info("覆盖率: %d/%d (%.1f%%)", mapped_count, total_count, mapped_count / total_count * 100)

    # Step 5: L1分布
    cur.execute(
        "SELECT industry_sw_l1, COUNT(*) FROM symbols "
        "WHERE market='astock' AND industry_sw_l1 IS NOT NULL "
        "GROUP BY industry_sw_l1 ORDER BY COUNT(*) DESC"
    )
    logger.info("申万一级行业分布:")
    for name, count in cur.fetchall():
        logger.info("  %-10s: %4d只", name, count)

    # Step 6: 建映射表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sw_industry_mapping (
            sw_l2_name VARCHAR(50) PRIMARY KEY,
            sw_l1_name VARCHAR(50) NOT NULL,
            sw_l1_code VARCHAR(20) DEFAULT '',
            sw_l2_code VARCHAR(20) DEFAULT ''
        )
    """)
    for sw2, sw1 in SW2_TO_SW1.items():
        cur.execute(
            "INSERT INTO sw_industry_mapping (sw_l2_name, sw_l1_name) "
            "VALUES (%s, %s) ON CONFLICT (sw_l2_name) DO UPDATE SET sw_l1_name = EXCLUDED.sw_l1_name",
            (sw2, sw1),
        )
    conn.commit()
    logger.info("sw_industry_mapping表: %d行", len(SW2_TO_SW1))

    conn.close()
    logger.info("Done")


if __name__ == "__main__":
    main()

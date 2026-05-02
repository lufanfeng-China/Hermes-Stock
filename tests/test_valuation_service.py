import unittest
from unittest import mock

from app.valuation.context import ValuationContext
from app.valuation.models import ValuationResult, ViewResult


class ValuationModelTests(unittest.TestCase):
    def test_view_result_fields_exist(self) -> None:
        row = ViewResult(view_name="earnings", low=1.0, mid=2.0, high=3.0, is_valid=True)
        self.assertEqual("earnings", row.view_name)
        self.assertEqual(2.0, row.mid)
        self.assertTrue(row.is_valid)

    def test_context_and_result_hold_required_fields(self) -> None:
        context = ValuationContext(
            market="sz",
            symbol="000333",
            stock_name="美的集团",
            valuation_template_id="consumer_quality",
            industry_level_1_name="家电",
            industry_level_2_name="白色家电",
            valuation_date="2026-05-01",
            latest_report_date="20260331",
            current_price=81.10,
            market_cap=5642.17,
            dynamic_pe=14.8,
            short_history=False,
            structural_break_date=None,
            rate_regime="neutral",
        )
        result = ValuationResult(
            market="sz",
            symbol="000333",
            stock_name="美的集团",
            version="valuation_v1",
            valuation_date="2026-05-01",
            output_level="standard",
            dominant_view="earnings",
            final_low=73.2,
            final_mid=84.5,
            final_high=95.8,
            current_price=81.10,
            upside_mid_pct=4.19,
            margin_of_safety_pct=-9.74,
            valuation_template_id=context.valuation_template_id,
            methodology_note="盈利/资产/收入三视角融合；行业模板=consumer_quality",
        )
        self.assertEqual("consumer_quality", context.valuation_template_id)
        self.assertEqual("standard", result.output_level)


class ValuationConfigTests(unittest.TestCase):
    def test_resolve_template_prefers_explicit_template_then_fallback(self) -> None:
        from app.valuation.config import resolve_valuation_template_id

        self.assertEqual(
            "consumer_quality",
            resolve_valuation_template_id("consumer_quality", "家电", "白色家电"),
        )
        self.assertEqual(
            "white_appliance",
            resolve_valuation_template_id(None, "家电", "白色家电"),
        )
        self.assertEqual(
            "premium_liquor",
            resolve_valuation_template_id(None, "食品饮料", "酿酒"),
        )
        self.assertEqual(
            "power_battery",
            resolve_valuation_template_id(None, "电力设备", "电池"),
        )
        self.assertEqual(
            "telecom_operator",
            resolve_valuation_template_id(None, "通信", "电信服务"),
        )
        self.assertEqual(
            "medical_device",
            resolve_valuation_template_id(None, "医药医疗", "医疗器械"),
        )
        self.assertEqual(
            "innovative_pharma",
            resolve_valuation_template_id(None, "医药医疗", "化学制药"),
        )
        self.assertEqual(
            "automation_equipment",
            resolve_valuation_template_id(None, "机械设备", "自动化设备"),
        )
        self.assertEqual(
            "engineering_machinery",
            resolve_valuation_template_id(None, "机械设备", "工程机械"),
        )
        self.assertEqual(
            "military_electronics",
            resolve_valuation_template_id(None, "国防军工", "军工电子"),
        )
        self.assertEqual(
            "aviation_equipment",
            resolve_valuation_template_id(None, "国防军工", "航空装备"),
        )
        self.assertEqual(
            "semiconductor_growth",
            resolve_valuation_template_id(None, "电子", "半导体"),
        )
        self.assertEqual(
            "consumer_electronics",
            resolve_valuation_template_id(None, "电子", "消费电子"),
        )
        self.assertEqual(
            "optical_photonics",
            resolve_valuation_template_id(None, "电子", "光学光电"),
        )
        self.assertEqual(
            "rare_metal",
            resolve_valuation_template_id(None, "有色", "稀有金属"),
        )
        self.assertEqual(
            "energy_metal",
            resolve_valuation_template_id(None, "有色", "能源金属"),
        )
        self.assertEqual(
            "auto_parts",
            resolve_valuation_template_id(None, "汽车", "汽车零部件"),
        )
        self.assertEqual(
            "general_equipment",
            resolve_valuation_template_id(None, "机械设备", "通用设备"),
        )
        self.assertEqual(
            "specialized_equipment",
            resolve_valuation_template_id(None, "机械设备", "专用设备"),
        )
        self.assertEqual(
            "software_service",
            resolve_valuation_template_id(None, "计算机", "软件服务"),
        )
        self.assertEqual(
            "power_grid_equipment",
            resolve_valuation_template_id(None, "电力设备", "电网设备"),
        )
        self.assertEqual(
            "telecom_equipment",
            resolve_valuation_template_id(None, "通信", "通信设备"),
        )
        self.assertEqual(
            "household_goods",
            resolve_valuation_template_id(None, "轻工制造", "家居用品"),
        )
        self.assertEqual(
            "food_processing",
            resolve_valuation_template_id(None, "食品饮料", "食品加工"),
        )
        self.assertEqual(
            "beverage_dairy",
            resolve_valuation_template_id(None, "食品饮料", "饮料乳品"),
        )
        self.assertEqual(
            "medical_service",
            resolve_valuation_template_id(None, "医药医疗", "医疗服务"),
        )
        self.assertEqual(
            "traditional_chinese_medicine",
            resolve_valuation_template_id(None, "医药医疗", "中药"),
        )
        self.assertEqual(
            "chemical_raw_material",
            resolve_valuation_template_id(None, "化工", "化学原料"),
        )
        self.assertEqual(
            "chemical_products",
            resolve_valuation_template_id(None, "化工", "化学制品"),
        )
        self.assertEqual(
            "chemical_fiber",
            resolve_valuation_template_id(None, "化工", "化纤"),
        )
        self.assertEqual(
            "biotech",
            resolve_valuation_template_id(None, "医药医疗", "生物制品"),
        )
        self.assertEqual(
            "pharma_distribution",
            resolve_valuation_template_id(None, "医药医疗", "医药商业"),
        )
        self.assertEqual(
            "photovoltaic_equipment",
            resolve_valuation_template_id(None, "电力设备", "光伏设备"),
        )
        self.assertEqual(
            "wind_power_equipment",
            resolve_valuation_template_id(None, "电力设备", "风电设备"),
        )
        self.assertEqual(
            "it_hardware",
            resolve_valuation_template_id(None, "计算机", "IT设备"),
        )
        self.assertEqual(
            "electronic_components",
            resolve_valuation_template_id(None, "电子", "元器件"),
        )
        self.assertEqual(
            "electric_utility",
            resolve_valuation_template_id(None, "公用事业", "电力"),
        )
        self.assertEqual(
            "environmental_services",
            resolve_valuation_template_id(None, "环保", "环境治理"),
        )
        self.assertEqual(
            "plastic_products",
            resolve_valuation_template_id(None, "化工", "塑料"),
        )
        self.assertEqual(
            "property_development",
            resolve_valuation_template_id(None, "房地产", "房地产开发"),
        )
        self.assertEqual(
            "agrochemical",
            resolve_valuation_template_id(None, "化工", "农用化工"),
        )
        self.assertEqual(
            "apparel_home_textile",
            resolve_valuation_template_id(None, "纺织服饰", "服装家纺"),
        )
        self.assertEqual(
            "misc_electronics",
            resolve_valuation_template_id(None, "电子", "其他电子"),
        )
        self.assertEqual(
            "packaging_printing",
            resolve_valuation_template_id(None, "轻工制造", "包装印刷"),
        )
        self.assertEqual(
            "logistics",
            resolve_valuation_template_id(None, "交通运输", "物流"),
        )
        self.assertEqual(
            "professional_engineering",
            resolve_valuation_template_id(None, "建筑", "专业工程"),
        )
        self.assertEqual(
            "engineering_consulting",
            resolve_valuation_template_id(None, "建筑", "工程咨询服务"),
        )
        self.assertEqual(
            "infrastructure_construction",
            resolve_valuation_template_id(None, "建筑", "基础建设"),
        )
        self.assertEqual(
            "decorative_building_materials",
            resolve_valuation_template_id(None, "建材", "装饰建材"),
        )
        self.assertEqual(
            "general_retail",
            resolve_valuation_template_id(None, "商贸", "一般零售"),
        )
        self.assertEqual(
            "cloud_service",
            resolve_valuation_template_id(None, "计算机", "云服务"),
        )
        self.assertEqual(
            "professional_services",
            resolve_valuation_template_id(None, "社会服务", "专业服务"),
        )
        self.assertEqual(
            "shipping_ports",
            resolve_valuation_template_id(None, "交通运输", "航运港口"),
        )
        self.assertEqual(
            "textile_manufacturing",
            resolve_valuation_template_id(None, "纺织服饰", "纺织制造"),
        )
        self.assertEqual(
            "gas_utility",
            resolve_valuation_template_id(None, "公用事业", "燃气"),
        )
        self.assertEqual(
            "ad_marketing",
            resolve_valuation_template_id(None, "传媒", "广告营销"),
        )
        self.assertEqual(
            "paper_products",
            resolve_valuation_template_id(None, "轻工制造", "造纸"),
        )
        self.assertEqual(
            "publishing",
            resolve_valuation_template_id(None, "传媒", "出版业"),
        )
        self.assertEqual(
            "home_appliance_components",
            resolve_valuation_template_id(None, "家电", "家电零部件"),
        )
        self.assertEqual(
            "environmental_equipment",
            resolve_valuation_template_id(None, "环保", "环保设备"),
        )
        self.assertEqual(
            "rail_transit_equipment",
            resolve_valuation_template_id(None, "机械设备", "轨交设备"),
        )
        self.assertEqual(
            "highway_rail_operator",
            resolve_valuation_template_id(None, "交通运输", "公路铁路"),
        )
        self.assertEqual(
            "motor_manufacturing",
            resolve_valuation_template_id(None, "电力设备", "电机制造"),
        )
        self.assertEqual(
            "tourism_services",
            resolve_valuation_template_id(None, "社会服务", "旅游"),
        )
        self.assertEqual(
            "small_appliance",
            resolve_valuation_template_id(None, "家电", "小家电"),
        )
        self.assertEqual(
            "coal_mining",
            resolve_valuation_template_id(None, "煤炭", "煤炭开采"),
        )
        self.assertEqual(
            "gaming_media",
            resolve_valuation_template_id(None, "传媒", "游戏"),
        )
        self.assertEqual(
            "other_power_equipment",
            resolve_valuation_template_id(None, "电力设备", "其他发电设备"),
        )
        self.assertEqual(
            "steel_standard",
            resolve_valuation_template_id(None, "钢铁", "普钢"),
        )
        self.assertEqual(
            "interior_decoration",
            resolve_valuation_template_id(None, "建筑", "装修装饰"),
        )
        self.assertEqual(
            "cement_materials",
            resolve_valuation_template_id(None, "建材", "水泥"),
        )
        self.assertEqual(
            "rubber_materials",
            resolve_valuation_template_id(None, "化工", "橡胶"),
        )
        self.assertEqual(
            "trade_distribution",
            resolve_valuation_template_id(None, "商贸", "贸易"),
        )
        self.assertEqual(
            "livestock_breeding",
            resolve_valuation_template_id(None, "农林牧渔", "养殖业"),
        )
        self.assertEqual(
            "feed_processing",
            resolve_valuation_template_id(None, "农林牧渔", "饲料"),
        )
        self.assertEqual(
            "ecommerce_service",
            resolve_valuation_template_id(None, "商贸", "电子商务"),
        )
        self.assertEqual(
            "agri_processing",
            resolve_valuation_template_id(None, "农林牧渔", "农产品加工"),
        )
        self.assertEqual(
            "seed_planting",
            resolve_valuation_template_id(None, "农林牧渔", "种植业"),
        )
        self.assertEqual(
            "film_cinema",
            resolve_valuation_template_id(None, "传媒", "影视院线"),
        )
        self.assertEqual(
            "snack_food",
            resolve_valuation_template_id(None, "食品饮料", "休闲食品"),
        )
        self.assertEqual(
            "condiment",
            resolve_valuation_template_id(None, "食品饮料", "调味品"),
        )
        self.assertEqual(
            "education_training",
            resolve_valuation_template_id(None, "社会服务", "教育培训"),
        )
        self.assertEqual(
            "leisure_culture_goods",
            resolve_valuation_template_id(None, "轻工制造", "文娱用品"),
        )
        self.assertEqual(
            "daily_chemical",
            resolve_valuation_template_id(None, "化工", "日用化工"),
        )
        self.assertEqual(
            "bank",
            resolve_valuation_template_id(None, "银行", "全国性银行"),
        )
        self.assertEqual(
            "generic_equity",
            resolve_valuation_template_id(None, "综合", "综合类"),
        )

    def test_refine_template_splits_engineering_machinery_by_style(self) -> None:
        from app.valuation.config import refine_valuation_template_id

        self.assertEqual(
            'construction_machinery',
            refine_valuation_template_id('engineering_machinery', '工程机械', {'dynamic_pe': 21.1}),
        )
        self.assertEqual(
            'engineering_machinery',
            refine_valuation_template_id('engineering_machinery', '工程机械', {'dynamic_pe': 50.7}),
        )
        self.assertEqual(
            'military_info_system',
            refine_valuation_template_id('military_electronics', '军工电子', {'dynamic_pe': None, 'eps': -0.11}),
        )
        self.assertEqual(
            'display_panel',
            refine_valuation_template_id('optical_photonics', '光学光电', {'dynamic_pe': 24.0, 'debt_ratio': 51.9}),
        )
        self.assertEqual(
            'consumer_assembly',
            refine_valuation_template_id('consumer_electronics', '消费电子', {'dynamic_pe': 24.5, 'revenue_per_share': 174.4}),
        )
        self.assertEqual(
            'aerospace_material',
            refine_valuation_template_id('aviation_equipment', '航空装备', {'dynamic_pe': 44.3, 'revenue_per_share': 6.6}),
        )
        self.assertEqual(
            'high_temp_alloy',
            refine_valuation_template_id('aviation_equipment', '航空装备', {'dynamic_pe': 68.0, 'revenue_per_share': 4.8}),
        )
        self.assertEqual(
            'testing_inspection_service',
            refine_valuation_template_id('professional_services', '专业服务', {'revenue_per_share': 4.1, 'debt_ratio': 21.7}),
        )
        self.assertEqual(
            'human_resource_service',
            refine_valuation_template_id('professional_services', '专业服务', {'revenue_per_share': 76.3, 'debt_ratio': 46.4}),
        )
        self.assertEqual(
            'textile_quality_manufacturing',
            refine_valuation_template_id('textile_manufacturing', '纺织制造', {'dynamic_pe': 18.5, 'profit_growth': -7.2}),
        )
        self.assertEqual(
            'textile_value_manufacturing',
            refine_valuation_template_id('textile_manufacturing', '纺织制造', {'dynamic_pe': 9.9, 'profit_growth': -36.9}),
        )
        self.assertEqual(
            'port_operator',
            refine_valuation_template_id('shipping_ports', '航运港口', {'revenue_growth': 0.0, 'debt_ratio': 0.0, 'revenue_per_share': 1.7}),
        )
        self.assertEqual(
            'shipping_carrier',
            refine_valuation_template_id('shipping_ports', '航运港口', {'revenue_growth': 26.9, 'debt_ratio': 45.5, 'revenue_per_share': 4.7}),
        )
        self.assertEqual(
            'media_ad_platform',
            refine_valuation_template_id('ad_marketing', '广告营销', {'revenue_per_share': 0.9, 'debt_ratio': 25.3}),
        )
        self.assertEqual(
            'digital_marketing_agency',
            refine_valuation_template_id('ad_marketing', '广告营销', {'revenue_per_share': 20.4, 'debt_ratio': 70.5}),
        )
        self.assertEqual(
            'appliance_precision_components',
            refine_valuation_template_id('home_appliance_components', '家电零部件', {'dynamic_pe': 46.5, 'debt_ratio': 33.3, 'revenue_per_share': 7.4}),
        )
        self.assertEqual(
            'appliance_manufacturing_components',
            refine_valuation_template_id('home_appliance_components', '家电零部件', {'dynamic_pe': 137.7, 'debt_ratio': 66.4, 'revenue_per_share': 19.1}),
        )
        self.assertEqual(
            'motor_control_components',
            refine_valuation_template_id('motor_manufacturing', '电机制造', {'dynamic_pe': 46.8, 'revenue_per_share': 29.3}),
        )
        self.assertEqual(
            'motor_manufacturing',
            refine_valuation_template_id('motor_manufacturing', '电机制造', {'dynamic_pe': 17.9, 'revenue_per_share': 6.4}),
        )
        self.assertEqual(
            'kitchen_appliance_brand',
            refine_valuation_template_id('small_appliance', '小家电', {'revenue_per_share': 28.5, 'debt_ratio': 48.8}),
        )
        self.assertEqual(
            'export_small_appliance',
            refine_valuation_template_id('small_appliance', '小家电', {'revenue_per_share': 19.5, 'debt_ratio': 40.2}),
        )
        self.assertEqual(
            'premium_game',
            refine_valuation_template_id('gaming_media', '游戏', {'revenue_per_share': 96.0, 'debt_ratio': 21.6}),
        )
        self.assertEqual(
            'gaming_media',
            refine_valuation_template_id('gaming_media', '游戏', {'revenue_per_share': 7.0, 'debt_ratio': 34.8}),
        )
        self.assertEqual(
            'commodity_trading',
            refine_valuation_template_id('trade_distribution', '贸易', {'revenue_per_share': 47.6, 'debt_ratio': 68.6}),
        )
        self.assertEqual(
            'export_supply_chain',
            refine_valuation_template_id('trade_distribution', '贸易', {'revenue_per_share': 24.7, 'debt_ratio': 48.5}),
        )
        self.assertEqual(
            'hog_breeding',
            refine_valuation_template_id('livestock_breeding', '养殖业', {'revenue_per_share': 23.9, 'debt_ratio': 50.7}),
        )
        self.assertEqual(
            'poultry_breeding',
            refine_valuation_template_id('livestock_breeding', '养殖业', {'revenue_per_share': 2.8, 'debt_ratio': 36.2}),
        )
        self.assertEqual(
            'film_content_production',
            refine_valuation_template_id('film_cinema', '影视院线', {'revenue_per_share': 0.43, 'debt_ratio': 9.1}),
        )
        self.assertEqual(
            'film_cinema',
            refine_valuation_template_id('film_cinema', '影视院线', {'revenue_per_share': 5.18, 'debt_ratio': 66.2}),
        )
        self.assertEqual(
            'distressed_education',
            refine_valuation_template_id('education_training', '教育培训', {'revenue_per_share': 0.37, 'debt_ratio': 85.9, 'eps': 0.01}),
        )
        self.assertEqual(
            'education_training',
            refine_valuation_template_id('education_training', '教育培训', {'revenue_per_share': 27.2, 'debt_ratio': 76.2, 'eps': 1.78}),
        )
        self.assertEqual(
            'carbon_black_materials',
            refine_valuation_template_id('rubber_materials', '橡胶', {'revenue_per_share': 11.4, 'debt_ratio': 70.5}),
        )
        self.assertEqual(
            'consumer_oil_processing',
            refine_valuation_template_id('agri_processing', '农产品加工', {'revenue_per_share': 46.4, 'debt_ratio': 54.0}),
        )
        self.assertEqual(
            'grain_storage_processing',
            refine_valuation_template_id('agri_processing', '农产品加工', {'revenue_per_share': 4.7, 'debt_ratio': 32.4}),
        )

    def test_template_defaults_expose_refined_sector_multiples(self) -> None:
        from app.valuation.config import get_template_defaults

        self.assertEqual({'pe': 16.0, 'pb': 2.5, 'ps': 1.4}, get_template_defaults('white_appliance'))
        self.assertEqual({'pe': 26.0, 'pb': 6.0, 'ps': 6.0}, get_template_defaults('premium_liquor'))
        self.assertEqual({'pe': 26.0, 'pb': 5.0, 'ps': 4.2}, get_template_defaults('power_battery'))
        self.assertEqual({'pe': 16.0, 'pb': 1.5, 'ps': 2.0}, get_template_defaults('telecom_operator'))
        self.assertEqual({'pe': 28.0, 'pb': 4.2, 'ps': 6.3}, get_template_defaults('medical_device'))
        self.assertEqual({'pe': 44.0, 'pb': 5.6, 'ps': 11.0}, get_template_defaults('innovative_pharma'))
        self.assertEqual({'pe': 38.0, 'pb': 4.8, 'ps': 4.0}, get_template_defaults('automation_equipment'))
        self.assertEqual({'pe': 45.0, 'pb': 7.0, 'ps': 10.0}, get_template_defaults('engineering_machinery'))
        self.assertEqual({'pe': 22.0, 'pb': 2.1, 'ps': 2.1}, get_template_defaults('construction_machinery'))
        self.assertEqual({'pe': 40.0, 'pb': 3.0, 'ps': 3.5}, get_template_defaults('military_electronics'))
        self.assertEqual({'pe': 50.0, 'pb': 4.8, 'ps': 10.0}, get_template_defaults('military_info_system'))
        self.assertEqual({'pe': 40.0, 'pb': 5.0, 'ps': 3.2}, get_template_defaults('aviation_equipment'))
        self.assertEqual({'pe': 42.0, 'pb': 1.6, 'ps': 1.8}, get_template_defaults('aerospace_material'))
        self.assertEqual({'pe': 68.0, 'pb': 4.2, 'ps': 8.0}, get_template_defaults('high_temp_alloy'))
        self.assertEqual({'pe': 78.0, 'pb': 9.0, 'ps': 18.0}, get_template_defaults('semiconductor_growth'))
        self.assertEqual({'pe': 30.0, 'pb': 4.2, 'ps': 1.5}, get_template_defaults('consumer_electronics'))
        self.assertEqual({'pe': 24.0, 'pb': 1.8, 'ps': 0.55}, get_template_defaults('consumer_assembly'))
        self.assertEqual({'pe': 38.0, 'pb': 4.5, 'ps': 6.5}, get_template_defaults('optical_photonics'))
        self.assertEqual({'pe': 18.0, 'pb': 0.85, 'ps': 0.6}, get_template_defaults('display_panel'))
        self.assertEqual({'pe': 17.0, 'pb': 3.7, 'ps': 1.7}, get_template_defaults('rare_metal'))
        self.assertEqual({'pe': 48.0, 'pb': 3.6, 'ps': 6.2}, get_template_defaults('energy_metal'))
        self.assertEqual({'pe': 24.0, 'pb': 2.3, 'ps': 1.4}, get_template_defaults('auto_parts'))
        self.assertEqual({'pe': 22.0, 'pb': 2.6, 'ps': 2.0}, get_template_defaults('general_equipment'))
        self.assertEqual({'pe': 26.0, 'pb': 3.1, 'ps': 2.8}, get_template_defaults('specialized_equipment'))
        self.assertEqual({'pe': 42.0, 'pb': 6.0, 'ps': 8.0}, get_template_defaults('software_service'))
        self.assertEqual({'pe': 20.0, 'pb': 2.2, 'ps': 1.8}, get_template_defaults('power_grid_equipment'))
        self.assertEqual({'pe': 30.0, 'pb': 3.0, 'ps': 2.4}, get_template_defaults('telecom_equipment'))
        self.assertEqual({'pe': 22.0, 'pb': 2.1, 'ps': 1.5}, get_template_defaults('household_goods'))
        self.assertEqual({'pe': 24.0, 'pb': 3.5, 'ps': 1.9}, get_template_defaults('food_processing'))
        self.assertEqual({'pe': 28.0, 'pb': 5.0, 'ps': 2.8}, get_template_defaults('beverage_dairy'))
        self.assertEqual({'pe': 26.0, 'pb': 3.4, 'ps': 2.6}, get_template_defaults('medical_service'))
        self.assertEqual({'pe': 27.0, 'pb': 3.8, 'ps': 2.5}, get_template_defaults('traditional_chinese_medicine'))
        self.assertEqual({'pe': 18.0, 'pb': 1.9, 'ps': 1.15}, get_template_defaults('chemical_raw_material'))
        self.assertEqual({'pe': 24.0, 'pb': 2.4, 'ps': 1.7}, get_template_defaults('chemical_products'))
        self.assertEqual({'pe': 14.0, 'pb': 1.1, 'ps': 0.85}, get_template_defaults('chemical_fiber'))
        self.assertEqual({'pe': 32.0, 'pb': 3.0, 'ps': 2.8}, get_template_defaults('biotech'))
        self.assertEqual({'pe': 14.0, 'pb': 1.5, 'ps': 0.16}, get_template_defaults('pharma_distribution'))
        self.assertEqual({'pe': 22.0, 'pb': 1.8, 'ps': 1.15}, get_template_defaults('photovoltaic_equipment'))
        self.assertEqual({'pe': 24.0, 'pb': 1.9, 'ps': 1.4}, get_template_defaults('wind_power_equipment'))
        self.assertEqual({'pe': 20.0, 'pb': 1.6, 'ps': 1.2}, get_template_defaults('it_hardware'))
        self.assertEqual({'pe': 34.0, 'pb': 3.6, 'ps': 2.2}, get_template_defaults('electronic_components'))
        self.assertEqual({'pe': 20.0, 'pb': 2.8, 'ps': 2.0}, get_template_defaults('electric_utility'))
        self.assertEqual({'pe': 30.0, 'pb': 1.45, 'ps': 2.6}, get_template_defaults('environmental_services'))
        self.assertEqual({'pe': 18.0, 'pb': 1.7, 'ps': 1.1}, get_template_defaults('plastic_products'))
        self.assertEqual({'pe': 6.0, 'pb': 0.22, 'ps': 0.18}, get_template_defaults('property_development'))
        self.assertEqual({'pe': 18.0, 'pb': 1.8, 'ps': 1.3}, get_template_defaults('agrochemical'))
        self.assertEqual({'pe': 20.0, 'pb': 1.8, 'ps': 1.2}, get_template_defaults('apparel_home_textile'))
        self.assertEqual({'pe': 28.0, 'pb': 3.2, 'ps': 2.6}, get_template_defaults('misc_electronics'))
        self.assertEqual({'pe': 16.0, 'pb': 1.8, 'ps': 1.0}, get_template_defaults('packaging_printing'))
        self.assertEqual({'pe': 16.0, 'pb': 1.5, 'ps': 1.1}, get_template_defaults('logistics'))
        self.assertEqual({'pe': 14.0, 'pb': 1.2, 'ps': 0.8}, get_template_defaults('professional_engineering'))
        self.assertEqual({'pe': 18.0, 'pb': 1.8, 'ps': 1.5}, get_template_defaults('engineering_consulting'))
        self.assertEqual({'pe': 5.5, 'pb': 0.2, 'ps': 0.12}, get_template_defaults('infrastructure_construction'))
        self.assertEqual({'pe': 20.0, 'pb': 2.2, 'ps': 1.6}, get_template_defaults('decorative_building_materials'))
        self.assertEqual({'pe': 18.0, 'pb': 1.4, 'ps': 0.75}, get_template_defaults('general_retail'))
        self.assertEqual({'pe': 36.0, 'pb': 3.8, 'ps': 3.0}, get_template_defaults('cloud_service'))
        self.assertEqual({'pe': 24.0, 'pb': 2.6, 'ps': 1.4}, get_template_defaults('professional_services'))
        self.assertEqual({'pe': 30.0, 'pb': 3.6, 'ps': 1.3}, get_template_defaults('testing_inspection_service'))
        self.assertEqual({'pe': 14.0, 'pb': 1.5, 'ps': 0.3}, get_template_defaults('human_resource_service'))
        self.assertEqual({'pe': 16.0, 'pb': 1.6, 'ps': 1.3}, get_template_defaults('shipping_ports'))
        self.assertEqual({'pe': 12.0, 'pb': 0.85, 'ps': 1.0}, get_template_defaults('port_operator'))
        self.assertEqual({'pe': 22.0, 'pb': 2.3, 'ps': 2.8}, get_template_defaults('shipping_carrier'))
        self.assertEqual({'pe': 14.0, 'pb': 1.2, 'ps': 0.9}, get_template_defaults('textile_manufacturing'))
        self.assertEqual({'pe': 18.0, 'pb': 2.4, 'ps': 2.2}, get_template_defaults('textile_quality_manufacturing'))
        self.assertEqual({'pe': 10.0, 'pb': 0.55, 'ps': 0.9}, get_template_defaults('textile_value_manufacturing'))
        self.assertEqual({'pe': 16.0, 'pb': 1.2, 'ps': 0.45}, get_template_defaults('gas_utility'))
        self.assertEqual({'pe': 22.0, 'pb': 2.0, 'ps': 1.1}, get_template_defaults('ad_marketing'))
        self.assertEqual({'pe': 28.0, 'pb': 5.7, 'ps': 6.0}, get_template_defaults('media_ad_platform'))
        self.assertEqual({'pe': 18.0, 'pb': 2.0, 'ps': 0.85}, get_template_defaults('digital_marketing_agency'))
        self.assertEqual({'pe': 16.0, 'pb': 1.0, 'ps': 0.75}, get_template_defaults('paper_products'))
        self.assertEqual({'pe': 18.0, 'pb': 0.8, 'ps': 1.3}, get_template_defaults('publishing'))
        self.assertEqual({'pe': 22.0, 'pb': 2.0, 'ps': 1.2}, get_template_defaults('home_appliance_components'))
        self.assertEqual({'pe': 42.0, 'pb': 6.0, 'ps': 6.0}, get_template_defaults('appliance_precision_components'))
        self.assertEqual({'pe': 20.0, 'pb': 2.4, 'ps': 1.2}, get_template_defaults('appliance_manufacturing_components'))
        self.assertEqual({'pe': 22.0, 'pb': 2.2, 'ps': 2.2}, get_template_defaults('environmental_equipment'))
        self.assertEqual({'pe': 15.0, 'pb': 0.9, 'ps': 0.8}, get_template_defaults('rail_transit_equipment'))
        self.assertEqual({'pe': 18.0, 'pb': 0.9, 'ps': 1.0}, get_template_defaults('highway_rail_operator'))
        self.assertEqual({'pe': 18.0, 'pb': 3.5, 'ps': 4.0}, get_template_defaults('motor_manufacturing'))
        self.assertEqual({'pe': 46.0, 'pb': 8.0, 'ps': 5.5}, get_template_defaults('motor_control_components'))
        self.assertEqual({'pe': 28.0, 'pb': 1.8, 'ps': 3.2}, get_template_defaults('tourism_services'))
        self.assertEqual({'pe': 16.0, 'pb': 2.2, 'ps': 1.1}, get_template_defaults('small_appliance'))
        self.assertEqual({'pe': 18.0, 'pb': 3.5, 'ps': 1.6}, get_template_defaults('kitchen_appliance_brand'))
        self.assertEqual({'pe': 14.0, 'pb': 1.4, 'ps': 0.9}, get_template_defaults('export_small_appliance'))
        self.assertEqual({'pe': 20.0, 'pb': 1.5, 'ps': 1.4}, get_template_defaults('coal_mining'))
        self.assertEqual({'pe': 16.0, 'pb': 2.6, 'ps': 3.0}, get_template_defaults('gaming_media'))
        self.assertEqual({'pe': 14.5, 'pb': 4.0, 'ps': 4.2}, get_template_defaults('premium_game'))
        self.assertEqual({'pe': 46.0, 'pb': 4.5, 'ps': 4.0}, get_template_defaults('other_power_equipment'))
        self.assertEqual({'pe': 14.0, 'pb': 0.75, 'ps': 0.45}, get_template_defaults('steel_standard'))
        self.assertEqual({'pe': 24.0, 'pb': 1.3, 'ps': 1.0}, get_template_defaults('interior_decoration'))
        self.assertEqual({'pe': 14.0, 'pb': 1.1, 'ps': 0.9}, get_template_defaults('cement_materials'))
        self.assertEqual({'pe': 22.0, 'pb': 1.3, 'ps': 0.9}, get_template_defaults('rubber_materials'))
        self.assertEqual({'pe': 16.0, 'pb': 0.9, 'ps': 0.2}, get_template_defaults('trade_distribution'))
        self.assertEqual({'pe': 18.0, 'pb': 1.6, 'ps': 1.2}, get_template_defaults('livestock_breeding'))
        self.assertEqual({'pe': 16.0, 'pb': 2.2, 'ps': 0.85}, get_template_defaults('feed_processing'))
        self.assertEqual({'pe': 24.0, 'pb': 2.8, 'ps': 1.6}, get_template_defaults('ecommerce_service'))
        self.assertEqual({'pe': 20.0, 'pb': 1.4, 'ps': 0.55}, get_template_defaults('agri_processing'))
        self.assertEqual({'pe': 24.0, 'pb': 1.7, 'ps': 2.0}, get_template_defaults('seed_planting'))
        self.assertEqual({'pe': 30.0, 'pb': 2.6, 'ps': 3.6}, get_template_defaults('film_cinema'))
        self.assertEqual({'pe': 21.0, 'pb': 2.3, 'ps': 1.8}, get_template_defaults('snack_food'))
        self.assertEqual({'pe': 34.0, 'pb': 4.6, 'ps': 6.0}, get_template_defaults('condiment'))
        self.assertEqual({'pe': 22.0, 'pb': 3.8, 'ps': 1.2}, get_template_defaults('education_training'))
        self.assertEqual({'pe': 26.0, 'pb': 2.8, 'ps': 2.2}, get_template_defaults('leisure_culture_goods'))
        self.assertEqual({'pe': 26.0, 'pb': 3.4, 'ps': 2.6}, get_template_defaults('daily_chemical'))
        self.assertEqual({'pe': 14.0, 'pb': 0.8, 'ps': 0.12}, get_template_defaults('commodity_trading'))
        self.assertEqual({'pe': 17.0, 'pb': 1.1, 'ps': 0.35}, get_template_defaults('export_supply_chain'))
        self.assertEqual({'pe': 17.0, 'pb': 1.3, 'ps': 1.4}, get_template_defaults('hog_breeding'))
        self.assertEqual({'pe': 21.0, 'pb': 1.9, 'ps': 1.6}, get_template_defaults('poultry_breeding'))
        self.assertEqual({'pe': 34.0, 'pb': 3.0, 'ps': 2.0}, get_template_defaults('film_content_production'))
        self.assertEqual({'pe': 10.0, 'pb': 1.1, 'ps': 0.6}, get_template_defaults('distressed_education'))
        self.assertEqual({'pe': 18.0, 'pb': 0.9, 'ps': 0.7}, get_template_defaults('carbon_black_materials'))
        self.assertEqual({'pe': 23.0, 'pb': 2.0, 'ps': 0.8}, get_template_defaults('consumer_oil_processing'))
        self.assertEqual({'pe': 17.0, 'pb': 1.0, 'ps': 0.28}, get_template_defaults('grain_storage_processing'))
        self.assertEqual({'pe': 15.0, 'pb': 2.4, 'ps': 1.8}, get_template_defaults('industrial_metal'))


class ValuationViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ValuationContext(
            market="sz",
            symbol="000333",
            stock_name="美的集团",
            valuation_template_id="consumer_quality",
            industry_level_1_name="家电",
            industry_level_2_name="白色家电",
            valuation_date="2026-05-01",
            latest_report_date="20260331",
            current_price=81.10,
            market_cap=5642.17,
            dynamic_pe=14.8,
            short_history=False,
            structural_break_date=None,
            rate_regime="neutral",
        )

    def test_compute_views_use_template_ranges(self) -> None:
        from app.valuation.config import get_template_defaults
        from app.valuation.views import compute_asset_view, compute_earnings_view, compute_revenue_view

        data = {
            "current_price": 81.10,
            "dynamic_pe": 14.8,
            "eps": 5.48,
            "net_assets": 1600.0,
            "revenue": 4100.0,
            "total_shares": 76.03,
        }
        config = get_template_defaults("consumer_quality")

        earnings = compute_earnings_view(data, self.context, config)
        asset = compute_asset_view(data, self.context, config)
        revenue = compute_revenue_view(data, self.context, config)

        self.assertTrue(earnings.is_valid)
        self.assertTrue(asset.is_valid)
        self.assertTrue(revenue.is_valid)
        self.assertAlmostEqual(5.48 * 22.0, earnings.mid, places=6)
        self.assertAlmostEqual((1600.0 / 76.03) * 4.0, asset.mid, places=6)
        self.assertAlmostEqual((4100.0 / 76.03) * 3.0, revenue.mid, places=6)

    def test_financial_templates_invalidate_revenue_view(self) -> None:
        from app.valuation.config import get_template_defaults
        from app.valuation.views import compute_revenue_view

        bank_context = ValuationContext(
            **{**self.context.__dict__, "valuation_template_id": "bank", "industry_level_1_name": "银行"}
        )
        data = {"revenue": 1200.0, "total_shares": 100.0}
        revenue = compute_revenue_view(data, bank_context, get_template_defaults("bank"))

        self.assertFalse(revenue.is_valid)
        self.assertIn("金融股", " ".join(revenue.notes))

    def test_missing_fields_invalidate_only_impacted_view(self) -> None:
        from app.valuation.config import get_template_defaults
        from app.valuation.views import compute_asset_view, compute_earnings_view, compute_revenue_view

        data = {
            "current_price": 81.10,
            "dynamic_pe": 14.8,
            "eps": 5.48,
            "net_assets": None,
            "revenue": None,
            "total_shares": 76.03,
        }
        config = get_template_defaults("consumer_quality")

        earnings = compute_earnings_view(data, self.context, config)
        asset = compute_asset_view(data, self.context, config)
        revenue = compute_revenue_view(data, self.context, config)

        self.assertTrue(earnings.is_valid)
        self.assertFalse(asset.is_valid)
        self.assertFalse(revenue.is_valid)


class ValuationWeightingTests(unittest.TestCase):
    def test_single_valid_view_outputs_cautious_reference(self) -> None:
        from app.valuation.weight_engine import blend_view_results, compute_output_level, compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=10.0, mid=12.0, high=14.0, is_valid=True),
            ViewResult(view_name="asset", low=None, mid=None, high=None, is_valid=False),
            ViewResult(view_name="revenue", low=None, mid=None, high=None, is_valid=False),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.8, "revenue_growth": 3.0, "profit_growth": 8.0, "debt_ratio": 42.0},
            "consumer_quality",
        )
        blended = blend_view_results(views, weights)

        self.assertEqual("earnings", pick_dominant_view(weights))
        self.assertEqual("cautious_reference", compute_output_level(views, short_history=False, structural_break=False))
        self.assertEqual(12.0, blended["mid"])

    def test_premium_liquor_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=1200.0, mid=1450.0, high=1700.0, is_valid=True),
            ViewResult(view_name="asset", low=760.0, mid=900.0, high=1030.0, is_valid=True),
            ViewResult(view_name="revenue", low=350.0, mid=410.0, high=470.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.98, "revenue_growth": 6.3, "profit_growth": 1.5, "debt_ratio": 12.1},
            "premium_liquor",
        )

        self.assertEqual("earnings", pick_dominant_view(weights))
        self.assertGreater(weights["earnings"], weights["asset"])
        self.assertGreater(weights["asset"], weights["revenue"])

    def test_white_appliance_weights_suppress_revenue_and_balance_earnings_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=76.0, mid=90.0, high=104.0, is_valid=True),
            ViewResult(view_name="asset", low=74.0, mid=88.0, high=102.0, is_valid=True),
            ViewResult(view_name="revenue", low=73.0, mid=87.0, high=101.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.14, "revenue_growth": 2.4, "profit_growth": 2.0, "debt_ratio": 60.0},
            "white_appliance",
        )

        self.assertGreater(weights["earnings"], weights["revenue"])
        self.assertGreater(weights["asset"], weights["revenue"])

    def test_power_battery_weights_prefer_growth_views_over_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=370.0, mid=435.0, high=500.0, is_valid=True),
            ViewResult(view_name="asset", low=350.0, mid=410.0, high=470.0, is_valid=True),
            ViewResult(view_name="revenue", low=360.0, mid=430.0, high=500.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.05, "revenue_growth": 18.0, "profit_growth": 15.0, "debt_ratio": 35.0},
            "power_battery",
        )

        self.assertEqual("earnings", pick_dominant_view(weights))
        self.assertGreater(weights["earnings"], weights["asset"])
        self.assertGreater(weights["revenue"], weights["asset"])

    def test_industrial_metal_weights_prefer_earnings_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=28.0, mid=32.0, high=36.0, is_valid=True),
            ViewResult(view_name="asset", low=18.0, mid=21.0, high=24.0, is_valid=True),
            ViewResult(view_name="revenue", low=17.0, mid=20.0, high=23.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.1, "revenue_growth": 4.0, "profit_growth": 6.0, "debt_ratio": 45.0},
            "industrial_metal",
        )

        self.assertEqual("earnings", pick_dominant_view(weights))
        self.assertGreater(weights["earnings"], weights["asset"])
        self.assertGreater(weights["asset"], weights["revenue"])

    def test_medical_device_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=62.0, mid=70.0, high=78.0, is_valid=True),
            ViewResult(view_name="asset", low=108.0, mid=120.0, high=132.0, is_valid=True),
            ViewResult(view_name="revenue", low=100.0, mid=112.0, high=124.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -2.4, "revenue_growth": 17.3, "profit_growth": 7.8, "debt_ratio": 34.0},
            "medical_device",
        )

        self.assertGreater(weights["asset"], weights["earnings"])
        self.assertGreater(weights["revenue"], weights["earnings"])

    def test_semiconductor_growth_weights_prefer_earnings_and_revenue_over_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=260.0, mid=312.0, high=364.0, is_valid=True),
            ViewResult(view_name="asset", low=220.0, mid=255.0, high=290.0, is_valid=True),
            ViewResult(view_name="revenue", low=270.0, mid=320.0, high=370.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.2, "revenue_growth": 80.0, "profit_growth": 200.0, "debt_ratio": 18.0},
            "semiconductor_growth",
        )

        self.assertEqual("earnings", pick_dominant_view(weights))
        self.assertGreater(weights["earnings"], weights["asset"])
        self.assertGreater(weights["revenue"], weights["asset"])

    def test_military_info_system_weights_anchor_mainly_on_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=None, mid=None, high=None, is_valid=False),
            ViewResult(view_name="asset", low=55.0, mid=65.0, high=75.0, is_valid=True),
            ViewResult(view_name="revenue", low=10.0, mid=14.0, high=18.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 2.2, "revenue_growth": -18.0, "profit_growth": -2.0, "debt_ratio": 12.0},
            "military_info_system",
        )

        self.assertGreater(weights["asset"], 0.7)
        self.assertLess(weights["revenue"], 0.3)

    def test_display_panel_weights_prefer_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=5.5, mid=6.5, high=7.5, is_valid=True),
            ViewResult(view_name="asset", low=22.0, mid=25.0, high=28.0, is_valid=True),
            ViewResult(view_name="revenue", low=30.0, mid=36.0, high=42.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 7.2, "revenue_growth": 0.8, "profit_growth": 5.8, "debt_ratio": 52.0},
            "display_panel",
        )

        self.assertGreater(weights["asset"], weights["revenue"])
        self.assertGreater(weights["earnings"], 0.2)

    def test_consumer_assembly_weights_suppress_revenue_but_keep_earnings_asset_balanced(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=90.0, mid=100.0, high=110.0, is_valid=True),
            ViewResult(view_name="asset", low=45.0, mid=55.0, high=65.0, is_valid=True),
            ViewResult(view_name="revenue", low=150.0, mid=180.0, high=210.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.54, "revenue_growth": 16.4, "profit_growth": 26.0, "debt_ratio": 73.6},
            "consumer_assembly",
        )

        self.assertGreater(weights["earnings"], weights["revenue"])
        self.assertGreater(weights["asset"], weights["revenue"])

    def test_aerospace_material_weights_prefer_asset_and_earnings_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=13.0, mid=15.0, high=17.0, is_valid=True),
            ViewResult(view_name="asset", low=15.0, mid=17.0, high=19.0, is_valid=True),
            ViewResult(view_name="revenue", low=10.0, mid=12.0, high=14.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.34, "revenue_growth": 6.4, "profit_growth": -20.1, "debt_ratio": 46.9},
            "aerospace_material",
        )

        self.assertGreater(weights["earnings"], weights["revenue"])
        self.assertGreater(weights["asset"], weights["revenue"])

    def test_high_temp_alloy_weights_prefer_earnings_and_asset_with_low_revenue_weight(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=70.0, mid=75.0, high=80.0, is_valid=True),
            ViewResult(view_name="asset", low=72.0, mid=78.0, high=84.0, is_valid=True),
            ViewResult(view_name="revenue", low=35.0, mid=40.0, high=45.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.59, "revenue_growth": 23.8, "profit_growth": 26.2, "debt_ratio": 25.9},
            "high_temp_alloy",
        )

        self.assertEqual('earnings', pick_dominant_view(weights))
        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_electric_utility_weights_anchor_on_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=25.0, mid=29.5, high=34.0, is_valid=True),
            ViewResult(view_name="asset", low=23.0, mid=27.4, high=31.8, is_valid=True),
            ViewResult(view_name="revenue", low=6.0, mid=7.1, high=8.2, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.73, "revenue_growth": 6.4, "profit_growth": 30.5, "debt_ratio": 57.3},
            "electric_utility",
        )

        self.assertEqual('earnings', pick_dominant_view(weights))
        self.assertGreater(weights['earnings'], weights['asset'])
        self.assertLess(weights['revenue'], 0.1)

    def test_environmental_services_weights_anchor_mainly_on_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=3.1, mid=3.9, high=4.7, is_valid=True),
            ViewResult(view_name="asset", low=6.0, mid=6.7, high=7.4, is_valid=True),
            ViewResult(view_name="revenue", low=4.9, mid=5.7, high=6.5, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 2.68, "revenue_growth": -5.2, "profit_growth": 5.25, "debt_ratio": 66.1},
            "environmental_services",
        )

        self.assertGreater(weights['asset'], weights['revenue'])
        self.assertGreater(weights['revenue'], weights['earnings'])
        self.assertLess(weights['earnings'], 0.15)

    def test_property_development_weights_anchor_on_asset_with_revenue_secondary(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=None, mid=None, high=None, is_valid=False),
            ViewResult(view_name="asset", low=3.8, mid=4.2, high=4.6, is_valid=True),
            ViewResult(view_name="revenue", low=3.0, mid=3.4, high=3.8, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.36, "revenue_growth": -23.86, "profit_growth": 4.71, "debt_ratio": 77.13},
            "property_development",
        )

        self.assertEqual('asset', pick_dominant_view(weights))
        self.assertGreater(weights['asset'], weights['revenue'])
        self.assertLess(weights['revenue'], 0.4)

    def test_testing_inspection_service_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=17.0, mid=19.0, high=21.0, is_valid=True),
            ViewResult(view_name="asset", low=15.0, mid=17.0, high=19.0, is_valid=True),
            ViewResult(view_name="revenue", low=4.5, mid=5.2, high=5.9, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.01, "revenue_growth": 16.2, "profit_growth": 30.9, "debt_ratio": 21.7},
            "testing_inspection_service",
        )

        self.assertEqual('earnings', pick_dominant_view(weights))
        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_human_resource_service_weights_suppress_revenue_overweight(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=22.0, mid=25.0, high=28.0, is_valid=True),
            ViewResult(view_name="asset", low=17.0, mid=19.0, high=21.0, is_valid=True),
            ViewResult(view_name="revenue", low=20.0, mid=23.0, high=26.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -0.84, "revenue_growth": 14.7, "profit_growth": 59.0, "debt_ratio": 46.4},
            "human_resource_service",
        )

        self.assertGreaterEqual(weights['earnings'], weights['asset'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_port_operator_weights_anchor_on_asset_and_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=4.6, mid=5.0, high=5.4, is_valid=True),
            ViewResult(view_name="asset", low=5.5, mid=5.9, high=6.3, is_valid=True),
            ViewResult(view_name="revenue", low=1.5, mid=1.7, high=1.9, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.83, "revenue_growth": 0.0, "profit_growth": 0.0, "debt_ratio": 0.0},
            "port_operator",
        )

        self.assertGreater(weights['asset'], weights['revenue'])
        self.assertGreater(weights['earnings'], weights['revenue'])

    def test_textile_quality_manufacturing_weights_keep_earnings_asset_above_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=9.0, mid=9.7, high=10.4, is_valid=True),
            ViewResult(view_name="asset", low=8.9, mid=9.5, high=10.1, is_valid=True),
            ViewResult(view_name="revenue", low=8.4, mid=9.0, high=9.6, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.48, "revenue_growth": 6.2, "profit_growth": -7.2, "debt_ratio": 31.6},
            "textile_quality_manufacturing",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_gas_utility_weights_suppress_revenue_and_anchor_on_earnings_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=11.0, mid=12.2, high=13.4, is_valid=True),
            ViewResult(view_name="asset", low=7.5, mid=8.4, high=9.3, is_valid=True),
            ViewResult(view_name="revenue", low=10.2, mid=11.4, high=12.6, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -3.25, "revenue_growth": -12.2, "profit_growth": 2.1, "debt_ratio": 53.8},
            "gas_utility",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_digital_marketing_agency_weights_prefer_revenue_over_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=0.8, mid=1.1, high=1.4, is_valid=True),
            ViewResult(view_name="asset", low=4.0, mid=4.4, high=4.8, is_valid=True),
            ViewResult(view_name="revenue", low=15.0, mid=17.3, high=19.6, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -7.5, "revenue_growth": 31.9, "profit_growth": 32.0, "debt_ratio": 70.5},
            "digital_marketing_agency",
        )

        self.assertEqual('revenue', pick_dominant_view(weights))
        self.assertGreater(weights['revenue'], weights['asset'])

    def test_appliance_precision_components_weights_anchor_on_earnings_and_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=42.0, mid=46.9, high=51.8, is_valid=True),
            ViewResult(view_name="asset", low=42.0, mid=46.8, high=51.6, is_valid=True),
            ViewResult(view_name="revenue", low=39.0, mid=44.4, high=49.8, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.19, "revenue_growth": 1.36, "profit_growth": 2.68, "debt_ratio": 33.3},
            "appliance_precision_components",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_environmental_equipment_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=3.2, mid=4.0, high=4.8, is_valid=True),
            ViewResult(view_name="asset", low=12.0, mid=13.6, high=15.2, is_valid=True),
            ViewResult(view_name="revenue", low=9.8, mid=12.0, high=14.2, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -5.75, "revenue_growth": 23.2, "profit_growth": 18.6, "debt_ratio": 53.6},
            "environmental_equipment",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_rail_transit_equipment_weights_prefer_asset_and_earnings_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=5.0, mid=6.0, high=7.0, is_valid=True),
            ViewResult(view_name="asset", low=6.0, mid=6.9, high=7.8, is_valid=True),
            ViewResult(view_name="revenue", low=4.8, mid=5.6, high=6.4, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -2.68, "revenue_growth": 10.6, "profit_growth": 10.7, "debt_ratio": 60.3},
            "rail_transit_equipment",
        )

        self.assertGreater(weights['asset'], weights['revenue'])
        self.assertGreater(weights['earnings'], weights['revenue'])

    def test_highway_rail_operator_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=4.6, mid=5.2, high=5.8, is_valid=True),
            ViewResult(view_name="asset", low=4.9, mid=5.6, high=6.3, is_valid=True),
            ViewResult(view_name="revenue", low=2.9, mid=3.4, high=3.9, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.41, "revenue_growth": 3.3, "profit_growth": 6.0, "debt_ratio": 19.8},
            "highway_rail_operator",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_motor_control_components_weights_prefer_earnings_and_revenue_over_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=170.0, mid=192.0, high=214.0, is_valid=True),
            ViewResult(view_name="asset", low=150.0, mid=168.0, high=186.0, is_valid=True),
            ViewResult(view_name="revenue", low=145.0, mid=161.0, high=177.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -0.88, "revenue_growth": 41.6, "profit_growth": 23.2, "debt_ratio": 45.8},
            "motor_control_components",
        )

        self.assertEqual('revenue', pick_dominant_view(weights))
        self.assertGreater(weights['earnings'], weights['asset'])
        self.assertGreater(weights['revenue'], weights['asset'])

    def test_tourism_services_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=10.5, mid=11.8, high=13.1, is_valid=True),
            ViewResult(view_name="asset", low=9.0, mid=10.2, high=11.4, is_valid=True),
            ViewResult(view_name="revenue", low=6.5, mid=7.4, high=8.3, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.71, "revenue_growth": 3.5, "profit_growth": -6.2, "debt_ratio": 16.7},
            "tourism_services",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_kitchen_appliance_brand_weights_prefer_earnings_and_revenue_over_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=44.0, mid=47.6, high=51.2, is_valid=True),
            ViewResult(view_name="asset", low=25.0, mid=29.8, high=34.6, is_valid=True),
            ViewResult(view_name="revenue", low=42.0, mid=45.6, high=49.2, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.72, "revenue_growth": 1.65, "profit_growth": 1.68, "debt_ratio": 48.8},
            "kitchen_appliance_brand",
        )

        self.assertGreater(weights['earnings'], weights['asset'])
        self.assertGreater(weights['revenue'], weights['asset'])

    def test_coal_mining_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=20.0, mid=26.0, high=32.0, is_valid=True),
            ViewResult(view_name="asset", low=18.0, mid=22.5, high=27.0, is_valid=True),
            ViewResult(view_name="revenue", low=17.0, mid=22.7, high=28.4, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 2.30, "revenue_growth": -3.0, "profit_growth": -12.4, "debt_ratio": 40.1},
            "coal_mining",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_premium_game_weights_favor_earnings_over_asset_and_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights, pick_dominant_view

        views = [
            ViewResult(view_name="earnings", low=360.0, mid=406.0, high=452.0, is_valid=True),
            ViewResult(view_name="asset", low=350.0, mid=393.0, high=436.0, is_valid=True),
            ViewResult(view_name="revenue", low=340.0, mid=384.0, high=428.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.12, "revenue_growth": 62.7, "profit_growth": 82.7, "debt_ratio": 21.6},
            "premium_game",
        )

        self.assertEqual('earnings', pick_dominant_view(weights))
        self.assertGreater(weights['earnings'], weights['asset'])
        self.assertGreater(weights['earnings'], weights['revenue'])

    def test_steel_standard_weights_prefer_asset_and_earnings_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=5.8, mid=6.6, high=7.4, is_valid=True),
            ViewResult(view_name="asset", low=6.6, mid=7.8, high=9.0, is_valid=True),
            ViewResult(view_name="revenue", low=5.7, mid=6.6, high=7.5, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.99, "revenue_growth": 5.7, "profit_growth": -8.6, "debt_ratio": 37.8},
            "steel_standard",
        )

        self.assertGreater(weights['asset'], weights['revenue'])
        self.assertGreater(weights['earnings'], weights['revenue'])

    def test_interior_decoration_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=3.2, mid=3.7, high=4.2, is_valid=True),
            ViewResult(view_name="asset", low=5.9, mid=6.8, high=7.7, is_valid=True),
            ViewResult(view_name="revenue", low=5.2, mid=6.0, high=6.8, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -7.89, "revenue_growth": -14.1, "profit_growth": -17.7, "debt_ratio": 54.4},
            "interior_decoration",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_cement_materials_weights_prefer_asset_and_earnings_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=19.0, mid=21.8, high=24.6, is_valid=True),
            ViewResult(view_name="asset", low=17.8, mid=20.1, high=22.4, is_valid=True),
            ViewResult(view_name="revenue", low=14.5, mid=16.1, high=17.7, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.37, "revenue_growth": 24.4, "profit_growth": 169.4, "debt_ratio": 53.6},
            "cement_materials",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_rubber_materials_weights_prefer_asset_and_revenue_over_earnings_when_earnings_weak(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=3.0, mid=4.1, high=5.2, is_valid=True),
            ViewResult(view_name="asset", low=4.8, mid=6.9, high=9.0, is_valid=True),
            ViewResult(view_name="revenue", low=8.0, mid=10.3, high=12.6, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.28, "revenue_growth": -12.9, "profit_growth": -167.7, "debt_ratio": 70.5},
            "rubber_materials",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_trade_distribution_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=0.6, mid=1.0, high=1.4, is_valid=True),
            ViewResult(view_name="asset", low=9.5, mid=10.8, high=12.1, is_valid=True),
            ViewResult(view_name="revenue", low=18.0, mid=21.5, high=25.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -120.0, "revenue_growth": -14.3, "profit_growth": -74.7, "debt_ratio": 68.6},
            "trade_distribution",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_livestock_breeding_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=13.0, mid=15.0, high=17.0, is_valid=True),
            ViewResult(view_name="asset", low=35.0, mid=40.0, high=45.0, is_valid=True),
            ViewResult(view_name="revenue", low=40.0, mid=46.0, high=52.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -1.2, "revenue_growth": 0.3, "profit_growth": -153.1, "debt_ratio": 53.1},
            "livestock_breeding",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_feed_processing_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=43.0, mid=50.0, high=57.0, is_valid=True),
            ViewResult(view_name="asset", low=35.0, mid=41.0, high=47.0, is_valid=True),
            ViewResult(view_name="revenue", low=58.0, mid=70.0, high=82.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.03, "revenue_growth": 13.2, "profit_growth": -30.8, "debt_ratio": 49.0},
            "feed_processing",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_ecommerce_service_weights_prefer_asset_and_earnings_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=28.0, mid=32.0, high=36.0, is_valid=True),
            ViewResult(view_name="asset", low=26.0, mid=30.0, high=34.0, is_valid=True),
            ViewResult(view_name="revenue", low=12.0, mid=15.0, high=18.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -0.54, "revenue_growth": 15.6, "profit_growth": -12.5, "debt_ratio": 38.9},
            "ecommerce_service",
        )

        self.assertGreater(weights['asset'], weights['revenue'])
        self.assertGreater(weights['earnings'], weights['revenue'])

    def test_seed_planting_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=1.0, mid=1.8, high=2.6, is_valid=True),
            ViewResult(view_name="asset", low=10.5, mid=12.0, high=13.5, is_valid=True),
            ViewResult(view_name="revenue", low=8.0, mid=9.5, high=11.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 6.33, "revenue_growth": -35.6, "profit_growth": -6145.6, "debt_ratio": 57.9},
            "seed_planting",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_film_cinema_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=1.1, mid=1.4, high=1.7, is_valid=True),
            ViewResult(view_name="asset", low=11.0, mid=12.4, high=13.8, is_valid=True),
            ViewResult(view_name="revenue", low=4.3, mid=5.1, high=5.9, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -9.84, "revenue_growth": -14.3, "profit_growth": 19.0, "debt_ratio": 43.1},
            "film_cinema",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_snack_food_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=20.0, mid=23.0, high=26.0, is_valid=True),
            ViewResult(view_name="asset", low=21.0, mid=24.0, high=27.0, is_valid=True),
            ViewResult(view_name="revenue", low=18.0, mid=21.0, high=24.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 1.9, "revenue_growth": 22.5, "profit_growth": 25.7, "debt_ratio": 17.8},
            "snack_food",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_condiment_weights_prefer_earnings_and_revenue_over_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=32.0, mid=38.0, high=44.0, is_valid=True),
            ViewResult(view_name="asset", low=24.0, mid=28.0, high=32.0, is_valid=True),
            ViewResult(view_name="revenue", low=30.0, mid=36.0, high=42.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 3.10, "revenue_growth": -1.57, "profit_growth": -7.75, "debt_ratio": 15.36},
            "condiment",
        )

        self.assertGreater(weights['earnings'], weights['asset'])
        self.assertGreater(weights['revenue'], weights['asset'])

    def test_education_training_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=0.8, mid=1.2, high=1.6, is_valid=True),
            ViewResult(view_name="asset", low=12.0, mid=14.0, high=16.0, is_valid=True),
            ViewResult(view_name="revenue", low=18.0, mid=21.0, high=24.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 6.05, "revenue_growth": 10.06, "profit_growth": 22.9, "debt_ratio": 76.18},
            "education_training",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_leisure_culture_goods_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=1.0, mid=1.4, high=1.8, is_valid=True),
            ViewResult(view_name="asset", low=5.0, mid=6.1, high=7.2, is_valid=True),
            ViewResult(view_name="revenue", low=4.5, mid=5.8, high=7.1, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 3.70, "revenue_growth": -17.27, "profit_growth": -191.71, "debt_ratio": 37.66},
            "leisure_culture_goods",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_daily_chemical_weights_prefer_earnings_and_revenue_over_asset(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=46.0, mid=52.0, high=58.0, is_valid=True),
            ViewResult(view_name="asset", low=38.0, mid=43.0, high=48.0, is_valid=True),
            ViewResult(view_name="revenue", low=44.0, mid=50.0, high=56.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.65, "revenue_growth": 17.84, "profit_growth": 132.76, "debt_ratio": 24.71},
            "daily_chemical",
        )

        self.assertGreater(weights['earnings'], weights['asset'])
        self.assertGreater(weights['revenue'], weights['asset'])

    def test_commodity_trading_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=0.02, mid=0.05, high=0.08, is_valid=True),
            ViewResult(view_name="asset", low=12.0, mid=14.0, high=16.0, is_valid=True),
            ViewResult(view_name="revenue", low=60.0, mid=75.0, high=90.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -120.35, "revenue_growth": -14.32, "profit_growth": -74.67, "debt_ratio": 68.63},
            "commodity_trading",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_export_supply_chain_weights_prefer_earnings_and_asset_over_revenue(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=8.0, mid=9.0, high=10.0, is_valid=True),
            ViewResult(view_name="asset", low=8.5, mid=9.5, high=10.5, is_valid=True),
            ViewResult(view_name="revenue", low=4.2, mid=5.0, high=5.8, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -2.25, "revenue_growth": 8.9, "profit_growth": -12.63, "debt_ratio": 48.46},
            "export_supply_chain",
        )

        self.assertGreater(weights['earnings'], weights['revenue'])
        self.assertGreater(weights['asset'], weights['revenue'])

    def test_hog_breeding_weights_prefer_revenue_and_asset_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=28.0, mid=33.0, high=38.0, is_valid=True),
            ViewResult(view_name="asset", low=24.0, mid=29.0, high=34.0, is_valid=True),
            ViewResult(view_name="revenue", low=37.0, mid=44.0, high=51.0, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 0.76, "revenue_growth": -17.1, "profit_growth": -127.05, "debt_ratio": 50.73},
            "hog_breeding",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_film_content_production_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=0.2, mid=0.4, high=0.6, is_valid=True),
            ViewResult(view_name="asset", low=12.0, mid=14.0, high=16.0, is_valid=True),
            ViewResult(view_name="revenue", low=3.0, mid=4.2, high=5.4, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": -2.0, "revenue_growth": -93.59, "profit_growth": -98.85, "debt_ratio": 9.08},
            "film_content_production",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])

    def test_distressed_education_weights_prefer_asset_and_revenue_over_earnings(self) -> None:
        from app.valuation.weight_engine import compute_view_weights

        views = [
            ViewResult(view_name="earnings", low=0.1, mid=0.2, high=0.3, is_valid=True),
            ViewResult(view_name="asset", low=0.4, mid=0.5, high=0.6, is_valid=True),
            ViewResult(view_name="revenue", low=0.35, mid=0.45, high=0.55, is_valid=True),
        ]
        weights = compute_view_weights(
            views,
            {"ocf_to_profit": 3.21, "revenue_growth": 4.31, "profit_growth": 18.33, "debt_ratio": 85.88},
            "distressed_education",
        )

        self.assertGreater(weights['asset'], weights['earnings'])
        self.assertGreater(weights['revenue'], weights['earnings'])


class ValuationServiceTests(unittest.TestCase):
    def test_build_valuation_result_aggregates_views_and_metadata(self) -> None:
        from app.valuation.service import build_valuation_result

        loaded = {
            "market": "sz",
            "symbol": "000333",
            "stock_name": "美的集团",
            "industry_level_1_name": "家电",
            "industry_level_2_name": "白色家电",
            "valuation_template_id": "",
            "valuation_date": "2026-05-01",
            "latest_report_date": "20260331",
            "current_price": 81.10,
            "market_cap": 5642.17,
            "dynamic_pe": 14.8,
            "eps": 5.48,
            "total_shares": 76.03,
            "float_shares": 68.52,
            "net_assets": 1600.0,
            "revenue": 4100.0,
            "profit_growth": 12.5,
            "revenue_growth": 9.2,
            "ocf_to_profit": 1.35,
            "free_cf": 260.0,
            "debt_ratio": 58.0,
            "short_history": False,
            "structural_break_date": None,
            "rate_regime": "neutral",
        }

        with mock.patch("app.valuation.service.load_valuation_inputs", return_value=loaded):
            payload = build_valuation_result("sz", "000333")

        self.assertTrue(payload["ok"])
        self.assertEqual("white_appliance", payload["valuation_template_id"])
        self.assertEqual("earnings", payload["dominant_view"])
        self.assertEqual("standard", payload["output_level"])
        self.assertEqual(3, len(payload["views"]))
        self.assertTrue(any(item["view_name"] == "revenue" and item["is_valid"] for item in payload["views"]))
        self.assertIn("行业模板=white_appliance", payload["methodology_note"])
        self.assertIsInstance(payload["risk_tags"], list)
        self.assertIsInstance(payload["failure_conditions"], list)

    def test_build_valuation_result_handles_single_valid_view_without_fabricating_missing_data(self) -> None:
        from app.valuation.service import build_valuation_result

        loaded = {
            "market": "sz",
            "symbol": "300999",
            "stock_name": "示例公司",
            "industry_level_1_name": "电子",
            "industry_level_2_name": "半导体",
            "valuation_template_id": "tech_growth",
            "valuation_date": "2026-05-01",
            "latest_report_date": "20260331",
            "current_price": 45.0,
            "market_cap": 300.0,
            "dynamic_pe": 30.0,
            "eps": 1.5,
            "total_shares": None,
            "float_shares": None,
            "net_assets": None,
            "revenue": None,
            "profit_growth": -8.0,
            "revenue_growth": 18.0,
            "ocf_to_profit": 0.6,
            "free_cf": -12.0,
            "debt_ratio": 35.0,
            "short_history": True,
            "structural_break_date": None,
            "rate_regime": "neutral",
        }

        with mock.patch("app.valuation.service.load_valuation_inputs", return_value=loaded):
            payload = build_valuation_result("sz", "300999")

        self.assertEqual("cautious_reference", payload["output_level"])
        self.assertEqual("earnings", payload["dominant_view"])
        self.assertEqual(1, sum(1 for item in payload["views"] if item["is_valid"]))
        self.assertEqual(payload["views"][0]["mid"], payload["final_mid"])
        self.assertIn("single-view", payload["methodology_note"])

    def test_build_valuation_result_passes_profit_growth_into_textile_refinement(self) -> None:
        from app.valuation.service import build_valuation_result

        loaded = {
            "market": "sz",
            "symbol": "002003",
            "stock_name": "伟星股份",
            "industry_level_1_name": "纺织服饰",
            "industry_level_2_name": "纺织制造",
            "valuation_template_id": "",
            "valuation_date": "2026-05-01",
            "latest_report_date": "20260331",
            "current_price": 10.0,
            "market_cap": 118.9,
            "dynamic_pe": 18.5,
            "eps": 0.54,
            "total_shares": 11.888896,
            "float_shares": 10.0,
            "net_assets": 47.21490944,
            "revenue": 48.61258944,
            "profit_growth": -7.23,
            "revenue_growth": 6.22,
            "ocf_to_profit": 0.48,
            "free_cf": 0.0,
            "debt_ratio": 31.56,
            "short_history": False,
            "structural_break_date": None,
            "rate_regime": "neutral",
        }

        with mock.patch("app.valuation.service.load_valuation_inputs", return_value=loaded):
            payload = build_valuation_result("sz", "002003")

        self.assertEqual("textile_quality_manufacturing", payload["valuation_template_id"])

    def test_build_valuation_result_passes_revenue_growth_into_shipping_refinement(self) -> None:
        from app.valuation.service import build_valuation_result

        loaded = {
            "market": "sh",
            "symbol": "600026",
            "stock_name": "中远海能",
            "industry_level_1_name": "交通运输",
            "industry_level_2_name": "航运港口",
            "valuation_template_id": "",
            "valuation_date": "2026-05-01",
            "latest_report_date": "20260331",
            "current_price": 21.59,
            "market_cap": 1029.0,
            "dynamic_pe": 20.07,
            "eps": 1.0756,
            "total_shares": 47.67,
            "float_shares": 47.67,
            "net_assets": 448.6,
            "revenue": 221.9,
            "profit_growth": 206.74,
            "revenue_growth": 26.92,
            "ocf_to_profit": 1.73,
            "free_cf": 0.0,
            "debt_ratio": 45.55,
            "short_history": False,
            "structural_break_date": None,
            "rate_regime": "neutral",
        }

        with mock.patch("app.valuation.service.load_valuation_inputs", return_value=loaded):
            payload = build_valuation_result("sh", "600026")

        self.assertEqual("shipping_carrier", payload["valuation_template_id"])

    def test_data_loader_prefers_ttm_eps_ttm_revenue_and_broader_equity_field_fallbacks(self) -> None:
        from app.valuation.data_loader import load_valuation_inputs

        industry_rows = [{
            "market": "sz",
            "symbol": "000333",
            "stock_name": "美的集团",
            "valuation_template_id": "consumer_quality",
            "industry_level_1_name": "家电",
            "industry_level_2_name": "白色家电",
        }]
        profile_response = {
            "ok": True,
            "profile": {
                "market": "sz",
                "symbol": "000333",
                "stock_name": "美的集团",
                "basic_info": {
                    "current_price": 81.10,
                    "dynamic_pe": 14.8,
                    "a_share_market_cap": 5642.17,
                    "total_shares": None,
                    "float_shares": 68.52,
                    "eps": 1.69,
                },
            },
        }
        financial_match = (
            "20260331",
            {
                "营业收入": 1310.0 * 1e8,
                "所有者权益（或股东权益）合计": 1600.0 * 1e8,
                "归属于母公司所有者的净利润": 126.0 * 1e8,
                "扣除非经常性损益后的净利润": 109.0 * 1e8,
                "经营活动产生的现金流量净额": 145.0 * 1e8,
                "总股本": 76.03 * 1e8,
            },
        )
        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sz:000333": {
                    "raw_sub_indicators": {
                        "revenue_growth": 9.2,
                        "profit_growth": 12.5,
                        "ocf_to_profit": 1.35,
                        "free_cf": 260.0 * 1e8,
                        "debt_ratio": 58.0,
                    },
                    "latest_period": "2026Q1",
                }
            },
        }

        def fake_load_quarter_row(period: str, symbol: str):
            if period == "2025A":
                return {"营业收入": 930.0 * 1e8}
            if period == "2025Q3":
                return {"营业收入": 980.0 * 1e8}
            if period == "2025Q2":
                return {"营业收入": 890.0 * 1e8}
            return None

        with (
            mock.patch("app.valuation.data_loader.search_index.load_security_rows", return_value=[{"market": "sz", "symbol": "000333", "stock_name": "美的集团"}]),
            mock.patch("app.valuation.data_loader.search_index.load_industry_rows", return_value=industry_rows),
            mock.patch("app.valuation.data_loader.search_index.stock_profile_response", return_value=profile_response),
            mock.patch("app.valuation.data_loader.search_index._lookup_financial_row", return_value=financial_match),
            mock.patch("app.valuation.data_loader.search_index._load_financial_snapshot", return_value=snapshot),
            mock.patch("app.valuation.data_loader.search_index._load_financial_quarter_row", side_effect=fake_load_quarter_row),
        ):
            payload = load_valuation_inputs("sz", "000333")

        self.assertEqual("consumer_quality", payload["valuation_template_id"])
        self.assertAlmostEqual(81.10 / 14.8, payload["eps"], places=6)
        self.assertAlmostEqual(76.03, payload["total_shares"], places=6)
        self.assertAlmostEqual(4110.0, payload["revenue"], places=6)
        self.assertAlmostEqual(1600.0, payload["net_assets"], places=6)
        self.assertAlmostEqual(9.2, payload["revenue_growth"], places=6)


if __name__ == "__main__":
    unittest.main()

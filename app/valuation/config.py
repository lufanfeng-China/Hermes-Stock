from __future__ import annotations

FALLBACK_TEMPLATE_MAP = {
    '家电': 'consumer_quality',
    '食品饮料': 'consumer_quality',
    '银行': 'bank',
    '非银金融': 'nonbank_finance',
    '有色': 'industrial_metal',
    '公用事业': 'utilities_infra',
    '医药医疗': 'healthcare_growth',
    '电子': 'tech_growth',
    '计算机': 'tech_growth',
    '机械设备': 'cyclical_manufacturing',
    '汽车': 'cyclical_manufacturing',
}

INDUSTRY_L2_TEMPLATE_MAP = {
    '白色家电': 'white_appliance',
    '酿酒': 'premium_liquor',
    '电池': 'power_battery',
    '电力': 'electric_utility',
    '燃气': 'gas_utility',
    '电信服务': 'telecom_operator',
    '广告营销': 'ad_marketing',
    '环境治理': 'environmental_services',
    '环保设备': 'environmental_equipment',
    '轨交设备': 'rail_transit_equipment',
    '医疗器械': 'medical_device',
    '化学制药': 'innovative_pharma',
    '农用化工': 'agrochemical',
    '塑料': 'plastic_products',
    '造纸': 'paper_products',
    '出版业': 'publishing',
    '装饰建材': 'decorative_building_materials',
    '自动化设备': 'automation_equipment',
    '工程机械': 'engineering_machinery',
    '专业工程': 'professional_engineering',
    '专业服务': 'professional_services',
    '工程咨询服务': 'engineering_consulting',
    '基础建设': 'infrastructure_construction',
    '军工电子': 'military_electronics',
    '航空装备': 'aviation_equipment',
    '半导体': 'semiconductor_growth',
    '消费电子': 'consumer_electronics',
    '一般零售': 'general_retail',
    '其他电子': 'misc_electronics',
    '光学光电': 'optical_photonics',
    '云服务': 'cloud_service',
    '稀有金属': 'rare_metal',
    '能源金属': 'energy_metal',
    '汽车零部件': 'auto_parts',
    '公路铁路': 'highway_rail_operator',
    '航运港口': 'shipping_ports',
    '通用设备': 'general_equipment',
    '专用设备': 'specialized_equipment',
    '电机制造': 'motor_manufacturing',
    '软件服务': 'software_service',
    '电网设备': 'power_grid_equipment',
    '通信设备': 'telecom_equipment',
    '房地产开发': 'property_development',
    '服装家纺': 'apparel_home_textile',
    '家居用品': 'household_goods',
    '家电零部件': 'home_appliance_components',
    '小家电': 'small_appliance',
    '食品加工': 'food_processing',
    '饮料乳品': 'beverage_dairy',
    '医疗服务': 'medical_service',
    '旅游': 'tourism_services',
    '中药': 'traditional_chinese_medicine',
    '化学原料': 'chemical_raw_material',
    '化学制品': 'chemical_products',
    '化纤': 'chemical_fiber',
    '纺织制造': 'textile_manufacturing',
    '生物制品': 'biotech',
    '医药商业': 'pharma_distribution',
    '光伏设备': 'photovoltaic_equipment',
    '风电设备': 'wind_power_equipment',
    'IT设备': 'it_hardware',
    '元器件': 'electronic_components',
    '包装印刷': 'packaging_printing',
    '物流': 'logistics',
    '煤炭开采': 'coal_mining',
    '游戏': 'gaming_media',
    '影视院线': 'film_cinema',
    '贸易': 'trade_distribution',
    '养殖业': 'livestock_breeding',
    '饲料': 'feed_processing',
    '电子商务': 'ecommerce_service',
    '农产品加工': 'agri_processing',
    '种植业': 'seed_planting',
    '休闲食品': 'snack_food',
    '调味品': 'condiment',
    '教育培训': 'education_training',
    '文娱用品': 'leisure_culture_goods',
    '日用化工': 'daily_chemical',
    '其他发电设备': 'other_power_equipment',
    '普钢': 'steel_standard',
    '装修装饰': 'interior_decoration',
    '水泥': 'cement_materials',
    '橡胶': 'rubber_materials',
}

TEMPLATE_DEFAULTS = {
    'consumer_quality': {'pe': 22.0, 'pb': 4.0, 'ps': 3.0},
    'white_appliance': {'pe': 16.0, 'pb': 2.5, 'ps': 1.4},
    'premium_liquor': {'pe': 26.0, 'pb': 6.0, 'ps': 6.0},
    'power_battery': {'pe': 26.0, 'pb': 5.0, 'ps': 4.2},
    'electric_utility': {'pe': 20.0, 'pb': 2.8, 'ps': 2.0},
    'gas_utility': {'pe': 16.0, 'pb': 1.2, 'ps': 0.45},
    'telecom_operator': {'pe': 16.0, 'pb': 1.5, 'ps': 2.0},
    'ad_marketing': {'pe': 22.0, 'pb': 2.0, 'ps': 1.1},
    'media_ad_platform': {'pe': 28.0, 'pb': 5.7, 'ps': 6.0},
    'digital_marketing_agency': {'pe': 18.0, 'pb': 2.0, 'ps': 0.85},
    'environmental_services': {'pe': 30.0, 'pb': 1.45, 'ps': 2.6},
    'environmental_equipment': {'pe': 22.0, 'pb': 2.2, 'ps': 2.2},
    'rail_transit_equipment': {'pe': 15.0, 'pb': 0.9, 'ps': 0.8},
    'medical_device': {'pe': 28.0, 'pb': 4.2, 'ps': 6.3},
    'innovative_pharma': {'pe': 44.0, 'pb': 5.6, 'ps': 11.0},
    'agrochemical': {'pe': 18.0, 'pb': 1.8, 'ps': 1.3},
    'plastic_products': {'pe': 18.0, 'pb': 1.7, 'ps': 1.1},
    'paper_products': {'pe': 16.0, 'pb': 1.0, 'ps': 0.75},
    'publishing': {'pe': 18.0, 'pb': 0.8, 'ps': 1.3},
    'decorative_building_materials': {'pe': 20.0, 'pb': 2.2, 'ps': 1.6},
    'automation_equipment': {'pe': 38.0, 'pb': 4.8, 'ps': 4.0},
    'engineering_machinery': {'pe': 45.0, 'pb': 7.0, 'ps': 10.0},
    'professional_engineering': {'pe': 14.0, 'pb': 1.2, 'ps': 0.8},
    'professional_services': {'pe': 24.0, 'pb': 2.6, 'ps': 1.4},
    'testing_inspection_service': {'pe': 30.0, 'pb': 3.6, 'ps': 1.3},
    'human_resource_service': {'pe': 14.0, 'pb': 1.5, 'ps': 0.3},
    'engineering_consulting': {'pe': 18.0, 'pb': 1.8, 'ps': 1.5},
    'infrastructure_construction': {'pe': 5.5, 'pb': 0.2, 'ps': 0.12},
    'construction_machinery': {'pe': 22.0, 'pb': 2.1, 'ps': 2.1},
    'military_electronics': {'pe': 40.0, 'pb': 3.0, 'ps': 3.5},
    'military_info_system': {'pe': 50.0, 'pb': 4.8, 'ps': 10.0},
    'aviation_equipment': {'pe': 40.0, 'pb': 5.0, 'ps': 3.2},
    'aerospace_material': {'pe': 42.0, 'pb': 1.6, 'ps': 1.8},
    'high_temp_alloy': {'pe': 68.0, 'pb': 4.2, 'ps': 8.0},
    'semiconductor_growth': {'pe': 78.0, 'pb': 9.0, 'ps': 18.0},
    'consumer_electronics': {'pe': 30.0, 'pb': 4.2, 'ps': 1.5},
    'general_retail': {'pe': 18.0, 'pb': 1.4, 'ps': 0.75},
    'misc_electronics': {'pe': 28.0, 'pb': 3.2, 'ps': 2.6},
    'consumer_assembly': {'pe': 24.0, 'pb': 1.8, 'ps': 0.55},
    'optical_photonics': {'pe': 38.0, 'pb': 4.5, 'ps': 6.5},
    'cloud_service': {'pe': 36.0, 'pb': 3.8, 'ps': 3.0},
    'display_panel': {'pe': 18.0, 'pb': 0.85, 'ps': 0.6},
    'rare_metal': {'pe': 17.0, 'pb': 3.7, 'ps': 1.7},
    'energy_metal': {'pe': 48.0, 'pb': 3.6, 'ps': 6.2},
    'auto_parts': {'pe': 24.0, 'pb': 2.3, 'ps': 1.4},
    'highway_rail_operator': {'pe': 18.0, 'pb': 0.9, 'ps': 1.0},
    'shipping_ports': {'pe': 16.0, 'pb': 1.6, 'ps': 1.3},
    'port_operator': {'pe': 12.0, 'pb': 0.85, 'ps': 1.0},
    'shipping_carrier': {'pe': 22.0, 'pb': 2.3, 'ps': 2.8},
    'general_equipment': {'pe': 22.0, 'pb': 2.6, 'ps': 2.0},
    'specialized_equipment': {'pe': 26.0, 'pb': 3.1, 'ps': 2.8},
    'motor_manufacturing': {'pe': 18.0, 'pb': 3.5, 'ps': 4.0},
    'motor_control_components': {'pe': 46.0, 'pb': 8.0, 'ps': 5.5},
    'software_service': {'pe': 42.0, 'pb': 6.0, 'ps': 8.0},
    'power_grid_equipment': {'pe': 20.0, 'pb': 2.2, 'ps': 1.8},
    'telecom_equipment': {'pe': 30.0, 'pb': 3.0, 'ps': 2.4},
    'property_development': {'pe': 6.0, 'pb': 0.22, 'ps': 0.18},
    'apparel_home_textile': {'pe': 20.0, 'pb': 1.8, 'ps': 1.2},
    'household_goods': {'pe': 22.0, 'pb': 2.1, 'ps': 1.5},
    'home_appliance_components': {'pe': 22.0, 'pb': 2.0, 'ps': 1.2},
    'appliance_precision_components': {'pe': 42.0, 'pb': 6.0, 'ps': 6.0},
    'appliance_manufacturing_components': {'pe': 20.0, 'pb': 2.4, 'ps': 1.2},
    'small_appliance': {'pe': 16.0, 'pb': 2.2, 'ps': 1.1},
    'kitchen_appliance_brand': {'pe': 18.0, 'pb': 3.5, 'ps': 1.6},
    'export_small_appliance': {'pe': 14.0, 'pb': 1.4, 'ps': 0.9},
    'gaming_media': {'pe': 16.0, 'pb': 2.6, 'ps': 3.0},
    'film_cinema': {'pe': 30.0, 'pb': 2.6, 'ps': 3.6},
    'film_content_production': {'pe': 34.0, 'pb': 3.0, 'ps': 2.0},
    'premium_game': {'pe': 14.5, 'pb': 4.0, 'ps': 4.2},
    'food_processing': {'pe': 24.0, 'pb': 3.5, 'ps': 1.9},
    'snack_food': {'pe': 21.0, 'pb': 2.3, 'ps': 1.8},
    'condiment': {'pe': 34.0, 'pb': 4.6, 'ps': 6.0},
    'beverage_dairy': {'pe': 28.0, 'pb': 5.0, 'ps': 2.8},
    'medical_service': {'pe': 26.0, 'pb': 3.4, 'ps': 2.6},
    'education_training': {'pe': 22.0, 'pb': 3.8, 'ps': 1.2},
    'distressed_education': {'pe': 10.0, 'pb': 1.1, 'ps': 0.6},
    'leisure_culture_goods': {'pe': 26.0, 'pb': 2.8, 'ps': 2.2},
    'tourism_services': {'pe': 28.0, 'pb': 1.8, 'ps': 3.2},
    'traditional_chinese_medicine': {'pe': 27.0, 'pb': 3.8, 'ps': 2.5},
    'chemical_raw_material': {'pe': 18.0, 'pb': 1.9, 'ps': 1.15},
    'chemical_products': {'pe': 24.0, 'pb': 2.4, 'ps': 1.7},
    'daily_chemical': {'pe': 26.0, 'pb': 3.4, 'ps': 2.6},
    'chemical_fiber': {'pe': 14.0, 'pb': 1.1, 'ps': 0.85},
    'textile_manufacturing': {'pe': 14.0, 'pb': 1.2, 'ps': 0.9},
    'textile_quality_manufacturing': {'pe': 18.0, 'pb': 2.4, 'ps': 2.2},
    'textile_value_manufacturing': {'pe': 10.0, 'pb': 0.55, 'ps': 0.9},
    'biotech': {'pe': 32.0, 'pb': 3.0, 'ps': 2.8},
    'pharma_distribution': {'pe': 14.0, 'pb': 1.5, 'ps': 0.16},
    'photovoltaic_equipment': {'pe': 22.0, 'pb': 1.8, 'ps': 1.15},
    'wind_power_equipment': {'pe': 24.0, 'pb': 1.9, 'ps': 1.4},
    'it_hardware': {'pe': 20.0, 'pb': 1.6, 'ps': 1.2},
    'electronic_components': {'pe': 34.0, 'pb': 3.6, 'ps': 2.2},
    'packaging_printing': {'pe': 16.0, 'pb': 1.8, 'ps': 1.0},
    'logistics': {'pe': 16.0, 'pb': 1.5, 'ps': 1.1},
    'coal_mining': {'pe': 20.0, 'pb': 1.5, 'ps': 1.4},
    'other_power_equipment': {'pe': 46.0, 'pb': 4.5, 'ps': 4.0},
    'steel_standard': {'pe': 14.0, 'pb': 0.75, 'ps': 0.45},
    'interior_decoration': {'pe': 24.0, 'pb': 1.3, 'ps': 1.0},
    'cement_materials': {'pe': 14.0, 'pb': 1.1, 'ps': 0.9},
    'rubber_materials': {'pe': 22.0, 'pb': 1.3, 'ps': 0.9},
    'carbon_black_materials': {'pe': 18.0, 'pb': 0.9, 'ps': 0.7},
    'trade_distribution': {'pe': 16.0, 'pb': 0.9, 'ps': 0.2},
    'commodity_trading': {'pe': 14.0, 'pb': 0.8, 'ps': 0.12},
    'export_supply_chain': {'pe': 17.0, 'pb': 1.1, 'ps': 0.35},
    'livestock_breeding': {'pe': 18.0, 'pb': 1.6, 'ps': 1.2},
    'hog_breeding': {'pe': 17.0, 'pb': 1.3, 'ps': 1.4},
    'poultry_breeding': {'pe': 21.0, 'pb': 1.9, 'ps': 1.6},
    'feed_processing': {'pe': 16.0, 'pb': 2.2, 'ps': 0.85},
    'ecommerce_service': {'pe': 24.0, 'pb': 2.8, 'ps': 1.6},
    'agri_processing': {'pe': 20.0, 'pb': 1.4, 'ps': 0.55},
    'consumer_oil_processing': {'pe': 23.0, 'pb': 2.0, 'ps': 0.8},
    'grain_storage_processing': {'pe': 17.0, 'pb': 1.0, 'ps': 0.28},
    'seed_planting': {'pe': 24.0, 'pb': 1.7, 'ps': 2.0},
    'cyclical_manufacturing': {'pe': 15.0, 'pb': 2.0, 'ps': 1.2},
    'industrial_metal': {'pe': 15.0, 'pb': 2.4, 'ps': 1.8},
    'utilities_infra': {'pe': 16.0, 'pb': 1.8, 'ps': 2.2},
    'bank': {'pe': 6.0, 'pb': 0.8, 'ps': None},
    'nonbank_finance': {'pe': 14.0, 'pb': 1.4, 'ps': None},
    'healthcare_growth': {'pe': 30.0, 'pb': 4.5, 'ps': 5.0},
    'tech_growth': {'pe': 35.0, 'pb': 5.0, 'ps': 6.0},
    'generic_equity': {'pe': 18.0, 'pb': 2.0, 'ps': 2.0},
}

FINANCIAL_TEMPLATES = {'bank', 'nonbank_finance'}


def resolve_valuation_template_id(explicit_template: str | None, industry_level_1_name: str | None, industry_level_2_name: str | None) -> str:
    text = str(explicit_template or '').strip()
    if text:
        return text
    level2 = str(industry_level_2_name or '').strip()
    if level2 in INDUSTRY_L2_TEMPLATE_MAP:
        return INDUSTRY_L2_TEMPLATE_MAP[level2]
    fallback = FALLBACK_TEMPLATE_MAP.get(str(industry_level_1_name or '').strip())
    if fallback:
        return fallback
    return 'generic_equity'


def refine_valuation_template_id(template_id: str | None, industry_level_2_name: str | None, metrics: dict[str, object] | None = None) -> str:
    current = str(template_id or '').strip() or 'generic_equity'
    level2 = str(industry_level_2_name or '').strip()
    metrics = metrics or {}
    if current == 'engineering_machinery' and level2 == '工程机械':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        if dynamic_pe is not None and dynamic_pe <= 30:
            return 'construction_machinery'
    if current == 'military_electronics' and level2 == '军工电子':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        try:
            eps = float(metrics.get('eps')) if metrics.get('eps') is not None else None
        except (TypeError, ValueError):
            eps = None
        if dynamic_pe is None or (eps is not None and eps <= 0):
            return 'military_info_system'
    if current == 'optical_photonics' and level2 == '光学光电':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if dynamic_pe is not None and dynamic_pe <= 30 and debt_ratio is not None and debt_ratio >= 45:
            return 'display_panel'
    if current == 'consumer_electronics' and level2 == '消费电子':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        if dynamic_pe is not None and dynamic_pe <= 26 and revenue_per_share is not None and revenue_per_share >= 30:
            return 'consumer_assembly'
    if current == 'professional_services' and level2 == '专业服务':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        if revenue_per_share is not None and revenue_per_share >= 20:
            return 'human_resource_service'
        return 'testing_inspection_service'
    if current == 'textile_manufacturing' and level2 == '纺织制造':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        try:
            profit_growth = float(metrics.get('profit_growth')) if metrics.get('profit_growth') is not None else None
        except (TypeError, ValueError):
            profit_growth = None
        if dynamic_pe is not None and dynamic_pe >= 15 and profit_growth is not None and profit_growth > -15:
            return 'textile_quality_manufacturing'
        return 'textile_value_manufacturing'
    if current == 'shipping_ports' and level2 == '航运港口':
        try:
            revenue_growth = float(metrics.get('revenue_growth')) if metrics.get('revenue_growth') is not None else None
        except (TypeError, ValueError):
            revenue_growth = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if revenue_growth is not None and revenue_growth >= 15 and debt_ratio is not None and debt_ratio >= 30:
            return 'shipping_carrier'
        return 'port_operator'
    if current == 'ad_marketing' and level2 == '广告营销':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if (revenue_per_share is not None and revenue_per_share >= 10) or (debt_ratio is not None and debt_ratio >= 60):
            return 'digital_marketing_agency'
        return 'media_ad_platform'
    if current == 'home_appliance_components' and level2 == '家电零部件':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        if dynamic_pe is not None and dynamic_pe >= 35 and debt_ratio is not None and debt_ratio <= 45:
            return 'appliance_precision_components'
        if (debt_ratio is not None and debt_ratio >= 55) or (revenue_per_share is not None and revenue_per_share >= 15):
            return 'appliance_manufacturing_components'
        return 'home_appliance_components'
    if current == 'motor_manufacturing' and level2 == '电机制造':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        if dynamic_pe is not None and dynamic_pe >= 35 and revenue_per_share is not None and revenue_per_share >= 20:
            return 'motor_control_components'
        return 'motor_manufacturing'
    if current == 'small_appliance' and level2 == '小家电':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if revenue_per_share is not None and revenue_per_share >= 25 and debt_ratio is not None and debt_ratio <= 55:
            return 'kitchen_appliance_brand'
        return 'export_small_appliance'
    if current == 'gaming_media' and level2 == '游戏':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if revenue_per_share is not None and revenue_per_share >= 50 and debt_ratio is not None and debt_ratio <= 30:
            return 'premium_game'
        return 'gaming_media'
    if current == 'trade_distribution' and level2 == '贸易':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if (revenue_per_share is not None and revenue_per_share >= 35) or (debt_ratio is not None and debt_ratio >= 60):
            return 'commodity_trading'
        return 'export_supply_chain'
    if current == 'livestock_breeding' and level2 == '养殖业':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if (revenue_per_share is not None and revenue_per_share >= 20) or (debt_ratio is not None and debt_ratio >= 48):
            return 'hog_breeding'
        return 'poultry_breeding'
    if current == 'film_cinema' and level2 == '影视院线':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if revenue_per_share is not None and revenue_per_share <= 1.5 and debt_ratio is not None and debt_ratio <= 20:
            return 'film_content_production'
        return 'film_cinema'
    if current == 'education_training' and level2 == '教育培训':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        try:
            eps = float(metrics.get('eps')) if metrics.get('eps') is not None else None
        except (TypeError, ValueError):
            eps = None
        if (
            (revenue_per_share is not None and revenue_per_share <= 1)
            or (debt_ratio is not None and debt_ratio >= 80)
            or (eps is not None and eps <= 0)
        ):
            return 'distressed_education'
        return 'education_training'
    if current == 'rubber_materials' and level2 == '橡胶':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        try:
            debt_ratio = float(metrics.get('debt_ratio')) if metrics.get('debt_ratio') is not None else None
        except (TypeError, ValueError):
            debt_ratio = None
        if debt_ratio is not None and debt_ratio >= 60 and revenue_per_share is not None and revenue_per_share >= 10:
            return 'carbon_black_materials'
        return 'rubber_materials'
    if current == 'agri_processing' and level2 == '农产品加工':
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        if revenue_per_share is not None and revenue_per_share >= 20:
            return 'consumer_oil_processing'
        return 'grain_storage_processing'
    if current == 'aviation_equipment' and level2 == '航空装备':
        try:
            dynamic_pe = float(metrics.get('dynamic_pe')) if metrics.get('dynamic_pe') is not None else None
        except (TypeError, ValueError):
            dynamic_pe = None
        try:
            revenue_per_share = float(metrics.get('revenue_per_share')) if metrics.get('revenue_per_share') is not None else None
        except (TypeError, ValueError):
            revenue_per_share = None
        if dynamic_pe is not None and revenue_per_share is not None and revenue_per_share <= 8:
            if dynamic_pe >= 60:
                return 'high_temp_alloy'
            if dynamic_pe <= 50:
                return 'aerospace_material'
    return current


def get_template_defaults(template_id: str | None) -> dict[str, float | None]:
    return dict(TEMPLATE_DEFAULTS.get(str(template_id or '').strip(), TEMPLATE_DEFAULTS['generic_equity']))

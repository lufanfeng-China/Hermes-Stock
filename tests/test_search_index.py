import tempfile
import unittest
from pathlib import Path


TNF_HEADER_SIZE = 50
TNF_RECORD_SIZE = 360
NAME_OFFSET = 31
PINYIN_OFFSET = 329


def build_tnf_record(code: str, name: str, pinyin: str) -> bytes:
    record = bytearray(TNF_RECORD_SIZE)
    record[0:6] = code.encode("ascii")
    name_bytes = name.encode("gbk")
    pinyin_bytes = pinyin.encode("ascii")
    record[NAME_OFFSET : NAME_OFFSET + len(name_bytes)] = name_bytes
    record[PINYIN_OFFSET : PINYIN_OFFSET + len(pinyin_bytes)] = pinyin_bytes
    return bytes(record)


class SearchIndexTests(unittest.TestCase):
    def test_parse_tnf_file_extracts_code_name_and_initials(self) -> None:
        from app.search.index import parse_tnf_file

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "shs.tnf"
            payload = bytearray(TNF_HEADER_SIZE)
            payload.extend(build_tnf_record("601600", "中国铝业", "ZGLY"))
            payload.extend(build_tnf_record("600000", "浦发银行", "PFYH"))
            path.write_bytes(bytes(payload))

            rows = parse_tnf_file(path, market="sh")

        self.assertEqual(
            [
                {
                    "market": "sh",
                    "symbol": "601600",
                    "stock_name": "中国铝业",
                    "name_initials": "zgly",
                },
                {
                    "market": "sh",
                    "symbol": "600000",
                    "stock_name": "浦发银行",
                    "name_initials": "pfyh",
                },
            ],
            rows,
        )

    def test_search_stocks_supports_code_name_and_initials(self) -> None:
        from app.search.index import search_stocks

        rows = [
            {"market": "sh", "symbol": "601600", "stock_name": "中国铝业", "name_initials": "zgly"},
            {"market": "sz", "symbol": "000001", "stock_name": "平安银行", "name_initials": "payh"},
            {"market": "sz", "symbol": "300750", "stock_name": "宁德时代", "name_initials": "ndsd"},
        ]

        self.assertEqual(["601600"], [row["symbol"] for row in search_stocks(rows, "601600")])
        self.assertEqual(["000001"], [row["symbol"] for row in search_stocks(rows, "平安")])
        self.assertEqual(["300750"], [row["symbol"] for row in search_stocks(rows, "nd")])
        self.assertEqual(["601600"], [row["symbol"] for row in search_stocks(rows, "zgly")])

    def test_build_concept_index_aggregates_member_count_and_stock_details(self) -> None:
        from app.search.index import build_concept_index, search_concepts

        securities = [
            {"market": "sh", "symbol": "601600", "stock_name": "中国铝业", "name_initials": "zgly"},
            {"market": "sz", "symbol": "000333", "stock_name": "美的集团", "name_initials": "mdjt"},
        ]
        industry_rows = [
            {
                "market": "sh",
                "symbol": "601600",
                "industry_level_1_name": "有色",
                "industry_level_2_name": "工业金属",
                "industry_level_3_name": "铝",
            },
            {
                "market": "sz",
                "symbol": "000333",
                "industry_level_1_name": "家电",
                "industry_level_2_name": "白色家电",
                "industry_level_3_name": "空调",
            },
        ]
        concept_rows = [
            {
                "concept_id": "deepseek",
                "concept_name": "DeepSeek概念",
                "market": "sh",
                "symbol": "601600",
            },
            {
                "concept_id": "deepseek",
                "concept_name": "DeepSeek概念",
                "market": "sz",
                "symbol": "000333",
            },
            {
                "concept_id": "apple",
                "concept_name": "苹果概念",
                "market": "sz",
                "symbol": "000333",
            },
        ]

        concepts = build_concept_index(concept_rows, securities, industry_rows)
        matched = search_concepts(concepts, "DeepSeek")

        self.assertEqual(1, len(matched))
        self.assertEqual("deepseek", matched[0]["concept_id"])
        self.assertEqual(2, matched[0]["member_count"])
        self.assertEqual(
            ["601600", "000333"],
            [row["symbol"] for row in matched[0]["members"]],
        )
        self.assertEqual("中国铝业", matched[0]["members"][0]["stock_name"])
        self.assertEqual("有色 / 工业金属 / 铝", matched[0]["members"][0]["industry_display"])

    def test_search_concepts_supports_partial_name_match(self) -> None:
        from app.search.index import search_concepts

        concepts = [
            {"concept_id": "deepseek", "concept_name": "DeepSeek概念", "member_count": 2, "members": []},
            {"concept_id": "apple", "concept_name": "苹果概念", "member_count": 3, "members": []},
        ]

        self.assertEqual(["apple"], [row["concept_id"] for row in search_concepts(concepts, "苹果")])
        self.assertEqual(["deepseek"], [row["concept_id"] for row in search_concepts(concepts, "seek")])

    def test_build_stock_profile_includes_industry_and_concepts(self) -> None:
        from app.search.index import build_stock_profile

        securities = [
            {"market": "sh", "symbol": "601600", "stock_name": "中国铝业", "name_initials": "zgly"},
            {"market": "sz", "symbol": "000333", "stock_name": "美的集团", "name_initials": "mdjt"},
        ]
        industry_rows = [
            {
                "market": "sh",
                "symbol": "601600",
                "industry_level_1_name": "有色",
                "industry_level_2_name": "工业金属",
                "industry_level_3_name": "铝",
            }
        ]
        concept_rows = [
            {
                "concept_id": "deepseek",
                "concept_name": "DeepSeek概念",
                "market": "sh",
                "symbol": "601600",
                "concept_filter_decision": "keep_core",
                "concept_filter_bucket": "core",
            },
            {
                "concept_id": "apple",
                "concept_name": "苹果概念",
                "market": "sh",
                "symbol": "601600",
                "concept_filter_decision": "keep_core",
                "concept_filter_bucket": "core",
            },
            {
                "concept_id": "apple",
                "concept_name": "苹果概念",
                "market": "sh",
                "symbol": "601600",
                "concept_filter_decision": "keep_core",
                "concept_filter_bucket": "core",
            },
            {
                "concept_id": "kdj",
                "concept_name": "KDJ超卖",
                "market": "sh",
                "symbol": "601600",
                "concept_filter_decision": "hide_from_default_ui",
                "concept_filter_bucket": "technical",
            },
            {
                "concept_id": "lockup",
                "concept_name": "不可减持(新规)",
                "market": "sh",
                "symbol": "601600",
                "concept_filter_decision": "hide_from_default_ui",
                "concept_filter_bucket": "shareholder",
            },
            {
                "concept_id": "smart-home",
                "concept_name": "智能家居",
                "market": "sz",
                "symbol": "000333",
                "concept_filter_decision": "keep_core",
                "concept_filter_bucket": "core",
            },
        ]

        profile = build_stock_profile("601600", securities, industry_rows, concept_rows)

        self.assertEqual("601600", profile["symbol"])
        self.assertEqual("sh", profile["market"])
        self.assertEqual("中国铝业", profile["stock_name"])
        self.assertEqual("zgly", profile["name_initials"])
        self.assertEqual("有色 / 工业金属 / 铝", profile["industry_display"])
        self.assertEqual(["DeepSeek概念", "苹果概念"], [row["concept_name"] for row in profile["core_concepts"]])
        self.assertEqual(2, profile["concept_count"])
        self.assertEqual(2, profile["core_concept_count"])
        self.assertEqual(["KDJ超卖"], [row["concept_name"] for row in profile["auxiliary_concepts"]["technical"]])
        self.assertEqual(["不可减持(新规)"], [row["concept_name"] for row in profile["auxiliary_concepts"]["shareholder"]])

    def test_build_stock_profile_falls_back_to_rule_classification_when_filter_fields_missing(self) -> None:
        from app.search.index import build_stock_profile

        securities = [{"market": "sh", "symbol": "601600", "stock_name": "中国铝业", "name_initials": "zgly"}]
        industry_rows = [{"market": "sh", "symbol": "601600", "industry_level_1_name": "有色", "industry_level_2_name": "工业金属", "industry_level_3_name": "铝"}]
        concept_rows = [
            {"concept_id": "a", "concept_name": "DeepSeek概念", "market": "sh", "symbol": "601600"},
            {"concept_id": "b", "concept_name": "KDJ超卖", "market": "sh", "symbol": "601600"},
            {"concept_id": "c", "concept_name": "不可减持(新规)", "market": "sh", "symbol": "601600"},
        ]

        profile = build_stock_profile("601600", securities, industry_rows, concept_rows)

        self.assertEqual(["DeepSeek概念"], [row["concept_name"] for row in profile["core_concepts"]])
        self.assertEqual(["KDJ超卖"], [row["concept_name"] for row in profile["auxiliary_concepts"]["technical"]])
        self.assertEqual(["不可减持(新规)"], [row["concept_name"] for row in profile["auxiliary_concepts"]["shareholder"]])

    def test_build_stock_profile_includes_rps_metrics(self) -> None:
        from app.search.index import build_stock_profile

        securities = [
            {"market": "sh", "symbol": "601600", "stock_name": "中国铝业", "name_initials": "zgly"},
            {"market": "sh", "symbol": "601168", "stock_name": "西部矿业", "name_initials": "xbky"},
            {"market": "sh", "symbol": "600111", "stock_name": "北方稀土", "name_initials": "bfxt"},
        ]
        industry_rows = [
            {"market": "sh", "symbol": "601600", "industry_level_1_name": "有色", "industry_level_2_name": "工业金属", "industry_level_3_name": "铝"},
            {"market": "sh", "symbol": "601168", "industry_level_1_name": "有色", "industry_level_2_name": "工业金属", "industry_level_3_name": "铜"},
            {"market": "sh", "symbol": "600111", "industry_level_1_name": "有色", "industry_level_2_name": "稀土", "industry_level_3_name": "稀土永磁"},
        ]
        concept_rows = []
        rps_rows = [
            {
                "trading_day": "2026-04-24",
                "market": "sh",
                "symbol": "601600",
                "rps_20": 60.76,
                "rps_50": 48.97,
                "return_20_pct": 4.7203,
                "return_50_pct": -5.2215,
                "rank_20": 2037,
                "rank_50": 2649,
                "universe_size": 5189,
            },
            {
                "trading_day": "2026-04-24",
                "market": "sh",
                "symbol": "601168",
                "rps_20": 82.35,
                "rps_50": 52.12,
                "return_20_pct": 12.1203,
                "return_50_pct": 3.2215,
                "rank_20": 812,
                "rank_50": 2210,
                "universe_size": 5189,
            },
            {
                "trading_day": "2026-04-24",
                "market": "sh",
                "symbol": "600111",
                "rps_20": 77.35,
                "rps_50": 58.12,
                "return_20_pct": 9.1203,
                "return_50_pct": 5.2215,
                "rank_20": 1200,
                "rank_50": 1800,
                "universe_size": 5189,
            }
        ]

        profile = build_stock_profile("601600", securities, industry_rows, concept_rows, rps_rows)

        self.assertEqual(60.76, profile["rps_20"])
        self.assertEqual(48.97, profile["rps_50"])
        self.assertIsNone(profile["rps_120"])
        self.assertIsNone(profile["rps_250"])
        self.assertEqual(2037, profile["rank_20"])
        self.assertEqual(5189, profile["universe_size"])
        self.assertEqual(2, profile["industry_rank_20"])
        self.assertEqual(2, profile["industry_rank_50"])
        self.assertEqual(2, profile["industry_universe_size"])

    def test_build_stock_profile_includes_basic_info_payload(self) -> None:
        from app.search.index import build_stock_profile

        securities = [{"market": "sz", "symbol": "000333", "stock_name": "美的集团", "name_initials": "mdjt"}]
        industry_rows = [{"market": "sz", "symbol": "000333", "industry_level_1_name": "家电", "industry_level_2_name": "白色家电", "industry_level_3_name": "空调"}]
        concept_rows = []
        basic_info = {
            "current_price": 81.10,
            "change_pct": -0.26,
            "volume_ratio": 1.23,
            "a_share_market_cap": 5642.17,
            "total_shares": 76.03,
            "float_shares": 68.52,
            "eps": 1.69,
            "dynamic_pe": 14.8,
        }

        profile = build_stock_profile("000333", securities, industry_rows, concept_rows, basic_info=basic_info)

        self.assertEqual(basic_info, profile["basic_info"])

    def test_search_rps_ranking_supports_window_and_name_filters(self) -> None:
        from app.search.index import build_rps_index, search_rps_rankings

        securities = [
            {"market": "sh", "symbol": "601600", "stock_name": "中国铝业", "name_initials": "zgly"},
            {"market": "sz", "symbol": "000333", "stock_name": "美的集团", "name_initials": "mdjt"},
            {"market": "sz", "symbol": "000001", "stock_name": "平安银行", "name_initials": "payh"},
        ]
        industry_rows = [
            {"market": "sh", "symbol": "601600", "industry_level_1_name": "有色", "industry_level_2_name": "工业金属", "industry_level_3_name": "铝"},
            {"market": "sz", "symbol": "000333", "industry_level_1_name": "家电", "industry_level_2_name": "白色家电", "industry_level_3_name": "空调"},
            {"market": "sz", "symbol": "000001", "industry_level_1_name": "银行", "industry_level_2_name": "股份制银行", "industry_level_3_name": "全国性银行"},
        ]
        rps_rows = [
            {"trading_day": "2026-04-24", "market": "sh", "symbol": "601600", "rps_20": 60.76, "rps_50": 48.97, "return_20_pct": 4.7203, "return_50_pct": -5.2215, "rank_20": 2037, "rank_50": 2649, "universe_size": 5189},
            {"trading_day": "2026-04-24", "market": "sz", "symbol": "000333", "rps_20": 88.12, "rps_50": 91.55, "return_20_pct": 12.15, "return_50_pct": 18.73, "rank_20": 615, "rank_50": 438, "universe_size": 5189},
            {"trading_day": "2026-04-24", "market": "sz", "symbol": "000001", "rps_20": 22.45, "rps_50": 40.10, "return_20_pct": -3.11, "return_50_pct": -7.86, "rank_20": 4025, "rank_50": 3108, "universe_size": 5189},
        ]

        index = build_rps_index(rps_rows, securities, industry_rows)
        top_rankings = search_rps_rankings(index, window=20, limit=2)
        filtered = search_rps_rankings(index, query="zgly", window=20, limit=5)

        self.assertEqual(["000333", "601600"], [row["symbol"] for row in top_rankings])
        self.assertEqual(["601600"], [row["symbol"] for row in filtered])
        self.assertEqual(60.76, filtered[0]["rps"])
        self.assertEqual("rps_20", filtered[0]["metric_key"])


if __name__ == "__main__":
    unittest.main()

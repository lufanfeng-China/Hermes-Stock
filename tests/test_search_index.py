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


if __name__ == "__main__":
    unittest.main()

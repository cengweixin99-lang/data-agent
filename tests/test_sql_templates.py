import unittest

from app.agent.sql_templates import try_generate_template_sql


class SQLTemplateTests(unittest.TestCase):
    def test_region_product_topn_groups_by_display_dimensions(self):
        sql = try_generate_template_sql("统计各地区销售量排行前三的产品")

        self.assertIsNotNone(sql)
        self.assertIn("PARTITION BY 地区", sql)
        self.assertIn("GROUP BY r.region_name, p.product_name", sql)
        self.assertNotIn("PARTITION BY r.region_id", sql)
        self.assertNotIn("GROUP BY r.region_id", sql)
        self.assertNotIn("GROUP BY r.region_name, p.product_id", sql)
        self.assertIn("WHERE 排名 <= 3", sql)

    def test_global_product_topn_groups_by_product_name(self):
        sql = try_generate_template_sql("查询销售额最高的前5个商品")

        self.assertIsNotNone(sql)
        self.assertIn("GROUP BY p.product_name", sql)
        self.assertNotIn("GROUP BY p.product_id", sql)
        self.assertIn("LIMIT 5", sql)


if __name__ == "__main__":
    unittest.main()
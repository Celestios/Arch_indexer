from engines.edge_weights import EdgeWeightCalculator


class TestCalculateWeight:
    def test_default_weight_no_classifications(self):
        result = EdgeWeightCalculator.calculate_weight({}, {}, set())
        assert result == 1.0

    def test_none_source_classifications(self):
        result = EdgeWeightCalculator.calculate_weight(None, {}, set())
        assert result == 1.0

    def test_none_target_classifications(self):
        result = EdgeWeightCalculator.calculate_weight({"layer": "ui"}, None, set())
        assert result == 1.0

    def test_same_layer_boost(self):
        src = {"layer": "ui"}
        tgt = {"layer": "ui"}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 1.5

    def test_different_layers_no_boost(self):
        src = {"layer": "ui"}
        tgt = {"layer": "domain"}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 1.0

    def test_higher_tier_to_lower_tier_penalty(self):
        src = {"tier": 3}
        tgt = {"tier": 1}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 0.5

    def test_lower_tier_to_higher_tier_no_penalty(self):
        src = {"tier": 1}
        tgt = {"tier": 3}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 1.0

    def test_same_tier_no_penalty(self):
        src = {"tier": 2}
        tgt = {"tier": 2}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 1.0

    def test_barrier_role_penalty(self):
        src = {"architectural_role": "gateway"}
        result = EdgeWeightCalculator.calculate_weight(src, {}, {"gateway"})
        assert result == 0.3

    def test_role_field_fallback(self):
        src = {"role": "gateway"}
        result = EdgeWeightCalculator.calculate_weight(src, {}, {"gateway"})
        assert result == 0.3

    def test_non_barrier_role_no_penalty(self):
        src = {"architectural_role": "service"}
        result = EdgeWeightCalculator.calculate_weight(src, {}, {"gateway"})
        assert result == 1.0

    def test_combined_same_layer_and_barrier(self):
        src = {"layer": "ui", "architectural_role": "gateway"}
        tgt = {"layer": "ui"}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, {"gateway"})
        assert result == 1.5 * 0.3

    def test_combined_same_layer_and_higher_tier(self):
        src = {"layer": "ui", "tier": 3}
        tgt = {"layer": "ui", "tier": 1}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 1.5 * 0.5

    def test_all_three_multipliers(self):
        src = {"layer": "ui", "tier": 3, "architectural_role": "gateway"}
        tgt = {"layer": "ui", "tier": 1}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, {"gateway"})
        expected = 1.0 * 1.5 * 0.5 * 0.3
        assert result == expected

    def test_non_numeric_tier_is_ignored(self):
        src = {"tier": "abc"}
        tgt = {"tier": 1}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 1.0

    def test_none_tier_values(self):
        src = {"tier": None}
        tgt = {"tier": 1}
        result = EdgeWeightCalculator.calculate_weight(src, tgt, set())
        assert result == 1.0

    def test_empty_classifications_dict(self):
        result = EdgeWeightCalculator.calculate_weight({}, {}, set())
        assert result == 1.0


class TestCollectBarriers:
    def test_empty_config(self):
        result = EdgeWeightCalculator.collect_barriers({})
        assert result == set()

    def test_no_propagation_handlers(self):
        config = {
            "src/": {
                "automatic_fields": {
                    "layer": {"handler": "assignment", "default": "core"}
                }
            }
        }
        result = EdgeWeightCalculator.collect_barriers(config)
        assert result == set()

    def test_automatic_field_barriers(self):
        config = {
            "src/": {
                "automatic_fields": {
                    "role": {
                        "handler": "propagation",
                        "barriers": {"gateway", "boundary"}
                    }
                }
            }
        }
        result = EdgeWeightCalculator.collect_barriers(config)
        assert result == {"gateway", "boundary"}

    def test_manual_field_barriers(self):
        config = {
            "src/": {
                "manual_fields": {
                    "tier": {
                        "handler": "propagation",
                        "barriers": {"critical"}
                    }
                }
            }
        }
        result = EdgeWeightCalculator.collect_barriers(config)
        assert result == {"critical"}

    def test_both_auto_and_manual_barriers(self):
        config = {
            "src/": {
                "automatic_fields": {
                    "role": {
                        "handler": "propagation",
                        "barriers": {"gateway"}
                    }
                },
                "manual_fields": {
                    "tier": {
                        "handler": "propagation",
                        "barriers": {"critical"}
                    }
                }
            }
        }
        result = EdgeWeightCalculator.collect_barriers(config)
        assert result == {"gateway", "critical"}

    def test_multiple_prefixes(self):
        config = {
            "src/": {
                "automatic_fields": {
                    "role": {
                        "handler": "propagation",
                        "barriers": {"a", "b"}
                    }
                }
            },
            "lib/": {
                "automatic_fields": {
                    "role": {
                        "handler": "propagation",
                        "barriers": {"b", "c"}
                    }
                }
            }
        }
        result = EdgeWeightCalculator.collect_barriers(config)
        assert result == {"a", "b", "c"}

    def test_empty_barriers_list(self):
        config = {
            "src/": {
                "automatic_fields": {
                    "role": {
                        "handler": "propagation",
                        "barriers": []
                    }
                }
            }
        }
        result = EdgeWeightCalculator.collect_barriers(config)
        assert result == set()

    def test_none_barriers(self):
        config = {
            "src/": {
                "automatic_fields": {
                    "role": {
                        "handler": "propagation",
                        "barriers": None
                    }
                }
            }
        }
        result = EdgeWeightCalculator.collect_barriers(config)
        assert result == set()

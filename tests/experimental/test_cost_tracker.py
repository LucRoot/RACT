__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.experimental.cost_tracker import aggregate_costs, budget_status

def test_aggregate_costs_totals():
    receipts = [
        {'provider': 'qwen', 'tokens': 10, 'cost': 0.01},
        {'provider': 'qwen', 'tokens': 20, 'cost': 0.02},
        {'provider': 'bonsai', 'tokens': 5, 'cost': 0.005},
    ]
    result = aggregate_costs(receipts)
    assert result['total']['tokens'] == 35
    assert result['per_provider']['qwen']['tokens'] == 30
    assert result['per_provider']['bonsai']['cost'] == 0.005

def test_budget_status():
    status = budget_status({'cost': 0.05}, {'cost': 0.1})
    assert status['spent'] == 0.05
    assert status['remaining'] == 0.05
    assert not status['over_budget']


def test_aggregate_costs_falls_back_to_cost_index():
    receipts = [
        {'provider': 'openai', 'tokens': 2000},
        {'provider': 'local', 'tokens': 10000},
    ]
    result = aggregate_costs(receipts)
    # openai blended rate = (0.15 + 0.60) / 2 / 1000 = 0.000375 per token
    assert result['per_provider']['openai']['cost'] == 0.75
    assert result['per_provider']['local']['cost'] == 0.0


def test_aggregate_costs_honours_input_output_split():
    receipts = [
        {'provider': 'anthropic', 'input_tokens': 1000, 'output_tokens': 500},
    ]
    result = aggregate_costs(receipts)
    # 3.0 + 7.5 = 10.5
    assert result['per_provider']['anthropic']['cost'] == 10.5

from balatro_ai_v2.solver.shadow_blind import SearchContinuation
from balatro_ai_v2.live.runner import SEARCH_VARIANTS
import pytest
from balatro_ai_v2.solver.shadow_blind import main


def test_continuation_uses_v6_options_and_replaces_history(monkeypatch):
    captured = {}

    class FakeSearch:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.history = []

        def select(self, observation):
            assert observation == 'public'
            return 'action', 'reason', {}

    monkeypatch.setattr('balatro_ai_v2.live.strategic.SearchPolicy', FakeSearch)
    policy = SearchContinuation()
    assert captured == SEARCH_VARIANTS['search-v6']
    assert policy.choose_action('public', None, ('first',)) == 'action'
    assert policy.policy.history == ['first']
    policy.choose_action('public', None, ('second',))
    assert policy.policy.history == ['second']


def test_two_antes_requires_ante_horizon(monkeypatch, tmp_path):
    monkeypatch.setattr('sys.argv', ['shadow_blind', '--trace', 'unused',
                                    '--decision', '0', '--antes', '2',
                                    '--output', str(tmp_path / 'report.json')])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not (tmp_path / 'report.json').exists()

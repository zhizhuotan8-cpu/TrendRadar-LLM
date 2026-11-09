import pytest

from trendradar.intelligence.budget import Budget, BudgetExceeded, BudgetedClient


def test_atomic_reservation_and_deadline():
    now = [0]
    budget = Budget(model_calls=1, output_tokens=10, seconds=5, clock=lambda: now[0])
    assert budget.reserve(30, model_calls=1, output_tokens=10) == 5
    with pytest.raises(BudgetExceeded):
        budget.reserve(bodies=1, model_calls=1)
    assert budget.used['bodies'] == 0
    now[0] = 5
    with pytest.raises(BudgetExceeded):
        budget.reserve()


def test_failed_model_call_consumes_budget():
    class Client:
        calls = 0
        def chat(self, messages, **kwargs):
            self.calls += 1
            assert kwargs['num_retries'] == 0
            raise RuntimeError('provider failure')
    client = Client()
    wrapper = BudgetedClient(client, Budget(model_calls=1))
    with pytest.raises(RuntimeError):
        wrapper.chat([], max_tokens=100)
    with pytest.raises(BudgetExceeded):
        wrapper.chat([], max_tokens=100)
    assert client.calls == 1

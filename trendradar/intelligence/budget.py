"""Per-run reservations: failed calls still consume capacity; tokens are upper bounds."""

import time


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, *, model_calls=12, output_tokens=24000, bodies=20,
                 searches=3, requests=30, seconds=300, clock=time.monotonic):
        self.limits = dict(model_calls=model_calls, output_tokens=output_tokens,
                           bodies=bodies, searches=searches, requests=requests)
        if any(type(v) is not int or v < 0 for v in self.limits.values()) or seconds <= 0:
            raise ValueError('Invalid budget')
        self.used = {key: 0 for key in self.limits}
        self.clock = clock
        self.deadline = clock() + seconds

    def reserve(self, timeout=30, **costs):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise BudgetExceeded('总时长预算已耗尽')
        for key, count in costs.items():
            if type(count) is not int or count < 0 or key not in self.limits:
                raise ValueError('Invalid reservation')
            if self.used[key] + count > self.limits[key]:
                raise BudgetExceeded(f'{key} 预算已耗尽')
        if timeout <= 0:
            raise ValueError('Positive timeout required')
        for key, count in costs.items():
            self.used[key] += count
        return min(timeout, remaining)

    def summary(self):
        return {'reserved': dict(self.used), 'limits': dict(self.limits),
                'remaining_seconds': max(0, self.deadline - self.clock()),
                'token_accounting': '预留输出上限，非实际计费 token'}


class BudgetedClient:
    def __init__(self, client, budget):
        self.client, self.budget = client, budget
        if getattr(client, 'fallback_models', []):
            raise ValueError('Disable fallback models for budgeted execution')

    def chat(self, messages, **kwargs):
        tokens = kwargs.get('max_tokens', 2000)
        kwargs['timeout'] = self.budget.reserve(kwargs.get('timeout', 30),
                                              model_calls=1, output_tokens=tokens)
        kwargs.update(max_tokens=tokens, num_retries=0)
        return self.client.chat(messages, **kwargs)


class BudgetedReader:
    def __init__(self, reader, budget):
        self.reader, self.budget = reader, budget

    def read_article(self, url, timeout=30):
        timeout = self.budget.reserve(timeout, bodies=1)
        return self.reader.read_article(url, timeout=timeout)

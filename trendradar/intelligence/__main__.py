"""python -m trendradar.intelligence daily|daemon"""

import argparse
from datetime import datetime, timezone
import json
import time
import pytz

from .runtime import DailyRunner, load_settings


def main():
    parser = argparse.ArgumentParser(description='大模型行业情报 Agent')
    parser.add_argument('command', choices=['daily', 'daemon'])
    parser.add_argument('--config', default='config/intelligence.yaml')
    parser.add_argument('--send', action='store_true', help='投递已保存简报到飞书')
    parser.add_argument('--retry-uncertain', action='store_true', help='明确重试可能已送达的简报')
    args = parser.parse_args()
    config = load_settings(args.config)
    runner = DailyRunner(config)
    if args.command == 'daily':
        print(json.dumps(runner.run(send=args.send, retry_uncertain=args.retry_uncertain), ensure_ascii=False))
        return
    # Single-instance deployment; 09:00 Shanghai is independent of host timezone.
    last_day = None
    while True:
        now = datetime.now(timezone.utc)
        local = now.astimezone(pytz.timezone('Asia/Shanghai'))
        if local.hour >= 9 and local.date() != last_day:
            try:
                print(json.dumps(runner.run(now, send=args.send), ensure_ascii=False), flush=True)
                last_day = local.date()
            except Exception:
                print('每日运行失败；60 秒后重试，详情请检查配置和网络。', flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()

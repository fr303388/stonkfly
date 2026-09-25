import sys
sys.path.insert(0, r'C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\stonkfly')
from stonkfly.market_sentiment import get_sentiment
s = get_sentiment(force_refresh=True)
print(f'headlines: {len(s["headlines"])}')
if s["headlines"]:
    print(f'latest: {s["headlines"][0]["time"]} {s["headlines"][0]["title_zh"][:30]}')

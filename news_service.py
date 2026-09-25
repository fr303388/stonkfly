"""獨立新聞抓取服務 - 每60秒更新一次 sentiment_cache.json"""
import time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stonkfly.market_sentiment import get_sentiment

CACHE_FILE = os.path.join("runs", "paper", "sentiment_cache.json")

def main():
    print("[news_service] 啟動新聞服務，每60秒更新一次", flush=True)
    while True:
        try:
            s = get_sentiment(force_refresh=True)
            print(f"[news_service] 更新成功，{len(s.get('headlines',[]))} 則新聞", flush=True)
        except Exception as e:
            print(f"[news_service] 錯誤: {e}", flush=True)
        time.sleep(60)

if __name__ == "__main__":
    main()

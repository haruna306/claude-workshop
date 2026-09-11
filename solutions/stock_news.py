"""
株式・相場ニュースを取得して一覧にする（講座の完成版）

講座では、このファイルを Claude Code に作ってもらいます。
うまく動かなかったとき、復習したいときに使ってください。

使い方
    1. 作業フォルダに .env を作り、NEWS_API_KEY= の右に自分のキーを貼る
    2. py -m pip install python-dotenv requests
    3. py stock_news.py

注意
    NewsAPI の無料枠は開発・テスト用です。
    記事は24時間遅れ、検索できるのは過去1ヶ月分まで、1日100回まで。
    リアルタイムの投資判断には使えません。
"""

import os
import sys

import requests
from dotenv import load_dotenv

# 検索の条件。ここを書き換えると取れるニュースが変わります。
KEYWORDS = "(Nikkei OR TOPIX OR Toyota OR NVIDIA)"
LANGUAGE = "en"        # NewsAPI は日本語記事が少ないため英語にしています
SORT_BY = "publishedAt"  # 新しい順。relevancy（関連度順）も選べます
PAGE_SIZE = 10           # 取得する件数

ENDPOINT = "https://newsapi.org/v2/everything"


def load_api_key():
    """.env から APIキーを読み込む。キーそのものは画面に出さない。"""
    load_dotenv()
    key = os.getenv("NEWS_API_KEY")

    if not key:
        print("NEWS_API_KEY が読み込めませんでした。")
        print()
        print("確認してみてください:")
        print("  ・作業フォルダに .env というファイルがありますか")
        print("  ・.env の中に NEWS_API_KEY= の行がありますか")
        print("  ・= の右側にキーが貼ってありますか")
        print("  ・ファイル名が .env.example のままになっていませんか")
        sys.exit(1)

    return key


def fetch_articles(key):
    """NewsAPI からニュースを取ってくる。"""
    params = {
        "q": KEYWORDS,
        "language": LANGUAGE,
        "sortBy": SORT_BY,
        "pageSize": PAGE_SIZE,
    }
    headers = {"X-Api-Key": key}

    try:
        res = requests.get(ENDPOINT, params=params, headers=headers, timeout=20)
    except requests.exceptions.ConnectionError:
        print("インターネットにつながらないようです。接続を確認してください。")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("応答がありませんでした。しばらく待ってから、もう一度試してください。")
        sys.exit(1)

    if res.status_code == 401:
        print("APIキーが受け付けられませんでした。")
        print(".env のキーが正しいか、NewsAPI のサイトで確認してください。")
        sys.exit(1)

    if res.status_code == 429:
        print("今日の利用回数の上限に達しました。")
        print("無料枠は1日100回までです。明日また試してください。")
        sys.exit(1)

    if res.status_code != 200:
        print(f"ニュースを取得できませんでした。（コード {res.status_code}）")
        sys.exit(1)

    return res.json().get("articles", [])


def show(articles):
    """取ってきたニュースを画面に並べる。"""
    if not articles:
        print("条件に合うニュースが見つかりませんでした。")
        print("KEYWORDS を短くすると見つかりやすくなります。")
        return

    print(f"{len(articles)} 件のニュースが見つかりました。")
    print("=" * 60)

    for i, a in enumerate(articles, start=1):
        published = (a.get("publishedAt") or "")[:10]
        source = (a.get("source") or {}).get("name", "")
        print(f"{i:>2}. [{published}] {source}")
        print(f"    {a.get('title', '')}")
        print(f"    {a.get('url', '')}")
        print()


def main():
    key = load_api_key()
    articles = fetch_articles(key)
    show(articles)
    print("※ 無料枠のため、記事は24時間ほど遅れています。")
    print("※ 投資判断には使えません。情報の整理までにとどめてください。")


if __name__ == "__main__":
    main()

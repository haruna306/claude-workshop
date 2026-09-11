# 付録：Berkshire Hathaway 13F Watcher

講座本編の NewsAPI 実習を終えた方向けの、ちょっと遊べる発展編です。

**SEC（米国証券取引委員会）の公式EDGARデータだけ**を使って、
Berkshire Hathaway の最新5期の Form 13F-HR を比較します。

## 何が見られる？

- 最新5期（約1年分）の保有株数
- 最新四半期の「新規」「全売却」「買い増し」「縮小」
- 5期連続の買い増し / 縮小
- 1年前と比べて新しく現れた / 消えた銘柄
- 最新13Fの上位20銘柄
- Markdownレポートへの自動保存

## なぜ5期？

13Fは四半期ごとなので、4つの提出だけでは「4時点」です。

**1年前の同じ四半期 → 最新四半期**までをきちんと比べるには、
5つの時点を並べると分かりやすくなります。

例：

```text
2025 Q2
2025 Q3
2025 Q4
2026 Q1
2026 Q2
```

これで「前期比」と「1年前比」の両方を見られます。

## 準備

Python が入っている状態で、ターミナルから：

```bash
pip install requests
```

本編を終えていれば、すでに `requests` が入っている可能性があります。

## 実行

このファイルがあるフォルダで：

```bash
python berkshire_13f.py
```

初回は、SECアクセス用のメールアドレスを入力します。

これはAPIキーではありません。SECへの自動アクセス時の
User-Agent（誰がアクセスしているかを示す情報）に使います。

毎回入力したくない場合は、環境変数 `SEC_CONTACT_EMAIL` に設定できます。

## 結果

実行すると、次のようなファイルが作られます。

```text
reports/
└─ 2026-09-11_berkshire_13f.md
```

中には、5期比較や新規・全売却などがまとめられます。

## Claude Code に読ませてみよう

完成したMarkdownをClaude Codeに読ませて：

```text
この13Fレポートを読んで、重要そうな変化を5つ選び、
「何が変わったか」「5期で見るとどういう流れか」を
初心者向けに説明してください。

13Fだけでは分からないことは、推測せず
「分からない」と書いてください。
```

と頼んでみましょう。

本編の

```text
外部データを取る
↓
Pythonで整理
↓
Claude Codeで読む
```

という流れを、そのままSECの公開データにも応用できます。

## 大事な注意

13Fはリアルタイムのポートフォリオではありません。

四半期末時点の一定の報告対象証券を示す資料で、
提出まで時間差があります。また、13Fだけで
Berkshire Hathawayのすべての資産や投資判断の理由が
分かるわけではありません。

この付録は **情報整理とプログラミング学習用** です。

## SEC公式資料

- EDGAR APIs  
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Accessing EDGAR Data / Fair Access  
  https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- Form 13F Data Sets  
  https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets

## 補足：ティッカーがないのはなぜ？

SECの13F Information Table には、銘柄名・証券クラス・CUSIPなどはありますが、
通常、株式ティッカーそのものは含まれていません。

この付録は「SEC公式データだけを使う」ことを優先しているため、
Apple の `AAPL` のようなティッカーへの変換はしていません。

後から別のデータ源を組み合わせて、CUSIP → ticker の変換を追加するのも
発展課題になります。

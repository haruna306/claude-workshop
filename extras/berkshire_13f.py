"""
Berkshire Hathaway 13F Watcher
================================
SEC EDGAR の公式データだけを使って、
Berkshire Hathaway の最新5期の Form 13F-HR を比較します。

できること
- 最新5期（約1年分）の13Fを取得
- 保有株数を5期横並びで比較
- 最新四半期の新規 / 全売却 / 買い増し / 縮小を抽出
- 5期連続の買い増し / 縮小を抽出
- 最新の上位20銘柄を表示
- Markdown レポートを reports/ に保存

注意
- 13Fはリアルタイムの保有状況ではありません。
- SEC公式13Fには通常「ティッカー」がないため、銘柄名・クラス・CUSIPで表示します。
- このプログラムは情報整理用で、投資判断を行うものではありません。
"""

from __future__ import annotations

import os
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
import xml.etree.ElementTree as ET

import requests


# -----------------------------
# 設定
# -----------------------------

BERKSHIRE_CIK = "0001067983"
MANAGER_NAME = "Berkshire Hathaway Inc."
NUM_PERIODS = 5
TOP_N = 20

# SECは、自動アクセス時に連絡先を含むUser-Agentを推奨しています。
# 環境変数 SEC_CONTACT_EMAIL がなければ、実行時に入力を求めます。
SEC_CONTACT_EMAIL = os.getenv("SEC_CONTACT_EMAIL", "").strip()

SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{BERKSHIRE_CIK}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

REQUEST_INTERVAL = 0.20  # 1秒5回以下。SECの上限10回/秒より余裕を持たせる。
TIMEOUT = 30


# -----------------------------
# SECアクセス
# -----------------------------

class SecClient:
    def __init__(self, contact_email: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"claude-workshop-13f/1.0 {contact_email}",
                "Accept-Encoding": "gzip, deflate",
                "Host": "data.sec.gov",
            }
        )
        self._last_request_at = 0.0

    def _wait(self):
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)

    def get_json(self, url: str) -> dict:
        self._wait()

        # data.sec.gov と www.sec.gov で Host が異なるため自動設定に任せる
        headers = {"User-Agent": self.session.headers["User-Agent"]}
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.json()

    def get_text(self, url: str) -> str:
        self._wait()
        headers = {"User-Agent": self.session.headers["User-Agent"]}
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.text


# -----------------------------
# 補助関数
# -----------------------------

def local_name(tag: str) -> str:
    """XML名前空間を除いたタグ名を返す。"""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def child_text(element: ET.Element, name: str, default: str = "") -> str:
    """直下または子孫から、ローカル名が一致する要素の文字列を取得。"""
    for child in element.iter():
        if local_name(child.tag) == name:
            return (child.text or "").strip()
    return default


def to_int(value: str) -> int:
    try:
        return int(float(value.replace(",", "").strip()))
    except (ValueError, AttributeError):
        return 0


def fmt_shares(value: int) -> str:
    """株数を読みやすく表示。"""
    if value == 0:
        return "—"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,}"


def fmt_money(value: int) -> str:
    """13Fの報告価額を読みやすく表示。"""
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,}"


def pct_change(old: int, new: int) -> str:
    if old == 0:
        return "NEW" if new > 0 else "—"
    return f"{(new - old) / old * 100:+.1f}%"


def quarter_label(report_date: str) -> str:
    """2026-06-30 -> 2026 Q2 のように表示。"""
    try:
        year, month, _ = map(int, report_date.split("-"))
        q = (month - 1) // 3 + 1
        return f"{year} Q{q}"
    except Exception:
        return report_date


# -----------------------------
# 13F提出履歴
# -----------------------------

def get_latest_13f_filings(client: SecClient, count: int = 5) -> list[dict]:
    data = client.get_json(SUBMISSIONS_URL)
    recent = data["filings"]["recent"]

    filings = []
    seen_report_dates = set()

    for i, form in enumerate(recent["form"]):
        # まずは通常の13F-HRのみ。修正版13F-HR/Aは重複を避けるため除外。
        if form != "13F-HR":
            continue

        report_date = recent["reportDate"][i]
        if not report_date or report_date in seen_report_dates:
            continue

        filings.append(
            {
                "form": form,
                "filing_date": recent["filingDate"][i],
                "report_date": report_date,
                "accession": recent["accessionNumber"][i],
                "primary_document": recent["primaryDocument"][i],
            }
        )
        seen_report_dates.add(report_date)

        if len(filings) >= count:
            break

    if len(filings) < count:
        raise RuntimeError(
            f"13F-HRを{count}期分見つけられませんでした（見つかったのは{len(filings)}期）。"
        )

    return filings


def filing_directory_url(accession: str) -> str:
    cik_without_zeros = str(int(BERKSHIRE_CIK))
    accession_no_dashes = accession.replace("-", "")
    return f"{ARCHIVES_BASE}/{cik_without_zeros}/{accession_no_dashes}"


def find_information_table_xml(client: SecClient, filing: dict) -> tuple[str, str]:
    """
    提出フォルダの index.json を見て、13F Information Table のXMLを探す。
    戻り値: (XML本文, XML URL)
    """
    folder_url = filing_directory_url(filing["accession"])
    index_url = f"{folder_url}/index.json"
    directory = client.get_json(index_url)

    candidates = []
    for item in directory.get("directory", {}).get("item", []):
        name = item.get("name", "")
        lower = name.lower()

        if not lower.endswith(".xml"):
            continue
        if lower == "primary_doc.xml":
            continue
        if lower.endswith(("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")):
            continue
        if lower in {"filingsummary.xml", "metalinks.xml"}:
            continue

        candidates.append(name)

    # ファイル名が infotable / informationtable っぽいものを優先
    candidates.sort(
        key=lambda n: (
            0 if ("info" in n.lower() and "table" in n.lower()) else 1,
            n.lower(),
        )
    )

    for name in candidates:
        xml_url = f"{folder_url}/{name}"
        xml_text = client.get_text(xml_url)

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue

        root_name = local_name(root.tag).lower()
        has_info_table = any(local_name(e.tag) == "infoTable" for e in root.iter())

        if root_name == "informationtable" or has_info_table:
            return xml_text, xml_url

    raise RuntimeError(
        f"Information Table XMLが見つかりませんでした: {filing['accession']}"
    )


# -----------------------------
# XML解析
# -----------------------------

def parse_information_table(xml_text: str) -> dict[tuple[str, str], dict]:
    """
    CUSIP + 株式クラス単位で集計。
    同一銘柄が複数行ある場合は株数・価額を合算する。
    """
    root = ET.fromstring(xml_text)
    aggregated: dict[tuple[str, str], dict] = {}

    for info in root.iter():
        if local_name(info.tag) != "infoTable":
            continue

        issuer = child_text(info, "nameOfIssuer")
        title = child_text(info, "titleOfClass")
        cusip = child_text(info, "cusip")
        value = to_int(child_text(info, "value"))
        shares = to_int(child_text(info, "sshPrnamt"))

        key = (cusip, title)

        if key not in aggregated:
            aggregated[key] = {
                "issuer": issuer,
                "title": title,
                "cusip": cusip,
                "shares": 0,
                "value": 0,
            }

        aggregated[key]["shares"] += shares
        aggregated[key]["value"] += value

    if not aggregated:
        raise RuntimeError("Information Tableから保有銘柄を読み取れませんでした。")

    return aggregated


# -----------------------------
# 比較・レポート
# -----------------------------

def build_rows(periods: list[dict]) -> list[dict]:
    """
    periodsは古い -> 新しい順。
    全期間の銘柄をまとめ、各期の株数・最新価額を付ける。
    """
    all_keys = set()
    for period in periods:
        all_keys.update(period["holdings"].keys())

    rows = []

    for key in all_keys:
        samples = []
        issuer = ""
        title = ""
        cusip = key[0]

        for period in periods:
            h = period["holdings"].get(key)
            if h:
                issuer = h["issuer"] or issuer
                title = h["title"] or title
                samples.append(h["shares"])
            else:
                samples.append(0)

        latest_h = periods[-1]["holdings"].get(key)
        latest_value = latest_h["value"] if latest_h else 0

        rows.append(
            {
                "key": key,
                "issuer": issuer,
                "title": title,
                "cusip": cusip,
                "shares": samples,
                "latest_value": latest_value,
            }
        )

    return rows


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in row) + " |")
    return "\n".join(lines)


def movement_table(rows: list[dict], old_idx: int, new_idx: int, limit: int = 20) -> str:
    sortable = []
    for r in rows:
        old = r["shares"][old_idx]
        new = r["shares"][new_idx]
        if old == 0 and new == 0:
            continue

        # 変化株数の絶対値で並べる
        sortable.append((abs(new - old), r))

    sortable.sort(key=lambda x: x[0], reverse=True)

    table_rows = []
    for _, r in sortable[:limit]:
        old = r["shares"][old_idx]
        new = r["shares"][new_idx]
        table_rows.append(
            [
                r["issuer"],
                r["title"],
                r["cusip"],
                fmt_shares(old),
                fmt_shares(new),
                pct_change(old, new),
            ]
        )

    return markdown_table(
        ["銘柄", "クラス", "CUSIP", "前期", "最新", "変化"],
        table_rows,
    )


def build_report(periods: list[dict], rows: list[dict]) -> str:
    labels = [quarter_label(p["report_date"]) for p in periods]
    oldest_label = labels[0]
    latest_label = labels[-1]

    prev_idx = len(periods) - 2
    latest_idx = len(periods) - 1

    # 最新四半期の変化
    new_latest = [
        r for r in rows
        if r["shares"][prev_idx] == 0 and r["shares"][latest_idx] > 0
    ]
    exited_latest = [
        r for r in rows
        if r["shares"][prev_idx] > 0 and r["shares"][latest_idx] == 0
    ]
    increased_latest = [
        r for r in rows
        if r["shares"][prev_idx] > 0 and r["shares"][latest_idx] > r["shares"][prev_idx]
    ]
    reduced_latest = [
        r for r in rows
        if r["shares"][latest_idx] > 0
        and r["shares"][prev_idx] > r["shares"][latest_idx]
    ]

    # 5期すべてで連続増加・減少
    continuous_up = [
        r for r in rows
        if all(r["shares"][i] > r["shares"][i - 1] for i in range(1, len(periods)))
    ]
    continuous_down = [
        r for r in rows
        if all(r["shares"][i] < r["shares"][i - 1] for i in range(1, len(periods)))
    ]

    # 1年前 vs 最新
    one_year_new = [
        r for r in rows
        if r["shares"][0] == 0 and r["shares"][-1] > 0
    ]
    one_year_exited = [
        r for r in rows
        if r["shares"][0] > 0 and r["shares"][-1] == 0
    ]

    # 最新上位
    latest_top = sorted(
        [r for r in rows if r["shares"][-1] > 0],
        key=lambda r: r["latest_value"],
        reverse=True,
    )[:TOP_N]

    def simple_list(items: list[dict], old_idx: int, new_idx: int, limit: int = 30) -> str:
        if not items:
            return "該当なし"
        items = sorted(
            items,
            key=lambda r: abs(r["shares"][new_idx] - r["shares"][old_idx]),
            reverse=True,
        )
        lines = []
        for r in items[:limit]:
            old = r["shares"][old_idx]
            new = r["shares"][new_idx]
            lines.append(
                f"- **{r['issuer']}** ({r['title']}, CUSIP {r['cusip']}) "
                f"{fmt_shares(old)} → {fmt_shares(new)} ({pct_change(old, new)})"
            )
        return "\n".join(lines)

    trend_headers = ["銘柄", "クラス", "CUSIP"] + labels + ["1年前比"]
    trend_rows = []
    for r in latest_top:
        trend_rows.append(
            [
                r["issuer"],
                r["title"],
                r["cusip"],
                *[fmt_shares(v) for v in r["shares"]],
                pct_change(r["shares"][0], r["shares"][-1]),
            ]
        )

    source_lines = []
    for p in periods:
        source_lines.append(
            f"- {quarter_label(p['report_date'])} "
            f"(報告日 {p['report_date']} / 提出日 {p['filing_date']}): "
            f"{p['filing_url']}"
        )

    report = f"""# Berkshire Hathaway 13F Watch

生成日: {date.today().isoformat()}

対象: **{MANAGER_NAME}**  
比較期間: **{oldest_label} → {latest_label}（最新5期）**

> このレポートはSEC EDGARのForm 13F-HRを機械的に整理したものです。
> 13Fは四半期末時点の一定の報告対象証券を示す資料で、リアルタイムの保有状況や
> Berkshire Hathaway全体の資産を表すものではありません。投資判断ではなく情報整理用です。

## まず見るところ

- 最新四半期の新規: **{len(new_latest)}件**
- 最新四半期の全売却: **{len(exited_latest)}件**
- 最新四半期の買い増し: **{len(increased_latest)}件**
- 最新四半期の縮小: **{len(reduced_latest)}件**
- 5期連続買い増し: **{len(continuous_up)}件**
- 5期連続縮小: **{len(continuous_down)}件**

## 最新の上位{TOP_N}銘柄：5期比較

※ 並び順は最新13Fの報告価額順。表の数値は保有株数です。

{markdown_table(trend_headers, trend_rows)}

## 最新四半期：新規

{simple_list(new_latest, prev_idx, latest_idx)}

## 最新四半期：全売却

{simple_list(exited_latest, prev_idx, latest_idx)}

## 最新四半期：買い増し

{simple_list(increased_latest, prev_idx, latest_idx)}

## 最新四半期：縮小

{simple_list(reduced_latest, prev_idx, latest_idx)}

## 5期連続で買い増し

{simple_list(continuous_up, 0, latest_idx)}

## 5期連続で縮小

{simple_list(continuous_down, 0, latest_idx)}

## 1年間で新規に現れた銘柄

{simple_list(one_year_new, 0, latest_idx)}

## 1年間で消えた銘柄

{simple_list(one_year_exited, 0, latest_idx)}

## 最新四半期の変化量 上位20件

{movement_table(rows, prev_idx, latest_idx, 20)}

## SEC公式ソース

{chr(10).join(source_lines)}

## Claude Codeで次にやってみる

このMarkdownをClaude Codeに読ませて、たとえば次のように頼めます。

> この13Fレポートを読んで、重要そうな変化を5つ選び、
> 「何が変わったか」「5期で見るとどういう流れか」を初心者向けに説明してください。
> 13Fだけでは分からないことは、推測せず「分からない」と書いてください。

"""
    return report


# -----------------------------
# メイン処理
# -----------------------------

def main():
    print("=" * 60)
    print("Berkshire Hathaway 13F Watcher")
    print("SEC公式データから最新5期を比較します")
    print("=" * 60)

    contact_email = SEC_CONTACT_EMAIL
    if not contact_email:
        print()
        print("SECへの自動アクセスでは、連絡先を含むUser-Agentを使います。")
        print("メールアドレスはAPIキーではなく、SECへのアクセス識別用です。")
        contact_email = input("SECアクセス用のメールアドレスを入力してください: ").strip()

    if "@" not in contact_email:
        print("メールアドレスの形式を確認してください。")
        sys.exit(1)

    client = SecClient(contact_email)

    try:
        print("\n1/3  Berkshire Hathaway の13F提出履歴を取得中...")
        filings_newest_first = get_latest_13f_filings(client, NUM_PERIODS)

        periods = []
        for i, filing in enumerate(reversed(filings_newest_first), start=1):
            label = quarter_label(filing["report_date"])
            print(f"2/3  [{i}/{NUM_PERIODS}] {label} のInformation Tableを取得中...")

            xml_text, xml_url = find_information_table_xml(client, filing)
            holdings = parse_information_table(xml_text)

            folder_url = filing_directory_url(filing["accession"])
            accession = filing["accession"]
            filing_url = f"{folder_url}/{accession}-index.htm"

            periods.append(
                {
                    **filing,
                    "holdings": holdings,
                    "xml_url": xml_url,
                    "filing_url": filing_url,
                }
            )

        print("3/3  5期比較レポートを作成中...")
        rows = build_rows(periods)
        report = build_report(periods, rows)

        report_dir = Path("reports")
        report_dir.mkdir(exist_ok=True)
        output_path = report_dir / f"{date.today().isoformat()}_berkshire_13f.md"
        output_path.write_text(report, encoding="utf-8")

        print("\n完成！")
        print(f"保存先: {output_path}")
        print()
        print("比較した期間:")
        for p in periods:
            print(
                f"  {quarter_label(p['report_date'])} "
                f"(報告日 {p['report_date']} / 提出日 {p['filing_date']})"
            )
        print()
        print("Claude Codeでレポートを開いて、")
        print("「重要な変化を5つ、初心者向けに説明して」と頼んでみてください。")

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "不明"
        print(f"\nSECへのアクセスでHTTPエラーが発生しました（{status}）。")
        print("少し時間をおいてから再実行してください。")
        print("連続実行しすぎないようにしてください。")
        sys.exit(1)
    except requests.RequestException as e:
        print("\n通信エラーが発生しました。")
        print("インターネット接続を確認して、もう一度実行してください。")
        print(f"詳細: {e}")
        sys.exit(1)
    except (RuntimeError, ET.ParseError, KeyError) as e:
        print("\n13Fデータの読み取り中にエラーが発生しました。")
        print(f"詳細: {e}")
        print("SEC側のファイル構成が変更された可能性もあります。")
        sys.exit(1)


if __name__ == "__main__":
    main()

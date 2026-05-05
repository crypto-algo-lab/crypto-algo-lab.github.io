"""
既存の _posts/ MarkdownファイルをNotion DBに登録するスクリプト。
notion_id を持たないファイルのみ対象。登録後、front matterに notion_id を追記する。

使用方法:
  python scripts/import_posts_to_notion.py
"""

import os
import re
import sys

import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get(
    "NOTION_DATABASE_ID", "a698ec5e-99c7-442b-a4bf-af8b2c4dfe51"
)
POSTS_DIR = os.path.join(os.path.dirname(__file__), "..", "_posts")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def parse_front_matter(content: str) -> tuple[dict, str]:
    """front matter と本文を分離してパースする。"""
    m = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not m:
        return {}, content
    fm_text, body = m.group(1), m.group(2)
    fm = {}
    for line in fm_text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"')
    return fm, body.strip()


def create_notion_page(fm: dict, body: str) -> str:
    """Notion DBにページを作成してpage_idを返す。"""
    title = fm.get("title", "無題")
    date_str = fm.get("date", "")
    categories = fm.get("categories", "[]").strip("[]").replace(" ", "")
    tags = fm.get("tags", "[]").strip("[]").replace(" ", "")
    excerpt = fm.get("excerpt", "")

    # カテゴリは単一select（最初の値のみ使用）
    first_cat = categories.split(",")[0].strip() if categories else ""
    tag_list = [{"name": t} for t in tags.split(",") if t.strip()]

    properties = {
        "タイトル": {"title": [{"text": {"content": title}}]},
        "ステータス": {"select": {"name": "公開済"}},
        "更新タイプ": {"select": {"name": "新規追加"}},
        "公開先": {"multi_select": [{"name": "GitHub Pages"}]},
    }

    if date_str:
        properties["公開日"] = {"date": {"start": date_str}}
    if first_cat:
        properties["カテゴリ"] = {"select": {"name": first_cat}}
    if tag_list:
        properties["タグ"] = {"multi_select": tag_list}
    if excerpt:
        properties["要約"] = {"rich_text": [{"text": {"content": excerpt[:2000]}}]}

    # 本文の冒頭200文字をNotionページ本文として登録
    children = []
    for para in body.split("\n\n")[:5]:
        para = para.strip()
        if not para or para.startswith("```") or para.startswith("#"):
            continue
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": para[:2000]}}]
            },
        })

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }
    if children:
        payload["children"] = children

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def inject_notion_id(fpath: str, notion_id: str) -> None:
    """front matter に notion_id を追記する。"""
    with open(fpath, encoding="utf-8") as f:
        content = f.read()

    # すでに notion_id があればスキップ
    if "notion_id:" in content:
        return

    # --- の直後に notion_id 行を挿入
    new_content = re.sub(
        r"^(---\n)",
        f"\\1notion_id: {notion_id}\n",
        content,
        count=1,
    )
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(new_content)


def main():
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN が設定されていません", file=sys.stderr)
        sys.exit(1)

    files = sorted(f for f in os.listdir(POSTS_DIR) if f.endswith(".md"))
    registered = 0

    for fname in files:
        fpath = os.path.join(POSTS_DIR, fname)
        with open(fpath, encoding="utf-8") as f:
            content = f.read()

        # すでにNotion管理済みならスキップ
        if "notion_id:" in content:
            print(f"  スキップ（登録済み）: {fname}")
            continue

        fm, body = parse_front_matter(content)
        if not fm.get("title"):
            print(f"  スキップ（タイトルなし）: {fname}")
            continue

        print(f"  Notionに登録中: {fname}")
        try:
            page_id = create_notion_page(fm, body)
            inject_notion_id(fpath, page_id)
            print(f"    → page_id: {page_id}")
            registered += 1
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\n完了: {registered} 件を Notion に登録しました")
    if registered > 0:
        print("※ git add _posts/ && git commit && git push で反映してください")


if __name__ == "__main__":
    main()

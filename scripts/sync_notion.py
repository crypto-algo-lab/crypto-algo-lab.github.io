"""
Notionの開発ログDBとJekyllブログを双方向同期するスクリプト。

動作仕様:
  - ステータスが「公開準備」または「公開済」 → _posts/ にファイルを作成/更新
  - ステータスがそれ以外（下書き・レビュー・非公開化）→ _posts/ からファイルを削除
  - Notionから削除 → _posts/ からファイルを削除

管理方法:
  記事ファイルのfront matterに notion_id を埋め込み、
  どのファイルがNotionから生成されたかを追跡する。

必要な環境変数:
  NOTION_TOKEN       : Notion Integration Token
  NOTION_DATABASE_ID : 対象DBのID

使用方法:
  python scripts/sync_notion.py
"""

import os
import re
import sys
from datetime import datetime, timezone

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


# ===== Notion API =====

def get_db_properties() -> dict:
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("properties", {})


def get_all_pages() -> list[dict]:
    """Notion DBの全ページを取得する（公開・非公開問わず）。"""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"sorts": [{"property": "日付", "direction": "descending"}]}
    results = []
    while True:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return results


def get_page_blocks(page_id: str) -> list[dict]:
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])


# ===== テキスト変換 =====

def extract_text(rich_text: list[dict]) -> str:
    return "".join(t.get("plain_text", "") for t in rich_text)


def block_to_markdown(block: dict) -> str:
    btype = block.get("type", "")
    data = block.get(btype, {})
    text = extract_text(data.get("rich_text", []))

    if btype == "paragraph":
        return f"{text}\n\n" if text else "\n"
    elif btype == "heading_1":
        return f"# {text}\n\n"
    elif btype == "heading_2":
        return f"## {text}\n\n"
    elif btype == "heading_3":
        return f"### {text}\n\n"
    elif btype == "bulleted_list_item":
        return f"- {text}\n"
    elif btype == "numbered_list_item":
        return f"1. {text}\n"
    elif btype == "code":
        lang = data.get("language", "")
        return f"```{lang}\n{text}\n```\n\n"
    elif btype == "quote":
        return f"> {text}\n\n"
    elif btype == "divider":
        return "---\n\n"
    else:
        return f"{text}\n\n" if text else ""


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "post"


def get_prop(props: dict, key: str) -> str:
    prop = props.get(key, {})
    ptype = prop.get("type", "")
    if ptype == "title":
        return extract_text(prop.get("title", []))
    elif ptype == "rich_text":
        return extract_text(prop.get("rich_text", []))
    elif ptype == "date":
        date_obj = prop.get("date") or {}
        return (date_obj.get("start") or "")[:10]
    elif ptype == "multi_select":
        return ",".join(s["name"] for s in prop.get("multi_select", []))
    elif ptype == "select":
        sel = prop.get("select") or {}
        return sel.get("name", "")
    elif ptype == "checkbox":
        return str(prop.get("checkbox", False))
    return ""


def is_published(props: dict, **kwargs) -> bool:
    """ステータスが「公開準備」または「公開済」の場合に公開と判定する。"""
    status = get_prop(props, "ステータス")
    return status in ("公開準備", "公開済")


# ===== ローカルファイル管理 =====

def scan_notion_posts() -> dict[str, str]:
    """
    _posts/ 内で notion_id を持つファイルを走査する。
    返り値: { notion_id: filepath }
    """
    result = {}
    os.makedirs(POSTS_DIR, exist_ok=True)
    for fname in os.listdir(POSTS_DIR):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(POSTS_DIR, fname)
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"^notion_id:\s*(.+)$", content, re.MULTILINE)
        if m:
            result[m.group(1).strip()] = fpath
    return result


def page_to_post(page: dict) -> tuple[str, str] | None:
    """Notionページ → (ファイル名, Markdownコンテンツ)"""
    props = page.get("properties", {})
    title = get_prop(props, "タイトル")
    if not title:
        return None

    date_str = get_prop(props, "公開日")
    if not date_str:
        created = page.get("created_time", "")
        date_str = created[:10] if created else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    categories = get_prop(props, "カテゴリ") or "開発ログ"
    tags = get_prop(props, "タグ") or ""
    excerpt = get_prop(props, "要約") or ""
    slug = get_prop(props, "slug") or ""

    cat_list = "[" + categories.strip() + "]"
    tag_list = "[" + ", ".join(t.strip() for t in tags.split(",") if t.strip()) + "]" if tags else "[]"
    excerpt_line = f'excerpt: "{excerpt}"\n' if excerpt else ""

    front_matter = (
        f"---\n"
        f"layout: post\n"
        f'title: "{title}"\n'
        f"date: {date_str}\n"
        f"notion_id: {page['id']}\n"
        f"categories: {cat_list}\n"
        f"tags: {tag_list}\n"
        f"{excerpt_line}"
        f"---\n\n"
    )

    blocks = get_page_blocks(page["id"])
    body = "".join(block_to_markdown(b) for b in blocks)
    if not body.strip() and excerpt:
        body = f"{excerpt}\n\n"

    content = front_matter + body
    filename = f"{date_str}-{slugify(title)}.md"
    return filename, content


# ===== メイン処理 =====

def main():
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN が設定されていません", file=sys.stderr)
        sys.exit(1)

    os.makedirs(POSTS_DIR, exist_ok=True)

    print(f"Notion DB ({NOTION_DATABASE_ID}) から全ページ取得中...")
    pages = get_all_pages()
    print(f"{len(pages)} 件取得")

    # ローカルのNotion管理ファイル一覧
    local_notion_files = scan_notion_posts()  # { notion_id: filepath }
    notion_ids_in_db = set()

    created = updated = deleted = skipped = 0

    for page in pages:
        page_id = page["id"]
        props = page.get("properties", {})
        notion_ids_in_db.add(page_id)

        published = is_published(props)
        existing_path = local_notion_files.get(page_id)

        if not published:
            # 非公開: ファイルが存在すれば削除
            if existing_path and os.path.exists(existing_path):
                os.remove(existing_path)
                print(f"  削除（非公開化）: {os.path.basename(existing_path)}")
                deleted += 1
            else:
                skipped += 1
            continue

        # 公開: 作成 or 更新
        result = page_to_post(page)
        if result is None:
            skipped += 1
            continue

        filename, content = result
        filepath = os.path.join(POSTS_DIR, filename)

        # 既存ファイルと内容比較
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8") as f:
                existing = f.read()
            if existing == content:
                skipped += 1
                continue
            # Notion本文が空のとき（フロントマターのみ）はローカルを保持
            if not body.strip():
                skipped += 1
                continue
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  更新: {filename}")
            updated += 1
        else:
            # 古いパスで管理されていた場合は削除してから作成
            if existing_path and os.path.exists(existing_path):
                os.remove(existing_path)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  作成: {filename}")
            created += 1

    # Notionから削除されたページのファイルを削除
    for page_id, fpath in local_notion_files.items():
        if page_id not in notion_ids_in_db and os.path.exists(fpath):
            os.remove(fpath)
            print(f"  削除（Notionから削除）: {os.path.basename(fpath)}")
            deleted += 1

    print(f"\n完了 — 作成:{created} 更新:{updated} 削除:{deleted} スキップ:{skipped}")


if __name__ == "__main__":
    main()

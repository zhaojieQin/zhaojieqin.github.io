"""
fetch_papers.py
放置位置：仓库根目录（与 _config.yml 同级）

功能：
  - 通过 Crossref API 抓取目标期刊的最新论文
  - 按关键词过滤
  - 输出到 _data/papers.json（供 Jekyll 读取）
  - 同时更新 README.md

用法：
  本地测试：python fetch_papers.py
  GitHub Actions 自动运行（见 .github/workflows/fetch.yml）
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ════════════════════════════════════════════════════════
#  配置区 — 修改关键词和期刊列表
# ════════════════════════════════════════════════════════

# 关键词列表（英文逗号分隔，可通过环境变量 KEYWORDS 覆盖）
KEYWORDS = [kw.strip() for kw in os.environ.get(
    "KEYWORDS",
    "turbulence,wake,vortex,renewable energy,wind turbine,"
    "drag reduction,heat transfer,fluid structure interaction,"
    "ocean energy,tidal energy,wave energy,boundary layer"
).split(",") if kw.strip()]

# 目标期刊（名称: ISSN）
# 如需添加期刊，在此处补充即可，ISSN 可在期刊官网或 issn.org 查询
JOURNALS = {
    "Physics of Fluids":                          "1089-7666",
    "Journal of Fluid Mechanics":                 "1469-7645",
    "Renewable Energy":                           "1879-0682",
    "Applied Energy":                             "1872-9118",
    "Journal of Fluids and Structures":           "1095-8622",
    "International Journal of Heat and Fluid Flow": "1879-2278",
    "Flow, Turbulence and Combustion":            "1573-1987",
    "Ocean Engineering":                          "1873-5258",
}

# 抓取最近多少天的文章（可通过环境变量 DAYS_BACK 覆盖）
DAYS_BACK = int(os.environ.get("DAYS_BACK", "7"))

# 输出目录（GitHub Actions 中设置为 _data，本地测试默认当前目录）
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "_data"))

# 每个期刊最多抓取条数
MAX_PER_JOURNAL = 50

# 归档最大保留条数
MAX_ARCHIVE = 500

# ════════════════════════════════════════════════════════
#  Crossref API 查询
# ════════════════════════════════════════════════════════

def crossref_search(issn: str, journal_name: str, from_date: str) -> list[dict]:
    """向 Crossref 查询指定期刊在 from_date 之后发表的文章。"""
    url = "https://api.crossref.org/works"
    params = {
        "filter": f"issn:{issn},from-pub-date:{from_date},type:journal-article",
        "rows":   MAX_PER_JOURNAL,
        "select": "DOI,title,author,published,published-print,abstract,URL",
        "mailto": "zhaojie.Qin@geo.uu.se",  # 使用"礼貌池"，速度更快，请替换为你的邮箱
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        items = resp.json()["message"]["items"]
    except requests.exceptions.RequestException as e:
        print(f"    [WARN] {journal_name} 请求失败: {e}")
        return []
    except (KeyError, ValueError) as e:
        print(f"    [WARN] {journal_name} 解析失败: {e}")
        return []

    results = []
    for item in items:
        title    = " ".join(item.get("title", ["(no title)"]))
        abstract = item.get("abstract", "")
        # 去除 Crossref 返回的 JATS XML 标签
        abstract = re.sub(r"<[^>]+>", " ", abstract)
        abstract = re.sub(r"\s+", " ", abstract).strip()

        doi = item.get("DOI", "")
        results.append({
            "journal":   journal_name,
            "title":     title,
            "doi":       doi,
            "url":       item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            "abstract":  abstract[:800] + ("…" if len(abstract) > 800 else ""),
            "authors":   _format_authors(item.get("author", [])),
            "published": _pub_date(item),
        })
    return results


def _format_authors(author_list: list) -> str:
    """格式化作者列表，最多显示前 4 位，超出显示 et al."""
    names = [
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in author_list[:4]
        if a.get("family")
    ]
    if not names:
        return ""
    result = ", ".join(names)
    if len(author_list) > 4:
        result += " et al."
    return result


def _pub_date(item: dict) -> str:
    """从 Crossref 条目中提取发表日期，格式 YYYY-MM-DD。"""
    for key in ("published", "published-print", "published-online"):
        parts = item.get(key, {}).get("date-parts", [[]])
        if parts and parts[0]:
            p = parts[0]
            year  = str(p[0]) if len(p) > 0 else "0000"
            month = str(p[1]).zfill(2) if len(p) > 1 else "01"
            day   = str(p[2]).zfill(2) if len(p) > 2 else "01"
            return f"{year}-{month}-{day}"
    return "unknown"


# ════════════════════════════════════════════════════════
#  关键词匹配
# ════════════════════════════════════════════════════════

def keyword_match(paper: dict, keywords: list[str]) -> list[str]:
    """返回论文标题+摘要中命中的关键词列表（不区分大小写）。"""
    haystack = (paper["title"] + " " + paper["abstract"]).lower()
    return [kw for kw in keywords if kw.lower() in haystack]


# ════════════════════════════════════════════════════════
#  主抓取流程
# ════════════════════════════════════════════════════════

def fetch_all() -> list[dict]:
    from_date = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    print(f"\n{'='*55}")
    print(f"  抓取范围: 最近 {DAYS_BACK} 天 (from {from_date})")
    print(f"  目标期刊: {len(JOURNALS)} 个")
    print(f"  关键词数: {len(KEYWORDS)} 个")
    print(f"{'='*55}\n")

    all_matched = []

    for journal_name, issn in JOURNALS.items():
        print(f"  → {journal_name}")
        papers = crossref_search(issn, journal_name, from_date)
        matched = []
        for p in papers:
            hits = keyword_match(p, KEYWORDS)
            if hits:
                p["keywords_matched"] = hits
                matched.append(p)
        print(f"     共 {len(papers)} 篇，命中 {len(matched)} 篇")
        all_matched.extend(matched)
        time.sleep(1)  # 礼貌等待，避免触发频率限制

    # 按发表日期降序排列
    all_matched.sort(key=lambda x: x["published"], reverse=True)
    print(f"\n  本次共命中: {len(all_matched)} 篇\n")
    return all_matched


# ════════════════════════════════════════════════════════
#  保存 JSON（供 Jekyll 的 _data 目录使用）
# ════════════════════════════════════════════════════════

def save_json(new_papers: list[dict]) -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "papers.json"

    # 读取已有存档
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [WARN] 读取旧数据失败: {e}")

    # 用 DOI 去重合并：新数据优先（更新摘要/链接等字段）
    existing_by_doi = {p["doi"]: p for p in existing if p.get("doi")}
    for p in new_papers:
        if p.get("doi"):
            existing_by_doi[p["doi"]] = p  # 用新数据覆盖

    combined = list(existing_by_doi.values())
    # 把没有 DOI 的旧数据也保留
    no_doi_old = [p for p in existing if not p.get("doi")]
    combined.extend(no_doi_old)

    # 排序、截断
    combined.sort(key=lambda x: x.get("published", ""), reverse=True)
    combined = combined[:MAX_ARCHIVE]

    path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    new_count = sum(1 for p in new_papers if p.get("doi") not in {x["doi"] for x in existing})
    print(f"  papers.json: 共 {len(combined)} 篇（新增 {new_count} 篇）")
    return combined


# ════════════════════════════════════════════════════════
#  生成 README.md（可选，方便在 GitHub 仓库页直接预览）
# ════════════════════════════════════════════════════════

def generate_readme(papers: list[dict]):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recent = papers[:30]

    # 按期刊分组
    by_journal: dict[str, list] = {}
    for p in recent:
        by_journal.setdefault(p["journal"], []).append(p)

    kw_str = "` `".join(KEYWORDS)
    lines = [
        "# 📡 Paper Tracker",
        "",
        f"> 自动更新于 **{now}**  ",
        f"> 监控期刊 **{len(JOURNALS)}** 个 · 关键词 `{kw_str}`",
        "",
        "---",
        "",
        f"## 🆕 最新 {len(recent)} 篇匹配论文",
        "",
    ]

    for journal, jpapers in by_journal.items():
        lines += [f"### {journal}", ""]
        for p in jpapers:
            kw_badges = " ".join(f"`{k}`" for k in p.get("keywords_matched", []))
            abstract_short = p["abstract"][:180] + ("…" if len(p["abstract"]) > 180 else "")
            lines += [
                f"**[{p['title']}]({p['url']})**  ",
                f"👤 {p['authors'] or 'N/A'} · 📅 {p['published']} · {kw_badges}  ",
                f"> {abstract_short}",
                "",
            ]

    lines += [
        "---",
        "",
        "## 📊 统计",
        f"| 项目 | 数值 |",
        f"|------|------|",
        f"| 归档论文总数 | **{len(papers)}** |",
        f"| 监控期刊数 | **{len(JOURNALS)}** |",
        f"| 追踪关键词数 | **{len(KEYWORDS)}** |",
        f"| 最后更新 | **{now}** |",
        "",
        "---",
        "",
        "*由 GitHub Actions 自动运行 · 数据来源 [Crossref API](https://www.crossref.org/)*",
    ]

    readme_path = Path(".") / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  README.md 已更新")


# ════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    papers     = fetch_all()
    all_papers = save_json(papers)
    generate_readme(all_papers)
    print("\n✅ 全部完成！\n")

"""
fetch_papers.py
放置位置：仓库根目录（与 _config.yml 同级）
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ════════════════════════════════════════════════════════
#  关键词配置
# ════════════════════════════════════════════════════════
KEYWORDS = [kw.strip() for kw in os.environ.get(
    "KEYWORDS",
    "lattice boltzmann method,"
    "lattice boltzmann,"
    "LBM,"
    "WRF,"
    "weather research and forecasting,"
    "diurnal cycle,"
    "diurnal variation,"
    "wind turbine,"
    "wind turbines,"
    "wake,"
    "wind farm,"
    "wind energy,"
    "turbulence,"
    "atmospheric boundary layer,"
    "ABL,"
    "vortex,"
    "drag reduction,"
    "heat transfer,"
    "fluid structure interaction,"
    "renewable energy,"
    "ocean energy,"
    "tidal,"
    "wave energy"
).split(",") if kw.strip()]

# ════════════════════════════════════════════════════════
#  期刊配置（名称: eISSN 或 ISSN，优先用 eISSN）
# ════════════════════════════════════════════════════════
JOURNALS = {
    # 流体力学
    "Physics of Fluids":                            "1089-7666",
    "Journal of Fluid Mechanics":                   "1469-7645",
    "Computers & Fluids":                           "1879-0747",
    "Computer Physics Communications":              "1879-2944",
    "Journal of Fluids and Structures":             "1095-8622",
    "Journal of Wind Engineering and Industrial Aerodynamics": "1872-8197",
    "International Journal of Heat and Fluid Flow": "1879-2278",
    "Ocean Engineering":                            "1873-5258",
    # 大气 / 地球系统
    "Journal of Geophysical Research: Atmospheres": "2169-8996",
    "Geoscientific Model Development":              "1991-9603",
    "Journal of Advances in Modeling Earth Systems":"1942-2466",
    "Advances in Atmospheric Sciences":             "1861-9533",
    # 能源
    "Renewable Energy":                             "1879-0682",
    "Applied Energy":                               "1872-9118",
    "Energy & Environmental Science":               "1754-5706",
}

# ════════════════════════════════════════════════════════
#  运行参数
# ════════════════════════════════════════════════════════
# 首次运行建议设 30，之后 Actions 每周跑自动改为 7
DAYS_BACK       = int(os.environ.get("DAYS_BACK", "30"))
OUTPUT_DIR      = Path(os.environ.get("OUTPUT_DIR", "_data"))
MAX_PER_JOURNAL = 50
MAX_ARCHIVE     = 500


# ════════════════════════════════════════════════════════
#  Crossref API 查询
# ════════════════════════════════════════════════════════
def crossref_search(issn: str, journal_name: str, from_date: str) -> list[dict]:
    url = "https://api.crossref.org/works"
    params = {
        "filter": f"issn:{issn},from-pub-date:{from_date},type:journal-article",
        "rows":   MAX_PER_JOURNAL,
        "select": "DOI,title,author,published,published-print,abstract,URL",
        "mailto": "your@email.com",   # ← 改成你的邮箱
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        items = resp.json()["message"]["items"]
    except requests.exceptions.RequestException as e:
        print(f"    [WARN] {journal_name}: {e}")
        return []
    except (KeyError, ValueError) as e:
        print(f"    [WARN] {journal_name} 解析失败: {e}")
        return []

    results = []
    for item in items:
        title    = " ".join(item.get("title", ["(no title)"]))
        abstract = item.get("abstract", "")
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
#  关键词匹配（不区分大小写）
# ════════════════════════════════════════════════════════
def keyword_match(paper: dict, keywords: list[str]) -> list[str]:
    haystack = (paper["title"] + " " + paper["abstract"]).lower()
    return [kw for kw in keywords if kw.lower() in haystack]


# ════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════
def fetch_all() -> list[dict]:
    from_date = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  抓取范围 : 最近 {DAYS_BACK} 天 (from {from_date})")
    print(f"  监控期刊 : {len(JOURNALS)} 个")
    print(f"  关键词数 : {len(KEYWORDS)} 个")
    print(f"{'='*60}\n")

    all_matched = []
    for journal_name, issn in JOURNALS.items():
        print(f"  → {journal_name}")
        papers  = crossref_search(issn, journal_name, from_date)
        matched = []
        for p in papers:
            hits = keyword_match(p, KEYWORDS)
            if hits:
                p["keywords_matched"] = hits
                matched.append(p)
        print(f"     {len(papers)} 篇中命中 {len(matched)} 篇")
        all_matched.extend(matched)
        time.sleep(1)

    all_matched.sort(key=lambda x: x["published"], reverse=True)
    print(f"\n  本次合计命中: {len(all_matched)} 篇\n")
    return all_matched


# ════════════════════════════════════════════════════════
#  保存 JSON
# ════════════════════════════════════════════════════════
def save_json(new_papers: list[dict]) -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "papers.json"

    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    by_doi = {p["doi"]: p for p in existing if p.get("doi")}
    for p in new_papers:
        if p.get("doi"):
            by_doi[p["doi"]] = p

    combined = list(by_doi.values())
    combined += [p for p in existing if not p.get("doi")]
    combined.sort(key=lambda x: x.get("published", ""), reverse=True)
    combined = combined[:MAX_ARCHIVE]

    path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    new_count = len([p for p in new_papers
                     if p.get("doi") not in {x["doi"] for x in existing}])
    print(f"  papers.json: 共 {len(combined)} 篇（新增 {new_count} 篇）")
    return combined


# ════════════════════════════════════════════════════════
#  生成 README
# ════════════════════════════════════════════════════════
def generate_readme(papers: list[dict]):
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recent = papers[:30]

    by_journal: dict[str, list] = {}
    for p in recent:
        by_journal.setdefault(p["journal"], []).append(p)

    kw_str = "` `".join(KEYWORDS[:10]) + ("` …" if len(KEYWORDS) > 10 else "`")
    lines  = [
        "# 📡 Paper Tracker",
        "",
        f"> 自动更新于 **{now}**  ",
        f"> 监控期刊 **{len(JOURNALS)}** 个 · 关键词 `{kw_str}",
        "",
        "---",
        "",
        f"## 🆕 最新 {len(recent)} 篇匹配论文",
        "",
    ]

    for journal, jpapers in by_journal.items():
        lines += [f"### {journal}", ""]
        for p in jpapers:
            kw_badges      = " ".join(f"`{k}`" for k in p.get("keywords_matched", []))
            abstract_short = p["abstract"][:180] + ("…" if len(p["abstract"]) > 180 else "")
            lines += [
                f"**[{p['title']}]({p['url']})**  ",
                f"👤 {p['authors'] or 'N/A'} · 📅 {p['published']} · {kw_badges}  ",
                f"> {abstract_short}",
                "",
            ]

    lines += [
        "---",
        "## 📊 统计",
        f"| 项目 | 数值 |",
        f"|------|------|",
        f"| 归档总数 | **{len(papers)}** |",
        f"| 监控期刊 | **{len(JOURNALS)}** |",
        f"| 关键词数 | **{len(KEYWORDS)}** |",
        f"| 最后更新 | **{now}** |",
        "",
        "*由 GitHub Actions 自动运行 · 数据来源 [Crossref API](https://www.crossref.org/)*",
    ]

    Path("README.md").write_text("\n".join(lines), encoding="utf-8")
    print("  README.md 已更新")


# ════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    papers     = fetch_all()
    all_papers = save_json(papers)
    generate_readme(all_papers)
    print("\n✅ 全部完成！\n")

from flask import Flask, render_template, request, abort
import pandas as pd
import os

app = Flask(__name__)
data_path = "data"

@app.route("/")
def index():
    # 이벤트 목록 (data/<event> 폴더)
    events = [
        d for d in os.listdir(data_path)
        if os.path.isdir(os.path.join(data_path, d))
    ]

    # 모든 이벤트별 자동완성용 배번 맵
    suggestions_map = {}
    for ev in events:
        csv_path = os.path.join(data_path, ev, "results.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, encoding="utf-8")
            # 문자열로 강제 변환
            suggestions_map[ev] = df["배번"].dropna().astype(str).unique().tolist()
        else:
            suggestions_map[ev] = []

    # 게시물 목록
    posts = []
    posts_dir = os.path.join(app.static_folder, "posts")
    if os.path.isdir(posts_dir):
        for fname in sorted(os.listdir(posts_dir)):
            if not fname.lower().endswith(".txt"):
                continue
            with open(os.path.join(posts_dir, fname), encoding="utf-8") as f:
                title = f.readline().lstrip("\ufeff").strip()
            posts.append({"filename": fname, "title": title})

    return render_template(
        "index.html",
        events=events,
        suggestions_map=suggestions_map,
        posts=posts
    )

@app.route("/search", methods=["POST"])
def search():
    event        = request.form["event"]
    keyword      = request.form["bib"].strip().upper()
    csv_path     = os.path.join(data_path, event, "results.csv")
    gallery_link = None
    suggestions  = []
    results      = []

    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path, encoding="utf-8")
        # 1) 숫자형 배번을 문자열로
        df["bib_str"] = df["배번"].dropna().astype(str)

        # 2) 정확 일치 필터링
        matches = df[df["bib_str"] == keyword]

        # 3) 파일명 중복 제거
        matches = matches.drop_duplicates(subset=["파일명"])

        # 4) 결과 리스트
        results = matches.values.tolist()

        # 5) 자동완성용 리스트
        suggestions = df["bib_str"].unique().tolist()

        # 6) OneDrive 링크
        link_path = os.path.join(data_path, event, "onedrive_link.txt")
        if os.path.exists(link_path):
            with open(link_path, encoding="utf-8") as f:
                gallery_link = f.read().strip()

    # 결과가 없을 때만 timeline.csv 읽기
    timeline = None
    if not results:
        tl_path = os.path.join(data_path, event, "timeline.csv")
        if os.path.exists(tl_path):
            tl_df = pd.read_csv(tl_path, encoding="utf-8")
            timeline = tl_df.values.tolist()

    return render_template(
        "results.html",
        event=event,
        keyword=keyword,
        results=results,
        link=gallery_link,
        suggestions=suggestions,
        timeline=timeline
    )

@app.route("/post/<filename>")
def post(filename):
    posts_dir = os.path.join(app.static_folder, "posts")
    if filename not in os.listdir(posts_dir) or not filename.lower().endswith(".txt"):
        abort(404)

    with open(os.path.join(posts_dir, filename), encoding="utf-8") as f:
        raw_title   = f.readline()
        title       = raw_title.lstrip("\ufeff").strip()
        content     = "\n".join(line.strip() for line in f.read().splitlines()).strip()

    base, _ = os.path.splitext(filename)
    images  = [
        f"{base}.{ext}" for ext in ("png","jpg","jpeg","gif")
        if os.path.exists(os.path.join(posts_dir, f"{base}.{ext}"))
    ]

    return render_template(
        "post.html",
        title=title,
        content=content,
        images=images
    )

if __name__ == "__main__":
    app.run(debug=True)

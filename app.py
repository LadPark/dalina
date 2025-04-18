from flask import Flask, render_template, request, abort
import pandas as pd
import os
import textwrap

app = Flask(__name__)
data_path = "data"

@app.route("/")
def index():
    # 이벤트 목록 (data/<event> 폴더가 있는 경우)
    events = [
        d for d in os.listdir(data_path)
        if os.path.isdir(os.path.join(data_path, d))
    ]

    # 기본 자동완성용 배번 리스트
    suggestions = []
    if events:
        default_event = events[0]
        csv_path = os.path.join(data_path, default_event, "results.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, encoding="utf-8")
            suggestions = df["배번"].dropna().unique().tolist()

    # static/posts 폴더에서 .txt 파일을 읽어 게시물 목록 생성
    posts = []
    posts_dir = os.path.join(app.static_folder, "posts")
    if os.path.isdir(posts_dir):
        for fname in sorted(os.listdir(posts_dir)):
            if not fname.lower().endswith(".txt"):
                continue
            full_path = os.path.join(posts_dir, fname)
            with open(full_path, encoding="utf-8") as f:
                raw_title = f.readline()
                title = raw_title.lstrip("\ufeff").strip()
            posts.append({
                "filename": fname,
                "title": title
            })

    return render_template(
        "index.html",
        events=events,
        suggestions=suggestions,
        posts=posts
    )

@app.route("/search", methods=["POST"])
def search():
    event = request.form["event"]
    keyword = request.form["bib"].strip().upper()
    csv_path = os.path.join(data_path, event, "results.csv")

    if not os.path.exists(csv_path):
        return render_template(
            "results.html",
            keyword=keyword,
            results=[],
            event=event,
            link=None
        )

    df = pd.read_csv(csv_path, encoding="utf-8")
    matches = df[df["배번"].str.contains(keyword, na=False)]
    results = matches.values.tolist()

    # 갤러리 링크 (onedrive_link.txt)
    gallery_link = None
    link_path = os.path.join(data_path, event, "onedrive_link.txt")
    if os.path.exists(link_path):
        with open(link_path, encoding="utf-8") as f:
            gallery_link = f.read().strip()

    return render_template(
        "results.html",
        keyword=keyword,
        results=results,
        event=event,
        link=gallery_link
    )

@app.route("/post/<filename>")
def post(filename):
    # posts 디렉터리 경로
    posts_dir = os.path.join(app.static_folder, "posts")
    # 유효한 .txt 파일인지 확인
    if filename not in os.listdir(posts_dir) or not filename.lower().endswith(".txt"):
        abort(404)

    # 텍스트 파일 읽기 (첫 줄: 제목, 나머지: 본문)
    full_path = os.path.join(posts_dir, filename)
    with open(full_path, encoding="utf-8") as f:
        raw_title = f.readline()
        title = raw_title.lstrip("\ufeff").strip()
        raw_content = f.read()
        content = textwrap.dedent(raw_content)
        lines = dedented.splitlines()
        stripped_lines = [ln.lstrip() for ln in lines]
        content = "\n".join(stripped_lines).strip()

    # 동일 이름의 이미지 파일 탐색 (.png, .jpg, .jpeg, .gif)
    base, _ = os.path.splitext(filename)
    images = []
    for ext in ("png", "jpg", "jpeg", "gif"):
        img_name = f"{base}.{ext}"
        if os.path.exists(os.path.join(posts_dir, img_name)):
            images.append(img_name)

    return render_template(
        "post.html",
        title=title,
        content=content,
        images=images
    )

if __name__ == "__main__":
    app.run(debug=True)

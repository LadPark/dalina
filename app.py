import os
import pandas as pd
from flask import Flask, render_template, request, abort, jsonify
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

app = Flask(__name__)
data_path = "data"
BUCKET_NAME = "dalina-photos"

# ─── S3 클라이언트 생성 ───────────────────────────────
s3 = boto3.client(
    "s3",
    region_name="ap-southeast-2",
    config=Config(signature_version="s3v4")
)

# ─── Presigned URL 생성 함수 ─────────────────────────
def generate_presigned_url(key, bucket=BUCKET_NAME, expires=3600):
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires
        )
    except ClientError as e:
        app.logger.error(f"Presign URL 생성 실패: {e}")
        return None

# ─── 메인 페이지 (index.html) ────────────────────────
@app.route("/")
def index():
    events = [d for d in os.listdir(data_path) if os.path.isdir(os.path.join(data_path, d))]
    suggestions_map = {}
    for ev in events:
        csv_path = os.path.join(data_path, ev, "results.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, encoding="utf-8")
            suggestions_map[ev] = df["배번"].dropna().unique().tolist()
        else:
            suggestions_map[ev] = []

    posts = []
    posts_dir = os.path.join(app.static_folder, "posts")
    if os.path.isdir(posts_dir):
        for fname in sorted(os.listdir(posts_dir)):
            if not fname.lower().endswith(".txt"):
                continue
            with open(os.path.join(posts_dir, fname), encoding="utf-8") as f:
                title = f.readline().lstrip("\ufeff").strip()
            posts.append({"filename": fname, "title": title})

    return render_template("index.html", events=events, suggestions_map=suggestions_map, posts=posts)

# ─── 배번 검색 결과 (results.html) ───────────────────
@app.route("/search", methods=["POST"])
def search():
    event = request.form["event"]
    bib = request.form["bib"].strip().upper()
    csv_path = os.path.join(data_path, event, "results.csv")
    items = []

    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path, encoding="utf-8")
        matches = df[df["배번"] == bib]
        for fn in matches["파일명"].drop_duplicates():
            thumb_key = f"{event}/thumbs/{fn}"
            preview_key = f"{event}/previews/{fn}"
            full_key = f"{event}/fulls/{fn}"
            items.append({
                "name": fn,
                "thumb": generate_presigned_url(thumb_key),
                "preview": generate_presigned_url(preview_key),
                "full": generate_presigned_url(full_key),
            })

    return render_template("results.html", event=event, bib=bib, items=items)

# ─── 공지사항 (post.html) ─────────────────────────────
@app.route("/post/<filename>")
def post(filename):
    posts_dir = os.path.join(app.static_folder, "posts")
    if filename not in os.listdir(posts_dir) or not filename.lower().endswith(".txt"):
        abort(404)
    full_path = os.path.join(posts_dir, filename)
    with open(full_path, encoding="utf-8") as f:
        title = f.readline().lstrip("\ufeff").strip()
        content = "\n".join(ln.strip() for ln in f.read().splitlines()).strip()
    base, _ = os.path.splitext(filename)
    images = [f"{base}{ext}" for ext in (".png", ".jpg", ".jpeg", ".gif")
              if os.path.exists(os.path.join(posts_dir, f"{base}{ext}"))]
    return render_template("post.html", title=title, content=content, images=images)

# ─── 이벤트별 타임라인 리스트 (timeline.html) ────────
@app.route("/event/<event>/timeline")
def timeline(event):
    csv_path = os.path.join(data_path, event, "timeline.csv")
    if not os.path.exists(csv_path):
        abort(404)

    df = pd.read_csv(csv_path, header=None, names=["file_no", "time"])
    filtered_df = df[df["time"].apply(lambda x: any(x.endswith(f":{str(i).zfill(2)}") for i in range(0, 60, 5)))]
    time_list = filtered_df["time"].tolist()

    map_image_path = os.path.join(app.static_folder, "maps", f"{event}.png")
    if os.path.exists(map_image_path):
        map_image_url = f"/static/maps/{event}.png"
    else:
        map_image_url = None

    return render_template("timeline.html", event=event, time_list=time_list, map_image_url=map_image_url)

# ─── 타임라인 특정 시간 선택 후 썸네일 초기 로딩 (timeline_time.html) ─────
@app.route("/event/<event>/timeline/<time>")
def timeline_time(event, time):
    csv_path = os.path.join(data_path, event, "timeline.csv")
    if not os.path.exists(csv_path):
        abort(404)

    df = pd.read_csv(csv_path, header=None, names=["file_no", "time"])
    row = df[df["time"] == time]
    if row.empty:
        abort(404)

    center_file_no = int(row.iloc[0]["file_no"])
    start_no = max(center_file_no - 15, 1)
    end_no = center_file_no + 15
    file_nos = list(range(start_no, end_no + 1))

    items = []
    for no in file_nos:
        filename = f"{no:05d}.jpg"
        thumb_key = f"{event}/thumbs/{filename}"
        preview_key = f"{event}/previews/{filename}"
        full_key = f"{event}/fulls/{filename}"

        items.append({
            "thumb": generate_presigned_url(thumb_key),
            "preview": generate_presigned_url(preview_key),
            "full": generate_presigned_url(full_key),
            "file_no": no
        })

    timeline_map = {int(row["file_no"]): row["time"] for _, row in df.iterrows()}

    map_image_path = os.path.join(app.static_folder, "maps", f"{event}.png")
    if os.path.exists(map_image_path):
        map_image_url = f"/static/maps/{event}.png"
    else:
        map_image_url = None

    return render_template(
        "timeline_time.html",
        event=event,
        time=time,
        items=items,
        center_file_no=center_file_no,
        timeline_map=timeline_map,
        map_image_url=map_image_url
    )

# ─── 추가 썸네일 로딩 (Lazy loading) ─────────────────
@app.route("/event/<event>/timeline/<time>/load_more", methods=["POST"])
def load_more(event, time):
    direction = request.form.get("direction")
    current_file_no = int(request.form.get("current_file_no"))

    if direction not in ["up", "down"]:
        abort(400)

    if direction == "up":
        start_no = max(current_file_no - 19, 1)
        end_no = current_file_no - 1
    else:
        start_no = current_file_no + 1
        end_no = current_file_no + 19

    file_nos = list(range(start_no, end_no + 1))

    items = []
    for no in file_nos:
        filename = f"{no:05d}.jpg"
        thumb_key = f"{event}/thumbs/{filename}"
        preview_key = f"{event}/previews/{filename}"
        full_key = f"{event}/fulls/{filename}"

        items.append({
            "thumb": generate_presigned_url(thumb_key),
            "preview": generate_presigned_url(preview_key),
            "full": generate_presigned_url(full_key),
            "file_no": no
        })

    return jsonify(items)

# ─── 메인 ─────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

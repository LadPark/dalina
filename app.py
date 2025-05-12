import os
import pandas as pd
from flask import Flask, render_template, request, abort, jsonify, redirect, g
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from face_recognition import extract_face_vector, compare_vectors, load_face_vectors
import time
import psutil
import tracemalloc
import json
import numpy as np
import uuid
import logging
from werkzeug.utils import secure_filename

# 기본 요청 로깅 설정
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('werkzeug')
log.setLevel(logging.DEBUG)

app = Flask(__name__)
data_path = "data"
BUCKET_NAME = "dalina-photos"

# 얼굴 벡터 캐시
face_vectors_cache = {}

# 고유 사용자 추적용
unique_users = set()

# S3 클라이언트 생성
s3 = boto3.client(
    "s3",
    region_name="ap-southeast-2",
    config=Config(signature_version="s3v4")
)

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

def load_all_face_vectors():
    print("⏳ 얼굴 벡터 캐시 로딩 시작...")

    continuation_token = None

    while True:
        if continuation_token:
            response = s3.list_objects_v2(
                Bucket=BUCKET_NAME, Prefix="", ContinuationToken=continuation_token
            )
        else:
            response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix="")

        for obj in response.get("Contents", []):
            parts = obj["Key"].split("/")
            if len(parts) == 3 and parts[1] == "face_vectors" and parts[2].endswith(".json1"):
                event_name = parts[0]
                if event_name in face_vectors_cache:
                    continue  # 중복 방지
                try:
                    s3_file_key = f"{event_name}/face_vectors/face_vectors.json1"
                    res = s3.get_object(Bucket=BUCKET_NAME, Key=s3_file_key)
                    content = res["Body"].read().decode("utf-8").splitlines()
                    vectors = []
                    for line in content:
                        record = json.loads(line.strip())
                        vectors.append({
                            "filename": record["filename"],
                            "vector": np.array(record["vector"], dtype=np.float32)
                        })
                    face_vectors_cache[event_name] = vectors
                    size_mb = sum(vec["vector"].nbytes for vec in vectors) / (1024 * 1024)
                    print(f"✔ 캐시됨: {event_name} ({len(vectors)}개 벡터, {size_mb:.2f} MB)")
                except Exception as e:
                    print(f"❌ {event_name} 캐시 실패: {e}")

        if response.get("IsTruncated"):
            continuation_token = response.get("NextContinuationToken")
        else:
            break

# 얼굴 벡터 로딩 (🔥 반드시 이 위치에서 전역 실행)
load_all_face_vectors()

@app.before_request
def start_resource_tracking():
    g.wall_start = time.time()
    g.cpu_start = time.process_time()
    g.process = psutil.Process(os.getpid())
    g.mem_start = g.process.memory_info().rss / 1024 / 1024
    tracemalloc.start()

    # 고유 사용자 추적
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ua = request.headers.get("User-Agent", "")
    user_key = f"{ip}_{ua}"
    ua_lower = ua.lower()
    is_bot = (
        "bot" in ua_lower or
        "crawler" in ua_lower or
        "spider" in ua_lower or
        "bingbot" in ua_lower or
        "facebookexternalhit" in ua_lower or
        "google" in ua_lower
    )

    if not is_bot:
        if user_key not in unique_users:
            print(f"[🆕 새로운 사용자] {user_key}")
        unique_users.add(user_key)
        print(f"[👥 누적 사용자 수] {len(unique_users)}명")

    # 사용자 요청 로그
    path = request.path
    method = request.method
    if (
        path.startswith("/search_face") or
        path.startswith("/process_face") or
        (path.startswith("/search") and method == "POST" and "bib" in request.form)
    ):
        print(f"[사용자 요청] {method} {path} from {ip} | UA: {ua}")

@app.after_request
def log_resource_usage(response):
    try:
        path = request.path
        user_agent = request.user_agent.string.lower()

        # 의미 없는 요청이면 리소스 로깅 생략
        if (
            path.startswith("/static/") or
            path.endswith(".ico") or
            "bot" in user_agent or
            "facebookexternalhit" in user_agent
        ):
            return response

        wall_end = time.time()
        cpu_end = time.process_time()
        mem_end = g.process.memory_info().rss / 1024 / 1024
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        if hasattr(g, 'mem_start'):
            print(f"\n🔧 [요청별] 리소스 사용 요약:")
            print(f"🕒 총 처리 시간 (wall): {wall_end - g.wall_start:.3f} 초")
            print(f"⚙️ CPU 시간: {cpu_end - g.cpu_start:.3f} 초")
            print(f"🧠 메모리 사용량 (시작 → 종료): {g.mem_start:.2f} MB → {mem_end:.2f} MB")
            print(f"📈 메모리 최대 피크: {peak / (1024 * 1024):.2f} MB")
    except Exception as e:
        print(f"[리소스 로깅 실패] {e}")
    return response

@app.route("/")
def index():
    events = sorted(
        [d for d in os.listdir(data_path) if os.path.isdir(os.path.join(data_path, d))],
        key=lambda d: d[:6],
        reverse=True
    )
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
                "file_no": int(fn[:5])
            })

    return render_template("results.html", event=event, bib=bib, items=items)

@app.route("/search_face", methods=["GET"])
def search_face():
    events = sorted(
        [d for d in os.listdir(data_path) if os.path.isdir(os.path.join(data_path, d))],
        key=lambda d: d[:6],
        reverse=True
    )
    return render_template("search_face.html", events=events)

@app.route("/process_face", methods=["POST"])
def process_face():
    file = request.files['face_image']
    temp_folder = 'temp'
    if not os.path.exists(temp_folder):
        os.makedirs(temp_folder)
        
    filename = f"{uuid.uuid4().hex}.jpg"
    file_path = os.path.join(temp_folder, filename)
    file.save(file_path)

    process = psutil.Process(os.getpid())
    mem_start = process.memory_info().rss / 1024 / 1024
    wall_start = time.time()
    cpu_start = time.process_time()
    tracemalloc.start()

    query_vector = extract_face_vector(file_path)
    if query_vector is None:
         return render_template("results.html", items=[], event="얼굴 인식", message="😢 사진에서 얼굴을 인식 할 수 없습니다.<br>다른 사진으로 시도하세요")

    event = request.form.get("event")
    if not event:
        return "이벤트를 선택해주세요."

    face_vectors = face_vectors_cache.get(event, [])
    search_results = compare_vectors(query_vector, face_vectors)

    wall_end = time.time()
    cpu_end = time.process_time()
    mem_end = process.memory_info().rss / 1024 / 1024
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n🔧 리소스 사용 요약:")
    print(f"🕒 총 처리 시간 (wall): {wall_end - wall_start:.3f} 초")
    print(f"⚙️ CPU 시간: {cpu_end - cpu_start:.3f} 초")
    print(f"🧠 메모리 사용량 (시작 → 종료): {mem_start:.2f} MB → {mem_end:.2f} MB")
    print(f"📈 메모리 최대 피크: {peak / (1024 * 1024):.2f} MB")

    if not search_results:
        return render_template("results.html", items=[], event=event, message="😢 일치하는 얼굴이 없습니다.")
    
    items = []
    for filename, similarity in search_results:
        thumb_key = f"{event}/thumbs/{filename}"
        preview_key = f"{event}/previews/{filename}"
        full_key = f"{event}/fulls/{filename}"
        items.append({
            "thumb": generate_presigned_url(thumb_key),
            "preview": generate_presigned_url(preview_key),
            "full": generate_presigned_url(full_key),
            "file_no": int(filename[:5])
        })

    return render_template("results.html", items=items, event=event)

# 이하 라우트 생략 (불변)


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
    map_image_url = f"/static/maps/{event}.png" if os.path.exists(map_image_path) else None

    return render_template("timeline.html", event=event, time_list=time_list, map_image_url=map_image_url)

# ─── 타임라인 특정 시간 썸네일 로딩 (focus 반영됨) ─────
@app.route("/event/<event>/timeline/<time>")
def timeline_time(event, time):
    csv_path = os.path.join(data_path, event, "timeline.csv")
    if not os.path.exists(csv_path):
        abort(404)

    df = pd.read_csv(csv_path, header=None, names=["file_no", "time"])
    row = df[df["time"] == time]
    if row.empty:
        abort(404)

    focus = request.args.get("focus", type=int)

    if focus:
        # ✅ focus 사진을 리스트 중간에 위치하게 로딩
        start_no = max(focus - 10, 1)
        end_no = focus + 20
        center_file_no = focus
    else:
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
    map_image_url = f"/static/maps/{event}.png" if os.path.exists(map_image_path) else None

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
        start_no = max(current_file_no - 40, 1)
        end_no = current_file_no - 1
    else:
        start_no = current_file_no + 1
        end_no = current_file_no + 40

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

# ─── 특정 사진 기준 타임라인 이동 ─────────────────────
@app.route("/event/<event>/timeline/from/<int:file_no>")
def timeline_from_file_no(event, file_no):
    csv_path = os.path.join(data_path, event, "timeline.csv")
    if not os.path.exists(csv_path):
        abort(404)
    df = pd.read_csv(csv_path, header=None, names=["file_no", "time"])
    row = df[df["file_no"] >= file_no].head(1)
    if row.empty:
        abort(404)
    time = row.iloc[0]["time"]
    return redirect(f"/event/{event}/timeline/{time}?focus={file_no}")

# ─── 메인 실행 ─────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

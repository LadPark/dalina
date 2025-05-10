import json
import boto3
import numpy as np
import joblib
import os
import gc
from PIL import Image
from insightface.app import FaceAnalysis
from numpy import dot
from numpy.linalg import norm

# ---------------------------------------------------------
# 모델 초기화 (insightface)
app = FaceAnalysis(name="buffalo_sc", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=0)

# PCA 모델 로드 (512 → 128)
base_dir = os.path.dirname(os.path.abspath(__file__))
pca_path = os.path.join(base_dir, "pca_512to128.pkl")
pca = joblib.load(pca_path)

# S3 클라이언트 초기화
s3 = boto3.client('s3')

# ---------------------------------------------------------
def load_resized_image_pil(path, max_size=1200):
    """
    최대 길이가 max_size를 넘지 않도록 PIL로 이미지 열고 리사이즈 (RAM 절약)
    """
    img = Image.open(path)
    img.thumbnail((max_size, max_size), Image.ANTIALIAS)
    return np.array(img.convert("RGB"))  # InsightFace는 RGB ndarray 필요

def extract_face_vector(image_path):
    """
    주어진 이미지 경로에서 얼굴 벡터를 추출한 후 PCA로 128차원으로 축소
    """
    try:
        resized = load_resized_image_pil(image_path)
        faces = app.get(resized)
        if len(faces) == 0:
            return None

        vec = np.array(faces[0].embedding, dtype=np.float32)
        face_embedding_128 = pca.transform([vec])[0]

        del resized, faces, vec
        gc.collect()

        print("Extracted 128-dim face vector:", face_embedding_128.tolist())
        return face_embedding_128.tolist()
    except Exception as e:
        print(f"❌ 벡터 추출 중 오류: {e}")
        return None

# ---------------------------------------------------------
def load_face_vectors_from_s3(bucket_name, event_name, file_name="face_vectors.json1"):
    """
    S3에서 PCA로 축소된 face_vectors.jsonl 파일을 읽어와 벡터를 로드
    """
    s3_file_key = f"{event_name}/face_vectors/{file_name}"
    print(f"S3 경로: {s3_file_key}")

    try:
        response = s3.get_object(Bucket=bucket_name, Key=s3_file_key)
        content = response["Body"].read().decode("utf-8").splitlines()

        face_vectors = []
        for line in content:
            record = json.loads(line.strip())
            face_vectors.append({
                "filename": record["filename"],
                "vector": np.array(record["vector"])
            })

        return face_vectors
    except Exception as e:
        print(f"Error loading face vectors: {e}")
        return []

# ---------------------------------------------------------
def load_face_vectors(event_name, bucket_name="dalina-photos"):
    """
    S3에서 해당 이벤트 이름에 대한 얼굴 벡터 리스트 로드
    """
    return load_face_vectors_from_s3(bucket_name, event_name)

# ---------------------------------------------------------
def cosine_similarity(vec1, vec2):
    """
    두 벡터 간의 코사인 유사도 계산
    """
    return dot(vec1, vec2) / (norm(vec1) * norm(vec2))

# ---------------------------------------------------------
def compare_vectors(query_vector, face_vectors, similarity_threshold=0.7):
    """
    128차원 얼굴 벡터와 DB 벡터를 비교하여 유사한 항목 반환
    """
    results = []

    for data in face_vectors:
        similarity = cosine_similarity(data["vector"], query_vector)
        if similarity >= similarity_threshold:
            results.append((data["filename"], similarity))

    results.sort(key=lambda x: x[0])
    return results

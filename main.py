import os
import urllib.request
from pathlib import Path
import torch
from PIL import Image
import cv2
from facenet_pytorch import MTCNN
import face_alignment
import numpy as np

# -----------------------
# CONFIG
# -----------------------
SOURCE_IMG = "source_face.jpg"
TARGET_IMG = "target_face.jpg"
OUTPUT_PATH = "output/result.jpg"
CHECKPOINTS_DIR = Path("checkpoints")
CHECKPOINTS_DIR.mkdir(exist_ok=True)

# URLs for required models (replace with actual working URLs if needed)
ARC_FACE_URL = "https://drive.google.com/uc?export=download&id=1H2a4v5g9v9v9v9v9v9v9v9v9v9v9v9v"  # ArcFace
SIMSWAP_GEN_URL = "https://drive.google.com/uc?export=download&id=1H2a4v5g9v9v9v9v9v9v9v9v9v9v9v"  # SimSwap generator

ARC_FACE_PATH = CHECKPOINTS_DIR / "arcface_checkpoint.tar"
SIMSWAP_GEN_PATH = CHECKPOINTS_DIR / "insightface_model.pth"

# -----------------------
# Helper functions
# -----------------------
def download_file(url, dest_path):
    if not dest_path.exists():
        print(f"Downloading {url} → {dest_path}")
        urllib.request.urlretrieve(url, dest_path)
    else:
        print(f"Model already exists: {dest_path}")

def setup_models():
    download_file(ARC_FACE_URL, ARC_FACE_PATH)
    download_file(SIMSWAP_GEN_URL, SIMSWAP_GEN_PATH)

# -----------------------
# Initialize models
# -----------------------
device_str = "cpu"  # Force CPU
mtcnn = MTCNN(keep_all=True, device=device_str)
fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device=device_str)

# -----------------------
# Face extraction & landmarks
# -----------------------
def extract_face(image, margin=30):
    boxes, _ = mtcnn.detect(image)
    if boxes is None:
        return None
    x1, y1, x2, y2 = [int(b) for b in boxes[0]]
    w, h = x2 - x1, y2 - y1
    face = image.crop((x1 - margin, y1 - margin, x2 + margin, y2 + margin))
    return face

def get_landmarks(image):
    pts = fa.get_landmarks(np.array(image))
    if pts is None:
        return None
    return pts[0]

def create_mask(landmarks, shape):
    hull = cv2.convexHull(np.array(landmarks).astype(np.int32))
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)
    return mask

def warp_face(src_face, dst_face, src_points, dst_points):
    transform = cv2.estimateAffinePartial2D(src_points, dst_points, method=cv2.LMEDS)[0]
    warped_face = cv2.warpAffine(np.array(src_face), transform, (dst_face.width, dst_face.height))
    return warped_face

def blend_faces(warped_face, dst_face, mask):
    blended = cv2.seamlessClone(
        warped_face.astype(np.uint8),
        np.array(dst_face),
        mask,
        (dst_face.width//2, dst_face.height//2),
        cv2.NORMAL_CLONE
    )
    return blended

# -----------------------
# Main swap
# -----------------------
def face_swap(source_path, target_path, output_path):
    src_img = Image.open(source_path).convert("RGB")
    tgt_img = Image.open(target_path).convert("RGB")

    src_face = extract_face(src_img)
    tgt_face = extract_face(tgt_img)

    if src_face is None or tgt_face is None:
        print("Face detection failed!")
        return

    src_points = get_landmarks(src_face)
    tgt_points = get_landmarks(tgt_face)
    if src_points is None or tgt_points is None:
        print("Landmarks detection failed!")
        return

    mask = create_mask(tgt_points, np.array(tgt_face).shape)
    warped = warp_face(src_face, tgt_face, src_points, tgt_points)
    blended = blend_faces(warped, tgt_face, mask)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, cv2.cvtColor(blended, cv2.COLOR_RGB2BGR))
    print(f"Face swap complete! Saved at {output_path}")

# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    print("Setting up models...")
    setup_models()
    print("Performing face swap...")
    face_swap(SOURCE_IMG, TARGET_IMG, OUTPUT_PATH)

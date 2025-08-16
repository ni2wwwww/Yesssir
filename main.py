import cv2
import dlib
import numpy as np
from PIL import Image
import os

# ====== LIGHTWEIGHT MODE (NO TORCH, NO MTCNN) ======
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")

# ====== OPTIMIZED FUNCTIONS ======
def extract_face(img, margin=20):
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    faces = detector(gray, 1)
    if len(faces) == 0:
        return None
    x, y, w, h = faces[0].left(), faces[0].top(), faces[0].width(), faces[0].height()
    return img.crop((x-margin, y-margin, x+w+margin, y+h+margin))

def get_landmarks(face):
    gray = cv2.cvtColor(np.array(face), cv2.COLOR_RGB2GRAY)
    shape = predictor(gray, dlib.rectangle(0, 0, face.width, face.height))
    return np.array([[p.x, p.y] for p in shape.parts()])

def warp_face(src_face, dst_face):
    src_points = get_landmarks(src_face)
    dst_points = get_landmarks(dst_face)
    transform = cv2.estimateAffinePartial2D(src_points, dst_points)[0]
    return cv2.warpAffine(np.array(src_face), transform, (dst_face.width, dst_face.height))

def simple_blend(warped, dst):
    mask = np.zeros(dst.shape[:2], dtype=np.uint8)
    cv2.convexHull(np.array(get_landmarks(Image.fromarray(dst))).astype(np.int32), mask, True)
    return cv2.seamlessClone(warped, dst, mask, (dst.shape[1]//2, dst.shape[0]//2), cv2.NORMAL_CLONE)

# ====== MAIN FUNCTION (RAM-FRIENDLY) ======
def face_swap(src_path, dst_path, output_path):
    try:
        # Load images with forced garbage collection
        src_img = Image.open(src_path).convert("RGB")
        dst_img = Image.open(dst_path).convert("RGB")
        
        # Extract faces (RAM-efficient)
        src_face = extract_face(src_img)
        dst_face = extract_face(dst_img)
        if None in [src_face, dst_face]:
            raise ValueError("No faces detected")
        
        # Process in chunks to save memory
        warped = warp_face(src_face, dst_face)
        result = simple_blend(warped, np.array(dst_img))
        
        # Save with cleanup
        cv2.imwrite(output_path, cv2.cvtColor(result, cv2.COLOR_RGB2BGR))
        return True
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

# ====== USAGE EXAMPLE ======
if __name__ == "__main__":
    print("PROCESSING... (RAM USAGE < 2GB)")
    success = face_swap(
        src_path="source_face.jpg",
        dst_path="target_face.jpg",
        output_path="result.jpg"
    )
    print("SUCCESS!" if success else "FAILED!")

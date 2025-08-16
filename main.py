import cv2
import numpy as np
from PIL import Image
import torch
from facenet_pytorch import MTCNN
import face_alignment

# -----------------------
# Device
# -----------------------
device = 'cuda' if torch.cuda.is_available() else 'cpu'

# -----------------------
# Models
# -----------------------
mtcnn = MTCNN(keep_all=True, device=device)
fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device=device)

# -----------------------
# Utility functions
# -----------------------
def extract_face(image, margin=20):
    """Detect and crop face from PIL Image"""
    image_np = np.array(image).astype(np.uint8)
    boxes, _ = mtcnn.detect(image_np)
    if boxes is None:
        return None
    x1, y1, x2, y2 = [int(b) for b in boxes[0]]
    return image.crop((
        max(x1 - margin, 0),
        max(y1 - margin, 0),
        x2 + margin,
        y2 + margin
    ))

def get_landmarks(image):
    """Return 68 landmarks for a face"""
    landmarks = fa.get_landmarks(np.array(image).astype(np.uint8))
    if landmarks is None:
        return None
    return landmarks[0]

def create_mask(landmarks, indices, shape, feather=15):
    """Create convex hull mask and apply feathering"""
    hull = cv2.convexHull(np.array(landmarks[indices]).astype(np.int32))
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)
    # Feather edges
    mask = cv2.GaussianBlur(mask, (feather*2+1, feather*2+1), 0)
    return mask

def color_transfer(src_face, dst_face, mask):
    """LAB color transfer per region"""
    src_lab = cv2.cvtColor(np.array(src_face), cv2.COLOR_RGB2LAB).astype(np.float32)
    dst_lab = cv2.cvtColor(np.array(dst_face), cv2.COLOR_RGB2LAB).astype(np.float32)
    for i in range(3):
        s_mean, s_std = src_lab[:,:,i][mask>0].mean(), src_lab[:,:,i][mask>0].std()
        d_mean, d_std = dst_lab[:,:,i][mask>0].mean(), dst_lab[:,:,i][mask>0].std()
        src_lab[:,:,i] = ((src_lab[:,:,i]-s_mean)*(d_std/(s_std+1e-6))) + d_mean
    return cv2.cvtColor(np.clip(src_lab,0,255).astype(np.uint8), cv2.COLOR_LAB2RGB)

def warp_region(src_face, dst_face, src_points, dst_points):
    """Warp source face region to match destination landmarks"""
    transform, _ = cv2.estimateAffinePartial2D(src_points, dst_points, method=cv2.LMEDS)
    warped = cv2.warpAffine(np.array(src_face), transform, (dst_face.width, dst_face.height))
    return warped

def seamless_clone(src_img, dst_img, mask):
    """Feathered seamless clone blending"""
    center = (dst_img.width//2, dst_img.height//2)
    blended = cv2.seamlessClone(np.array(src_img).astype(np.uint8),
                                np.array(dst_img).astype(np.uint8),
                                mask,
                                center,
                                cv2.NORMAL_CLONE)
    return blended

# -----------------------
# Main face swap function
# -----------------------
def face_swap(source_path, target_path, output_path):
    src_img = Image.open(source_path).convert("RGB")
    dst_img = Image.open(target_path).convert("RGB")

    # Detect faces
    src_face = extract_face(src_img)
    dst_face = extract_face(dst_img)
    if src_face is None or dst_face is None:
        print("Face detection failed!")
        return

    # Landmarks
    src_lm = get_landmarks(src_face)
    dst_lm = get_landmarks(dst_face)
    if src_lm is None or dst_lm is None:
        print("Landmarks detection failed!")
        return

    # -----------------------
    # Region indices
    # -----------------------
    FACE_IDX = list(range(0, 17)) + list(range(17, 27)) + list(range(27,36))
    EYES_IDX = list(range(36, 48))
    LIPS_IDX = list(range(48, 60))
    EYEBROWS_IDX = list(range(17, 27))
    # Forehead/Hair (approx. above eyebrows)
    FOREHEAD_IDX = np.array([[int(x), int(y-20)] for x,y in dst_lm[17:27]])

    # Create masks
    face_mask = create_mask(dst_lm, FACE_IDX, np.array(dst_face).shape)
    eyes_mask = create_mask(dst_lm, EYES_IDX, np.array(dst_face).shape)
    lips_mask = create_mask(dst_lm, LIPS_IDX, np.array(dst_face).shape)
    eyebrows_mask = create_mask(dst_lm, EYEBROWS_IDX, np.array(dst_face).shape)
    # Forehead mask (polygon)
    forehead_mask = np.zeros(np.array(dst_face).shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(forehead_mask, cv2.convexHull(np.array(FOREHEAD_IDX).astype(np.int32)), 255)
    forehead_mask = cv2.GaussianBlur(forehead_mask, (31,31), 0)

    # Combined mask
    combined_mask = cv2.bitwise_or(face_mask, eyes_mask)
    combined_mask = cv2.bitwise_or(combined_mask, lips_mask)
    combined_mask = cv2.bitwise_or(combined_mask, eyebrows_mask)
    combined_mask = cv2.bitwise_or(combined_mask, forehead_mask)

    # Color match
    src_face_colored = color_transfer(src_face, dst_face, combined_mask)

    # Warp
    warped_face = warp_region(src_face_colored, dst_face, src_lm, dst_lm)

    # Seamless cloning
    output = seamless_clone(warped_face, dst_face, combined_mask)

    # Optional: slight sharpening for realism
    output = cv2.detailEnhance(output, sigma_s=10, sigma_r=0.15)

    # Save
    cv2.imwrite(output_path, output)
    print(f"Ultra-realistic face swap complete! Saved as {output_path}")

# -----------------------
# Run example
# -----------------------
if __name__ == "__main__":
    face_swap("source.jpg", "target.jpg", "output.jpg")

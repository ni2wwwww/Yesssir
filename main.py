import cv2
import numpy as np
import torch
from facenet_pytorch import MTCNN
from PIL import Image
import face_alignment
import os

# Initialize models
mtcnn = MTCNN(keep_all=True, device='cuda' if torch.cuda.is_available() else 'cpu')
fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, 
                                device='cuda' if torch.cuda.is_available() else 'cpu')

def extract_face(image, margin=30):
    """Extract face using MTCNN with margin"""
    boxes, _ = mtcnn.detect(image)
    if boxes is None:
        return None
    x, y, w, h = [int(b) for b in boxes[0]]
    face = image.crop((x - margin, y - margin, x + w + margin, y + h + margin))
    return face

def get_landmarks(image):
    """Get facial landmarks using face-alignment"""
    return fa.get_landmarks(np.array(image))[0]

def create_convexhull_mask(landmarks, image_shape):
    """Create convex hull mask from landmarks"""
    hull = cv2.convexHull(np.array(landmarks).astype(np.int32))
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)
    return mask

def warp_face(src_face, dst_face, src_points, dst_points):
    """Warp source face to match destination face"""
    transform = cv2.estimateAffinePartial2D(src_points, dst_points, method=cv2.LMEDS)[0]
    warped_face = cv2.warpAffine(np.array(src_face), transform, (dst_face.width, dst_face.height))
    return warped_face

def blend_faces(warped_face, dst_face, mask):
    """Blend warped face with destination face"""
    r_mean, g_mean, b_mean = cv2.mean(np.array(dst_face), mask=mask)[:3]
    warped_face = warped_face.astype(np.float32)
    warped_face[:,:,0] += (r_mean - np.mean(warped_face[:,:,0]))
    warped_face[:,:,1] += (g_mean - np.mean(warped_face[:,:,1]))
    warped_face[:,:,2] += (b_mean - np.mean(warped_face[:,:,2]))
    
    blended = cv2.seamlessClone(
        warped_face.astype(np.uint8),
        np.array(dst_face),
        mask,
        (dst_face.width//2, dst_face.height//2),
        cv2.NORMAL_CLONE
    )
    return blended

def face_swap(src_img_path, dst_img_path, output_path):
    """Main face swap function"""
    # Load images
    src_img = Image.open(src_img_path).convert("RGB")
    dst_img = Image.open(dst_img_path).convert("RGB")

    # Extract faces
    src_face = extract_face(src_img)
    dst_face = extract_face(dst_img)
    
    if src_face is None or dst_face is None:
        print("Face detection failed!")
        return

    # Get landmarks
    src_points = get_landmarks(src_face)
    dst_points = get_landmarks(dst_face)

    # Create mask from destination landmarks
    mask = create_convexhull_mask(dst_points, np.array(dst_face).shape)

    # Warp and blend
    warped_face = warp_face(src_face, dst_face, src_points, dst_points)
    blended = blend_faces(warped_face, dst_face, mask)

    # Final output
    cv2.imwrite(output_path, cv2.cvtColor(blended, cv2.COLOR_RGB2BGR))

if __name__ == "__main__":
    face_swap(
        src_img_path="source.jpg",
        dst_img_path="target.jpg",
        output_path="output.jpg"
    )
    print("Face swap complete!")

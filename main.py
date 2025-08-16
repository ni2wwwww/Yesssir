import cv2
import numpy as np

# -----------------------
# CONFIG
# -----------------------
SOURCE_IMG = "source_face.jpg"
TARGET_IMG = "target_face.jpg"
OUTPUT_PATH = "advanced_swap_no_model.jpg"

# -----------------------
# Load images
# -----------------------
source = cv2.imread(SOURCE_IMG)
target = cv2.imread(TARGET_IMG)

# Convert to RGB
source_rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
target_rgb = cv2.cvtColor(target, cv2.COLOR_BGR2RGB)

# -----------------------
# Face detection using Haar cascades
# -----------------------
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

def get_face_box(img):
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
    if len(faces) == 0:
        raise ValueError("No face detected!")
    x, y, w, h = faces[0]
    return x, y, w, h

sx, sy, sw, sh = get_face_box(source_rgb)
tx, ty, tw, th = get_face_box(target_rgb)

# -----------------------
# Extract face and rough hair region
# -----------------------
source_face = source_rgb[sy:sy+sh, sx:sx+sw]

# Rough hair region: top 40% of the face box
hair_region = source_face[0:int(0.4*sh), :, :]

# Resize face and hair to target face
source_face_resized = cv2.resize(source_face, (tw, th))
hair_resized = cv2.resize(hair_region, (tw, int(0.4*th)))

# -----------------------
# Create mask for blending face + hair
# -----------------------
mask = np.zeros(source_face_resized.shape, dtype=np.uint8)
mask[:, :, :] = 255

# Optionally add a soft feather for hair blending
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15,15))
mask = cv2.erode(mask, kernel)

# -----------------------
# Color correction (match skin tone roughly)
# -----------------------
def color_correct(source_face, target_face):
    source_lab = cv2.cvtColor(source_face, cv2.COLOR_RGB2LAB).astype(np.float32)
    target_lab = cv2.cvtColor(target_face, cv2.COLOR_RGB2LAB).astype(np.float32)
    for i in range(3):
        s_mean, s_std = source_lab[:,:,i].mean(), source_lab[:,:,i].std()
        t_mean, t_std = target_lab[:,:,i].mean(), target_lab[:,:,i].std()
        source_lab[:,:,i] = ((source_lab[:,:,i]-s_mean)*(t_std/(s_std+1e-6))) + t_mean
    return cv2.cvtColor(np.clip(source_lab,0,255).astype(np.uint8), cv2.COLOR_LAB2RGB)

source_face_colored = color_correct(source_face_resized, target_rgb[ty:ty+th, tx:tx+tw])

# -----------------------
# Paste hair roughly onto target
# -----------------------
target_hair_region = target_rgb[ty:ty+int(0.4*th), tx:tx+tw]
hair_colored = color_correct(hair_resized, target_hair_region)
target_rgb[ty:ty+int(0.4*th), tx:tx+tw] = cv2.addWeighted(target_hair_region, 0.5, hair_colored, 0.5, 0)

# -----------------------
# Seamless cloning for face
# -----------------------
center = (tx + tw//2, ty + th//2)
output = cv2.seamlessClone(cv2.cvtColor(source_face_colored, cv2.COLOR_RGB2BGR),
                           target,
                           mask,
                           center,
                           cv2.NORMAL_CLONE)

# -----------------------
# Save output
# -----------------------
cv2.imwrite(OUTPUT_PATH, output)
print(f"Advanced face + hair swap completed! Saved as {OUTPUT_PATH}")

import cv2  
import dlib  
import numpy as np  
import torch  
from facenet_pytorch import MTCNN, InceptionResnetV1  
from PIL import Image  
import face_alignment  
from torchvision import transforms  
import os  

# ====== INIT MODELS (LOAD ONCE, SWAP FOREVER) ======  
mtcnn = MTCNN(keep_all=True, device='cuda' if torch.cuda.is_available() else 'cpu')  
predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")  
fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device='cuda' if torch.cuda.is_available() else 'cpu')  
resnet = InceptionResnetV1(pretrained='vggface2').eval()  

# ====== CORE FUNCTIONS ======  
def extract_face(image, margin=30):  
    boxes, _ = mtcnn.detect(image)  
    if boxes is None:  
        return None  
    x, y, w, h = [int(b) for b in boxes[0]]  
    face = image.crop((x - margin, y - margin, x + w + margin, y + h + margin))  
    return face  

def get_landmarks(face):  
    return fa.get_landmarks(np.array(face))[0]  

def warp_face(src_face, dst_face):  
    src_points = get_landmarks(src_face)  
    dst_points = get_landmarks(dst_face)  
    transform = cv2.estimateAffinePartial2D(src_points, dst_points, method=cv2.LMEDS)[0]  
    warped_face = cv2.warpAffine(np.array(src_face), transform, (dst_face.width, dst_face.height))  
    return warped_face  

def create_mask(face):  
    landmarks = get_landmarks(face)  
    hull = cv2.convexHull(np.array(landmarks).astype(np.int32))  
    mask = np.zeros((face.height, face.width), dtype=np.uint8)  
    cv2.fillConvexPoly(mask, hull, 255)  
    return mask  

def blend_faces(warped_face, dst_face, mask):  
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

def transfer_hair_and_lighting(src_img, dst_img, blended_face):  
    mask = np.zeros(src_img.shape[:2], np.uint8)  
    bgdModel = np.zeros((1,65), np.float64)  
    fgdModel = np.zeros((1,65), np.float64)  
    rect = (50,50,src_img.shape[1]-100,src_img.shape[0]-100)  
    cv2.grabCut(src_img, mask, rect, bgdModel, fgdModel, 5, cv2.GC_INIT_WITH_RECT)  
    hair_mask = np.where((mask==2)|(mask==0),0,1).astype('uint8')  
    hair = src_img * hair_mask[:,:,np.newaxis]  
    final = cv2.addWeighted(blended_face, 0.85, hair, 0.15, 0)  
    return final  

# ====== MAIN FUNCTION ======  
def face_swap(src_img_path, dst_img_path, output_path):  
    src_img = Image.open(src_img_path).convert("RGB")  
    dst_img = Image.open(dst_img_path).convert("RGB")  

    src_face = extract_face(src_img)  
    dst_face = extract_face(dst_img)  

    if src_face is None or dst_face is None:  
        print("NO FACES DETECTED! ABORTING.")  
        return  

    warped_face = warp_face(src_face, dst_face)  
    mask = create_mask(dst_face)  
    blended = blend_faces(warped_face, dst_face, mask)  

    final = transfer_hair_and_lighting(np.array(src_img), np.array(dst_img), blended)  
    cv2.imwrite(output_path, cv2.cvtColor(final, cv2.COLOR_RGB2BGR))  

# ====== EXAMPLE USAGE ======  
if __name__ == "__main__":  
    face_swap(  
        src_img_path="source_face.jpg",  
        dst_img_path="target_face.jpg",  
        output_path="output_swap.jpg"  
    )  
    print("FACE SWAP COMPLETE. ENJOY YOUR WARCRIME.")  

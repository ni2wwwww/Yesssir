import os
import subprocess
import sys
from pathlib import Path
import shutil
import urllib.request
import zipfile

# -----------------------
# CONFIG
# -----------------------
DFL_DIR = Path("DeepFaceLab")            # DeepFaceLab folder
SRC_IMG = Path("source_face.jpg")        # Your source face
DST_IMG = Path("target_face.jpg")        # Your target face
WORKSPACE_DIR = DFL_DIR / "workspace"
SRC_DIR = WORKSPACE_DIR / "data_src"
DST_DIR = WORKSPACE_DIR / "data_dst"
RESULT_DIR = WORKSPACE_DIR / "result"
MODEL_DIR = WORKSPACE_DIR / "model"
PRETRAIN_URL = "https://github.com/iperov/DeepFaceLab/releases/download/v2.0.0/Original_CPU.pth"  # Lightweight CPU model

# -----------------------
# HELPER FUNCTIONS
# -----------------------
def run(cmd):
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def download_file(url, dest):
    if dest.exists():
        print(f"{dest} already exists, skipping download.")
        return
    print(f"Downloading {url} to {dest} ...")
    urllib.request.urlretrieve(url, dest)
    print("Download complete.")

def prepare_workspace():
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    DST_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(SRC_IMG, SRC_DIR / SRC_IMG.name)
    shutil.copy(DST_IMG, DST_DIR / DST_IMG.name)
    print("Workspace ready.")

def install_requirements():
    print("Installing CPU-only DeepFaceLab requirements with --break-system-packages...")
    run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "--break-system-packages",
         "tensorflow-cpu==2.12.0", "opencv-python==4.7.0.72",
         "ffmpeg-python", "dlib", "h5py", "numpy==1.23.5", "tqdm",
         "scikit-image", "imutils"])

def setup_deepfacelab():
    if not DFL_DIR.exists():
        print("Downloading DeepFaceLab CPU version...")
        zip_path = Path("DeepFaceLab_CPU.zip")
        dfl_url = "https://github.com/iperov/DeepFaceLab/releases/download/v2.0.0/DeepFaceLab_Linux_CPU.zip"  # example
        download_file(dfl_url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(DFL_DIR)
        zip_path.unlink()
        print("DeepFaceLab extracted.")
    else:
        print("DeepFaceLab folder exists, skipping download.")

def download_pretrained_model():
    dest = MODEL_DIR / "Original_CPU.pth"
    download_file(PRETRAIN_URL, dest)

# -----------------------
# DEEPFACELAB STEPS
# -----------------------
def extract_faces():
    print("Extracting faces from source and target...")
    run([sys.executable, str(DFL_DIR / "main.py"), "extract",
         "--input-dir", str(SRC_DIR),
         "--output-dir", str(SRC_DIR / "aligned"),
         "--detector", "s3fd"])
    run([sys.executable, str(DFL_DIR / "main.py"), "extract",
         "--input-dir", str(DST_DIR),
         "--output-dir", str(DST_DIR / "aligned"),
         "--detector", "s3fd"])

def merge_face():
    print("Merging swapped face onto target using pre-trained CPU model...")
    run([sys.executable, str(DFL_DIR / "main.py"), "merge",
         "--input-dir", str(DST_DIR),
         "--output-dir", str(RESULT_DIR),
         "--model-dir", str(MODEL_DIR)])

# -----------------------
# MAIN
# -----------------------
if __name__ == "__main__":
    print("=== DeepFaceLab CPU Fully Automated Pipeline ===")
    install_requirements()
    setup_deepfacelab()
    prepare_workspace()
    download_pretrained_model()
    extract_faces()
    merge_face()
    print(f"✅ Face swap complete! Check {RESULT_DIR} for results.")

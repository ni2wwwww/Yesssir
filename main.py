# bot.py
#
# First, install all required dependencies using this command:
# pip install python-telegram-bot==20.3 torch==2.0.1 torchvision==0.15.2 opencv-python==4.8.0.74 Pillow==10.0.0 ffmpeg-python==0.2.0 insightface==0.7.3 numpy==1.24.3 onnxruntime==1.15.1

import os
import logging
import asyncio
import uuid
import shutil
from urllib import request

import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import cv2
import torch
import numpy as np
from PIL import Image
import ffmpeg

# --- Model Loading and Core SimSwap Dependencies ---
# NOTE: To keep this a single file, parts of the original SimSwap repository
# (specifically models/networks.py) are included directly here.
# Insightface is also a key dependency for face detection and alignment.

try:
    import insightface
    from insightface.app import FaceAnalysis
except ImportError:
    print("Insightface not found. Please install it: pip install insightface")
    exit()

# --- Configuration ---
BOT_TOKEN = "7678348871:AAFKNVn1IAp46iBcTTOwo31i4WlT2KcZWGE"  # <--- IMPORTANT: REPLACE WITH YOUR BOT TOKEN
TEMP_DIR = "./temp_simswap_bot"
MODELS_DIR = "./models"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Global Variables ---
user_sessions = {}
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
FACE_SWAPPER = None
FACE_ANALYSER = None

# --- Helper Functions for Model Downloading ---
def download_file(url, save_path):
    """Downloads a file from a URL and saves it locally."""
    if not os.path.exists(save_path):
        logger.info(f"Downloading {os.path.basename(save_path)} from {url}...")
        try:
            request.urlretrieve(url, save_path)
            logger.info("Download complete.")
        except Exception as e:
            logger.error(f"Failed to download {url}. Error: {e}")
            # Clean up partial file if download failed
            if os.path.exists(save_path):
                os.remove(save_path)
            raise e
    else:
        logger.info(f"{os.path.basename(save_path)} already exists.")

def setup_models():
    """
    Downloads and initializes all the required deep learning models.
    This function is called once when the bot starts.
    """
    global FACE_SWAPPER, FACE_ANALYSER

    # 1. Download Insightface models
    # Insightface's FaceAnalysis will handle its own model downloads automatically
    # when it's initialized for the first time. We just need to create the .insightface/models dir
    insightface_models_dir = os.path.join(os.path.expanduser('~'), '.insightface', 'models')
    os.makedirs(insightface_models_dir, exist_ok=True)

    # 2. Download SimSwap pretrained model weights
    simswap_model_url = "https://github.com/neuralchen/SimSwap/releases/download/1.0/simswap.pth"
    simswap_model_path = os.path.join(MODELS_DIR, "simswap.pth")
    download_file(simswap_model_url, simswap_model_path)

    # 3. Initialize FaceAnalysis for face detection/alignment
    logger.info("Initializing Insightface FaceAnalysis model...")
    FACE_ANALYSER = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider' if DEVICE == 'cuda' else 'CPUExecutionProvider'])
    FACE_ANALYSER.prepare(ctx_id=0, det_size=(640, 640))
    logger.info("Insightface model initialized.")

    # 4. Initialize SimSwap model
    logger.info("Initializing SimSwap model...")
    try:
        from simswap_models import fs_networks # Defined at the bottom of the file
        net = fs_networks.FS(os.path.join(MODELS_DIR, 'simswap.pth'))
        net.eval()
        FACE_SWAPPER = net.to(DEVICE)
        logger.info("SimSwap model initialized and moved to " + DEVICE)
    except Exception as e:
        logger.error(f"Could not load SimSwap model: {e}")
        raise e

# --- Core Face Swapping Logic ---
async def swap_face(source_img_path, target_path):
    """
    Performs face swapping on an image or video.
    """
    source_img = cv2.imread(source_img_path)
    source_faces = FACE_ANALYSER.get(source_img)
    if not source_faces:
        raise ValueError("No face detected in the source image.")
    source_face = sorted(source_faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]), reverse=True)[0]

    # Check if target is image or video
    file_ext = os.path.splitext(target_path)[1].lower()
    is_video = file_ext in ['.mp4', '.mov', '.avi', '.mkv']

    if is_video:
        return await process_video(source_face, target_path)
    else:
        return process_image(source_face, target_path)

def process_image(source_face, target_img_path):
    """Processes a single target image."""
    target_img = cv2.imread(target_img_path)
    target_faces = FACE_ANALYSER.get(target_img)
    if not target_faces:
        raise ValueError("No face detected in the target image.")

    result_img = target_img.copy()
    for target_face in target_faces:
        result_img = FACE_SWAPPER(source_face, target_face, source_img, result_img)

    output_path = os.path.join(TEMP_DIR, f"swapped_{uuid.uuid4()}.jpg")
    cv2.imwrite(output_path, result_img)
    return output_path, 'image'

async def process_video(source_face, target_video_path):
    """Processes a target video frame by frame."""
    output_path = os.path.join(TEMP_DIR, f"swapped_{uuid.uuid4()}.mp4")
    
    # Use ffmpeg to check for audio stream
    has_audio = False
    try:
        probe = ffmpeg.probe(target_video_path)
        video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
        audio_streams = [s for s in probe['streams'] if s['codec_type'] == 'audio']
        if audio_streams:
            has_audio = True
    except ffmpeg.Error as e:
        logger.error(f"ffmpeg probe error: {e.stderr}")
        # Assume no audio if probe fails
        has_audio = False

    cap = cv2.VideoCapture(target_video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Define the codec and create VideoWriter object
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp_video_path = os.path.join(TEMP_DIR, f"temp_video_{uuid.uuid4()}.mp4")
    out = cv2.VideoWriter(temp_video_path, fourcc, fps, (width, height))

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        target_faces = FACE_ANALYSER.get(frame)
        if target_faces:
            result_frame = frame.copy()
            for target_face in target_faces:
                result_frame = FACE_SWAPPER(source_face, None, None, result_frame, target_face=target_face)
            out.write(result_frame)
        else:
            # If no face is detected, write the original frame
            out.write(frame)

    cap.release()
    out.release()
    
    # If original video had audio, combine it with the new video frames
    if has_audio:
        logger.info("Combining video with original audio...")
        input_video = ffmpeg.input(temp_video_path)
        input_audio = ffmpeg.input(target_video_path).audio
        (
            ffmpeg
            .concat(input_video, input_audio, v=1, a=1)
            .output(output_path, y='-y') # -y to overwrite output file if it exists
            .run(quiet=True)
        )
        os.remove(temp_video_path) # Clean up temp video file
    else:
        # If no audio, just rename the temp file
        os.rename(temp_video_path, output_path)

    return output_path, 'video'


# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Welcome to the SimSwap Bot!\n\n"
        "Please send two photos:\n"
        "1. The photo with the face you want to USE (source).\n"
        "2. The photo or video you want to put the face ONTO (target).\n\n"
        "I will process them in the order you send them."
    )

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming photos and videos, managing the user session."""
    user_id = update.message.from_user.id
    message = update.message
    
    file_id = None
    file_ext = '.jpg' # Default to jpg for photos
    is_video = False

    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.video:
        file_id = message.video.file_id
        file_ext = '.mp4'
        is_video = True
    
    if not file_id:
        await message.reply_text("Sorry, I can only process photos and videos.")
        return

    bot = context.bot
    
    # Initialize session for new user
    if user_id not in user_sessions:
        user_sessions[user_id] = {'source': None, 'target': None, 'session_id': str(uuid.uuid4())}
    
    session = user_sessions[user_id]
    session_path = os.path.join(TEMP_DIR, session['session_id'])
    os.makedirs(session_path, exist_ok=True)

    try:
        new_file = await bot.get_file(file_id)
        
        if not session['source']:
            if is_video:
                await message.reply_text("The first image must be a photo (source face), not a video. Please send a photo.")
                return
            
            source_path = os.path.join(session_path, f"source{file_ext}")
            await new_file.download_to_drive(source_path)
            session['source'] = source_path
            await message.reply_text("✅ Source face saved. Now send the target image or video.")

        elif not session['target']:
            target_path = os.path.join(session_path, f"target{file_ext}")
            await new_file.download_to_drive(target_path)
            session['target'] = target_path
            
            status_msg = await message.reply_text("✅ Target saved, processing...")
            
            if is_video:
                await status_msg.edit_text("⏳ Processing video... This may take a while.")

            # --- Trigger the swap ---
            source_file = session['source']
            target_file = session['target']
            
            result_path, result_type = await swap_face(source_file, target_file)

            # Send result
            await status_msg.edit_text("✅ Processing complete! Sending your result...")
            if result_type == 'image':
                await bot.send_photo(chat_id=user_id, photo=open(result_path, 'rb'))
            elif result_type == 'video':
                await bot.send_video(chat_id=user_id, video=open(result_path, 'rb'))
            
            # --- Cleanup and reset session ---
            shutil.rmtree(session_path, ignore_errors=True)
            del user_sessions[user_id]

    except ValueError as e:
        await message.reply_text(f"❌ Error: {e}. Resetting session. Please start over.")
        if os.path.exists(session_path):
            shutil.rmtree(session_path, ignore_errors=True)
        if user_id in user_sessions:
            del user_sessions[user_id]
            
    except Exception as e:
        logger.error(f"An unexpected error occurred for user {user_id}: {e}", exc_info=True)
        await message.reply_text("❌ An unexpected error occurred. Resetting session. Please try again.")
        if os.path.exists(session_path):
            shutil.rmtree(session_path, ignore_errors=True)
        if user_id in user_sessions:
            del user_sessions[user_id]

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)


def main() -> None:
    """Start the bot."""
    # First, setup all the DL models
    try:
        setup_models()
    except Exception as e:
        logger.error(f"FATAL: Could not initialize models. The bot will not start. Error: {e}")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))

    # on non command i.e message - handle the message on Telegram
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))

    # log all errors
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot is running. Press Ctrl-C to stop.")
    application.run_polling()


# --- SimSwap Model Definitions ---
# This section contains the necessary model architecture classes,
# adapted from the official SimSwap repository to make this file self-contained.
# Source: https://github.com/neuralchen/SimSwap/blob/main/models/networks.py

from torch.nn import Linear, Conv2d, BatchNorm2d, PReLU, Sequential, Module
from torch.nn import functional as F
from collections import namedtuple
import torch.nn as nn

class simswap_models:
    class EqualLinear(Module):
        def __init__(self, in_dim, out_dim, bias=True, bias_init=0, lr_mul=1, activation=None):
            super().__init__()
            self.weight = nn.Parameter(torch.randn(out_dim, in_dim).div_(lr_mul))
            if bias:
                self.bias = nn.Parameter(torch.zeros(out_dim).fill_(bias_init))
            else:
                self.bias = None
            self.activation = activation
            self.scale = (1 / math.sqrt(in_dim)) * lr_mul
            self.lr_mul = lr_mul
        def forward(self, input):
            if self.activation:
                out = F.linear(input, self.weight * self.scale)
                out = F.leaky_relu(out, 0.2)
            else:
                out = F.linear(input, self.weight * self.scale, bias=self.bias * self.lr_mul)
            return out
        def __repr__(self):
            return (f'{self.__class__.__name__}({self.weight.shape[1]}, {self.weight.shape[0]})')

    class Flatten(Module):
        def forward(self, input):
            return input.view(input.size(0), -1)

    class SEModule(Module):
        def __init__(self, channels, reduction=16):
            super(simswap_models.SEModule, self).__init__()
            self.avg_pool = nn.AdaptiveAvgPool2d(1)
            self.fc1 = Conv2d(channels, channels // reduction, kernel_size=1, padding=0, bias=False)
            self.relu = nn.ReLU(inplace=True)
            self.fc2 = Conv2d(channels // reduction, channels, kernel_size=1, padding=0, bias=False)
            self.sigmoid = nn.Sigmoid()
        def forward(self, x):
            module_input = x
            x = self.avg_pool(x)
            x = self.fc1(x)
            x = self.relu(x)
            x = self.fc2(x)
            x = self.sigmoid(x)
            return module_input * x

    class Bottleneck_IR_SE(Module):
        def __init__(self, in_channel, depth, stride):
            super(simswap_models.Bottleneck_IR_SE, self).__init__()
            if in_channel == depth:
                self.shortcut_layer = nn.MaxPool2d(1, stride)
            else:
                self.shortcut_layer = Sequential(
                    Conv2d(in_channel, depth, (1, 1), stride, bias=False), 
                    BatchNorm2d(depth)
                )
            self.res_layer = Sequential(
                BatchNorm2d(in_channel),
                Conv2d(in_channel, depth, (3, 3), (1, 1), 1, bias=False), 
                PReLU(depth),
                Conv2d(depth, depth, (3, 3), stride, 1, bias=False), 
                BatchNorm2d(depth),
                simswap_models.SEModule(depth, 16)
            )
        def forward(self, x):
            shortcut = self.shortcut_layer(x)
            res = self.res_layer(x)
            return res + shortcut
        
    class fs_networks:
        class Iresnet(Module):
            def __init__(self, block, layers, use_se=True):
                super(simswap_models.fs_networks.Iresnet, self).__init__()
                self.in_channel = 64
                self.use_se = use_se
                self.conv1 = Sequential(
                    Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False),
                    BatchNorm2d(64),
                    PReLU(64)
                )
                self.layer1 = self._make_layer(block, 64, layers[0], stride=2)
                self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
                self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
                self.layer4 = self._make_layer(block, 512, layers[3], stride=2)
                self.conv_out = Sequential(
                    BatchNorm2d(512),
                    simswap_models.Flatten(),
                    Linear(512 * 7 * 7, 512),
                    BatchNorm2d(512)
                )

            def _make_layer(self, block, depth, num_blocks, stride):
                layers = []
                layers.append(block(self.in_channel, depth, stride))
                self.in_channel = depth
                for i in range(1, num_blocks):
                    layers.append(block(self.in_channel, depth, 1))
                return Sequential(*layers)

            def forward(self, x):
                x = self.conv1(x)
                x1 = self.layer1(x)
                x2 = self.layer2(x1)
                x3 = self.layer3(x2)
                x4 = self.layer4(x3)
                x_out = self.conv_out(x4)
                return [x1, x2, x3, x4], x_out
        
        class ADDGenerator(Module):
            def __init__(self, c_id=512):
                super(simswap_models.fs_networks.ADDGenerator, self).__init__()
                self.conv_list = nn.ModuleList([
                    simswap_models.fs_networks.conv_block(512, 512, 3, 1, 1), simswap_models.fs_networks.conv_block(512, 512, 3, 1, 1),
                    simswap_models.fs_networks.conv_block(512, 512, 3, 1, 1), simswap_models.fs_networks.conv_block(256, 256, 3, 1, 1),
                    simswap_models.fs_networks.conv_block(256, 256, 3, 1, 1), simswap_models.fs_networks.conv_block(128, 128, 3, 1, 1),
                    simswap_models.fs_networks.conv_block(128, 128, 3, 1, 1), simswap_models.fs_networks.conv_block(64, 64, 3, 1, 1),
                    simswap_models.fs_networks.conv_block(64, 64, 3, 1, 1)
                ])
                self.adain_list = nn.ModuleList([
                    simswap_models.fs_networks.AdaIN(512, c_id), simswap_models.fs_networks.AdaIN(512, c_id),
                    simswap_models.fs_networks.AdaIN(512, c_id), simswap_models.fs_networks.AdaIN(256, c_id),
                    simswap_models.fs_networks.AdaIN(256, c_id), simswap_models.fs_networks.AdaIN(128, c_id),
                    simswap_models.fs_networks.AdaIN(128, c_id), simswap_models.fs_networks.AdaIN(64, c_id),
                    simswap_models.fs_networks.AdaIN(64, c_id)
                ])
                self.upsample = nn.Upsample(scale_factor=2, mode='bilinear')
                self.to_rgb = simswap_models.fs_networks.conv_block(64, 3, 3, 1, 1, act='tanh')

            def forward(self, x, c):
                x_list = [x[-1]]
                for i in range(len(self.conv_list)):
                    if i > 0 and i % 2 == 1:
                        x = self.upsample(x)
                    if i > 0 and i < 3:
                        x = torch.cat([x, x_list[-(i // 2 + 1)]], dim=1)
                    x = self.conv_list[i](x)
                    x = self.adain_list[i](x, c)
                return self.to_rgb(x)
        
        class conv_block(Module):
            def __init__(self, in_c, out_c, k, s, p, act='relu'):
                super().__init__()
                self.conv = Conv2d(in_c, out_c, k, s, p)
                self.norm = BatchNorm2d(out_c)
                if act == 'relu':
                    self.act = nn.ReLU()
                elif act == 'tanh':
                    self.act = nn.Tanh()
            def forward(self, x):
                return self.act(self.norm(self.conv(x)))

        class AdaIN(Module):
            def __init__(self, n_c, c_id):
                super().__init__()
                self.norm = BatchNorm2d(n_c, affine=False)
                self.fc = Linear(c_id, n_c * 2)
            def forward(self, x, c):
                h = self.fc(c)
                h = h.view(h.size(0), h.size(1), 1, 1)
                gamma, beta = torch.chunk(h, chunks=2, dim=1)
                return (1 + gamma) * self.norm(x) + beta

        class FS(Module):
            def __init__(self, model_path):
                super(simswap_models.fs_networks.FS, self).__init__()
                self.E = simswap_models.fs_networks.Iresnet(simswap_models.Bottleneck_IR_SE, [3, 4, 23, 3])
                self.G = simswap_models.fs_networks.ADDGenerator()
                self.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
                self.to(DEVICE)
            
            def forward(self, I_s, I_t_face, I_t, I_t_full, target_face=None):
                if target_face is not None:
                    # Video processing case
                    I_t_full_align_crop, M_t = self.crop_and_align(I_t_full, [target_face])
                    _, C_t = self.E(F.interpolate(I_t_full_align_crop, [112, 112], mode='bilinear', align_corners=True))
                    with torch.no_grad():
                        _, C_s = self.E(F.interpolate(self.crop_and_align(I_s, [I_s_face])[0], [112, 112], mode='bilinear', align_corners=True))
                    I_r = self.G(C_t, C_s)
                    I_r = F.interpolate(I_r, [224, 224], mode='bilinear', align_corners=True)
                    return self.paste_back(I_r, M_t, I_t_full)
                else:
                    # Image processing case
                    I_s_align_crop, M_s = self.crop_and_align(I_s, [I_s_face])
                    I_t_align_crop, M_t = self.crop_and_align(I_t, [I_t_face])
                    with torch.no_grad():
                        _, C_s = self.E(F.interpolate(I_s_align_crop, [112, 112], mode='bilinear', align_corners=True))
                    _, C_t = self.E(F.interpolate(I_t_align_crop, [112, 112], mode='bilinear', align_corners=True))
                    I_r = self.G(C_t, C_s)
                    I_r = F.interpolate(I_r, [224, 224], mode='bilinear', align_corners=True)
                    return self.paste_back(I_r, M_t, I_t)

            def crop_and_align(self, I, face_info):
                face = face_info[0]
                lmk = face.kps.astype(np.int32)
                # Simplified alignment for bot usage
                IM, M = self.align_face(I, lmk)
                return torch.tensor(IM, dtype=torch.float32, device=DEVICE).permute(0, 3, 1, 2), torch.tensor(M, dtype=torch.float32, device=DEVICE)

            def align_face(self, img, lmk, output_size=224):
                tform = self.estimate_norm(lmk, output_size)
                return self.warp_and_crop(img, tform, output_size)

            def estimate_norm(self, lmk, image_size):
                from skimage import transform as trans
                arcface_dst = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                                        [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)
                tform = trans.SimilarityTransform()
                tform.estimate(lmk, arcface_dst)
                return tform

            def warp_and_crop(self, img, tform, output_size):
                from skimage.transform import warp
                warped = warp(img, tform.inverse, output_shape=(output_size, output_size), preserve_range=True).astype(np.uint8)
                return np.expand_dims(warped, axis=0), np.expand_dims(tform.params, axis=0)

            def paste_back(self, I_r, M, I_t):
                I_r = I_r.permute(0, 2, 3, 1).cpu().numpy()
                M_inv = np.linalg.inv(M.cpu().numpy())
                I_r_255 = (I_r[0] * 127.5 + 127.5).clip(0, 255).astype(np.uint8)
                
                from skimage.transform import warp
                mask = np.ones((224, 224, 1), dtype=np.float32) * 255
                warped_mask = warp(mask, M_inv[0], output_shape=(I_t.shape[0], I_t.shape[1]), preserve_range=True).astype(np.uint8)
                warped_img = warp(I_r_255, M_inv[0], output_shape=(I_t.shape[0], I_t.shape[1]), preserve_range=True).astype(np.uint8)
                
                # Simple blending
                mask_blur = cv2.GaussianBlur(warped_mask, (15, 15), 0) / 255.0
                
                result = I_t * (1 - mask_blur) + warped_img * mask_blur
                return result.astype(np.uint8)


if __name__ == "__main__":
    # A check to ensure the user replaces the token
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! PLEASE REPLACE 'YOUR_BOT_TOKEN_HERE' WITH YOUR ACTUAL BOT TOKEN !!!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        main()


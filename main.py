# bot.py

# 1. DEPENDENCIES
# Install all required libraries using this command:
# pip install python-telegram-bot==20.3 torch torchvision opencv-python Pillow ffmpeg-python insightface numpy onnxruntime onnxruntime-gpu

import asyncio
import os
import logging
import cv2
import torch
import numpy as np
import ffmpeg
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from insightface.app import FaceAnalysis
from insightface.model_zoo import get_model

# 2. CONFIGURATION
# --- IMPORTANT ---
# Replace "YOUR_BOT_TOKEN" with your actual Telegram Bot Token
BOT_TOKEN = "7678348871:AAFKNVn1IAp46iBcTTOwo31i4WlT2KcZWGE" 

# --- Model & File Paths ---
# Directory to store user-uploaded files and results
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# --- Bot Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 3. GLOBAL VARIABLES & MODEL INITIALIZATION
# This section handles the setup of the deep learning models.
# We initialize them once globally to avoid reloading them for every request,
# which would be very slow.

# --- Device Configuration (CUDA or CPU) ---
# Check if CUDA is available and set the device accordingly.
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Using device: {DEVICE}")

# --- User Session Management ---
# A dictionary to hold the state for each user.
# The key is the user_id, and the value is another dictionary
# holding the path to their source face image.
# Example: {12345: {'source_path': 'temp/12345_source.jpg'}}
user_sessions = {}

# --- InsightFace Model Loading ---
# This can take a few seconds when the bot starts for the first time
# as it may need to download the model weights.
try:
    logger.info("Initializing InsightFace models...")
    
    # Face Analysis model to detect and analyze faces
    face_analyzer = FaceAnalysis(
        name='buffalo_l', 
        providers=['CUDAExecutionProvider' if DEVICE == 'cuda' else 'CPUExecutionProvider']
    )
    face_analyzer.prepare(ctx_id=0, det_size=(640, 640))

    # Face Swapper model
    face_swapper = get_model(
        'inswapper_128.onnx', 
        providers=['CUDAExecutionProvider' if DEVICE == 'cuda' else 'CPUExecutionProvider']
    )
    logger.info("InsightFace models initialized successfully.")
except Exception as e:
    logger.error(f"Error initializing InsightFace models: {e}")
    face_analyzer = None
    face_swapper = None

# 4. CORE PROCESSING FUNCTIONS
async def process_image(source_path: str, target_path: str, output_path: str) -> bool:
    """
    Performs face swapping on a single target image.
    """
    if not face_analyzer or not face_swapper:
        logger.error("Models are not available.")
        return False
        
    try:
        # Read source and target images
        source_img = cv2.imread(source_path)
        target_img = cv2.imread(target_path)
        
        if source_img is None or target_img is None:
            logger.error("Could not read one of the images.")
            return False

        # Detect faces
        source_faces = face_analyzer.get(source_img)
        target_faces = face_analyzer.get(target_img)

        if not source_faces:
            logger.warning("No face found in the source image.")
            return False
        if not target_faces:
            logger.warning("No face found in the target image.")
            # If no face in target, we can just return the original target
            cv2.imwrite(output_path, target_img)
            return True

        # Perform the swap
        # We use the first detected face from the source image
        # and swap it onto all detected faces in the target image.
        result_img = target_img.copy()
        for target_face in target_faces:
            result_img = face_swapper.get(result_img, target_face, source_faces[0], paste_back=True)

        # Save the result
        cv2.imwrite(output_path, result_img)
        return True
    except Exception as e:
        logger.error(f"Error during image processing: {e}")
        return False

async def process_video(source_path: str, target_path: str, output_path: str, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """
    Performs face swapping on a target video, frame by frame.
    """
    if not face_analyzer or not face_swapper:
        logger.error("Models are not available.")
        return False

    try:
        await context.bot.send_message(chat_id, "⏳ Processing video... This might take a while depending on the length.")

        # --- Video and Audio File Paths ---
        processed_video_no_audio_path = output_path.replace('.mp4', '_no_audio.mp4')
        
        # --- Load Source Face ---
        source_img = cv2.imread(source_path)
        source_faces = face_analyzer.get(source_img)
        if not source_faces:
            await context.bot.send_message(chat_id, "❌ Error: No face found in the source image.")
            return False
        source_face = source_faces[0]

        # --- Video Processing Setup ---
        cap = cv2.VideoCapture(target_path)
        if not cap.isOpened():
            await context.bot.send_message(chat_id, "❌ Error: Could not open the target video file.")
            return False
            
        # Get video properties
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        
        out = cv2.VideoWriter(processed_video_no_audio_path, fourcc, fps, (width, height))

        # --- Frame-by-Frame Processing ---
        frame_count = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            # Detect faces in the current frame
            target_faces = face_analyzer.get(frame)
            
            # If faces are found, swap them
            if target_faces:
                for target_face in target_faces:
                    frame = face_swapper.get(frame, target_face, source_face, paste_back=True)
            
            out.write(frame)
            frame_count += 1
            if frame_count % 100 == 0:
                 logger.info(f"Processed {frame_count} frames for user {chat_id}")


        cap.release()
        out.release()
        
        logger.info(f"Video processing complete for user {chat_id}. Now merging audio.")

        # --- Audio Merging with ffmpeg-python ---
        # Check if the original video has an audio stream
        try:
            probe = ffmpeg.probe(target_path)
            if any(stream['codec_type'] == 'audio' for stream in probe['streams']):
                input_video = ffmpeg.input(processed_video_no_audio_path)
                input_audio = ffmpeg.input(target_path).audio
                ffmpeg.output(input_video, input_audio, output_path, c='copy').run(overwrite_output=True)
                os.remove(processed_video_no_audio_path) # Clean up the no-audio file
            else:
                # No audio stream, just rename the file
                os.rename(processed_video_no_audio_path, output_path)
        except ffmpeg.Error as e:
            logger.warning(f"ffmpeg error (likely no audio stream): {e}. Using video without audio.")
            os.rename(processed_video_no_audio_path, output_path)

        return True

    except Exception as e:
        logger.error(f"Error during video processing for user {chat_id}: {e}")
        await context.bot.send_message(chat_id, f"❌ An unexpected error occurred during video processing: {e}")
        return False


# 5. TELEGRAM BOT HANDLERS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! 👋\n\n"
        "I'm a realistic face swap bot. Here's how to use me:\n\n"
        "1. Send me a clear photo of the **source face** you want to use.\n"
        "2. Send me the **target image or video** you want to swap the face onto.\n\n"
        "I'll process them and send you the result! Use /reset if you want to start over."
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /reset command. Clears the user's session."""
    user_id = update.effective_user.id
    if user_id in user_sessions:
        # Clean up any temporary files associated with the session
        if 'source_path' in user_sessions[user_id] and os.path.exists(user_sessions[user_id]['source_path']):
            os.remove(user_sessions[user_id]['source_path'])
        del user_sessions[user_id]
        await update.message.reply_text("✅ Your session has been reset. You can now send a new source face.")
    else:
        await update.message.reply_text("You don't have an active session to reset.")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Main handler for receiving photos and videos. It manages the user's state.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not face_analyzer or not face_swapper:
        await update.message.reply_text("❌ Bot is currently under maintenance. The AI models could not be loaded. Please try again later.")
        return

    # --- State 1: User has NOT sent a source image yet ---
    if user_id not in user_sessions:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            source_path = os.path.join(TEMP_DIR, f"{user_id}_source.jpg")
            await photo_file.download_to_drive(source_path)
            
            # Verify a face exists in the source image
            source_img = cv2.imread(source_path)
            if face_analyzer.get(source_img):
                user_sessions[user_id] = {'source_path': source_path}
                await update.message.reply_text("✅ Source face saved. Now, please send the target image or video.")
            else:
                os.remove(source_path) # Clean up invalid file
                await update.message.reply_text("❌ No face was detected in the photo you sent. Please send a clear, forward-facing picture for the source face.")
        else:
            await update.message.reply_text("Please send a photo for the source face first.")
        return

    # --- State 2: User has sent a source, now waiting for target ---
    source_path = user_sessions[user_id]['source_path']
    
    try:
        is_video = False
        if update.message.photo:
            target_file = await update.message.photo[-1].get_file()
            target_path = os.path.join(TEMP_DIR, f"{user_id}_target.jpg")
            output_path = os.path.join(TEMP_DIR, f"{user_id}_result.jpg")
            await target_file.download_to_drive(target_path)
        elif update.message.video:
            is_video = True
            video_file = await update.message.video.get_file()
            target_path = os.path.join(TEMP_DIR, f"{user_id}_target.mp4")
            output_path = os.path.join(TEMP_DIR, f"{user_id}_result.mp4")
            await video_file.download_to_drive(target_path)
        else:
            await update.message.reply_text("Unsupported file type. Please send a photo or video as the target.")
            return

        await update.message.reply_text("✅ Target saved, processing...")

        # --- Trigger Processing ---
        if is_video:
            success = await process_video(source_path, target_path, output_path, context, chat_id)
        else:
            success = await process_image(source_path, target_path, output_path)

        # --- Send Result ---
        if success and os.path.exists(output_path):
            await update.message.reply_text("✅ Processing complete! Here is your result:")
            if is_video:
                await context.bot.send_video(chat_id=chat_id, video=open(output_path, 'rb'), supports_streaming=True)
            else:
                await context.bot.send_photo(chat_id=chat_id, photo=open(output_path, 'rb'))
        else:
            await update.message.reply_text("❌ Something went wrong during the face swap process. Please try again or use different images. Use /reset to start over.")

    except Exception as e:
        logger.error(f"An error occurred in handle_media for user {user_id}: {e}")
        await update.message.reply_text("❌ An unexpected error occurred. Please use /reset and try again.")
    
    finally:
        # --- Clean up session and files ---
        if user_id in user_sessions:
            files_to_clean = [
                user_sessions[user_id].get('source_path'),
                locals().get('target_path'),
                locals().get('output_path')
            ]
            for f in files_to_clean:
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError as e:
                        logger.error(f"Error removing file {f}: {e}")
            del user_sessions[user_id]
            logger.info(f"Session and files cleaned up for user {user_id}.")


# 6. MAIN FUNCTION TO RUN THE BOT
def main():
    """Starts the bot."""
    if BOT_TOKEN == "YOUR_BOT_TOKEN":
        logger.error("!!! BOT TOKEN IS NOT SET. Please replace 'YOUR_BOT_TOKEN' with your actual token. !!!")
        return

    if not face_analyzer or not face_swapper:
        logger.error("!!! Could not initialize InsightFace models. The bot cannot start. Check logs for errors. !!!")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot is starting...")
    application.run_polling()
    logger.info("Bot has stopped.")

if __name__ == '__main__':
    main()

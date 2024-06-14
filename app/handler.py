'''
The MIT License (MIT)
Copyright © 2024 Dominic Powers

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''
import warnings

''' Suppress all warnings (FOR PRODUCTION) '''
warnings.filterwarnings("ignore")

import runpod
import os
import cv2
import numpy as np
import torch
import time
import multiprocessing
from gfpgan import GFPGANer

from utils.file_utils import download_file, upload_to_s3, sync_checkpoints, map_network_volume

def enhance_faces_in_video(input_video_url, bucket_name):
    try:
        print(f'[Enhancer]: Processing GFPGAN enhancer on {input_video_url}')
        # Download the input video
        input_video_path, error = download_file(input_video_url, 'input_video.mp4')

        if error:
            return None, error

        # Generate the output video path
        timestamp = time.strftime("%Y_%m_%d_%H.%M.%S")
        output_video_path = f"enhanced_{timestamp}.mp4"

        # Initialize GFPGAN with the correct model path
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f'[Enhancer]: [device]: {device}')

        # call model
        gfpganer = GFPGANer(model_path='/app/gfpgan/weights/GFPGANv1.4.pth', upscale=2, arch='clean', channel_multiplier=2, device=device)

        # Read the input video
        cap = cv2.VideoCapture(input_video_path)
        if not cap.isOpened():
            raise FileNotFoundError("Error: Could not open input video.")

        fps = int(cap.get(cv2.CAP_PROP_FPS))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Temporary directory for frames
        tmp_dir = 'temp_frames'
        os.makedirs(tmp_dir, exist_ok=True)

        frame_number = 0

        while True:
            ret, frame = cap.read()

            if not ret:
                break

            # Ensure frame dimensions are correct
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height))

            # Enhance the face in the frame using GFPGAN
            _, _, enhanced_frame = gfpganer.enhance(frame, has_aligned=False, only_center_face=False, paste_back=True)

            # Save enhanced frame to disk
            frame_path = os.path.join(tmp_dir, f"frame_{frame_number:06d}.png")
            cv2.imwrite(frame_path, enhanced_frame)
            frame_number += 1

        cap.release()

        # Get the number of CPU cores
        num_cores = multiprocessing.cpu_count()

        # Use ffmpeg to combine frames into a video and include audio
        cmd = (
            f"ffmpeg -y -loglevel error -thread_queue_size {num_cores} -r {fps} -i {tmp_dir}/frame_%06d.png "
            f"-i {input_video_path} -c:v libx264 -pix_fmt yuv420p -profile:v baseline -level 3.0 "
            f"-c:a aac -strict experimental -b:a 128k -movflags +faststart {output_video_path}"
        )
        os.system(cmd)

        # Clean up temporary frames
        for file_name in os.listdir(tmp_dir):
            file_path = os.path.join(tmp_dir, file_name)
            if os.path.isfile(file_path):
                os.unlink(file_path)
        os.rmdir(tmp_dir)

        # Upload the enhanced video to S3
        object_name = os.path.basename(output_video_path)

        uploaded_url, error = upload_to_s3(output_video_path, bucket_name, object_name)
        if error:
            print(f'[Enhancer][ERROR]: upload_to_s3 failed {error}')
            sys.exit(1)

        # Try to clean up local files
        try:
            os.remove(input_video_path)
            os.remove(output_video_path)
        except:
            pass

        return uploaded_url, None

    except Exception as e:
        return None, e

""" Handler function that will be used to process jobs. """
def handler(job):
    job_input = job['input']

    input_video_url = job_input.get('input_video_url')
    bucket_name = 'Enhanced_GFPGAN'

    if not input_video_url:
        return {"error": "'input_video_url' is required in job input."}

    result, error = enhance_faces_in_video(input_video_url, bucket_name)

    if error:
        print(f'[Enhancer][ERROR]: enahnce_faces_in_video failed: {error}')
        sys.exit(1)
    else:
        return {"output_video_url": result}

if __name__ == "__main__":

    result, error = map_network_volume()
    if error:
        print(f'[Enhancer][WARNING]: Could not map network volume: {error}')

    # Initial load (if needed) to populate network volume with checkpoints
    result, error = sync_checkpoints()
    
    if error:
        print(f'[Enhancer][ERROR]: Failed to download checkpoints: {error}')
        sys.exit(1)

    runpod.serverless.start({"handler": handler})

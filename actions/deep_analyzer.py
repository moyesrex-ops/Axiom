import os
import time
import uuid
import json
import logging
from pathlib import Path

try:
    import yt_dlp
    _YT_DLP_OK = True
except ImportError:
    _YT_DLP_OK = False

try:
    import cv2
    import mss
    import numpy as np
    _RECORDING_OK = True
except ImportError:
    _RECORDING_OK = False

from google import genai

def get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _download_youtube(url: str, output_path: str) -> str:
    ydl_opts = {
        'format': 'best[height<=720]',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output_path

def _record_screen(duration_sec: int, output_path: str):
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        width = monitor["width"]
        height = monitor["height"]
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, 10.0, (width, height))
        
        start_time = time.time()
        while time.time() - start_time < duration_sec:
            img = sct.grab(monitor)
            frame = np.array(img)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            out.write(frame)
            time.sleep(0.1) # approx 10fps
        
        out.release()
    return output_path

def deep_analyze(file_path: str, prompt: str, player=None) -> str:
    if player:
        player.write_log("Uploading file to Gemini...")
        
    client = genai.Client(api_key=_get_api_key(), http_options={'api_version': 'v1beta'})
    
    video_file = client.files.upload(file=file_path)
    
    if player:
        player.write_log("Wait for processing...")
        
    while video_file.state.name == "PROCESSING":
        time.sleep(2)
        video_file = client.files.get(name=video_file.name)
        
    if video_file.state.name == "FAILED":
        return "Video processing failed."
        
    if player:
        player.write_log("Analyzing video content...")
        
    response = client.models.generate_content(
        model='gemini-3.1-pro-preview',
        contents=[
            video_file,
            f"You are AXIOM. Deeply process this video logically according to what the user wants: {prompt}"
        ]
    )
    
    try:
        client.files.delete(name=video_file.name)
        os.remove(file_path)
    except:
        pass
        
    return response.text

def deep_analyzer(
    parameters: dict,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Deep Multimodal Analyzer (YouTube & Screen Recording).
    """
    params = parameters or {}
    action = params.get("action", "youtube")
    prompt = params.get("prompt", "Analyze this video in detail.")
    
    desktop = Path.home() / "Desktop"
    temp_file = str(desktop / f"axiom_analysis_{uuid.uuid4().hex[:6]}.mp4")
    
    try:
        if action == "youtube":
            if not _YT_DLP_OK:
                return "yt-dlp missing. pip install yt-dlp"
            url = params.get("url")
            if not url:
                return "No YouTube URL provided for deep analysis."
            if speak:
                speak("Downloading video for deep analysis. This may take a moment, sir.")
            if player:
                player.write_log(f"Downloading YT: {url}")
                
            _download_youtube(url, temp_file)
            
        elif action == "screen":
            if not _RECORDING_OK:
                return "Screen recording dependencies missing."
            duration = int(params.get("duration", 10))
            if speak:
                speak(f"Recording your screen for {duration} seconds. Please keep the content visible.")
            if player:
                player.write_log(f"Recording screen ({duration}s)")
                
            _record_screen(duration, temp_file)
            
        else:
            return f"Unknown action: {action}"
            
        if speak:
            speak("Upload complete. Processing and analyzing the video now.")
            
        analysis = deep_analyze(temp_file, prompt, player)
        
        if speak:
             speak("Analysis complete. Reading results.")
            
        return analysis
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        return f"Deep Analyzer failed: {str(e)}"

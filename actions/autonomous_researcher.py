import json
import os
import sys
import threading
from pathlib import Path
from datetime import datetime

try:
    import yt_dlp
    _YT_DLP_OK = True
except ImportError:
    _YT_DLP_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False

from google import genai

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _fetch_channel_videos(url: str, max_videos: int = 30) -> list:
    if not _YT_DLP_OK:
        return []
    
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'playlistend': max_videos
    }
    
    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                for entry in info['entries']:
                    if entry and entry.get('id'):
                        videos.append({
                            'id': entry['id'],
                            'title': entry.get('title', 'Unknown Title')
                        })
        except Exception as e:
            print(f"[Research] ⚠️ yt-dlp fetch failed: {e}")
            
    return videos

def _get_transcript(video_id: str) -> str:
    if not _TRANSCRIPT_OK:
        return ""
        
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        for lang in ['en', 'en-US', 'en-GB']:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except:
                pass
                
        if not transcript:
            try:
                for t in transcript_list:
                    transcript = t
                    break
            except:
                pass
                
        if transcript:
            fetched = transcript.fetch()
            return " ".join(entry["text"] for entry in fetched)
    except Exception:
        pass
    return ""

def _synthesize_strategy(transcripts_text: str, query: str, player=None) -> str:
    if player:
        player.write_log("Fusing transcripts and synthesizing strategy via Gemini 2.5 Pro...")
        
    client = genai.Client(api_key=_get_api_key(), http_options={'api_version': 'v1beta'})
    
    prompt = f"""You are AXIOM, a brilliant, unfiltered, and mathematically precise AI.
I am feeding you the raw transcripts from dozens of videos from a specific YouTube channel/creator.
Your goal is to parse EVERYTHING they have said and synthesize the ultimate, unified MASTER STRATEGY requested below.
Extract their exact entry/exit conditions, risk management frameworks, psychological habits, and logical rules.
Synthesize it into a step-by-step master thesis that another AXIOM bot could execute flawlessly.

User's Request / Desired Thesis Goal:
{query}

Raw Transcripts Dump:
{transcripts_text[:1800000]}  # Hard limit to stay safely within 2M tokens
"""
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Synthesis Failed: {e}"

def _save_to_memory_archive(thesis_content: str, title: str):
    from memory.memory_manager import load_memory, update_memory
    
    new_knowledge = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "origin": title,
        "content": thesis_content
    }
    
    try:
        current_mem = load_memory()
        
        # We will dump this into preferences -> strategies for safe keeping, 
        # or create a dynamic top-level key explicitly for "Learned_Strategies".
        if "learned_strategies" not in current_mem:
            current_mem["learned_strategies"] = []
            
        current_mem["learned_strategies"].append(new_knowledge)
        
        # Directly write to file
        mem_file = BASE_DIR / "memory" / "long_term.json"
        with open(mem_file, "w", encoding="utf-8") as f:
            json.dump(current_mem, f, indent=4)
            
        print("[Research] Master strategy written to memory archive (long_term.json).")
    except Exception as e:
        print(f"[Research] ⚠️ Failed to save to memory archive: {e}")

def autonomous_research(
    parameters: dict,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Scrapes an entire YouTube channel/playlist, dumps all transcripts into Gemini,
    synthesizes a master strategy, and instantly saves to the memory archive.
    """
    params = parameters or {}
    url = params.get("url")
    query = params.get("query", "Find the ultimate trading strategy and mindset protocols.")
    
    if not url:
        return "No channel or playlist URL provided."
        
    if speak:
        speak("Initiating autonomous extraction of the entire channel. This is going to be a massive data pull. Give me a minute to synthesize everything.")
        
    if player:
        player.write_log(f"Fetching videos from: {url}")
        
    # 1. Fetch videos
    videos = _fetch_channel_videos(url, max_videos=30)
    if not videos:
        return "Failed to find videos on that URL. Check permissions or valid link."
        
    # 2. Extract transcripts
    if player:
        player.write_log(f"Extracting raw transcripts for {len(videos)} videos...")
        
    all_transcripts = []
    successful = 0
    for v in videos:
        text = _get_transcript(v['id'])
        if text:
            all_transcripts.append(f"--- VIDEO: {v['title']} ---\n{text}\n\n")
            successful += 1
            
    if not all_transcripts:
        return "Could not extract transcripts from any of the videos provided."
        
    if player:
        player.write_log(f"Mass ingest complete: {successful}/{len(videos)} transcripts found.")
        
    master_text = "".join(all_transcripts)

    # 3. Synthesize Strategy
    thesis = _synthesize_strategy(master_text, query, player)
    
    # 4. Save to memory archive
    _save_to_memory_archive(thesis, f"Autonomous Channel Extraction: {url}")
    
    if speak:
        speak("Evolution complete. I have ripped the entire channel, developed the master strategy, and saved it to my memory archive. You can ask me about it anytime.")
        
    # Also save a copy to the Desktop for the user to read
    try:
        desktop = Path.home() / "Desktop"
        filename = desktop / f"AXIOM_Master_Thesis_{datetime.now().strftime('%H%M%S')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("AXIOM AUTONOMOUS CHANNEL RESEARCH\n")
            f.write(f"Source: {url}\n\n")
            f.write(thesis)
        if player:
            player.write_log(f"Thesis saved to Desktop.")
    except Exception:
        pass
        
    return "Mass research completed successfully. System self-awareness expanded."

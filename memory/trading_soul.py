import json
import os
from pathlib import Path
from datetime import datetime

def get_base_dir():
    import sys
    if getattr(sys, "frozen", False): return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key():
    config_path = get_base_dir() / "config" / "api_keys.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]
    except Exception:
        return ""

SOUL_FILE = get_base_dir() / "memory" / "trading_soul.json"

def reflect_on_trade(symbol: str, profit: float, reason: str):
    """
    Called autonomously after a trade is closed. Analyzes why it won/lost 
    and physically updates Axiom's persistent trading psychology.
    """
    if not SOUL_FILE.exists():
        with open(SOUL_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "core_philosophy": "Protect capital above all else. Do not trust hope.", 
                "lessons_learned": [], 
                "trade_history": []
            }, f, indent=4)
            
    with open(SOUL_FILE, "r", encoding="utf-8") as f:
        soul = json.load(f)
        
    soul["trade_history"].append({
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "profit": profit,
        "reason_closed": reason
    })
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        prompt = f"""
        You are Axiom's internal Trading Soul.
        You just closed a trade on {symbol}. The net profit/loss was {profit}.
        The reason it was closed: {reason}
        
        Current Core Philosophy: {soul.get('core_philosophy', '')}
        
        Write a hyper-concise, brutal psychological reflection. Did you win because of pure luck or strict execution? Did you lose because of a structural breakdown or bad risk?
        Generate exactly ONE new unbreakable rule to add to your behavior.
        """
        
        response = model.generate_content(prompt)
        lesson = response.text.strip()
        
        soul["lessons_learned"].append({
            "timestamp": datetime.now().isoformat(),
            "lesson": lesson
        })
        
        # Neural Link: Mirror lessons to the main neural context
        try:
            from memory.memory_manager import save_to_nexus
            save_to_nexus(f"Trading Wisdom: {symbol}", lesson)
        except: pass
        
        with open(SOUL_FILE, "w", encoding="utf-8") as f:
            json.dump(soul, f, indent=4)
            
    except Exception as e:
        print(f"[SOUL] Reflection generation failed: {e}")

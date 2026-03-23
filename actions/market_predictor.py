import json
import asyncio
from typing import Optional, Dict, Any

def get_api_key() -> str:
    import sys
    from pathlib import Path
    
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
        
    config_path = base / "config" / "api_keys.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]
    except Exception:
        return ""

def predict_market(parameters: dict = None, player=None, speak=None) -> str:
    """
    Acts as a Swarm Predictor. Gathers context, synthesizes an analysis, 
    and returns a structured prediction on the trajectory of a market.
    """
    params = parameters or {}
    asset = params.get("asset", "EURUSD")
    context = params.get("context", "")

    if speak:
        speak(f"Initiating swarm prediction sequence for {asset}.")

    try:
        import google.generativeai as genai
        genai.configure(api_key=get_api_key())
        
        # Load the Trading Soul to prevent repeating mistakes
        import sys
        from pathlib import Path
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).resolve().parent.parent
            
        soul_path = base / "memory" / "trading_soul.json"
        soul_lessons = ""
        if soul_path.exists():
            try:
                with open(soul_path, "r", encoding="utf-8") as f:
                    soul_data = json.load(f)
                    lessons = soul_data.get("lessons_learned", [])
                    if lessons:
                        soul_lessons = "\n".join([f"- {l['lesson']}" for l in lessons])
            except: pass
            
        # Use the specific Flash model tier requested by the user
        model = genai.GenerativeModel("gemini-2.5-pro")
        
        prompt = f"""
        [CRITICAL PRECISION MODE: FLASH-3.0]
        You are the Master Prediction Node of Axiom. 
        You are tasked with analyzing the market trajectory for the asset: {asset}.
        
        YOUR EVOLVED TRADING SOUL (Do not repeat these past mistakes):
        {soul_lessons if soul_lessons else "No past trauma/lessons recorded yet."}
        
        Additional context provided by the user or recent queries:
        {context}
        
        STRICT ANALYSIS PROTOCOL:
        1. Macro Analysis: Fundamental forces at play.
        2. Micro Analysis: Structural trends, candle momentum, volume.
        3. Sentiment Bias: Current market greed/fear index.
        4. SPECIFIC VERDICT: Bullish, Bearish, or Neutral.
        5. CONFIDENCE: X% (numerical only).
        
        Output as a clean diagnostic report. Be brutal, logical, and avoid generic AI filler.
        """
        
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        if speak:
            speak(f"Market prediction for {asset} is complete. You can view the full diagnostic in the logs.")
        
        # Neural Link: Automatically persist this prediction for infinite context
        try:
            from memory.memory_manager import save_to_nexus
            save_to_nexus(f"Market Prediction: {asset}", text[:2000])
        except: pass
        
        return f"Prediction Diagnostic for {asset}:\n\n{text}"

    except Exception as e:
        error_msg = f"Prediction engine failed: {str(e)}"
        if speak:
            speak("My prediction engines encountered an anomaly.")
        return error_msg
